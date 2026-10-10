#!/usr/bin/env python3
"""Claude Code's capture: every hook event runs it, and it writes the call records through ledger.py.

    python3 capture_claude_code.py <event> [--ledger <folder>]

with the hook's payload on standard input. It prints nothing on standard output and exits 0 on every
path, including a payload that is empty or is not JSON, so it never blocks or changes a call. It
imposes no time limit.

What each event does:

  * PreToolUse on Agent or Task: the dispatch record. A pending file,
    <ledger>/.pending/<session>/<tool_use_id>.json, holds what the return needs.
  * PreToolUse on SendMessage, which resumes a subagent or sends it a message: a dispatch record, route
    subagent, the message as its brief. Its agent is the one `to` names when the ledger already holds
    that agent id; otherwise the record says the message is addressed to something else. The return
    is written at that agent's next SubagentStop, as a background call's is. PostToolUse on
    SendMessage keeps the tool response for it; PostToolUseFailure writes a failed return.
  * SubagentStart: a witness line, and a pending file keyed by the agent id.
  * PostToolUse on Agent or Task, a foreground call: the return record. The tool response is the one
    payload carrying both the call id and the agent id. The model, the four counters and the
    isolation evidence are read from the subagent's own transcript, at the path SubagentStop stored
    or at <CLAUDE_CONFIG_DIR or ~/.claude>/projects/*/<session>/subagents/agent-<id>.jsonl.
  * PostToolUse on Agent or Task, a background call: only the join of call id to agent id, since
    the subagent is still running.
  * SubagentStop: a witness line. For a background call, and for each message sent to the agent, the
    return record, joined through the pending files; for a foreground call, the transcript path and
    effort level are stored for the PostToolUse that follows.
  * PreToolUse on Bash (the shell tool subagent-tools.json names): a dispatch record, route cli, when
    the command matches cli-patterns.json.
  * PostToolUse on Bash: the return record for a matched command, which exited 0. Claude Code sends
    a command that exits non-zero to PostToolUseFailure instead, which writes a failed return. Where
    the command printed a `claude -p --output-format json` envelope naming its session, the inner
    session's own transcript is read for the model, the four counters and the isolation evidence:
    under the CLAUDE_CONFIG_DIR the command set, or else the calling session's configuration folder.
    A transcript that is absent, or that does not carry the envelope's result, leaves each of them
    unrecorded, saying why.

A background return waits until the subagent's own transcript shows it has ended, re-reading it with
no limit of its own; the harness's time-out on hooks is the only bound. It has ended at the first of:
its final request stopped for a reason other than tool_use and holds the answer SubagentStop reports;
its final request is a call to one of the harness's hand-back tools (subagent-tools.json), whose
input at the tool's answer key is then the answer; or the transcript does not exist when SubagentStop
fires, so the harness kept none, and the model and counters read that it kept none. The wait is
recorded as `tokens.read_after_seconds`.

The brief's frontmatter gives `persona-name`, `act_kind`, `user_answer` and `task`, each at the key of
the same name unless `config.json`'s `frontmatter` map names another; a map replaces a default key by
key. Every dispatch record carries `act_kind`, the kind of act the call performs: the brief's value,
translated through the file `config.json`'s
`kind_names` names (each kind in kinds.json to the value a brief gives for it). A brief value that
is already one of the kinds is kept. A value that is neither is `unrecorded (<value> is not a
kind)`, with an error line at stage `setting`, and the record is still written. A brief naming no
kind, or a command-line call, is unrecorded, saying so.

Where `config.json` names a `triage_command`, it runs at each subagent dispatch (Agent, Task and
SendMessage here; spawn_agent in Codex; task in OpenCode) and at each call.py call, never at a
command-line call or a script's own model request. It gets the brief on standard input and, in its
environment, SUBAGENT_LEDGER_CALL_ID (the dispatch's call id), SUBAGENT_LEDGER_SESSION,
SUBAGENT_LEDGER_DIR and SUBAGENT_LEDGER_SCRIPTS; it prints one JSON object, {"kind": "<a kind or
none>", "reason": "<text>"}. Its reading is `triage_kind`: the kind, `unrecorded (the triage read
none)`, `unrecorded (no triage ran)` where no command is named, or `unrecorded (the triage failed:
<why>)` for a non-zero exit, output that is not one JSON object, or a name not in kinds.json.
`act_kind` is then the brief's kind where the brief names one, otherwise the triage's when it read
one, otherwise unrecorded with the reason. The triage's run time is `triage_seconds` in
harness_payload. It is given no time limit, and it never stops or changes the call: whatever it
does, the dispatch record is written.

`effort_assigned` is the effort the dispatching agent set for this call, read from the tool's input
at the key subagent-tools.json names (`effort_keys`); `unrecorded (the agent set no effort for this
call)` where it set none, and `unrecorded (the harness lets the caller set no effort for this call)`
where the tool has no such key. The session's own effort level is never read for it.

For a call of the kind `user-decision`, `user_answer` notes whether the user answered first: the
caller's transcript (`transcript_path`) is read for an answered AskUserQuestion call between the
caller's previous dispatch in the ledger (or the start of the transcript) and this PreToolUse. The
brief's own statement, at the key `frontmatter` names for `user_answer`, is kept beside it as
`agent_record` and never read as the evidence. Any other kind reads `none (not a user decision)`.
Reading it never stops, delays or changes the call.

A failure at any stage writes one error line through ledger.error(), naming the session, call id
and event read from the raw payload before anything else.
"""

import contextlib
import datetime
import fcntl
import glob
import io
import json
import os
import re
import shlex
import subprocess
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

import commands  # noqa: E402
import ledger  # noqa: E402
import transcripts  # noqa: E402

HARNESS = 'claude-code'
SUBAGENT_TOOLS = ('Agent', 'Task')
RESUME_TOOL = 'SendMessage'
PATTERNS_FILE = HERE / 'cli-patterns.json'
KINDS_FILE = HERE / 'kinds.json'
TOOLS_FILE = HERE / 'subagent-tools.json'
PENDING = '.pending'
AUTH_VARIABLES = ('ANTHROPIC_API_KEY', 'CLAUDE_CODE_OAUTH_TOKEN', 'ANTHROPIC_AUTH_TOKEN',
                  'CLAUDE_CODE_USE_BEDROCK', 'CLAUDE_CODE_USE_VERTEX')
FRONTMATTER_FIELDS = ('persona-name', 'act_kind', 'task')
# The brief's frontmatter keys read when config.json has no `frontmatter` map; a map replaces them key by key.
DEFAULT_FRONTMATTER = {'act_kind': 'act_kind', 'user_answer': 'user_answer', 'persona-name': 'persona-name',
                       'task': 'task'}
NO_KIND = 'unrecorded (the brief names no kind; no triage ran)'
NO_KIND_CLI = 'unrecorded (the command names no kind; no triage ran)'
# The triage: a command named by config.json's `triage_command`, run at each subagent or call-script
# dispatch with the brief on standard input. It prints {"kind": "<a kind or none>", "reason": "<text>"}.
TRIAGE_SETTING = 'triage_command'
CALL_ID_VARIABLE = 'SUBAGENT_LEDGER_CALL_ID'
SESSION_VARIABLE = 'SUBAGENT_LEDGER_SESSION'
SCRIPTS_VARIABLE = 'SUBAGENT_LEDGER_SCRIPTS'
NO_TRIAGE = 'unrecorded (no triage ran)'
TRIAGE_READ_NONE = 'unrecorded (the triage read none)'
TRIAGE_FAILED = 'unrecorded (the triage failed: %s)'
NO_KIND_TRIAGE_NONE = 'unrecorded (the brief names no kind; the triage read none)'
NO_KIND_TRIAGE_FAILED = 'unrecorded (the brief names no kind; the triage failed)'
TRIAGE_REASON_LIMIT = 300
# effort_assigned: the effort the dispatching agent set for this call, read from the dispatch tool's
# input at the key subagent-tools.json names for that tool (`effort_keys`).
NO_EFFORT_SETTING = 'unrecorded (the harness lets the caller set no effort for this call)'
NO_EFFORT_SET = 'unrecorded (the agent set no effort for this call)'
NO_TRANSCRIPT_KEPT = 'unrecorded (the harness kept no transcript for this subagent)'
USER_DECISION = 'user-decision'
NOT_A_DECISION = 'none (not a user decision)'
# Each harness's tool for putting a question to the user and getting the answer back.
QUESTION_TOOLS = {'claude-code': 'AskUserQuestion'}
DISPATCH_AGENT = 'unrecorded (not yet returned)'
CLI_AGENT = 'unrecorded (no agent: cli call)'
SUBAGENT_COST = 'unrecorded (the harness reports no cost for a subagent)'
NOT_A_SCRIPT = 'unrecorded (not a call script)'
EMPTY_REASON = {'class': 'empty_answer', 'text': 'the call was served and its answer was empty'}
COUNTER_NAMES = (('input', 'input_tokens'), ('cache_write', 'cache_creation_input_tokens'),
                 ('cache_read', 'cache_read_input_tokens'), ('output', 'output_tokens'))
ABSENT_FROM_BRIEF = {
    'persona-name': 'unrecorded (the brief names no persona)',
    'act_kind': NO_KIND,
    'task': 'unrecorded (the brief names no task)',
}
# A background call's transcript may still be written when SubagentStop fires, so its counters are
# read only once the transcript shows the subagent has ended (see wait_for_end). The capture sets no
# limit on that wait: the harness's own time-out on hooks is the only bound. This is how often it
# re-reads.
REREAD_SECONDS = 0.1
NAMED_IN_PROMPT = re.compile(r'''[^\s'"`()<>|;,]+''')
_ARRIVAL = {}


class Held:
    """What an error line names, read from the raw payload before any other work."""

    def __init__(self, event, payload):
        payload = payload if isinstance(payload, dict) else {}
        response = payload.get('tool_response') if isinstance(payload.get('tool_response'), dict) else {}
        self.event = event or 'unrecorded (no event named on the command line)'
        self.session = _text(payload.get('session_id'), 'unrecorded (session_id absent from %s)' % self.event)
        self.call_id = _text(payload.get('tool_use_id'), 'unrecorded (tool_use_id absent from %s)' % self.event)
        agent = payload.get('agent_id') or response.get('agentId')
        self.agent_id = _text(agent, 'unrecorded (no agent id in %s)' % self.event)
        self.keys = sorted(str(key) for key in payload)

    def error(self, folder, stage, reason, record='unknown'):
        ledger.error(ledger=folder, stage=stage, reason=reason, session=self.session,
                     call_id=self.call_id, agent_id=self.agent_id, harness=HARNESS, event=self.event,
                     record=record, payload_keys=self.keys)


def _text(value, absent):
    return value if isinstance(value, str) and value else absent


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
        Held(event, None).error(folder, 'payload', 'the payload on standard input is %s: %s'
                                % (shown, exc))
        return
    held = Held(event, payload)
    try:
        folder = ledger.ledger_folder(folder)
        _route(event, payload, folder, held)
    except Exception as exc:  # the capture's own fault: recorded, never raised to the hook
        held.error(folder, 'payload', 'the capture failed: %s: %s' % (type(exc).__name__, exc))


def _route(event, payload, folder, held):
    tool = payload.get('tool_name')
    if event == 'PreToolUse' and tool in SUBAGENT_TOOLS:
        return pre_agent(payload, folder, held)
    if event == 'PostToolUse' and tool in SUBAGENT_TOOLS:
        return post_agent(payload, folder, held)
    if event == 'PostToolUseFailure' and tool in SUBAGENT_TOOLS + (RESUME_TOOL,):
        return post_agent_failure(payload, folder, held)
    if event == 'PreToolUse' and tool == RESUME_TOOL:
        return pre_resume(payload, folder, held)
    if event == 'PostToolUse' and tool == RESUME_TOOL:
        return post_resume(payload, folder, held)
    if event == 'SubagentStart':
        return subagent_start(payload, folder, held)
    if event == 'SubagentStop':
        return subagent_stop(payload, folder, held)
    if event == 'PreToolUse' and tool in shell_tools(HARNESS):
        return pre_shell(payload, folder, held)
    if event in ('PostToolUse', 'PostToolUseFailure') and tool in shell_tools(HARNESS):
        return post_shell(event, payload, folder, held)
    return None


def harness_entry(harness):
    """The harness's entry in subagent-tools.json. Raises if the file cannot be read: the capture's
    own fault, written as an error line by handle()."""
    entry = json.loads(TOOLS_FILE.read_text(encoding='utf-8'))['harnesses'].get(harness)
    return entry if isinstance(entry, dict) else {}


def shell_tools(harness):
    """The names of the harness's shell tools, from subagent-tools.json."""
    names = harness_entry(harness).get('shell_tools')
    return tuple(name for name in names if isinstance(name, str)) if isinstance(names, list) else ()


def handback_tools(harness):
    """{tool name: the input key holding the answer} for the harness's hand-back tools."""
    out = {}
    for item in harness_entry(harness).get('handback') or []:
        if isinstance(item, dict) and isinstance(item.get('tool'), str) and isinstance(item.get('answer_key'), str):
            out[item['tool']] = item['answer_key']
    return out


# ---------------------------------------------------------------------------
# The Agent tool
# ---------------------------------------------------------------------------

def pre_agent(payload, folder, held):
    if held.call_id.startswith('unrecorded ('):
        held.error(folder, 'payload', 'no call_id (tool_use_id absent from PreToolUse)', record='dispatch')
        return
    given = payload.get('tool_input') if isinstance(payload.get('tool_input'), dict) else {}
    prompt = given.get('prompt') if isinstance(given.get('prompt'), str) else ''
    brief, source = brief_of(prompt, payload.get('cwd'))
    at = ledger.now()
    fields = common(payload, folder, route='subagent')
    fields.update({
        'call_id': held.call_id,
        'agent_id': DISPATCH_AGENT,
        'dispatched_at': at,
        'model_requested': given.get('model') if isinstance(given.get('model'), str) and given.get('model') else None,
        'auth_route': auth_route(),
        'brief_source': source,
        'effort_assigned': effort_assigned_of(HARNESS, payload.get('tool_name'), payload),
    })
    found, seconds = dispatch_kind(folder, brief if source else prompt, held)
    fields.update(found)
    fields['harness_payload'] = with_triage_time(payload, seconds)
    fields['user_answer'] = user_answer_of(folder, HARNESS, held.session, fields['caller'],
                                           payload.get('transcript_path'), fields['act_kind'],
                                           brief if source else prompt)
    with pending_lock(folder, held.session):
        write_pending(folder, held.session, held.call_id, {
            'call_id': held.call_id, 'dispatched_at': at,
            'run_in_background': bool(given.get('run_in_background')),
        })
    ledger.dispatch(ledger=folder, brief=brief or None, prompt=prompt if source and prompt else None,
                    **fields)


def subagent_start(payload, folder, held):
    if held.agent_id.startswith('unrecorded ('):
        held.error(folder, 'payload', 'agent_id absent from SubagentStart', record='witness')
    ledger.witness(ledger=folder, event='SubagentStart', session=held.session, agent_id=held.agent_id,
                   call_id='unrecorded (not carried by SubagentStart)', at=ledger.now())
    if held.agent_id.startswith('unrecorded ('):
        return
    with pending_lock(folder, held.session):
        write_pending(folder, held.session, 'agent-' + held.agent_id, {
            'agent_id': held.agent_id, 'agent_type': payload.get('agent_type'),
            'started_at': ledger.now()})


def post_agent(payload, folder, held):
    response = payload.get('tool_response') if isinstance(payload.get('tool_response'), dict) else {}
    agent = response.get('agentId')
    if is_background(response):
        if not isinstance(agent, str) or not agent:
            held.error(folder, 'payload', 'agentId absent from PostToolUse on a background call',
                       record='return')
            return
        with pending_lock(folder, held.session):
            write_join(folder, held.session, agent, {'call_id': held.call_id,
                                                     'caller': common(payload, folder, 'subagent')['caller'],
                                                     'tool_response': response})
        return
    with pending_lock(folder, held.session):
        stop = read_pending(folder, held.session, 'stop-' + agent) if agent else None
        sent = read_pending(folder, held.session, held.call_id)
        if not isinstance(agent, str) or not agent:
            held.error(folder, 'payload', 'agentId absent from PostToolUse', record='return')
            agent_field = 'unrecorded (agentId absent from PostToolUse)'
            path = None
        else:
            agent_field = agent
            path = (stop or {}).get('agent_transcript_path') or transcripts.lane_path(held.session, agent)
        answer = answer_text(response.get('content'))
        outcome, reason = agent_outcome(response.get('status'), answer)
        fields = common(payload, folder, route='subagent')
        fields.update({
            'call_id': held.call_id,
            'agent_id': agent_field,
            'outcome': outcome,
            'outcome_reason': reason,
            'cost': SUBAGENT_COST,
            'spend_line': NOT_A_SCRIPT,
            'effort': effort_from_stop(stop),
        })
        if sent and sent.get('dispatched_at'):
            fields['dispatched_at'] = sent['dispatched_at']
        fields.update(from_transcript(path, response.get('resolvedModel'), response.get('usage')))
        payload_kept = dict(payload)
        payload_kept['tool_response'] = dict(response)
        if 'content' in response:
            payload_kept['tool_response']['content'] = answer
        prompt = (payload.get('tool_input') or {}).get('prompt') if isinstance(payload.get('tool_input'), dict) else None
        fields['harness_payload'] = without_texts(payload_kept, prompt, ON_DISPATCH_BRIEF)
        ledger.ret(ledger=folder, answer=answer, **fields)
        if agent:
            clear_pending(folder, held.session, [held.call_id, 'agent-' + agent, 'stop-' + agent,
                                                 'join-' + agent])
        else:
            clear_pending(folder, held.session, [held.call_id])


def post_agent_failure(payload, folder, held):
    """A subagent call the harness reports as failed: a failed return, class harness_error."""
    with pending_lock(folder, held.session):
        sent = read_pending(folder, held.session, held.call_id)
        text = payload.get('error') if isinstance(payload.get('error'), str) else 'the harness reported a failure'
        fields = common(payload, folder, route='subagent')
        fields.update({
            'call_id': held.call_id,
            'agent_id': 'unrecorded (no agent id in PostToolUseFailure)',
            'outcome': 'failed',
            'outcome_reason': ledger.reason_for(HARNESS, text),
            'cost': SUBAGENT_COST, 'spend_line': NOT_A_SCRIPT,
            'model': 'unrecorded (the call failed before a transcript could be joined)',
            'tokens': 'unrecorded (the call failed before a transcript could be joined)',
            'effort': 'unrecorded (no SubagentStop was joined to this call)',
            'isolation': 'unrecorded (the call failed before a transcript could be joined)',
            'harness_payload': without_texts(payload, (payload.get('tool_input') or {}).get('prompt'), ON_DISPATCH_BRIEF),
        })
        if sent and sent.get('dispatched_at'):
            fields['dispatched_at'] = sent['dispatched_at']
        ledger.ret(ledger=folder, **fields)
        clear_pending(folder, held.session, [held.call_id, 'resume-' + held.call_id])


# ---------------------------------------------------------------------------
# SendMessage: a message to a subagent, which resumes it if it has stopped
# ---------------------------------------------------------------------------

def message_text(value):
    if isinstance(value, str):
        return value
    return json.dumps(value, ensure_ascii=False) if value is not None else ''


def agent_known(folder, session, agent):
    """Whether the session's ledger, or its pending files, already hold this agent id."""
    target = pending_dir(folder, session)
    if (target / ('agent-%s.json' % _safe(agent))).is_file() or (target / ('join-%s.json' % _safe(agent))).is_file():
        return True
    path = Path(folder) / ('%s.jsonl' % session)
    try:
        lines = path.read_text(encoding='utf-8', errors='replace').splitlines() if path.is_file() else []
    except OSError:
        return False
    for line in lines:
        if agent not in line:
            continue
        try:
            row = json.loads(line)
        except ValueError:
            continue
        if isinstance(row, dict) and row.get('agent_id') == agent:
            return True
    return False


def agent_called(folder, session, agent):
    """(whether a dispatch or return record in the session's ledger names this agent id, the read error).

    Witness lines are not counted: a witness names an agent whether or not its call was recorded. The read
    error is None when the ledger was read, or holds no file yet."""
    path = Path(folder) / ('%s.jsonl' % session)
    if not path.exists():
        return False, None
    try:
        text = path.read_text(encoding='utf-8', errors='replace')
    except OSError as exc:
        return False, '%s: %s' % (type(exc).__name__, exc)
    for line in text.splitlines():
        if agent not in line:
            continue
        try:
            row = json.loads(line)
        except ValueError:
            continue
        if isinstance(row, dict) and row.get('agent_id') == agent and row.get('record') in ('dispatch', 'return'):
            return True, None
    return False, None


def pre_resume(payload, folder, held):
    if held.call_id.startswith('unrecorded ('):
        held.error(folder, 'payload', 'no call_id (tool_use_id absent from PreToolUse)', record='dispatch')
        return
    given = payload.get('tool_input') if isinstance(payload.get('tool_input'), dict) else {}
    to = given.get('to')
    message = message_text(given.get('message'))
    known = isinstance(to, str) and to and agent_known(folder, held.session, to)
    if known:
        agent_field = to
    else:
        agent_field = 'unrecorded (the message is addressed to %s, not an agent id this ledger holds)' % (
            to if isinstance(to, str) and to else 'no one named')
    at = ledger.now()
    fields = common(payload, folder, route='subagent')
    fields.update({
        'call_id': held.call_id,
        'agent_id': agent_field,
        'dispatched_at': at,
        'model_requested': None,
        'auth_route': auth_route(),
        'brief_source': None,
        'effort_assigned': effort_assigned_of(HARNESS, payload.get('tool_name'), payload),
    })
    found, seconds = dispatch_kind(folder, message, held)
    fields.update(found)
    fields['harness_payload'] = with_triage_time(payload, seconds)
    fields['user_answer'] = user_answer_of(folder, HARNESS, held.session, fields['caller'],
                                           payload.get('transcript_path'), fields['act_kind'], message)
    with pending_lock(folder, held.session):
        write_pending(folder, held.session, held.call_id, {'call_id': held.call_id, 'dispatched_at': at})
        if known:
            write_pending(folder, held.session, 'resume-' + held.call_id, {
                'call_id': held.call_id, 'agent_id': to, 'dispatched_at': at,
                'caller': fields['caller']})
    ledger.dispatch(ledger=folder, brief=message or None, **fields)


def post_resume(payload, folder, held):
    """Keep the tool response for the return written at the agent's next stop; write nothing yet."""
    response = payload.get('tool_response')
    with pending_lock(folder, held.session):
        kept = read_pending(folder, held.session, 'resume-' + held.call_id)
        if kept is None:
            return
        kept['tool_response'] = response
        write_pending(folder, held.session, 'resume-' + held.call_id, kept)


def read_resumes(folder, session, agent):
    """The messages sent to this agent still waiting for its next stop: (pending name, data), oldest first."""
    found = []
    for path in sorted(pending_dir(folder, session).glob('resume-*.json')):
        try:
            data = json.loads(path.read_text(encoding='utf-8'))
        except (OSError, ValueError):
            continue
        if isinstance(data, dict) and data.get('agent_id') == agent and isinstance(data.get('call_id'), str):
            found.append((path.stem, data))
    return sorted(found, key=lambda item: item[1].get('dispatched_at') or '')


def subagent_stop(payload, folder, held):
    if held.agent_id.startswith('unrecorded ('):
        held.error(folder, 'payload', 'agent_id absent from SubagentStop', record='witness')
    ledger.witness(ledger=folder, event='SubagentStop', session=held.session, agent_id=held.agent_id,
                   call_id='unrecorded (not carried by SubagentStop)', at=ledger.now())
    if held.agent_id.startswith('unrecorded ('):
        return
    agent = held.agent_id
    stop = {'agent_transcript_path': payload.get('agent_transcript_path'),
            'effort': (payload.get('effort') or {}).get('level') if isinstance(payload.get('effort'), dict) else None,
            'last_assistant_message': payload.get('last_assistant_message'),
            'stopped_at': ledger.now(), 'payload': payload}
    with pending_lock(folder, held.session):
        join = read_join(folder, held.session, agent)
        resumes = read_resumes(folder, held.session, agent)
        background = agent in background_ids(payload)
        if join is None and not resumes and background:
            # Nothing pending for this agent. If the ledger already holds a call to it, the agent was
            # resumed and has stopped once more than it was called: the witness line above records the
            # stop, and no call is missing. Otherwise its PostToolUse join was never written: no guessed
            # record, but an error line, since a call may truly be missing.
            called, unread = agent_called(folder, held.session, agent)
            if called:
                return
            if unread:
                held.error(folder, 'payload', 'no pending join for background agent %s, and the ledger could '
                           'not be read to find an earlier call to it: %s' % (agent, unread), record='return')
            else:
                held.error(folder, 'payload', 'no pending join for background agent %s: its PostToolUse '
                           'was not seen, so the return cannot be joined to a call' % agent, record='return')
            return
        if join is None and not background:
            # A foreground call: keep what the PostToolUse that follows needs; never the answer text.
            kept = dict(stop)
            kept.pop('last_assistant_message', None)
            kept.pop('payload', None)
            write_pending(folder, held.session, 'stop-' + agent, kept)
        if join is None and not resumes:
            return
        ending = background_ending(folder, held, agent, stop)
        if join is not None:
            if not join.get('call_id'):
                held.error(folder, 'payload', 'no pending join for background agent %s' % agent, record='return')
            else:
                write_background_return(folder, held, agent, stop, join, ending,
                                        [join['call_id'], 'agent-' + agent, 'stop-' + agent, 'join-' + agent])
        for name, data in resumes:
            write_background_return(folder, held, agent, stop, data, ending, [data['call_id'], name])


def background_ending(folder, held, agent, stop):
    """How the subagent's run ended, read from its transcript once it shows the end: the answer, how it
    was read, and the transcript's path. Called under the pending lock."""
    payload = stop.get('payload') or {}
    answer = stop.get('last_assistant_message')
    answer = answer if isinstance(answer, str) else ''
    path = stop.get('agent_transcript_path')
    if not path:
        if payload:
            held.error(folder, 'payload', 'agent_transcript_path absent from SubagentStop', record='return')
        path = transcripts.lane_path(held.session, agent)
    answer, how = wait_for_end(path, answer, handback_tools(HARNESS))
    if how != 'handback' and 'last_assistant_message' not in payload and payload:
        held.error(folder, 'payload', 'last_assistant_message absent from SubagentStop', record='return')
    return {'answer': answer, 'how': how, 'path': path,
            'seconds': round(time.monotonic() - _ARRIVAL.get('at', time.monotonic()), 3)}


def write_background_return(folder, held, agent, stop, join, ending, cleared):
    """The return record of a background call, or of a message sent to the agent, at SubagentStop.
    Called under the pending lock."""
    payload = stop.get('payload') or {}
    call_id = join['call_id']
    response = join.get('tool_response')
    response = response if isinstance(response, dict) else {}
    sent = read_pending(folder, held.session, call_id)
    answer = ending['answer']
    outcome, reason = agent_outcome('completed', answer)
    fields = common(payload or {'cwd': None, 'agent_id': None}, folder, route='subagent')
    fields['caller'] = join.get('caller') or fields['caller']
    fields.update({
        'call_id': call_id,
        'agent_id': agent,
        'outcome': outcome,
        'outcome_reason': reason,
        'cost': SUBAGENT_COST,
        'spend_line': NOT_A_SCRIPT,
        'effort': stop.get('effort') or 'unrecorded (effort.level absent from SubagentStop)',
    })
    if sent and sent.get('dispatched_at'):
        fields['dispatched_at'] = sent['dispatched_at']
    elif join.get('dispatched_at'):
        fields['dispatched_at'] = join['dispatched_at']
    if ending['how'] == 'no transcript':
        fields.update({'model': NO_TRANSCRIPT_KEPT, 'tokens': NO_TRANSCRIPT_KEPT, 'isolation': NO_TRANSCRIPT_KEPT})
    else:
        fields.update(from_transcript(ending['path'], response.get('resolvedModel'), None))
    if isinstance(fields.get('tokens'), dict):
        fields['tokens']['read_after_seconds'] = ending['seconds']
    kept = dict(payload)
    kept['post_tool_use_response'] = join.get('tool_response')
    if isinstance(kept.get('last_assistant_message'), str) and ending['how'] != 'handback':
        kept['last_assistant_message'] = answer
    fields['harness_payload'] = without_texts(kept, response.get('prompt'), ON_DISPATCH_BRIEF)
    ledger.ret(ledger=folder, answer=answer, **fields)
    clear_pending(folder, held.session, cleared)


def wait_for_end(path, answer, handbacks):
    """(the answer, how the run's end was read), once the transcript shows the subagent has ended.

    It re-reads the transcript with no limit of its own, and ends at the first of: the transcript does
    not exist (`no transcript`), so the harness kept none; the final request is a call to a hand-back
    tool (`handback`), whose input at its answer key is the answer; the final request stopped for a
    reason other than tool_use and holds `answer` (`text`). With no path to read it returns at once
    (`no path`).
    """
    if not path:
        return answer, 'no path'
    if not os.path.exists(str(path)):
        return answer, 'no transcript'
    while True:
        found = transcript_end(path, answer, handbacks)
        if found is not None:
            return found
        time.sleep(REREAD_SECONDS)


def final_request(path):
    """The rows of the transcript's final request, grouped by message id, or None."""
    try:
        rows = transcripts.rows_of(path)
    except OSError:
        return None
    groups, order = {}, []
    for position, row in enumerate(row for row in rows if transcripts._usage(row) is not None):
        key = transcripts._group_key(row, position)
        if key not in groups:
            groups[key] = []
            order.append(key)
        groups[key].append(row)
    return groups[order[-1]] if order else None


def transcript_end(path, answer, handbacks):
    """(answer, how) when the final request ends the run, else None."""
    for row in final_request(path) or []:
        content = (row.get('message') or {}).get('content')
        for part in content if isinstance(content, list) else []:
            if isinstance(part, dict) and part.get('type') == 'tool_use' and part.get('name') in handbacks:
                given = part.get('input') if isinstance(part.get('input'), dict) else {}
                value = given.get(handbacks[part['name']])
                return (value if isinstance(value, str) else message_text(value)), 'handback'
    return (answer, 'text') if transcript_complete(path, answer) else None


def transcript_complete(path, answer):
    """True when the final request carries `answer` and stopped for a reason other than tool_use."""
    last = final_request(path)
    if last is None:
        return False
    reasons = [(row.get('message') or {}).get('stop_reason') for row in last]
    stopped = [reason for reason in reasons if reason is not None]
    if not stopped or 'tool_use' in stopped:
        return False
    wanted = (answer or '').strip()
    if not wanted:
        return True
    said = []
    for row in last:
        content = (row.get('message') or {}).get('content')
        if isinstance(content, list):
            said.extend(part.get('text', '') for part in content
                        if isinstance(part, dict) and isinstance(part.get('text'), str))
    return wanted in '\n'.join(said)


def is_background(response):
    return response.get('isAsync') is True or response.get('status') == 'async_launched'


def background_ids(payload):
    tasks = payload.get('background_tasks')
    if not isinstance(tasks, list):
        return set()
    return set(task.get('id') for task in tasks if isinstance(task, dict) and task.get('type') == 'subagent')


def agent_outcome(status, answer):
    if status == 'completed':
        if answer.strip():
            return 'served', 'none (served)'
        return 'empty', dict(EMPTY_REASON)
    text = status if isinstance(status, str) and status else 'the tool response carried no status'
    return 'failed', {'class': 'harness_error', 'text': text[:ledger.REASON_LIMIT]}


def answer_text(content):
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return '\n'.join(part.get('text', '') for part in content
                         if isinstance(part, dict) and isinstance(part.get('text'), str))
    return ''


def effort_from_stop(stop):
    if stop is None:
        return 'unrecorded (effort.level absent: no SubagentStop was seen for this agent)'
    return stop.get('effort') or 'unrecorded (effort.level absent from SubagentStop)'


def from_transcript(path, resolved, usage):
    """model, tokens and isolation from the subagent's transcript; the checks beside them."""
    if not path:
        why = 'unrecorded (the subagent transcript was not found)'
        return {'model': why, 'tokens': why, 'isolation': why}
    reading = transcripts.read(path)
    if reading['error']:
        why = 'unrecorded (%s)' % reading['error']
        return {'model': why, 'tokens': why, 'isolation': why}
    out = {'model': reading['model'] or 'unrecorded (the transcript names no model)',
           'tokens': dict(reading['tokens']),
           'isolation': transcripts.isolation(reading)}
    if isinstance(resolved, str) and resolved and reading['model'] and resolved != reading['model']:
        out['model_check'] = {'harness': resolved, 'transcript': reading['model']}
    if isinstance(usage, dict) and reading['last_request']:
        hook = dict((label, usage.get(native)) for label, native in COUNTER_NAMES)
        last = reading['last_request']
        differ = dict((label, hook[label] - last[label]) for label, _ in COUNTER_NAMES
                      if isinstance(hook[label], int) and hook[label] != last[label])
        if differ:
            out['tokens']['counter_check'] = {'hook_last_request': hook, 'transcript_last_request': last,
                                              'difference': differ}
    return out


# ---------------------------------------------------------------------------
# The Bash route: command-line model calls
# ---------------------------------------------------------------------------

def load_patterns():
    return json.loads(PATTERNS_FILE.read_text(encoding='utf-8'))


def match_command(command, patterns=None):
    """The pattern entry and the part of the command that make a model call, or (None, None)."""
    if not isinstance(command, str) or not command.strip():
        return None, None
    patterns = patterns or load_patterns()
    # The split is commands.py's: at shell operators outside quotes, with here-document bodies set
    # aside, so a quoted `|` or a here-document line is never a command.
    for part in commands.parts(command):
        words = part.words
        if not words:
            continue
        program = part.program
        args = words[1:]
        for entry in patterns['patterns']:
            if program != entry['program']:
                continue
            if any(word in patterns['not_a_call'] for word in args):
                continue
            marked = any(word in entry['flags'] for word in args) or (
                args and args[0] in entry['subcommands'])
            if marked:
                return entry, words
    return None, None


def requested_model(words, entry):
    for at, word in enumerate(words):
        for flag in entry.get('model_flags', []):
            if word == flag and at + 1 < len(words):
                return words[at + 1]
            if word.startswith(flag + '='):
                return word.split('=', 1)[1]
    return None


def pre_shell(payload, folder, held):
    given = payload.get('tool_input') if isinstance(payload.get('tool_input'), dict) else {}
    cli_dispatch(folder, held, given.get('command'), common(payload, folder, route='cli'), payload,
                 HARNESS, auth_route, 'PreToolUse')


def cli_dispatch(folder, held, command, fields, payload, harness, own_auth, event):
    """The dispatch record of a command-line model call made through a harness's shell tool.

    Nothing is written when the command makes no model call by cli-patterns.json. `fields` holds the
    session, harness, caller and project of the calling harness; `own_auth` gives the sign-in route
    when the command runs that same harness, whose sign-in the capture can read.
    """
    entry, words = match_command(command)
    if entry is None:
        return
    if held.call_id.startswith('unrecorded ('):
        held.error(folder, 'payload', 'no call_id (the call id is absent from %s)' % event, record='dispatch')
        return
    at = ledger.now()
    fields = dict(fields, route='cli')
    fields.update({
        'call_id': held.call_id,
        'agent_id': CLI_AGENT,
        'dispatched_at': at,
        'model_requested': requested_model(words, entry),
        'auth_route': own_auth() if entry['harness'] == harness else
        'unrecorded (the command runs %s, whose sign-in this capture does not read)' % entry['program'],
        'brief_source': 'unrecorded (the brief is the command itself)',
        'harness_payload': payload,
    })
    fields.update(optional_fields(folder, None, held, cli=True))
    fields['user_answer'] = NOT_A_DECISION
    with pending_lock(folder, held.session):
        write_pending(folder, held.session, 'cli-' + held.call_id,
                      {'call_id': held.call_id, 'dispatched_at': at, 'program': entry['program'],
                       'harness': entry['harness']})
    ledger.dispatch(ledger=folder, brief=command, **fields)


def cli_return(folder, held, fields, command, output, exit_code, kept):
    """The return record of a matched command-line call, from what the shell tool gave back.

    `output` is the command's printed output and `exit_code` its exit code, or None where the harness
    reports none. Where the output is a JSON result envelope, the model, outcome and cost come from
    it; otherwise a non-zero exit is `failed`, its class read from reasons.json, and the model and
    cost read that the output names none. Nothing is written for a command that was not matched.
    """
    with pending_lock(folder, held.session):
        sent = read_pending(folder, held.session, 'cli-' + held.call_id)
        if sent is None:
            return  # not a command-line model call
        output = output if isinstance(output, str) else ''
        fields = dict(fields, route='cli')
        fields.update({
            'call_id': held.call_id, 'agent_id': CLI_AGENT, 'spend_line': NOT_A_SCRIPT,
            'dispatched_at': sent.get('dispatched_at'),
            'effort': 'unrecorded (a command-line call reports no effort to this capture)',
            'tokens': 'unrecorded (a command-line call\'s counters are not read by this capture)',
            'isolation': 'unrecorded (a command-line call\'s own record is not read by this capture)',
        })
        failed = isinstance(exit_code, int) and not isinstance(exit_code, bool) and exit_code != 0
        envelope, _ = envelope_in(output)
        if envelope is not None:
            answer = envelope.get('result') if isinstance(envelope.get('result'), str) else ''
            outcome, reason, model, cost = envelope_fields(envelope)
        else:
            answer = output
            model = 'unrecorded (the command\'s output names no model)'
            cost = 'unrecorded (the command\'s output reports no cost)'
            if failed:
                outcome, reason = 'failed', None
            elif answer.strip():
                outcome, reason = 'served', 'none (served)'
            else:
                outcome, reason = 'empty', dict(EMPTY_REASON)
        if reason is None or (failed and outcome != 'failed'):
            outcome = 'failed'
            reason = ledger.reason_for(sent.get('harness') or HARNESS, output,
                                       'the command exited with code %s' % exit_code)
        fields.update({'outcome': outcome, 'outcome_reason': reason, 'model': model, 'cost': cost})
        fields['harness_payload'] = without_texts(kept, command, ON_DISPATCH_BRIEF)
        ledger.ret(ledger=folder, answer=answer, **fields)
        clear_pending(folder, held.session, ['cli-' + held.call_id])


def post_shell(event, payload, folder, held):
    with pending_lock(folder, held.session):
        sent = read_pending(folder, held.session, 'cli-' + held.call_id)
        if sent is None:
            return  # not a command-line model call
        response = payload.get('tool_response') if isinstance(payload.get('tool_response'), dict) else {}
        fields = common(payload, folder, route='cli')
        fields.update({
            'call_id': held.call_id, 'agent_id': CLI_AGENT, 'spend_line': NOT_A_SCRIPT,
            'dispatched_at': sent.get('dispatched_at'),
            'effort': 'unrecorded (a command-line call reports no effort to this capture)',
            'tokens': 'unrecorded (a command-line call\'s counters are not read by this capture)',
            'isolation': 'unrecorded (a command-line call\'s own record is not read by this capture)',
        })
        kept = dict(payload)
        if event == 'PostToolUseFailure':
            text = payload.get('error') if isinstance(payload.get('error'), str) else ''
            envelope, output = envelope_in(text.split('\n', 1)[1] if '\n' in text else '')
            answer = output
            outcome, reason = 'failed', ledger.reason_for(HARNESS, text) if text else {
                'class': 'other', 'text': 'PostToolUseFailure carried no error text'}
            if envelope is not None:
                _, reason_from_envelope, model, cost = envelope_fields(envelope)
                reason = reason_from_envelope if isinstance(reason_from_envelope, dict) else reason
                answer = envelope.get('result') if isinstance(envelope.get('result'), str) else ''
                fields.update({'model': model, 'cost': cost})
                fields.update(inner_reading(envelope, command_of(payload), payload, model))
                kept['error'] = (text.split('\n', 1)[0] + '\n') if '\n' in text else text
                kept['envelope'] = envelope
            else:
                fields.update({'model': 'unrecorded (the command\'s output names no model)',
                               'cost': 'unrecorded (the command\'s output reports no cost)'})
            fields.update({'outcome': outcome, 'outcome_reason': reason})
        else:
            stdout = response.get('stdout') if isinstance(response.get('stdout'), str) else ''
            envelope, _ = envelope_in(stdout)
            if envelope is not None:
                answer = envelope.get('result') if isinstance(envelope.get('result'), str) else ''
                outcome, reason, model, cost = envelope_fields(envelope)
                kept['tool_response'] = dict(response, stdout=envelope)
            else:
                answer = stdout
                if response.get('interrupted') is True:
                    outcome, reason = 'failed', {'class': 'harness_error',
                                                 'text': 'the command was interrupted'}
                elif answer.strip():
                    outcome, reason = 'served', 'none (served)'
                else:
                    outcome, reason = 'empty', dict(EMPTY_REASON)
                model = 'unrecorded (the command\'s output names no model)'
                cost = 'unrecorded (the command\'s output reports no cost)'
            fields.update({'outcome': outcome, 'outcome_reason': reason, 'model': model, 'cost': cost})
            if envelope is not None:
                fields.update(inner_reading(envelope, command_of(payload), payload, model))
        command = command_of(payload)
        fields['harness_payload'] = without_texts(kept, command, ON_DISPATCH_BRIEF)
        ledger.ret(ledger=folder, answer=answer, **fields)
        clear_pending(folder, held.session, ['cli-' + held.call_id])


def command_of(payload):
    given = payload.get('tool_input') if isinstance(payload.get('tool_input'), dict) else {}
    return given.get('command') if isinstance(given.get('command'), str) else None


def config_set_by(command):
    """The CLAUDE_CONFIG_DIR a command sets before it runs `claude`, or None."""
    found = None
    for part in re.split(r'\|\||&&|;|\||\n', command or ''):
        try:
            words = shlex.split(part)
        except ValueError:
            words = part.split()
        if words and words[0] == 'export':
            words = words[1:]
        for word in words:
            if word.startswith('CLAUDE_CONFIG_DIR='):
                found = os.path.expanduser(word.split('=', 1)[1])
            elif word != 'env' and not re.match(r'^[A-Za-z_][A-Za-z0-9_]*=', word):
                if os.path.basename(word) == 'claude':
                    return found
                break
    return found


def answer_texts(rows):
    """Every text the transcript's messages carry, singly and joined per message id."""
    grouped, order, singles = {}, [], []
    for position, row in enumerate(rows):
        message = row.get('message') if isinstance(row.get('message'), dict) else None
        if message is None:
            continue
        content = message.get('content')
        texts = [content] if isinstance(content, str) else [
            part['text'] for part in content or [] if isinstance(part, dict) and isinstance(part.get('text'), str)]
        if not texts:
            continue
        singles.extend(texts)
        key = message.get('id') if isinstance(message.get('id'), str) else 'row-%d' % position
        if key not in grouped:
            grouped[key] = []
            order.append(key)
        grouped[key].extend(texts)
    return singles + ['\n'.join(grouped[key]) for key in order] + [''.join(grouped[key]) for key in order]


def inner_reading(envelope, command, payload, envelope_model=None):
    """tokens, model and isolation from the inner `claude -p` session's own transcript.

    The transcript is <config>/projects/*/<session_id>.jsonl, where <config> is the CLAUDE_CONFIG_DIR
    the command set, or else the calling session's configuration folder. It is read only when it
    carries the envelope's result: the result is the last thing a `-p` run writes, so a transcript
    holding it is complete, and one that does not may be short.
    """
    session = envelope.get('session_id')
    if not isinstance(session, str) or not session:
        why = 'unrecorded (the envelope names no session, so its transcript cannot be found)'
        return {'tokens': why, 'isolation': why}
    named = config_set_by(command)
    if named:
        folders = [Path(named)]
    else:
        folders = [transcripts.config_folder()]
        path = payload.get('transcript_path')
        if isinstance(path, str) and '/projects/' in path:
            folders.append(Path(path.split('/projects/', 1)[0]))
    found = None
    for folder in folders:
        hits = sorted(glob.glob(str(Path(folder) / 'projects' / '*' / ('%s.jsonl' % glob.escape(session)))))
        if hits:
            found = Path(hits[0])
            break
    if found is None:
        why = 'unrecorded (no transcript for session %s under %s)' % (
            session, ' or '.join(str(Path(folder) / 'projects') for folder in folders))
        return {'tokens': why, 'isolation': why}
    try:
        rows = transcripts.rows_of(found)
    except OSError as exc:
        why = 'unrecorded (the transcript of session %s could not be read: %s)' % (session, exc)
        return {'tokens': why, 'isolation': why}
    result = envelope.get('result')
    wanted = result.strip() if isinstance(result, str) else ''
    if not wanted or not any(wanted in text for text in answer_texts(rows)):
        why = ('unrecorded (the transcript of session %s does not carry the envelope\'s result, so a count '
               'taken from it could be short)' % session)
        return {'tokens': why, 'isolation': why}
    reading = transcripts.read(found)
    if reading['error']:
        why = 'unrecorded (%s)' % reading['error']
        return {'tokens': why, 'isolation': why}
    out = {'tokens': dict(reading['tokens']), 'isolation': transcripts.isolation(reading)}
    if reading['model']:
        out['model'] = reading['model']
        if isinstance(envelope_model, str) and not envelope_model.startswith('unrecorded (') \
                and envelope_model != reading['model']:
            out['model_check'] = {'harness': envelope_model, 'transcript': reading['model']}
    return out


def envelope_in(text):
    """A JSON result envelope printed by the command, and the text it was read from."""
    stripped = (text or '').strip()
    if not stripped.startswith('{'):
        return None, text or ''
    try:
        envelope = json.loads(stripped)
    except ValueError:
        return None, text
    if isinstance(envelope, dict) and ('modelUsage' in envelope or envelope.get('type') == 'result'):
        return envelope, text
    return None, text


def envelope_fields(envelope):
    """outcome, outcome_reason, model and cost from a `--output-format json` envelope."""
    models = envelope.get('modelUsage')
    if isinstance(models, dict) and models:
        model = ', '.join(sorted(models))
    else:
        model = 'unrecorded (the command\'s output names no model)'
    cost = envelope.get('total_cost_usd')
    cost = ({'value': cost, 'currency': 'USD', 'field': 'total_cost_usd'}
            if isinstance(cost, (int, float)) and not isinstance(cost, bool)
            else 'unrecorded (the command\'s output reports no cost)')
    result = envelope.get('result') if isinstance(envelope.get('result'), str) else ''
    terminal = envelope.get('terminal_reason')
    if envelope.get('is_error') is True or (terminal not in (None, 'completed')):
        detail = {'is_error': envelope.get('is_error'), 'terminal_reason': terminal,
                  'api_error_status': envelope.get('api_error_status')}
        return 'failed', ledger.reason_for(HARNESS, result, json.dumps(detail)), model, cost
    if not result.strip():
        return 'empty', dict(EMPTY_REASON), model, cost
    return 'served', 'none (served)', model, cost


# ---------------------------------------------------------------------------
# Fields common to every record, the brief, and the optional fields
# ---------------------------------------------------------------------------

def common(payload, folder, route):
    agent = payload.get('agent_id')
    return {
        'session': payload.get('session_id') if isinstance(payload.get('session_id'), str) and payload.get('session_id')
        else 'unrecorded (session_id absent from the payload)',
        'harness': HARNESS,
        'route': route,
        'caller': agent if isinstance(agent, str) and agent else 'parent',
        'project': project_of(payload.get('cwd')),
    }


def project_of(cwd):
    if not isinstance(cwd, str) or not cwd:
        return 'unrecorded (cwd absent from the payload)'
    for folder in [Path(cwd)] + list(Path(cwd).parents):
        if (folder / '.git').exists():
            return folder.name
    return 'unrecorded (the working folder is in no git repository)'


def auth_route():
    """The route the call authenticates by: the names of the variables set, never their values."""
    named = [name for name in AUTH_VARIABLES if os.environ.get(name)]
    if named:
        return 'environment: %s' % ', '.join(named)
    folder = os.environ.get('CLAUDE_CONFIG_DIR')
    return 'login, configuration folder %s' % (folder if folder else '~/.claude (the default)')


def brief_of(prompt, cwd):
    """The brief and the path the prompt named for it, or the prompt and None.

    Each word of the prompt that could be a path is tried in order: an absolute or ~ path as it
    stands, any other relative to the hook's working folder. The first that is a readable file wins.
    """
    for found in NAMED_IN_PROMPT.findall(prompt or ''):
        candidate = found.rstrip('.,:;!?')
        if not candidate or candidate in ('.', '..'):
            continue
        path = Path(os.path.expanduser(candidate))
        if not path.is_absolute():
            if not isinstance(cwd, str) or not cwd:
                continue
            path = Path(cwd) / path
        try:
            if path.is_file():
                return path.read_text(encoding='utf-8'), candidate
        except (OSError, UnicodeDecodeError, ValueError):
            continue
    return prompt, None


def without_texts(payload, text, marker):
    """The payload with every string equal to `text` replaced by `marker`, so no brief stays inline.

    The writer itself replaces a string equal to a text it copies with `moved to <path>`. This
    covers the case it cannot see: a return record, which carries no brief.
    """
    if not isinstance(text, str) or not text or marker is None:
        return payload

    def walk(node):
        if isinstance(node, str):
            return marker if node == text else node
        if isinstance(node, dict):
            return dict((key, walk(value)) for key, value in node.items())
        if isinstance(node, list):
            return [walk(value) for value in node]
        return node
    return walk(payload)


ON_DISPATCH_BRIEF = 'not kept: the dispatch record copies the brief and names the copy'


def read_config(folder):
    path = Path(folder) / ledger.CONFIG_FILE
    if not path.is_file():
        return {}, path
    data = json.loads(path.read_text(encoding='utf-8'))
    return (data if isinstance(data, dict) else {}), path


def optional_fields(folder, brief, held=None, cli=False):
    """persona-name, act_kind, task and grouping, from the brief's frontmatter.

    `act_kind` is the brief's value translated by kind_of(); a command-line call has no brief to read.
    """
    config, path = read_config(folder)
    keys = frontmatter_keys(config)
    out = {}
    front = frontmatter(brief) if isinstance(brief, str) else {}
    for name in FRONTMATTER_FIELDS:
        value = lookup(front, keys[name]) if keys.get(name) else None
        if not keys.get(name):
            out[name] = 'unrecorded (%s names no frontmatter key for %s)' % (ledger.CONFIG_FILE, name)
        elif isinstance(value, str) and value:
            out[name] = kind_of(folder, value, held) if name == 'act_kind' else value
        else:
            out[name] = ABSENT_FROM_BRIEF[name]
    if cli:
        out['act_kind'] = NO_KIND_CLI
    table_name = config.get('grouping_table')
    persona = out['persona-name']
    if not isinstance(table_name, str) or not table_name:
        out['grouping'] = 'unrecorded (no grouping table in %s)' % ledger.CONFIG_FILE
    elif persona.startswith('unrecorded ('):
        out['grouping'] = 'unrecorded (the brief names no persona)'
    else:
        table_path = Path(table_name) if os.path.isabs(table_name) else path.parent / table_name
        try:
            table = json.loads(table_path.read_text(encoding='utf-8')).get('grouping', {})
        except (OSError, ValueError, AttributeError) as exc:
            out['grouping'] = 'unrecorded (the grouping table could not be read: %s)' % exc
        else:
            found = table.get(persona) or table.get(persona.lower())
            out['grouping'] = found if isinstance(found, str) and found else (
                'unrecorded (%s is not in the grouping table)' % persona)
    return out


def kind_list():
    """The kinds' names from kinds.json, or None when it cannot be read."""
    try:
        return [entry['name'] for entry in json.loads(KINDS_FILE.read_text(encoding='utf-8'))['kinds']]
    except (OSError, ValueError, KeyError, TypeError):
        return None


def is_kind(value):
    """True for a kind's name; False for `unrecorded (...)`, `none (...)` or anything not a string."""
    return isinstance(value, str) and bool(value) and not value.startswith(('unrecorded (', 'none ('))


def _one_line(text):
    text = ' '.join(str(text).split())
    return text if len(text) <= TRIAGE_REASON_LIMIT else text[:TRIAGE_REASON_LIMIT - 3] + '...'


def run_triage(folder, text, held):
    """(triage_kind, seconds the triage ran or None): the command config.json names, run on the brief.

    The command runs through the shell, so it may name a path with variables, with the brief on
    standard input and the call id, the session, the ledger folder and this scripts folder in its
    environment. No time limit is set. Its answer is read by triage_reading(). It never raises: a
    failure is the reading `unrecorded (the triage failed: <why>)`, and the call goes on unchanged.
    """
    try:
        config, _path = read_config(folder)
    except (OSError, ValueError) as exc:
        return TRIAGE_FAILED % _one_line('%s could not be read: %s' % (ledger.CONFIG_FILE, type(exc).__name__)), None
    command = config.get(TRIAGE_SETTING)
    if command is None or command == '':
        return NO_TRIAGE, None
    if not isinstance(command, str):
        return TRIAGE_FAILED % ('%s is not a command line' % TRIAGE_SETTING), None
    env = dict(os.environ)
    env.update({CALL_ID_VARIABLE: str(held.call_id), SESSION_VARIABLE: str(held.session),
                ledger.FOLDER_VARIABLE: str(folder), SCRIPTS_VARIABLE: str(HERE)})
    started = time.monotonic()
    try:
        done = subprocess.run(command, shell=True, input=text if isinstance(text, str) else '',
                              capture_output=True, text=True, env=env)
    except (OSError, ValueError) as exc:
        return (TRIAGE_FAILED % _one_line('it could not be started: %s' % exc),
                round(time.monotonic() - started, 3))
    return triage_reading(done.returncode, done.stdout, done.stderr), round(time.monotonic() - started, 3)


def triage_reading(code, out, err):
    """triage_kind from the triage's exit code and output: a kind, or `unrecorded (<why>)`."""
    try:
        answer = json.loads(out)
    except (TypeError, ValueError):
        answer = None
    reason = answer.get('reason') if isinstance(answer, dict) else None
    if code != 0:
        why = reason if isinstance(reason, str) and reason.strip() else (
            (err or '').strip().splitlines()[-1] if (err or '').strip() else 'it gave no reason')
        return TRIAGE_FAILED % _one_line('it exited %d: %s' % (code, why))
    if not isinstance(answer, dict):
        return TRIAGE_FAILED % 'its output is not one JSON object'
    kind = answer.get('kind')
    if kind == 'none':
        return TRIAGE_READ_NONE
    names = kind_list()
    if names is None:
        return TRIAGE_FAILED % 'kinds.json could not be read'
    if isinstance(kind, str) and kind in names:
        return kind
    if isinstance(kind, str) and kind:
        return TRIAGE_FAILED % _one_line('%s is not a kind' % kind)
    return TRIAGE_FAILED % 'its output names no kind'


def act_kind_of(brief_kind, triage_kind):
    """The kind the record uses: the brief's where it names one, else the triage's, else why neither."""
    if is_kind(brief_kind):
        return brief_kind
    if is_kind(triage_kind):
        return triage_kind
    if brief_kind == NO_KIND:
        if triage_kind == TRIAGE_READ_NONE:
            return NO_KIND_TRIAGE_NONE
        if isinstance(triage_kind, str) and triage_kind.startswith(TRIAGE_FAILED.split('%s')[0]):
            return NO_KIND_TRIAGE_FAILED
    return brief_kind


def dispatch_kind(folder, text, held):
    """The brief's fields for a subagent or call-script dispatch, with the triage's reading.

    Returns (persona-name, act_kind, triage_kind, task and grouping; the seconds the triage ran or None).
    """
    fields = optional_fields(folder, text, held)
    triage_kind, seconds = run_triage(folder, text, held)
    fields['triage_kind'] = triage_kind
    fields['act_kind'] = act_kind_of(fields['act_kind'], triage_kind)
    return fields, seconds


def with_triage_time(payload, seconds):
    """harness_payload with the triage's run time beside it, as `triage_seconds`, when a triage ran."""
    if seconds is None or not isinstance(payload, dict):
        return payload
    return dict(payload, triage_seconds=seconds)


def effort_assigned_of(harness, tool, payload):
    """The effort the dispatching agent set for this call, or why there is none. Never the session's own."""
    try:
        keys = harness_entry(harness).get('effort_keys')
    except (OSError, ValueError, KeyError, TypeError) as exc:
        return 'unrecorded (subagent-tools.json could not be read: %s)' % type(exc).__name__
    key = keys.get(tool) if isinstance(keys, dict) else None
    if not isinstance(key, str) or not key:
        return NO_EFFORT_SETTING
    given = payload.get('tool_input') if isinstance(payload, dict) else None
    value = given.get(key) if isinstance(given, dict) else None
    if isinstance(value, str) and value:
        return value
    return NO_EFFORT_SET


def frontmatter_keys(config):
    """The brief's frontmatter key for each field: the defaults, each replaced where config.json's
    `frontmatter` map names the field."""
    keys = dict(DEFAULT_FRONTMATTER)
    named = config.get('frontmatter') if isinstance(config, dict) else None
    if isinstance(named, dict):
        keys.update((name, key) for name, key in named.items() if isinstance(key, str) or key is None)
    return keys


def kind_names(folder):
    """{kind: the value a brief gives for it} for every kind in kinds.json, and why not where it cannot be read.

    Without `kind_names` in config.json each kind maps to itself. An entry of the named file's `kinds`
    object is either the value itself or an object holding it under `value`.
    """
    try:
        names = [entry['name'] for entry in json.loads(KINDS_FILE.read_text(encoding='utf-8'))['kinds']]
    except (OSError, ValueError, KeyError, TypeError) as exc:
        return None, 'kinds.json could not be read: %s' % type(exc).__name__
    config, path = read_config(folder)
    named = config.get('kind_names')
    if not named:
        return dict((name, name) for name in names), None
    table_path = Path(named) if os.path.isabs(named) else path.parent / named
    try:
        table = json.loads(table_path.read_text(encoding='utf-8'))['kinds']
    except (OSError, ValueError, KeyError, TypeError) as exc:
        return None, 'the kind map %s could not be read: %s' % (named, type(exc).__name__)
    out = {}
    for name in names:
        entry = table.get(name) if isinstance(table, dict) else None
        value = entry.get('value') if isinstance(entry, dict) else entry
        out[name] = value if isinstance(value, str) and value else None
    return out, None


def kind_of(folder, value, held=None):
    """The kind a brief's value names, or `unrecorded (<why>)` with an error line at stage `setting`."""
    table, why = kind_names(folder)
    if table is not None:
        if value in table:
            return value
        found = [name for name, mapped in table.items() if mapped == value]
        if len(found) == 1:
            return found[0]
        why = '%s is not a kind' % value
    reason = why
    if held is not None:
        held.error(folder, 'setting', reason, record='dispatch')
    else:
        ledger.error(ledger=folder, stage='setting', reason=reason, record='dispatch', harness=HARNESS)
    return 'unrecorded (%s)' % reason


def _time(value):
    if not isinstance(value, str):
        return None
    try:
        return datetime.datetime.fromisoformat(value.replace('Z', '+00:00'))
    except ValueError:
        return None


def previous_dispatch_at(folder, session, caller):
    """When the caller last dispatched a call in this session's ledger, or None if it has not.

    A dispatch record whose `caller` is not filled is counted as the caller's, so the window is never
    wider than the ledger can show.
    """
    path = Path(folder) / ('%s.jsonl' % session)
    latest = None
    try:
        rows = path.read_text(encoding='utf-8').splitlines() if path.is_file() else []
    except OSError:
        return None
    for raw in rows:
        try:
            row = json.loads(raw)
        except ValueError:
            continue
        if not isinstance(row, dict) or row.get('record') != 'dispatch':
            continue
        who = row.get('caller')
        if isinstance(who, str) and who and not who.startswith('unrecorded (') and who != caller:
            continue
        at = _time(row.get('dispatched_at'))
        if at is not None and (latest is None or at > latest):
            latest = at
    return latest


def user_answer_of(folder, harness, session, caller, transcript_path, kind, brief):
    """user_answer for a dispatch: the evidence from the caller's transcript, and the agent's own statement."""
    if kind != USER_DECISION:
        return NOT_A_DECISION
    tool = QUESTION_TOOLS.get(harness)
    if not tool:
        return 'unrecorded (no question tool for %s)' % harness
    if not isinstance(transcript_path, str) or not transcript_path:
        return 'unrecorded (transcript_path absent from PreToolUse)'
    try:
        calls = transcripts.question_calls(transcript_path, tool)
    except (OSError, ValueError) as exc:
        return "unrecorded (the caller's transcript could not be read: %s)" % type(exc).__name__
    since = previous_dispatch_at(folder, session, caller)
    found = [call for call in calls if _time(call['asked_at']) is not None
             and (since is None or _time(call['asked_at']) > since)]
    config, _path = read_config(folder)
    keys = frontmatter_keys(config)
    statement = lookup(frontmatter(brief), keys['user_answer']) if (
        isinstance(brief, str) and keys.get('user_answer')) else None
    record = statement if isinstance(statement, str) and statement else 'none'
    if not found:
        return {'answered_first': 'not found', 'question_call': None, 'asked_at': None, 'answered_at': None,
                'agent_record': record}
    latest = max(found, key=lambda call: _time(call['answered_at']) or _time(call['asked_at']))
    return {'answered_first': 'yes', 'question_call': latest['id'], 'asked_at': latest['asked_at'],
            'answered_at': latest['answered_at'], 'agent_record': record}


def frontmatter(text):
    """A brief's YAML frontmatter, read for nested mappings of plain scalars only."""
    lines = text.splitlines()
    if not lines or lines[0].strip() != '---':
        return {}
    root, stack = {}, [(-1, None)]
    stack[0] = (-1, root)
    for line in lines[1:]:
        if line.strip() == '---':
            break
        if not line.strip() or line.lstrip().startswith('#') or line.lstrip().startswith('- '):
            continue
        found = re.match(r'^(\s*)([^:\s][^:]*?):(?:\s+(.*))?$', line)
        if not found:
            continue
        indent, key, value = len(found.group(1)), found.group(2).strip(), (found.group(3) or '').strip()
        while stack and stack[-1][0] >= indent:
            stack.pop()
        parent = stack[-1][1] if stack else root
        if not isinstance(parent, dict):
            continue
        if value == '':
            parent[key] = {}
            stack.append((indent, parent[key]))
        else:
            if len(value) >= 2 and value[0] == value[-1] and value[0] in '\'"':
                value = value[1:-1]
            parent[key] = value
    return root


def lookup(tree, dotted):
    node = tree
    for part in dotted.split('.'):
        if not isinstance(node, dict) or part not in node:
            return None
        node = node[part]
    return node


# ---------------------------------------------------------------------------
# Pending files: what one event leaves for the next
# ---------------------------------------------------------------------------

def _safe(name):
    return re.sub(r'[^A-Za-z0-9._:-]', '_', name)[:200]


def pending_dir(folder, session):
    session = session if session and not session.startswith('unrecorded (') else 'unattributed'
    return Path(folder) / PENDING / _safe(session)


@contextlib.contextmanager
def pending_lock(folder, session):
    target = pending_dir(folder, session)
    target.mkdir(parents=True, exist_ok=True)
    with open(target / '.lock', 'a') as handle:
        fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


def write_pending(folder, session, name, data):
    target = pending_dir(folder, session) / ('%s.json' % _safe(name))
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(data, ensure_ascii=False), encoding='utf-8')


def read_pending(folder, session, name):
    target = pending_dir(folder, session) / ('%s.json' % _safe(name))
    try:
        return json.loads(target.read_text(encoding='utf-8'))
    except (OSError, ValueError):
        return None


def write_join(folder, session, agent, data):
    write_pending(folder, session, 'join-' + agent, data)


def read_join(folder, session, agent):
    return read_pending(folder, session, 'join-' + agent)


def clear_pending(folder, session, names):
    for name in names:
        try:
            (pending_dir(folder, session) / ('%s.json' % _safe(name))).unlink()
        except OSError:
            pass


if __name__ == '__main__':
    sys.exit(main())
