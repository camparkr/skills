#!/usr/bin/env python3
"""Codex's capture: hook events on its subagent tool and its shell tool run it, and it writes the call records.

It writes them through ledger.py.

    python3 capture_codex.py <event> [--ledger <folder>]

with the hook's payload on standard input. It prints nothing on standard output and exits 0 on every
path, including a payload that is empty or is not JSON, so it never blocks or changes a call. It
imposes no time limit.

Tool names. Codex 0.142.5 named the subagent tool `spawn_agent` and the shell tool `exec_command` in its
hook events; Codex 0.162.1 names them `Agent` and `Bash` (its hooks documentation, 'Tool coverage'). The
capture takes the names subagent-tools.json lists for Codex, `tools` and `shell_tools`, which hold both.

What each event does (Codex 0.142.5, as observed, and 0.162.1 where it differs):

  * PreToolUse on the subagent tool: the dispatch record. The brief is `tool_input.message`; where that
    is ciphertext (0.162.x passed one encrypted), the copy is kept as sent and `brief_source` reads
    `unrecorded (the harness passed the brief encrypted)`. The payload's
    own `model` is the parent session's, so it is never taken as the model asked for: that is
    `tool_input.model` where the tool is given one, and otherwise none was asked. The ledger folder's
    `triage_command`, where named, runs here, and `act_kind`, `triage_kind` and `effort_assigned` are
    read as in capture_claude_code.py; spawn_agent takes no effort setting for the call.
  * PostToolUse on the subagent tool: fires when the spawn returns. Where `tool_response` names an
    `agent_id` (0.142.5), it stores the join of `tool_use_id` to that agent and writes nothing else.
    Where it names none (0.162.x sends `{"task_name": …}` only), the spawn stays pending, its response
    kept for the return's `harness_payload`, and SubagentStart joins it.
  * SubagentStart: a witness line. Then, where no join names its agent yet, it joins the oldest spawn
    in the session still waiting for an agent, by the order of their dispatches. Where no spawn is
    waiting and the ledger has never named the agent, the harness sent no event for the spawn: the
    start writes the dispatch itself, its call id the agent's id and its brief fields
    `unrecorded (the harness sent no dispatch event for this subagent)`.
  * SubagentStop: a witness line, then the return record, joined to its call through the stored
    join. The subagent's rollout, at `agent_transcript_path`, is read once the stop's turn holds the
    answer SubagentStop reports and the counter row written after it, or the turn's end. The stop's
    turn is the one whose `task_started` row carries the payload's `turn_id`; where no row does, the
    rollout's last turn. Codex writes
    `task_complete` only after this hook returns, so the capture never waits for that row. There is
    no limit on the wait beyond the harness's own time-out on hooks. The model, the
    four counters, the effort and the isolation evidence come from the rollout; the answer from
    `last_assistant_message`. The payload's own `model` stays in `harness_payload` and never stands
    for the model the rollout names.
  * PreToolUse on the shell tool subagent-tools.json names (`exec_command`, or `Bash` on 0.162.1): a
    dispatch record, route cli, when the command (`tool_input.cmd` on 0.142.5, `tool_input.command` on
    0.162.1) matches cli-patterns.json, as the Claude
    Code capture's shell route does. A command that makes no model call writes nothing.
  * PostToolUse on the shell tool: the matched command's return record. Codex sends no separate event
    for a command that fails: its exit code is read from the tool response, which is an object
    holding `exit_code` (0.142.5's rows), or text, or a list of text items. In text it is either the
    line 'Process exited with code <n>' (0.142.5) or, after the line 'Output:', a JSON object holding
    `exit_code` (0.162.x, after 'Script completed' and 'Wall time'). A non-zero code is a failed call;
    a response with no exit code readable is `failed`, class `unreadable`, never `served`.
  * Any other PreToolUse or PostToolUse writes an error line naming its tool: a hook runs only for the
    tools its matcher admits, so a tool event that reaches the capture and is not recorded is a fault
    to see, never noise.

The shell tool's payloads were reconstructed from a rollout's `exec_command` rows, since Codex runs
no hook it does not trust; the shapes read here are those rows' (the tool name, `cmd` and `workdir`
in the input, the output text).

A failure at any stage writes one error line through ledger.error(), naming the session, call id and
event read from the raw payload before anything else.
"""

import base64
import contextlib
import io
import json
import os
import re
import shlex
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

import capture_claude_code as shared  # noqa: E402
import ledger  # noqa: E402
import transcripts  # noqa: E402

HARNESS = 'codex'
DISPATCH_AGENT = 'unrecorded (not yet returned)'
SUBAGENT_COST = 'unrecorded (the harness reports no cost for a subagent)'
NOT_A_SCRIPT = 'unrecorded (not a call script)'
ON_DISPATCH_BRIEF = shared.ON_DISPATCH_BRIEF
# How often the rollout is re-read while its last turn has not ended. No limit is set on the wait.
REREAD_SECONDS = 0.1
EXIT_LINE = re.compile(r'Process exited with code (-?\d+)')
OUTPUT_LINE = re.compile(r'(?m)^Output:[ \t]*$')
NO_EXIT_CODE = {'class': 'unreadable', 'text': 'the response carries no exit code'}
NOT_RECORDED = 'not a tool this capture records'
NO_SPAWN_EVENT = 'unrecorded (the harness sent no dispatch event for this subagent)'
ENCRYPTED = 'unrecorded (the harness passed the brief encrypted)'
# A Fernet token, the form of the encrypted message Codex 0.162.x passed to its subagent: base64url text whose
# first decoded byte is 0x80, then a timestamp, an IV, the ciphertext and a 32-byte HMAC.
FERNET = re.compile(r'gAAAAA[A-Za-z0-9_-]{50,}={0,2}')
_ARRIVAL = {}


class Held(shared.Held):
    """What an error line names, read from the raw payload before any other work."""

    def __init__(self, event, payload):
        shared.Held.__init__(self, event, payload)
        payload = payload if isinstance(payload, dict) else {}
        agent = payload.get('agent_id') or response_of(payload).get('agent_id')
        self.agent_id = shared._text(agent, 'unrecorded (no agent id in %s)' % self.event)

    def error(self, folder, stage, reason, record='unknown'):
        ledger.error(ledger=folder, stage=stage, reason=reason, session=self.session,
                     call_id=self.call_id, agent_id=self.agent_id, harness=HARNESS, event=self.event,
                     record=record, payload_keys=self.keys)


def response_of(payload):
    """`tool_response`, which Codex sends as a JSON string; a dict, or {} if it is neither."""
    response = payload.get('tool_response') if isinstance(payload, dict) else None
    if isinstance(response, str):
        try:
            response = json.loads(response)
        except ValueError:
            return {}
    return response if isinstance(response, dict) else {}


# ---------------------------------------------------------------------------
# Entry points
# ---------------------------------------------------------------------------

def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    folder = None
    if '--ledger' in argv:
        at = argv.index('--ledger')
        folder = argv[at + 1] if at + 1 < len(argv) else None
        del argv[at:at + 2]
    event = argv[0] if argv else None
    try:
        text = sys.stdin.read()
    except Exception as exc:  # standard input itself could not be read
        text = None
        Held(event, None).error(folder, 'payload', 'standard input could not be read: %s' % exc)
    if text is not None:
        with contextlib.redirect_stdout(io.StringIO()):
            handle(event, text, folder)
    return 0


def handle(event, text, folder=None):
    """Handle one hook event's payload text. Never raises; every failure is an error line."""
    _ARRIVAL['at'] = time.monotonic()
    try:
        payload = json.loads(text)
        if not isinstance(payload, dict):
            raise ValueError('the payload is not a JSON object')
    except (TypeError, ValueError) as exc:
        shown = 'empty' if not (text or '').strip() else 'not JSON'
        Held(event, None).error(folder, 'payload', 'the payload on standard input is %s: %s' % (shown, exc))
        return
    held = Held(event, payload)
    try:
        folder = ledger.ledger_folder(folder)
        _route(event, payload, folder, held)
    except Exception as exc:  # the capture's own fault: recorded, never raised to the hook
        held.error(folder, 'payload', 'the capture failed: %s: %s' % (type(exc).__name__, exc))


def _route(event, payload, folder, held):
    tool = payload.get('tool_name')
    if event == 'PreToolUse' and tool in subagent_tools():
        return pre_spawn(payload, folder, held)
    if event == 'PostToolUse' and tool in subagent_tools():
        return post_spawn(payload, folder, held)
    if event == 'PreToolUse' and tool in shared.shell_tools(HARNESS):
        return pre_shell(payload, folder, held)
    if event == 'PostToolUse' and tool in shared.shell_tools(HARNESS):
        return post_shell(payload, folder, held)
    if event == 'SubagentStart':
        return subagent_start(payload, folder, held)
    if event == 'SubagentStop':
        return subagent_stop(payload, folder, held)
    if event in ('PreToolUse', 'PostToolUse'):
        # Never dropped silently: the hook ran because its matcher admitted the tool.
        held.error(folder, 'payload', '%s on %s: %s' % (event, tool if isinstance(tool, str) and tool else
                                                        'a tool the payload does not name', NOT_RECORDED))
    return None


def subagent_tools():
    """The names of Codex's subagent tool, from subagent-tools.json."""
    names = shared.harness_entry(HARNESS).get('tools')
    return tuple(name for name in names if isinstance(name, str)) if isinstance(names, list) else ()


# ---------------------------------------------------------------------------
# The events
# ---------------------------------------------------------------------------

def common(payload, route='subagent'):
    return {
        'session': payload.get('session_id') if isinstance(payload.get('session_id'), str) and payload.get('session_id')
        else 'unrecorded (session_id absent from the payload)',
        'harness': HARNESS,
        'route': route,
        'caller': 'parent',
        'project': shared.project_of(payload.get('cwd')),
    }


def auth_route():
    """CODEX_HOME and whether OPENAI_API_KEY is set: names, never values."""
    home = os.environ.get('CODEX_HOME')
    key = 'set' if os.environ.get('OPENAI_API_KEY') else 'not set'
    return 'CODEX_HOME %s; OPENAI_API_KEY %s' % (home if home else '~/.codex (the default)', key)


def pre_spawn(payload, folder, held):
    if held.call_id.startswith('unrecorded ('):
        held.error(folder, 'payload', 'no call_id (tool_use_id absent from PreToolUse)', record='dispatch')
        return
    given = payload.get('tool_input') if isinstance(payload.get('tool_input'), dict) else {}
    message = given.get('message') if isinstance(given.get('message'), str) else ''
    if not message:
        held.error(folder, 'payload', 'tool_input.message absent from PreToolUse', record='dispatch')
    encrypted = is_ciphertext(message)
    brief, source = (message, None) if encrypted else shared.brief_of(message, payload.get('cwd'))
    asked = given.get('model')
    at = ledger.now()
    fields = common(payload)
    fields.update({
        'call_id': held.call_id,
        'agent_id': DISPATCH_AGENT,
        'dispatched_at': at,
        'model_requested': asked if isinstance(asked, str) and asked else None,
        'auth_route': auth_route(),
        'brief_source': ENCRYPTED if encrypted else source,
        'effort_assigned': shared.effort_assigned_of(HARNESS, payload.get('tool_name'), payload),
    })
    found, seconds = shared.dispatch_kind(folder, brief if source else message, held)
    fields.update(found)
    fields['harness_payload'] = shared.with_triage_time(payload, seconds)
    fields['user_answer'] = shared.user_answer_of(folder, HARNESS, held.session, fields.get('caller'),
                                                  payload.get('transcript_path'), fields['act_kind'],
                                                  brief if source else message)
    with shared.pending_lock(folder, held.session):
        shared.write_pending(folder, held.session, held.call_id,
                             {'call_id': held.call_id, 'dispatched_at': at, 'awaiting_agent': True,
                              'order': time.time_ns()})
    ledger.dispatch(ledger=folder, brief=brief or None, prompt=message if source and message else None,
                    **fields)


def is_ciphertext(text):
    """Whether a brief is a Fernet token, as Codex 0.162.x passed its subagent's message."""
    if not isinstance(text, str) or not FERNET.fullmatch(text.strip()):
        return False
    try:
        raw = base64.urlsafe_b64decode(text.strip() + '=' * (-len(text.strip()) % 4))
    except ValueError:
        return False
    return len(raw) >= 57 and raw[0] == 0x80


def command_of(payload):
    """The shell command a payload carries: `tool_input.cmd` or `command`, a string or an argument list."""
    given = payload.get('tool_input') if isinstance(payload.get('tool_input'), dict) else {}
    command = given.get('cmd') if given.get('cmd') is not None else given.get('command')
    if isinstance(command, list) and all(isinstance(word, str) for word in command):
        if len(command) >= 3 and command[1] in ('-c', '-lc'):
            return command[2]
        return ' '.join(shlex.quote(word) for word in command)
    return command if isinstance(command, str) else None


def _code(value):
    return value if isinstance(value, int) and not isinstance(value, bool) else None


def response_text(response):
    """The text of a shell tool's response given as a string or a list of text items, or None."""
    if isinstance(response, str):
        return response
    if isinstance(response, list):
        parts = []
        for item in response:
            if isinstance(item, str):
                parts.append(item)
            elif isinstance(item, dict) and isinstance(item.get('text'), str):
                parts.append(item['text'])
        return '\n'.join(parts) if parts else None
    return None


def result_object(text):
    """The first JSON object in `text` holding `exit_code`, or None."""
    decoder = json.JSONDecoder()
    at = text.find('{')
    while at != -1:
        try:
            found, _ = decoder.raw_decode(text, at)
        except ValueError:
            found = None
        if isinstance(found, dict) and 'exit_code' in found:
            return found
        at = text.find('{', at + 1)
    return None


def shell_output(response):
    """(the command's output, its exit code or None) from the shell tool's response."""
    if isinstance(response, dict):
        code = response.get('exit_code', response.get('exitCode'))
        for key in ('output', 'aggregated_output', 'stdout', 'formatted_output'):
            if isinstance(response.get(key), str):
                return response[key], _code(code)
        return json.dumps(response, ensure_ascii=False), _code(code)
    text = response_text(response)
    if text is None:
        return '', None
    found = EXIT_LINE.search(text)
    if found:
        output = text.split('\nOutput:\n', 1)[1] if '\nOutput:\n' in text else text
        return output, int(found.group(1))
    marker = OUTPUT_LINE.search(text)
    after = text[marker.end():].lstrip('\n') if marker else text
    result = result_object(after)
    if result is not None:
        output = result.get('output') if isinstance(result.get('output'), str) else after
        return output, _code(result.get('exit_code'))
    return after, None


def pre_shell(payload, folder, held):
    shared.cli_dispatch(folder, held, command_of(payload), common(payload, route='cli'), payload, HARNESS,
                        auth_route, 'PreToolUse')


def post_shell(payload, folder, held):
    raw = payload.get('tool_response')
    if isinstance(raw, str):
        try:
            parsed = json.loads(raw)
        except ValueError:
            parsed = None
        raw = parsed if isinstance(parsed, (dict, list)) else raw
    output, code = shell_output(raw)
    kept = dict(payload)
    text = response_text(raw)
    if text is not None:
        # Kept as the header and the output, so the output, which is the answer, is moved to its file
        # like any other answer.
        marker = OUTPUT_LINE.search(text)
        kept['tool_response'] = {'header': text[:marker.start()] if marker else '', 'output': output,
                                 'exit_code': code if code is not None else 'unrecorded (none readable)'}
    shared.cli_return(folder, held, common(payload, route='cli'), command_of(payload), output, code, kept,
                      no_code=NO_EXIT_CODE)


def store_join(folder, session, agent, data):
    """Keep the join of call id to agent id for the SubagentStop that writes the return."""
    shared.write_join(folder, session, agent, data)


def post_spawn(payload, folder, held):
    response = response_of(payload)
    agent = response.get('agent_id')
    with shared.pending_lock(folder, held.session):
        sent = shared.read_pending(folder, held.session, held.call_id)
        if isinstance(agent, str) and agent:
            earlier = shared.read_join(folder, held.session, agent)
            if earlier and earlier.get('call_id') not in (None, held.call_id):
                # A SubagentStart joined this agent to another waiting spawn before this response named it.
                # The response is the harness's own word, so that spawn waits again.
                other = shared.read_pending(folder, held.session, earlier['call_id'])
                if other is not None:
                    shared.write_pending(folder, held.session, earlier['call_id'],
                                         dict(other, awaiting_agent=True))
            store_join(folder, held.session, agent, {'call_id': held.call_id, 'tool_response': response})
            if sent is not None:
                shared.write_pending(folder, held.session, held.call_id, dict(sent, awaiting_agent=False))
            return
        joined = join_naming(folder, held.session, held.call_id)
        if joined is not None:
            # SubagentStart came first and joined this spawn: its response goes with the join.
            name, data = joined
            shared.write_pending(folder, held.session, name, dict(data, tool_response=response or
                                                                  payload.get('tool_response')))
            return
        if sent is None:
            held.error(folder, 'payload', 'the spawn\'s response names no agent and its PreToolUse was not seen, '
                       'so no SubagentStart can be joined to it', record='return')
            return
        # No agent named: the spawn waits for the next SubagentStart, its response kept for the return.
        shared.write_pending(folder, held.session, held.call_id,
                             dict(sent, awaiting_agent=True, tool_response=response or payload.get('tool_response')))


def join_naming(folder, session, call_id):
    """(the pending file's name, its data) of the join that names `call_id`, or None."""
    for path in sorted(shared.pending_dir(folder, session).glob('join-*.json')):
        try:
            data = json.loads(path.read_text(encoding='utf-8'))
        except (OSError, ValueError):
            continue
        if isinstance(data, dict) and data.get('call_id') == call_id:
            return path.stem, data
    return None


def oldest_waiting(folder, session):
    """The pending data of the oldest spawn in the session still waiting for an agent, by dispatch order."""
    waiting = []
    for path in shared.pending_dir(folder, session).glob('*.json'):
        if path.name.startswith(('join-', 'cli-', 'stop-')):
            continue
        try:
            data = json.loads(path.read_text(encoding='utf-8'))
        except (OSError, ValueError):
            continue
        if isinstance(data, dict) and data.get('awaiting_agent') and data.get('call_id'):
            waiting.append(data)
    waiting.sort(key=lambda data: (str(data.get('dispatched_at') or ''), data.get('order') or 0,
                                   str(data['call_id'])))
    return waiting[0] if waiting else None


def subagent_start(payload, folder, held):
    if held.agent_id.startswith('unrecorded ('):
        held.error(folder, 'payload', 'agent_id absent from SubagentStart', record='witness')
    ledger.witness(ledger=folder, event='SubagentStart', session=held.session, agent_id=held.agent_id,
                   call_id='unrecorded (not carried by SubagentStart)', at=ledger.now())
    if held.agent_id.startswith('unrecorded ('):
        return
    agent = held.agent_id
    with shared.pending_lock(folder, held.session):
        if shared.read_join(folder, held.session, agent):
            return  # the spawn's response named this agent
        waiting = oldest_waiting(folder, held.session)
        if waiting is not None:
            data = {'call_id': waiting['call_id'], 'tool_response': waiting.get('tool_response'),
                    'joined_at': 'SubagentStart, by dispatch order'}
            store_join(folder, held.session, agent, data)
            shared.write_pending(folder, held.session, waiting['call_id'], dict(waiting, awaiting_agent=False))
            return
        called, _ = shared.agent_called(folder, held.session, agent)
        if called:
            return  # a further turn of an agent whose call the ledger already holds
        dispatch_from_start(payload, folder, held, agent)


def dispatch_from_start(payload, folder, held, agent):
    """The dispatch of a subagent whose spawn sent no event: written at its SubagentStart, under the lock."""
    at = ledger.now()
    fields = common(payload)
    fields.update({
        'call_id': agent,
        'agent_id': agent,
        'dispatched_at': at,
        'model_requested': None,
        'auth_route': auth_route(),
        'brief_path': NO_SPAWN_EVENT,
        'brief_source': NO_SPAWN_EVENT,
        'harness_payload': payload,
    })
    shared.write_pending(folder, held.session, agent, {'call_id': agent, 'dispatched_at': at,
                                                       'awaiting_agent': False})
    store_join(folder, held.session, agent, {'call_id': agent, 'tool_response': None,
                                             'joined_at': 'SubagentStart, no spawn event'})
    ledger.dispatch(ledger=folder, **fields)


def subagent_stop(payload, folder, held):
    if held.agent_id.startswith('unrecorded ('):
        held.error(folder, 'payload', 'agent_id absent from SubagentStop', record='witness')
    ledger.witness(ledger=folder, event='SubagentStop', session=held.session, agent_id=held.agent_id,
                   call_id='unrecorded (not carried by SubagentStop)', at=ledger.now())
    if held.agent_id.startswith('unrecorded ('):
        return
    agent = held.agent_id
    with shared.pending_lock(folder, held.session):
        join = shared.read_join(folder, held.session, agent)
    if not join or not join.get('call_id'):
        # Nothing pending for this agent. If the ledger already holds a return naming it, this is a further
        # stop after its call returned, and the witness line above records it. Otherwise a call may be
        # missing. A dispatch alone does not count here: on Codex only a SubagentStart's own dispatch names
        # the agent, and it writes its join with it, so such a dispatch with no join and no return is a call
        # missing its return.
        called, unread = shared.agent_called(folder, held.session, agent, records=('return',))
        if called:
            return
        if unread:
            held.error(folder, 'payload', 'no pending join for agent %s, and the ledger could not be read to '
                       'find an earlier call to it: %s' % (agent, unread), record='return')
        else:
            held.error(folder, 'payload', 'no pending join for agent %s: its PostToolUse on the subagent tool '
                       'was not seen, so the return cannot be joined to a call' % agent, record='return')
        return
    call_id = join['call_id']
    answer = payload.get('last_assistant_message')
    if not isinstance(answer, str):
        held.error(folder, 'payload', 'last_assistant_message absent from SubagentStop', record='return')
        answer = ''
    path = payload.get('agent_transcript_path')
    if not isinstance(path, str) or not path:
        held.error(folder, 'payload', 'agent_transcript_path absent from SubagentStop', record='return')
        path = None
    turn = payload.get('turn_id') if isinstance(payload.get('turn_id'), str) else None
    wait_for_rollout(path, answer, turn)
    waited = round(time.monotonic() - _ARRIVAL.get('at', time.monotonic()), 3)
    fields = common(payload)
    fields.update({'call_id': call_id, 'agent_id': agent, 'cost': SUBAGENT_COST,
                   'spend_line': NOT_A_SCRIPT})
    fields.update(from_rollout(path, waited))
    fields.update(dict(zip(('outcome', 'outcome_reason'), rollout_outcome(path, answer))))
    with shared.pending_lock(folder, held.session):
        sent = shared.read_pending(folder, held.session, call_id)
        if sent and sent.get('dispatched_at'):
            fields['dispatched_at'] = sent['dispatched_at']
        kept = dict(payload)
        kept['post_tool_use_response'] = join.get('tool_response')
        fields['harness_payload'] = kept
        ledger.ret(ledger=folder, answer=answer, **fields)
        shared.clear_pending(folder, held.session, [call_id, 'join-' + agent])


def wait_for_rollout(path, answer, turn=None):
    """Re-read the rollout until the stop's turn holds the answer and the counter row after it.

    No limit of the capture's own: the harness's time-out on hooks is the only bound.
    """
    if not path:
        return
    while not transcripts.codex_complete(path, answer, turn):
        time.sleep(REREAD_SECONDS)


def from_rollout(path, waited):
    """model, tokens, effort and isolation from the subagent's own rollout."""
    if not path:
        why = 'unrecorded (agent_transcript_path absent from SubagentStop)'
        return {'model': why, 'tokens': why, 'effort': why, 'isolation': why}
    reading = transcripts.read(path)
    if reading['error']:
        why = 'unrecorded (%s)' % reading['error']
        return {'model': why, 'tokens': why, 'effort': why, 'isolation': why}
    tokens = reading['tokens']
    if isinstance(tokens, dict):
        tokens = dict(tokens, read_after_seconds=waited)
    return {'model': reading['model'] or 'unrecorded (the rollout names no model)',
            'tokens': tokens,
            'effort': reading.get('effort') or 'unrecorded (the rollout records no effort)',
            'isolation': transcripts.isolation(reading)}


def rollout_outcome(path, answer):
    """served or empty from the answer; failed where the rollout's last turn was aborted."""
    aborted = None
    if path:
        try:
            for row in transcripts.rows_of(path):
                payload = row.get('payload') if isinstance(row.get('payload'), dict) else {}
                if row.get('type') == 'event_msg' and payload.get('type') == 'turn_aborted':
                    aborted = payload
                elif row.get('type') == 'event_msg' and payload.get('type') == 'task_started':
                    aborted = None
        except OSError:
            pass
    if aborted is not None:
        text = aborted.get('reason') if isinstance(aborted.get('reason'), str) else json.dumps(aborted)
        return 'failed', ledger.reason_for(HARNESS, text, fallback='harness_error')
    return shared.agent_outcome('completed', answer)


if __name__ == '__main__':
    sys.exit(main())
