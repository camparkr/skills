#!/usr/bin/env python3
"""One hook entry per event: run the check the ledger folder's config.json names for it, then the capture, in one
process.

    python3 wrapper.py <event> [--ledger <folder>]          (a hook command, with the payload on standard input)
    python3 wrapper.py --hook-entries [--ledger <folder>]   (print the hook entries to place, with their time limit)

The capture is installed nowhere else on an event the wrapper holds. Which checks run is config.json's `checks`,
beside `triage_command`: a command for `stop` runs at each SubagentStop; one for `handback` at PreToolUse on the
harness's hand-back tools (subagent-tools.json `handback`); one for `dispatch` at PreToolUse on Agent and Task; one
for `gate` at every PreToolUse of the parent (a payload with no `agent_id`), whatever the tool; and one for `context`
after the capture at the parent's PostToolUse on Agent or Task and at its UserPromptSubmit. A check gets the payload
on standard input and, in its environment, SUBAGENT_LEDGER_DIR, SUBAGENT_LEDGER_SESSION and SUBAGENT_LEDGER_SCRIPTS;
it prints one JSON object, {"refuse": true or false, "reason": "<text>"}, and may add keys of its own; a `context`
check may add `context`, text the wrapper hands the parent as additionalContext. `check_seconds` bounds each check
(10 by default). With no check named, the wrapper only runs the capture, and writes what the capture alone writes.

What each part does:

  * The check runs first. A check that exits non-zero, prints anything but that object, or cannot start refuses
    nothing: its result reads `not_checkable (check error: <reason>)`. One that runs past its bound is stopped and
    refuses nothing: `not_checkable (check timed out)`. Its time is `check_seconds`.
  * At a stop or a hand-back the check's result is kept for the call's one return (pending.py, `checkResult`): its
    own keys less `refuse`, with `event`, `at`, `refused`, `reason`, `result` (`checked`, or `not_checkable (...)`),
    `check_seconds` and, at a hand-back, `tool_use_id`. Then the capture runs: at a stop it writes the witness line,
    carrying the stop's result, and at a stop the check refused, no return; at a hand-back it writes no call record,
    and the wrapper has it write the witness line carrying the hand-back's result, refused or not, before the call
    goes on and so before its report can reach the parent.
  * The gate runs before anything else at the parent's PreToolUse. Where it refuses, the call is refused: an Agent or
    Task call gets its dispatch record and one `failed` return, class refused_by_check, as a refused dispatch does;
    for any other tool the capture is not run, since the call never runs. A gate that errors or overruns refuses
    nothing, and a witness line records its result, `not_checkable (...)`, under `check_results`. A member's tool
    call never meets the gate; where no check and no capture route applies to it, the wrapper exits at once.
  * The context step runs after the capture, so a foreground call's return is on the record when it reads. Its text
    is printed as hookSpecificOutput additionalContext, at PostToolUse and at UserPromptSubmit alike.
  * At PostToolUse on a hand-back tool the kept result is marked delivered, with the SHA-256 of the message
    delivered. With a hand-back check on and no result kept for that call, one is kept saying so, so its return reads
    `unrecorded (no check result when the return was written)`.
  * At a dispatch, the check's time and result go on the dispatch record's harness_payload as `wrapper`. Where it
    refused, the capture writes the dispatch record and then one `failed` return, class refused_by_check, with the
    refusal's text, both at this PreToolUse, and no pending file is left.
  * The capture runs on every path. The wrapper refuses only where a check that ran decided to: never because the
    capture failed or the check failed. A refusal is printed in the form the event takes: at PreToolUse,
    hookSpecificOutput with permissionDecision `deny` and the reason; at SubagentStop, {"decision": "block",
    "reason": ...}. Otherwise it prints nothing. It exits 0 on every path.

The hook's time limit is set explicitly in the hook entries, above the capture's longest wait: `--hook-entries`
prints them, each with `timeout` set to `background_wait_seconds` plus `check_seconds` plus a margin of 30 seconds.
With a `gate` check named, the PreToolUse entry matches every tool, and the limit holds one more `check_seconds`,
since a PreToolUse may run the gate and then the dispatch check; with a `context` check named, a UserPromptSubmit
entry is added. It refuses (exit 2) where `background_wait_seconds` is not set, since an unbounded wait has no limit to
sit above. Placing the entries in settings other sessions load is the user's act.
"""

import contextlib
import datetime
import hashlib
import io
import json
import math
import os
import shlex
import subprocess
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

import capture_claude_code as capture  # noqa: E402
import ledger  # noqa: E402
import pending  # noqa: E402

CHECK_SECONDS = 10
MARGIN_SECONDS = 30
DISPATCH_TOOLS = ('Agent', 'Task')
CAPTURED_PRE = ('Agent', 'Task', 'Bash', 'SendMessage', 'TaskStop', 'SubagentHandback', 'WebSearch', 'WebFetch')
CHECKED = 'checked'
TIMED_OUT = 'not_checkable (check timed out)'
CHECK_ERROR = 'not_checkable (check error: %s)'
# The events the wrapper holds, with the tool matcher each takes (None: every tool, or an event with no tool).
EVENTS = (
    ('PreToolUse', 'Agent|Task|Bash|SendMessage|TaskStop|SubagentHandback|WebSearch|WebFetch|mcp__.*'),
    ('PostToolUse', 'Agent|Task|Bash|SendMessage|TaskStop|SubagentHandback|WebSearch|WebFetch|mcp__.*'),
    ('PostToolUseFailure', 'Agent|Task|Bash|SendMessage|WebSearch|WebFetch|mcp__.*'),
    ('SessionStart', None),
    ('SubagentStart', None),
    ('SubagentStop', None),
)
CONTEXT_EVENT = 'UserPromptSubmit'


def config_of(folder):
    try:
        data = json.loads((Path(folder) / ledger.CONFIG_FILE).read_text(encoding='utf-8'))
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def check_bound(config):
    value = config.get('check_seconds')
    if isinstance(value, bool) or not isinstance(value, (int, float)) or value <= 0:
        return CHECK_SECONDS
    return value


def at_once(event, payload, checks):
    """Whether this event needs nothing from the wrapper: a PreToolUse on a tool the capture does not read and no
    check takes, such as a member's Read when the PreToolUse entry matches every tool for the gate."""
    if event != 'PreToolUse':
        return False
    tool = payload.get('tool_name')
    if not isinstance(tool, str) or tool in CAPTURED_PRE or tool.startswith('mcp__'):
        return False
    if not payload.get('agent_id') and checks.get('gate'):
        return False
    return which_check(event, payload) is None


def gate_witness(payload, folder, result, seconds):
    """A witness line saying the gate could not decide at this call: it refused nothing. Never raises."""
    held = capture.Held('PreToolUse', payload)
    try:
        ledger.witness(ledger=str(folder), event='PreToolUse', session=held.session,
                       agent_id='unrecorded (no agent: the parent)', call_id=held.call_id, at=now(),
                       check_results=[{'check': 'gate', 'result': result, 'check_seconds': seconds}])
    except Exception as exc:
        held.error(str(folder), 'payload', 'the gate\'s witness line could not be written: %s' % exc, record='witness')


def context_of(event, payload, command, folder, config):
    """The context check's text for this event, or None."""
    if payload.get('agent_id') or not isinstance(command, str) or not command:
        return None
    if not (event == CONTEXT_EVENT or (event == 'PostToolUse' and payload.get('tool_name') in DISPATCH_TOOLS)):
        return None
    try:
        text = json.dumps(payload)
        env = dict(os.environ, SUBAGENT_LEDGER_DIR=str(folder), SUBAGENT_LEDGER_SESSION=str(payload.get('session_id')),
                   SUBAGENT_LEDGER_SCRIPTS=str(HERE))
        done = subprocess.run(shlex.split(command), input=text, capture_output=True, text=True, env=env,
                              cwd=str(folder), timeout=check_bound(config))
        said = json.loads(done.stdout) if done.returncode == 0 else {}
    except (OSError, ValueError, subprocess.SubprocessError):
        return None
    found = said.get('context') if isinstance(said, dict) else None
    return found if isinstance(found, str) and found else None


def which_check(event, payload):
    """`stop`, `handback`, `dispatch` or None: the check this event and tool take."""
    tool = payload.get('tool_name')
    if event == 'SubagentStop':
        return 'stop'
    if event == 'PreToolUse' and tool in capture.handback_tools(capture.HARNESS):
        return 'handback'
    if event == 'PreToolUse' and tool in DISPATCH_TOOLS:
        return 'dispatch'
    return None


def run_check(command, text, folder, session, bound):
    """(refused, reason, the check's own keys, result, seconds). Refuses only on the check's own decision."""
    began = time.monotonic()
    env = dict(os.environ, SUBAGENT_LEDGER_DIR=str(folder), SUBAGENT_LEDGER_SESSION=str(session),
               SUBAGENT_LEDGER_SCRIPTS=str(HERE))
    try:
        done = subprocess.run(shlex.split(command), input=text, capture_output=True, text=True, env=env,
                              cwd=str(folder), timeout=bound)
    except subprocess.TimeoutExpired:
        return False, None, {}, TIMED_OUT, round(time.monotonic() - began, 3)
    except (OSError, ValueError) as exc:
        return False, None, {}, CHECK_ERROR % one_line(exc), round(time.monotonic() - began, 3)
    seconds = round(time.monotonic() - began, 3)
    if done.returncode != 0:
        return False, None, {}, CHECK_ERROR % one_line(done.stderr or 'exit %d' % done.returncode), seconds
    try:
        said = json.loads(done.stdout)
        if not isinstance(said, dict) or not isinstance(said.get('refuse'), bool):
            raise ValueError('the check printed no object with a true or false `refuse`')
    except ValueError as exc:
        return False, None, {}, CHECK_ERROR % one_line(exc), seconds
    reason = said.get('reason') if isinstance(said.get('reason'), str) else ''
    own = dict((key, value) for key, value in said.items() if key not in ('refuse', 'reason'))
    return said['refuse'], reason, own, said.get('result', CHECKED), seconds


def one_line(text):
    text = ' '.join(str(text).split())
    return text if len(text) <= 200 else text[:197] + '...'


def now():
    return datetime.datetime.now(datetime.timezone.utc).strftime('%Y-%m-%dT%H:%M:%S.%f')[:-3] + 'Z'


def keep(folder, session, agent, data):
    if not isinstance(agent, str) or not agent:
        return
    directory = capture.pending_dir(folder, session)
    with capture.pending_lock(folder, session):
        pending.keep_result(directory, agent, data, capture._safe)


def mark_delivered(folder, payload, check_on):
    """At PostToolUse on a hand-back: mark its kept result delivered, or keep one saying none was left."""
    session, agent, call = payload.get('session_id'), payload.get('agent_id'), payload.get('tool_use_id')
    if not isinstance(agent, str) or not agent or not isinstance(call, str):
        return
    given = payload.get('tool_input') if isinstance(payload.get('tool_input'), dict) else {}
    key = capture.handback_tools(capture.HARNESS).get(payload.get('tool_name'))
    message = given.get(key) if key else None
    digest = hashlib.sha256(message.encode('utf-8')).hexdigest() if isinstance(message, str) else None
    directory = capture.pending_dir(folder, session)
    with capture.pending_lock(folder, session):
        for path in pending._kept_paths(directory, agent, capture._safe):
            try:
                data = json.loads(path.read_text(encoding='utf-8'))
            except (OSError, ValueError):
                continue
            if isinstance(data, dict) and data.get('tool_use_id') == call:
                data.update(delivered=True, delivered_sha256=digest)
                path.write_text(json.dumps(data, ensure_ascii=False), encoding='utf-8')
                return
        if check_on:
            pending.keep_result(directory, agent, {'event': 'PreToolUse', 'tool_use_id': call, 'missing': True,
                                                   'delivered': True, 'delivered_sha256': digest}, capture._safe)


def refusal(event, reason):
    if event == 'SubagentStop':
        return {'decision': 'block', 'reason': reason}
    return {'hookSpecificOutput': {'hookEventName': event, 'permissionDecision': 'deny',
                                   'permissionDecisionReason': reason}}


def handle(event, text, folder_named):
    """Run the gate and the event's check, then the capture, then the context step. Returns what to print, or None."""
    try:
        payload = json.loads(text)
        payload = payload if isinstance(payload, dict) else {}
    except (TypeError, ValueError):
        payload = {}
    folder, config, checks, which, decision, gated, kept = None, {}, {}, None, None, False, None
    try:
        folder = Path(ledger.ledger_folder(folder_named))
        config = config_of(folder)
        checks = config.get(capture.CHECKS_SETTING) if isinstance(config.get(capture.CHECKS_SETTING), dict) else {}
        if at_once(event, payload, checks):
            return None
        gate = checks.get('gate')
        if event == 'PreToolUse' and not payload.get('agent_id') and isinstance(gate, str) and gate:
            refused, reason, _own, result, seconds = run_check(gate, text, folder, payload.get('session_id'),
                                                               check_bound(config))
            if result != CHECKED:
                gate_witness(payload, folder, result, seconds)
            if refused:
                decision, gated = reason or 'refused by the gate', True
        which = which_check(event, payload)
        command = checks.get(which) if which and not gated else None
        if isinstance(command, str) and command:
            refused, reason, own, result, seconds = run_check(command, text, folder, payload.get('session_id'),
                                                              check_bound(config))
            if which == 'dispatch':
                capture.WRAPPER_NOTE.update(check_seconds=seconds, result=result, refused=refused)
            else:
                kept = dict(own)
                kept.update(event=event, at=now(), refused=refused, reason=reason, result=result,
                            check_seconds=seconds)
                if which == 'handback':
                    kept['tool_use_id'] = payload.get('tool_use_id')
                keep(folder, payload.get('session_id'), payload.get('agent_id'), kept)
            if refused:
                decision = reason or 'refused by the check'
        if event == 'PostToolUse' and payload.get('tool_name') in capture.handback_tools(capture.HARNESS):
            mark_delivered(folder, payload, isinstance(checks.get('handback'), str) and bool(checks.get('handback')))
    except Exception as exc:  # the wrapper's own fault: recorded, refuses nothing
        capture.Held(event, payload).error(folder_named, 'payload', 'the wrapper failed before the capture: %s: %s'
                                           % (type(exc).__name__, exc))
        decision, gated = None, False
    tool = payload.get('tool_name')
    with contextlib.redirect_stdout(io.StringIO()):
        if not gated or tool in DISPATCH_TOOLS:
            capture.handle(event, text, folder_named)
        if decision is not None and (which == 'dispatch' or (gated and tool in DISPATCH_TOOLS)):
            capture.refused_dispatch(payload, folder_named, decision)
        if which == 'handback' and kept is not None:
            capture.handback_witness(payload, folder_named, kept)
    if decision is not None:
        return refusal(event, decision)
    try:
        found = context_of(event, payload, checks.get('context'), folder, config) if folder is not None else None
    except Exception:
        found = None
    if found:
        return {'hookSpecificOutput': {'hookEventName': event, 'additionalContext': found}}
    return None


def hook_entries(folder_named):
    """(exit code, the hook entries to place, or why not)."""
    folder = Path(ledger.ledger_folder(folder_named)).resolve()
    config = config_of(folder)
    wait = config.get(capture.WAIT_SETTING)
    if isinstance(wait, bool) or not isinstance(wait, (int, float)) or wait <= 0:
        return 2, ('%s sets no %s: the background wait is unbounded, so no time limit can sit above it'
                   % (folder / ledger.CONFIG_FILE, capture.WAIT_SETTING))
    checks = config.get(capture.CHECKS_SETTING) if isinstance(config.get(capture.CHECKS_SETTING), dict) else {}
    bounds = 2 if checks.get('gate') else 1
    limit = int(math.ceil(wait + bounds * check_bound(config) + MARGIN_SECONDS))
    command = 'python3 "%s" %%s --ledger "%s"' % (Path(__file__).resolve(), folder)
    events = list(EVENTS)
    if checks.get('context'):
        events.append((CONTEXT_EVENT, None))
    hooks = {}
    for event, matcher in events:
        if event == 'PreToolUse' and checks.get('gate'):
            matcher = None  # the gate decides at every tool call of the parent
        entry = {'hooks': [{'type': 'command', 'command': command % event, 'timeout': limit}]}
        if matcher:
            entry = dict({'matcher': matcher}, **entry)
        hooks[event] = [entry]
    return 0, {'hooks': hooks}


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    folder = None
    if '--ledger' in argv:
        at = argv.index('--ledger')
        folder = argv[at + 1] if at + 1 < len(argv) else None
        del argv[at:at + 2]
    if argv[:1] == ['--hook-entries']:
        code, out = hook_entries(folder)
        if code:
            print('wrapper: refused: %s' % out, file=sys.stderr)
            return code
        print(json.dumps(out, indent=2))
        return 0
    event = argv[0] if argv else None
    try:
        text = sys.stdin.read()
    except Exception:
        text = ''
    try:
        decision = handle(event, text, folder)
    except Exception:  # nothing the wrapper does may refuse or fail the call
        decision = None
    if decision is not None:
        print(json.dumps(decision))
    return 0


if __name__ == '__main__':
    sys.exit(main())
