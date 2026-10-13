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
    Every message, whether it was queued for a running agent or resumed a stopped one, is answered by
    the turn it is delivered in, and no response wording is read to tell the two apart: its return is
    written at the first SubagentStop after the message appears in the agent's transcript as
    delivered (a row of a form subagent-tools.json lists under `delivery`, holding its text: a user row,
    or an attachment row of type queued_command), with that turn's answer, counters, model and isolation.
    Where the transcript cannot be read, it is written at the first stop of a turn that started
    (SubagentStart) after the message was sent. A message whose `to` is no agent id the ledger holds,
    and whose response carries no `resumedAgentId`, is addressed to another session: no stop here will
    answer it, so its return is written at its PostToolUse, `served` where the response's `success` is
    true and `failed` otherwise, its answer the response's message.
  * PreToolUse on TaskStop (subagent-tools.json `stop`) naming an agent with a pending call: a pending
    file, `stopped-<agent>`. The agent's stop, waiting for its transcript to end, ends on it, and each
    call still pending for the agent gets its return: `failed`, class `stopped_by_caller`, its answer
    `unrecorded (the caller stopped the subagent)`, its counters from the transcript as it stands.
    PostToolUse on TaskStop writes the same return where none was written. A stop naming no pending
    agent, such as a background shell task, writes nothing.
  * SubagentStart: a witness line, and a pending file keyed by the agent id. Each message still
    waiting for this agent's stop is marked as sent before a turn that started.
  * PostToolUse on Agent or Task, a foreground call: the return record. The tool response is the one
    payload carrying both the call id and the agent id. The model, the four counters and the
    isolation evidence are read from the subagent's own transcript, at the path SubagentStop stored
    or at <CLAUDE_CONFIG_DIR or ~/.claude>/projects/*/<session>/subagents/agent-<id>.jsonl.
  * PostToolUse on Agent or Task, a background call: only the join of call id to agent id, since
    the subagent is still running.
  * SubagentStop: a witness line. For a background call, and for each message sent to the agent, the
    return record, joined through the pending files; for a foreground call, the transcript path and
    effort level are stored for the PostToolUse that follows, while the call has no return record. A
    further stop, after the agent's calls have their returns, writes its witness line and no pending
    file. Writing a return removes the pending files for its call and its agent.
  * PreToolUse on Bash (the shell tool subagent-tools.json names): a dispatch record, route cli, when
    the command makes a model call by cli-patterns.json, read by commands.reading() through wrappers,
    compound commands, here-documents and the script files it runs, read now. One record per tool call;
    `harness_payload.matched` lists the sites found.
  * PreToolUse on WebSearch, WebFetch or an MCP tool (subagent-tools.json `outside_tools`): the dispatch of a
    search, a fetch or an MCP read, routes search, fetch and mcp, its agent `unrecorded (no agent: <route> call)`.
    The brief is the query; the URL, a blank line and the prompt; or the MCP tool's input as JSON. A pending file,
    out-<tool_use_id>, holds the dispatch time for the return. No triage runs. An MCP server config.json's
    `mcp_not_calls` lists writes nothing.
  * PostToolUse or PostToolUseFailure on one of them: its return. A search is served where its results hold a
    title-and-URL item; a fetch by its HTTP code alone (no code: failed, class unreadable); an MCP read where a
    text part is not empty. The failure event's `error` is the reason text.
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
input at the tool's answer key is then the answer; the transcript does not exist when SubagentStop
fires, so the harness kept none, and the model and counters read that it kept none; or the answer
SubagentStop reports appears in a request after the one that preceded this stop's turn. That last
covers a stop read after the agent was resumed, when the resumed run is already in the same file.
The turn is found by what started it: a background dispatch's turn opens the transcript, and a
message's turn starts at the first row of a listed delivery form holding that message. The model, the
counters and the isolation evidence are then that turn's, ending at the request that holds the answer.
The wait is recorded as `tokens.read_after_seconds`.

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
command-line call or a script's own model request. A relative path at the start of its script
argument is resolved against the ledger folder, as `grouping_table` and `kind_names` are; an
absolute path is used as given. It gets the brief on standard input and, in its
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
caller's previous dispatch in the ledger (or the start of the transcript) and this PreToolUse. A
script's own request made for another call, whose record names that call in
`harness_payload.serves_call_id`, is not a dispatch by the caller and does not open the window. The
brief's own statement, at the key `frontmatter` names for `user_answer`, is kept beside it as
`agent_record` and never read as the evidence. Any other kind reads `none (not a user decision)`.
Reading it never stops, delays or changes the call.

A failure at any stage writes one error line through ledger.error(), naming the session, call id
and event read from the raw payload before anything else.
"""

import base64
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
# A subagent its caller stops (TaskStop) mid-tool ends its transcript in that tool call: the wait above ends on a
# `stopped-<agent>` pending file, written at PreToolUse on the stop tool. A test switches this off.
READ_STOPS = True
STOPPED_ANSWER = 'unrecorded (the caller stopped the subagent)'
STOPPED_REASON = {'class': 'stopped_by_caller', 'text': 'the caller stopped the subagent while it ran'}
# A SendMessage whose `to` is no agent id the ledger holds, and whose response names no resumedAgentId, goes to
# another session: its return is written at its PostToolUse. A test switches this off.
MESSAGES_OUTSIDE = True
OUTSIDE_AGENT = 'unrecorded (addressed outside this session: %s)'
OUTSIDE_READING = 'unrecorded (a message to another session: this session holds no record of its run)'
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
    if READ_STOPS and event == 'PreToolUse' and tool in stop_tools(HARNESS):
        return pre_stop(payload, folder, held)
    if READ_STOPS and event == 'PostToolUse' and tool in stop_tools(HARNESS):
        return post_stop(payload, folder, held)
    if event == 'SubagentStart':
        return subagent_start(payload, folder, held)
    if event == 'SubagentStop':
        return subagent_stop(payload, folder, held)
    if event == 'PreToolUse' and tool in shell_tools(HARNESS):
        return pre_shell(payload, folder, held)
    if event in ('PostToolUse', 'PostToolUseFailure') and tool in shell_tools(HARNESS):
        return post_shell(event, payload, folder, held)
    route = outside_route(HARNESS, tool) if event in OUTSIDE_EVENTS else None
    if route == 'mcp' and not_a_call(folder, mcp_server_of(HARNESS, tool, payload.get('mcp_server'))[0]):
        return None  # a server config.json's mcp_not_calls lists: its tools are not calls
    if route is not None and event == 'PreToolUse':
        return pre_outside(payload, folder, held, route)
    if route is not None:
        return post_outside(event, payload, folder, held, route)
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


def stop_tools(harness):
    """{tool name: the input key holding the agent id} for the tools by which a caller stops a subagent."""
    out = {}
    for item in harness_entry(harness).get('stop') or []:
        if isinstance(item, dict) and isinstance(item.get('tool'), str) and isinstance(item.get('agent_key'), str):
            out[item['tool']] = item['agent_key']
    return out


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
        # A turn has started after each message still waiting for this agent's stop: where the transcript
        # cannot be read, the message's return is written at this turn's stop.
        for name, data in read_resumes(folder, held.session, held.agent_id):
            if not data.get('turn_started_after'):
                data['turn_started_after'] = True
                write_pending(folder, held.session, name, data)


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


def agent_called(folder, session, agent, records=('dispatch', 'return')):
    """(whether a record of a kind in `records` in the session's ledger names this agent id, the read error).

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
        if isinstance(row, dict) and row.get('agent_id') == agent and row.get('record') in records:
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
                'caller': fields['caller'], 'message': message})
    ledger.dispatch(ledger=folder, brief=message or None, **fields)


def post_resume(payload, folder, held):
    """Keep the tool response for the return written at the agent's next stop; write nothing yet. A message to
    another session, told by structure alone, has its return written now (outside_return)."""
    response = payload.get('tool_response')
    with pending_lock(folder, held.session):
        kept = read_pending(folder, held.session, 'resume-' + held.call_id)
        if kept is None:
            if MESSAGES_OUTSIDE:
                outside_return(payload, folder, held)
            return
        kept['tool_response'] = response
        write_pending(folder, held.session, 'resume-' + held.call_id, kept)


def outside_return(payload, folder, held):
    """The return of a SendMessage to another session, at its PostToolUse. Called under the pending lock.

    A message is to a subagent where its `to` is an agent id the ledger holds, or its response carries
    `resumedAgentId`; otherwise it is to another session, and no stop of this session will answer it. Its outcome
    is the response's `success`: `served` where true, `failed` otherwise; its answer is the response's message.
    No response wording is read to decide this."""
    given = payload.get('tool_input') if isinstance(payload.get('tool_input'), dict) else {}
    to = given.get('to')
    response = payload.get('tool_response')
    if isinstance(response, str):
        try:
            response = json.loads(response)
        except ValueError:
            pass
    if isinstance(response, dict) and response.get('resumedAgentId'):
        return
    if isinstance(to, str) and to and agent_known(folder, held.session, to):
        return
    if held.call_id.startswith('unrecorded ('):
        held.error(folder, 'payload', 'no call_id (tool_use_id absent from PostToolUse)', record='return')
        return
    if isinstance(response, dict):
        served = response.get('success') is True
        answer = message_text(response.get('message'))
    else:
        served = False
        answer = message_text(response)
    sent = read_pending(folder, held.session, held.call_id)
    fields = common(payload, folder, route='subagent')
    fields.update({
        'call_id': held.call_id,
        'agent_id': OUTSIDE_AGENT % (to if isinstance(to, str) and to else 'no one named'),
        'outcome': 'served' if served else 'failed',
        'outcome_reason': 'none (served)' if served else ledger.reason_for(
            HARNESS, answer, 'the message was not delivered'),
        'cost': SUBAGENT_COST, 'spend_line': NOT_A_SCRIPT,
        'model': OUTSIDE_READING, 'tokens': OUTSIDE_READING, 'isolation': OUTSIDE_READING,
        'effort': OUTSIDE_READING,
        'harness_payload': without_texts(payload, message_text(given.get('message')), ON_DISPATCH_BRIEF),
    })
    if sent and sent.get('dispatched_at'):
        fields['dispatched_at'] = sent['dispatched_at']
    ledger.ret(ledger=folder, answer=answer, **fields)
    clear_pending(folder, held.session, [held.call_id])


# ---------------------------------------------------------------------------
# TaskStop: a caller stops a running subagent
# ---------------------------------------------------------------------------

def stopped_agent(payload):
    given = payload.get('tool_input') if isinstance(payload.get('tool_input'), dict) else {}
    key = stop_tools(HARNESS).get(payload.get('tool_name'))
    agent = given.get(key) if key else None
    return agent if isinstance(agent, str) and agent else None


def pending_call_for(folder, session, agent):
    """Whether a call to this agent is still waiting for its return: a background dispatch joined to it, or a
    message sent to it."""
    return read_join(folder, session, agent) is not None or bool(read_resumes(folder, session, agent))


def pre_stop(payload, folder, held):
    """A stop naming an agent with a pending call writes a `stopped-<agent>` pending file, which ends the wait of
    that agent's stop. A stop naming no pending agent (a background shell task, or an agent already returned)
    writes nothing."""
    agent = stopped_agent(payload)
    if agent is None:
        return
    with pending_lock(folder, held.session):
        if pending_call_for(folder, held.session, agent):
            write_pending(folder, held.session, 'stopped-' + agent,
                          {'agent_id': agent, 'stopped_at': ledger.now(), 'call_id': held.call_id})


def post_stop(payload, folder, held):
    """Where the stopped agent's call still has no return, write it now: the harness may send no SubagentStop."""
    agent = stopped_agent(payload)
    if agent is None:
        return
    with pending_lock(folder, held.session):
        if read_pending(folder, held.session, 'stopped-' + agent) is None:
            return
        write_stopped(folder, held, agent, None, payload)


def write_stopped(folder, held, agent, stop, stop_tool_payload=None):
    """The return of each call still pending for a stopped agent: `failed`, class stopped_by_caller, its counters
    from the transcript as it stands. `stop` is what SubagentStop gave, where the return is written there;
    otherwise `stop_tool_payload` is the stop tool's PostToolUse payload. Called under the pending lock."""
    path = (stop or {}).get('agent_transcript_path') or transcripts.lane_path(held.session, agent)
    payload = (stop or {}).get('payload') or {}
    base = payload or stop_tool_payload or {'cwd': None, 'agent_id': None}
    calls = []
    join = read_join(folder, held.session, agent)
    if join is not None and join.get('call_id'):
        calls.append((join, [join['call_id'], 'join-' + agent]))
    for name, data in read_resumes(folder, held.session, agent):
        calls.append((data, [data['call_id'], name]))
    for data, cleared in calls:
        response = data.get('tool_response') if isinstance(data.get('tool_response'), dict) else {}
        sent = read_pending(folder, held.session, data['call_id'])
        fields = common(base, folder, route='subagent')
        fields['caller'] = data.get('caller') or fields['caller']
        fields.update({
            'call_id': data['call_id'], 'agent_id': agent, 'outcome': 'failed',
            'outcome_reason': dict(STOPPED_REASON), 'cost': SUBAGENT_COST, 'spend_line': NOT_A_SCRIPT,
            'effort': (stop or {}).get('effort') or 'unrecorded (no SubagentStop was joined to this call)',
            'answer_path': STOPPED_ANSWER,
        })
        if sent and sent.get('dispatched_at'):
            fields['dispatched_at'] = sent['dispatched_at']
        elif data.get('dispatched_at'):
            fields['dispatched_at'] = data['dispatched_at']
        if path and os.path.exists(str(path)):
            fields.update(from_transcript(path, response.get('resolvedModel'), None))
        else:
            fields.update({'model': NO_TRANSCRIPT_KEPT, 'tokens': NO_TRANSCRIPT_KEPT, 'isolation': NO_TRANSCRIPT_KEPT})
        kept = dict(payload) if payload else dict(stop_tool_payload or {})
        kept['stopped_by'] = read_pending(folder, held.session, 'stopped-' + agent)
        kept['post_tool_use_response'] = data.get('tool_response')
        kept.pop('last_assistant_message', None)
        fields['harness_payload'] = without_texts(kept, response.get('prompt'), ON_DISPATCH_BRIEF)
        ledger.ret(ledger=folder, **fields)
        clear_pending(folder, held.session, cleared)
    clear_pending(folder, held.session, ['stopped-' + agent, 'agent-' + agent, 'stop-' + agent])


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
                clear_pending(folder, held.session, ['agent-' + agent, 'stop-' + agent])
                return
            if unread:
                held.error(folder, 'payload', 'no pending join for background agent %s, and the ledger could '
                           'not be read to find an earlier call to it: %s' % (agent, unread), record='return')
            else:
                held.error(folder, 'payload', 'no pending join for background agent %s: its PostToolUse '
                           'was not seen, so the return cannot be joined to a call' % agent, record='return')
            return
        kept_for_return = False
        if join is None and not background:
            # A foreground call: keep what the PostToolUse that follows needs, never the answer text, but only
            # while the agent's call has no return record. A further stop after that return writes its witness
            # line above and no pending file, and the agent's own pending files go.
            returned, unread = agent_called(folder, held.session, agent, records=('return',))
            if returned and not unread:
                clear_pending(folder, held.session, ['agent-' + agent, 'stop-' + agent])
            else:
                kept = dict(stop)
                kept.pop('last_assistant_message', None)
                kept.pop('payload', None)
                write_pending(folder, held.session, 'stop-' + agent, kept)
                kept_for_return = True
        if join is None and not resumes:
            return
        starter = turn_starter(join, resumes, kept_for_return)
    # The wait for the transcript runs outside the lock, so the session's other hooks are not held behind it;
    # the lock is taken again only to write, and what is pending is read again then.
    ending = background_ending(folder, held, agent, stop, starter)
    if ending['how'] == 'stopped':
        with pending_lock(folder, held.session):
            if read_pending(folder, held.session, 'stopped-' + agent) is not None:
                write_stopped(folder, held, agent, stop)
        return
    with pending_lock(folder, held.session):
        if join is not None:
            now = read_join(folder, held.session, agent)
            if now is None or now.get('call_id') != join.get('call_id'):
                join = None  # another hook wrote this call's return while the stop waited
        resumes = [(name, read_pending(folder, held.session, name)) for name, _ in resumes]
        resumes = [(name, data) for name, data in resumes if isinstance(data, dict)]
        if join is not None:
            if not join.get('call_id'):
                held.error(folder, 'payload', 'no pending join for background agent %s' % agent, record='return')
            else:
                write_background_return(folder, held, agent, stop, join, ending,
                                        [join['call_id'], 'agent-' + agent, 'stop-' + agent, 'join-' + agent])
        for name, data in resumes:
            # A message is answered by the turn it is delivered in, which may be a later one.
            own = delivered_ending(ending, data)
            if own is None:
                continue
            # The return removes the pending files for its call and its agent, except a stop file just kept
            # for a foreground call whose PostToolUse has not yet come.
            cleared = [data['call_id'], name, 'agent-' + agent]
            if not kept_for_return:
                cleared.append('stop-' + agent)
            write_background_return(folder, held, agent, stop, data, own, cleared)


def turn_starter(join, resumes, foreground=False):
    """What started the turn this stop ends: ('dispatch', None) for a background dispatch, or a foreground call
    still waiting for its return, whose turn opens the transcript; ('resume', <its message>) for the oldest
    message still waiting for a stop; None if neither is known."""
    if join is not None or foreground:
        return ('dispatch', None)
    for _, data in resumes:
        message = data.get('message')
        return ('resume', message) if isinstance(message, str) and message.strip() else None
    return None


def delivered_ending(ending, data):
    """The ending a message's return is written with at this stop, or None where it waits for a later stop.

    Where the transcript can be read, the message has been delivered by this stop when a row of a listed
    delivery form holding it comes before the end of the request that holds this stop's answer; its return
    then takes this stop's answer, and the counters of the turn it was delivered in, from the turn's first
    row to that request. The turn begins after the last request before that row that stopped for a reason
    other than tool_use, or at the transcript's start. Where the transcript cannot be read, it is written at the first stop of a turn
    that started after the message was sent."""
    message = data.get('message')
    rows = None
    if ending['how'] not in ('no transcript', 'no path'):
        try:
            rows = transcripts.rows_of(ending['path'])
        except OSError:
            rows = None
    if rows is None:
        return ending if data.get('turn_started_after') else None
    if not isinstance(message, str) or not message.strip():
        return ending
    delivered = turn_start(rows, ('resume', message))
    end = ending['span'][1] if ending.get('span') else final_request_end(rows)
    if delivered is None or end is None or delivered > end:
        return None
    return dict(ending, span=(turn_begun(rows, delivered), end))


def turn_begun(rows, position):
    """The first row of the turn that row `position` falls in: the row after the last request before it that
    stopped for a reason other than tool_use, or 0."""
    groups, order = {}, []
    for at, row in enumerate(rows[:position]):
        if transcripts._usage(row) is None:
            continue
        key = transcripts._group_key(row, at)
        if key not in groups:
            groups[key] = []
            order.append(key)
        groups[key].append(at)
    begun = 0
    for key in order:
        reasons = [(rows[at].get('message') or {}).get('stop_reason') for at in groups[key]]
        stopped = [reason for reason in reasons if reason is not None]
        if stopped and 'tool_use' not in stopped:
            begun = groups[key][-1] + 1
    return begun


def final_request_end(rows):
    """The last row of the transcript's final request, counted from 0, or None."""
    groups, order = {}, []
    for position, row in enumerate(rows):
        if transcripts._usage(row) is None:
            continue
        key = transcripts._group_key(row, position)
        if key not in groups:
            groups[key] = []
            order.append(key)
        groups[key].append(position)
    return groups[order[-1]][-1] if order else None


def background_ending(folder, held, agent, stop, turn=None):
    """How the subagent's run ended, read from its transcript once it shows the end: the answer, how it
    was read, the transcript's path, and the rows of this stop's turn where the end was read within a turn.
    Called outside the pending lock, so the session's other hooks run while it waits."""
    payload = stop.get('payload') or {}
    answer = stop.get('last_assistant_message')
    answer = answer if isinstance(answer, str) else ''
    path = stop.get('agent_transcript_path')
    if not path:
        if payload:
            held.error(folder, 'payload', 'agent_transcript_path absent from SubagentStop', record='return')
        path = transcripts.lane_path(held.session, agent)
    answer, how, span = wait_for_end(path, answer, handback_tools(HARNESS), turn,
                                     ended=lambda: stop_ended(folder, held.session, agent))
    if how != 'handback' and 'last_assistant_message' not in payload and payload:
        held.error(folder, 'payload', 'last_assistant_message absent from SubagentStop', record='return')
    return {'answer': answer, 'how': how, 'path': path, 'span': span,
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
        fields.update(from_transcript(ending['path'], response.get('resolvedModel'), None, ending.get('span')))
    if isinstance(fields.get('tokens'), dict):
        fields['tokens']['read_after_seconds'] = ending['seconds']
    kept = dict(payload)
    kept['post_tool_use_response'] = join.get('tool_response')
    if isinstance(kept.get('last_assistant_message'), str) and ending['how'] != 'handback':
        kept['last_assistant_message'] = answer
    fields['harness_payload'] = without_texts(kept, response.get('prompt'), ON_DISPATCH_BRIEF)
    ledger.ret(ledger=folder, answer=answer, **fields)
    clear_pending(folder, held.session, cleared)


def stop_ended(folder, session, agent):
    """Whether the wait of this agent's stop should end without reading the transcript's end: its caller stopped it
    (a `stopped-<agent>` pending file), or no call to it is pending any longer, since another hook wrote its
    return."""
    if not READ_STOPS:
        return False
    if read_pending(folder, session, 'stopped-' + agent) is not None:
        return True
    return not pending_call_for(folder, session, agent)


def wait_for_end(path, answer, handbacks, turn=None, ended=None):
    """(the answer, how the run's end was read, the rows of the turn or None), once the transcript shows the
    subagent has ended.

    It re-reads the transcript with no limit of its own, and ends at the first of: the transcript does
    not exist (`no transcript`), so the harness kept none; the final request is a call to a hand-back
    tool (`handback`), whose input at its answer key is the answer; the final request stopped for a
    reason other than tool_use and holds `answer` (`text`); or `answer` appears in a request after the
    one that preceded this stop's turn (`turn`), as when the agent was resumed and its later run is
    already in the file. Then the third value is (first row, last row) of the turn, ending with the
    request that holds the answer, so the counters are that turn's and not the later run's. `turn` says
    what started the turn (see turn_starter); with none, that last check is not made. With no path to
    read it returns at once (`no path`). Where `ended` is given and returns true between reads, the wait ends
    (`stopped`): the caller stopped the subagent, or another hook wrote its return.
    """
    if not path:
        return answer, 'no path', None
    if not os.path.exists(str(path)):
        return answer, 'no transcript', None
    while True:
        found = transcript_end(path, answer, handbacks)
        if found is not None:
            return found + (None,)
        span = answer_in_turn(path, answer, turn)
        if span is not None:
            return answer, 'turn', span
        if ended is not None and ended():
            return answer, 'stopped', None
        time.sleep(REREAD_SECONDS)


def turn_start(rows, turn):
    """The row that starts the turn, counted from 0, or None where it is not found. A dispatch's turn opens
    the transcript. A message's turn starts at the first row of a delivery form subagent-tools.json lists
    whose text holds the message."""
    if turn is None:
        return None
    kind, message = turn
    if kind == 'dispatch':
        return 0
    wanted = message.strip()
    forms = delivery_forms(HARNESS)
    for position, row in enumerate(rows):
        said = delivered_text(row, forms)
        if said is not None and wanted in said:
            return position
    return None


def delivery_forms(harness):
    """[(the values a row must hold, by dotted key; the dotted key of its text)] for the row forms in which the
    harness's transcript shows a message delivered to a subagent, from subagent-tools.json (`delivery`)."""
    out = []
    for item in harness_entry(harness).get('delivery') or []:
        if isinstance(item, dict) and isinstance(item.get('match'), dict) and isinstance(item.get('text_at'), str):
            out.append((item['match'], item['text_at']))
    return out


def value_at(row, dotted):
    """The value at a dotted key of a transcript row, or None."""
    value = row
    for key in dotted.split('.'):
        if not isinstance(value, dict):
            return None
        value = value.get(key)
    return value


def delivered_text(row, forms):
    """The text a row holds as a delivered message, where it is of one of `forms`, else None. The text is a
    string, or a list of parts whose `text` parts are joined."""
    for match, text_at in forms:
        if all(value_at(row, key) == wanted for key, wanted in match.items()):
            content = value_at(row, text_at)
            if isinstance(content, str):
                return content
            if isinstance(content, list):
                return '\n'.join(part.get('text', '') for part in content
                                 if isinstance(part, dict) and part.get('type') == 'text'
                                 and isinstance(part.get('text'), str))
    return None


def answer_in_turn(path, answer, turn):
    """(first row, last row) of the turn when a request after the one that preceded the turn holds `answer`
    in its text, else None. The last row is the last of that request's rows."""
    wanted = (answer or '').strip()
    if not wanted or turn is None:
        return None
    try:
        rows = transcripts.rows_of(path)
    except OSError:
        return None
    start = turn_start(rows, turn)
    if start is None:
        return None
    groups, order = {}, []
    for position, row in enumerate(rows):
        if transcripts._usage(row) is None:
            continue
        key = transcripts._group_key(row, position)
        if key not in groups:
            groups[key] = []
            order.append(key)
        groups[key].append(position)
    for key in order:
        if groups[key][0] < start:
            continue
        said = []
        for position in groups[key]:
            content = (rows[position].get('message') or {}).get('content')
            if isinstance(content, list):
                said.extend(part.get('text', '') for part in content
                            if isinstance(part, dict) and isinstance(part.get('text'), str))
        if wanted in '\n'.join(said):
            return (start, groups[key][-1])
    return None


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


def from_transcript(path, resolved, usage, span=None):
    """model, tokens and isolation from the subagent's transcript, or from one turn of it where `span` names
    that turn's rows; the checks beside them."""
    if not path:
        why = 'unrecorded (the subagent transcript was not found)'
        return {'model': why, 'tokens': why, 'isolation': why}
    reading = transcripts.read(path, span)
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
                 HARNESS, auth_route, 'PreToolUse', cwd=payload.get('cwd'))


def cli_dispatch(folder, held, command, fields, payload, harness, own_auth, event, cwd=None):
    """The dispatch record of a command-line model call made through a harness's shell tool.

    Nothing is written when the command makes no model call by cli-patterns.json, read by commands.reading():
    through wrappers, compound commands, here-documents and the script files the command runs, which are read
    now, resolved against `cwd`. One record is written for the tool call, however many sites it holds;
    `harness_payload.matched` lists them, and `harness_payload.notes` says why a script was not read. `fields`
    holds the session, harness, caller and project of the calling harness; `own_auth` gives the sign-in route
    when every site runs that same harness, whose sign-in the capture can read.
    """
    if not isinstance(command, str) or not command.strip():
        return
    found = commands.reading(command, load_patterns(), cwd)
    if not found.sites:
        return
    if held.call_id.startswith('unrecorded ('):
        held.error(folder, 'payload', 'no call_id (the call id is absent from %s)' % event, record='dispatch')
        return
    at = ledger.now()
    programs = sorted(set(entry['program'] for entry, _ in found.calls))
    hosts = sorted(set(site['host'] for site in found.sites if 'host' in site))
    harnesses = set(entry['harness'] for entry, _ in found.calls)
    single = len(found.calls) == 1 and not hosts
    if harnesses == {harness} and not hosts:
        auth = own_auth()
    else:
        named = ', '.join(programs + hosts)
        auth = 'unrecorded (the command runs %s, whose sign-in this capture does not read)' % named
    kept = dict(payload) if isinstance(payload, dict) else {'payload': payload}
    kept['matched'] = found.sites
    if found.notes:
        kept['notes'] = found.notes
    fields = dict(fields, route='cli')
    fields.update({
        'call_id': held.call_id,
        'agent_id': CLI_AGENT,
        'dispatched_at': at,
        'model_requested': requested_model(found.calls[0][1], found.calls[0][0]) if single else None,
        'auth_route': auth,
        'brief_source': 'unrecorded (the brief is the command itself)',
        'harness_payload': kept,
    })
    fields.update(optional_fields(folder, None, held, cli=True))
    fields['user_answer'] = NOT_A_DECISION
    first = found.calls[0][0] if found.calls else None
    with pending_lock(folder, held.session):
        write_pending(folder, held.session, 'cli-' + held.call_id,
                      {'call_id': held.call_id, 'dispatched_at': at,
                       'program': first['program'] if first else hosts[0],
                       'harness': first['harness'] if first else harness,
                       'wrapped': not (single and found.sites[0]['how'] == 'direct')})
    ledger.dispatch(ledger=folder, brief=command, **fields)


WRAPPED_MODEL = 'unrecorded (a wrapped command\'s output names no single model)'


def cli_return(folder, held, fields, command, output, exit_code, kept, no_code=None):
    """The return record of a matched command-line call, from what the shell tool gave back.

    `output` is the command's printed output and `exit_code` its exit code, or None where the harness
    reports none. Where the output is a JSON result envelope, the model, outcome and cost come from
    it; otherwise a non-zero exit is `failed`, its class read from reasons.json, and the model and
    cost read that the output names none. `no_code`, where given, is the reason for a call whose
    exit code could not be read: such a call is `failed` with it, never `served`. Nothing is written
    for a command that was not matched.
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
            model = WRAPPED_MODEL if sent.get('wrapped') else 'unrecorded (the command\'s output names no model)'
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
        if exit_code is None and no_code is not None:
            outcome, reason = 'failed', dict(no_code)
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
                fields.update({'model': WRAPPED_MODEL if sent.get('wrapped') else
                               'unrecorded (the command\'s output names no model)',
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
                model = WRAPPED_MODEL if sent.get('wrapped') else 'unrecorded (the command\'s output names no model)'
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


# ---------------------------------------------------------------------------
# Searches, fetches and MCP reads: calls with no agent, on the routes search, fetch and mcp
# ---------------------------------------------------------------------------

OUTSIDE_EVENTS = ('PreToolUse', 'PostToolUse', 'PostToolUseFailure')
OUTSIDE_PENDING = 'out-'
NOT_CALLS_SETTING = 'mcp_not_calls'
NO_AGENT_OUTSIDE = 'unrecorded (no agent: %s call)'
OUTSIDE_COST = 'unrecorded (the harness reports no cost for this route)'
# The keys of the tool's input that hold the brief, for the routes whose brief is not the whole input.
BRIEF_KEYS = {'search': ('query',), 'fetch': ('url', 'prompt')}


def outside_route(harness, tool):
    """`search`, `fetch` or `mcp` for a tool subagent-tools.json names among the harness's `outside_tools`, else None.

    An MCP tool is matched here by its prefix (Claude Code, Codex); OpenCode's plugin matches its own by the servers
    its configuration names, and hands the server on."""
    if not isinstance(tool, str) or not tool:
        return None
    rules = harness_entry(harness).get('outside_tools')
    if not isinstance(rules, dict):
        return None
    for route in ('search', 'fetch'):
        names = rules.get(route)
        if isinstance(names, list) and tool in names:
            return route
    rule = rules.get('mcp')
    prefix = rule.get('prefix') if isinstance(rule, dict) else None
    if isinstance(prefix, str) and prefix and tool.startswith(prefix) and len(tool) > len(prefix):
        return 'mcp'
    return None


def mcp_server_of(harness, tool, given=None):
    """(the MCP server's name, where it was read) for an MCP tool: the payload's own `mcp_server.name` where it
    carries one, else the tool name's part between the prefix and the next separator; (None, why) where neither
    names one."""
    if isinstance(given, dict) and isinstance(given.get('name'), str) and given.get('name'):
        return given['name'], 'mcp_server.name'
    rule = (harness_entry(harness).get('outside_tools') or {}).get('mcp')
    prefix = rule.get('prefix') if isinstance(rule, dict) else None
    separator = rule.get('separator') if isinstance(rule, dict) else None
    if isinstance(tool, str) and isinstance(prefix, str) and isinstance(separator, str) and separator \
            and tool.startswith(prefix):
        rest = tool[len(prefix):]
        if separator in rest and rest.split(separator, 1)[0]:
            return rest.split(separator, 1)[0], 'the tool name'
    return None, 'the payload carries no mcp_server.name and the tool name %s names no server' % tool


def not_calls(folder):
    """The server names config.json's `mcp_not_calls` lists: tools of these servers are not calls. A name ending
    in `*` covers every server whose name begins with what precedes it."""
    try:
        config, _path = read_config(folder)
    except (OSError, ValueError):
        return []
    names = config.get(NOT_CALLS_SETTING)
    return [name for name in names if isinstance(name, str) and name] if isinstance(names, list) else []


def not_a_call(folder, server, names=None):
    """Whether an MCP server is one config.json's `mcp_not_calls` lists."""
    if not isinstance(server, str) or not server:
        return False
    for name in not_calls(folder) if names is None else names:
        if name.endswith('*') and server.startswith(name[:-1]):
            return True
        if name == server:
            return True
    return False


def outside_brief(route, given):
    """(the brief, or None; the input key whose absence left none, or None). A search's brief is its query; a
    fetch's its URL, a blank line, then its prompt where the tool takes one; an MCP read's its arguments as JSON."""
    if route == 'mcp':
        return (json.dumps(given, ensure_ascii=False), None) if isinstance(given, dict) else (None, 'the input')
    if route == 'search':
        query = given.get('query') if isinstance(given, dict) else None
        return (query, None) if isinstance(query, str) and query else (None, 'query')
    url = given.get('url') if isinstance(given, dict) else None
    if not isinstance(url, str) or not url:
        return None, 'url'
    prompt = given.get('prompt')
    return (url + '\n\n' + prompt if isinstance(prompt, str) and prompt else url), None


def input_moved(given, route, marker):
    """The tool's input with the keys that hold the brief replaced by `marker`; for an MCP read, the marker alone."""
    if route == 'mcp':
        return marker
    if not isinstance(given, dict):
        return given
    return dict((key, marker if key in BRIEF_KEYS[route] and isinstance(value, str) and value else value)
                for key, value in given.items())


def outside_call_dispatch(folder, held, harness, route, given, kept, input_key, fields, event, server=None):
    """The dispatch record of a search, fetch or MCP read, and its `out-` pending file.

    `given` is the tool's input; `kept` the payload kept as harness_payload, its input at `input_key`; `fields` the
    session, harness, caller and project; `server` (name, where read) for an MCP read. Nothing is written for a call
    with no call id but an error line."""
    if held.call_id.startswith('unrecorded ('):
        held.error(folder, 'payload', 'no call_id (the call id is absent from %s)' % event, record='dispatch')
        return
    brief, absent = outside_brief(route, given)
    kept = dict(kept)
    if brief is not None:
        kept[input_key] = input_moved(given, route, brief)
        brief_path = None
    else:
        brief_path = 'unrecorded (%s absent from %s)' % (absent, event)
        held.error(folder, 'payload', '%s absent from %s' % (absent, event), record='dispatch')
    if server is not None:
        kept['server'] = server[0] if server[0] else 'unrecorded (%s)' % server[1]
    at = ledger.now()
    fields = dict(fields, route=route)
    fields.update(optional_fields(folder, None, held))
    fields.update({
        'call_id': held.call_id,
        'agent_id': NO_AGENT_OUTSIDE % route,
        'dispatched_at': at,
        'model_requested': None,
        'effort_assigned': NO_EFFORT_SETTING,
        'auth_route': 'unrecorded (the payload names no sign-in for a %s call)' % route,
        'brief_source': "unrecorded (the brief is the tool's input)",
        'act_kind': 'unrecorded (a %s call names no kind; no triage ran)' % route,
        'triage_kind': NO_TRIAGE,
        'user_answer': NOT_A_DECISION,
        'harness_payload': kept,
    })
    if brief_path is not None:
        fields['brief_path'] = brief_path
    with pending_lock(folder, held.session):
        write_pending(folder, held.session, OUTSIDE_PENDING + held.call_id,
                      {'call_id': held.call_id, 'dispatched_at': at, 'route': route})
    ledger.dispatch(ledger=folder, brief=brief, **fields)


def outside_call_return(folder, held, route, tool, given, kept, input_key, fields, reading, server=None):
    """The return record of a search, fetch or MCP read, from `reading`: (outcome, outcome_reason, answer or None,
    result_size). The input keys that held the brief read that the dispatch record copies it. Clears the call's
    `out-` pending file."""
    if held.call_id.startswith('unrecorded ('):
        held.error(folder, 'payload', 'no call_id (the call id is absent from the return event)', record='return')
        return
    outcome, reason, answer, size = reading
    kept = without_texts(dict(kept), outside_brief(route, given)[0], ON_DISPATCH_BRIEF)
    if input_key in kept:
        kept[input_key] = input_moved(given, route, ON_DISPATCH_BRIEF)
    kept['result_size'] = size
    if server is not None:
        kept['server'] = server[0] if server[0] else 'unrecorded (%s)' % server[1]
    fields = dict(fields, route=route)
    fields.update({
        'call_id': held.call_id,
        'agent_id': NO_AGENT_OUTSIDE % route,
        'outcome': outcome,
        'outcome_reason': reason,
        'model': 'unrecorded (the %s response names no model)' % tool,
        'effort': 'unrecorded (a %s call reports no effort)' % route,
        'tokens': 'unrecorded (a %s call reports no counters)' % route,
        'cost': OUTSIDE_COST,
        'isolation': 'unrecorded (the capture reads no record of what a %s call touched)' % route,
        'spend_line': NOT_A_SCRIPT,
        'harness_payload': kept,
    })
    with pending_lock(folder, held.session):
        sent = read_pending(folder, held.session, OUTSIDE_PENDING + held.call_id)
        if sent and sent.get('dispatched_at'):
            fields['dispatched_at'] = sent['dispatched_at']
        ledger.ret(ledger=folder, answer=answer if answer else None, **fields)
        clear_pending(folder, held.session, [OUTSIDE_PENDING + held.call_id])


def search_items(results):
    """The count of title-and-URL entries across the content lists of a search's result objects."""
    count = 0
    for item in results:
        content = item.get('content') if isinstance(item, dict) else None
        if isinstance(content, list):
            count += sum(1 for entry in content if isinstance(entry, dict) and 'title' in entry and 'url' in entry)
    return count


def fetch_outcome(response):
    """(outcome, outcome_reason) of a web fetch, from its HTTP code alone: 200 to 299 served, or empty where `bytes`
    is 0; any other code failed, its class read from reasons.json against `HTTP <code> <codeText>`; no code failed,
    class unreadable, never served without evidence."""
    code = response.get('code') if isinstance(response, dict) else None
    if not isinstance(code, int) or isinstance(code, bool):
        return 'failed', {'class': 'unreadable', 'text': 'the fetch response carries no HTTP code'}
    if 200 <= code <= 299:
        if response.get('bytes') == 0:
            return 'empty', dict(EMPTY_REASON)
        return 'served', 'none (served)'
    said = response.get('codeText')
    text = ('HTTP %d %s' % (code, said)) if isinstance(said, str) and said else 'HTTP %d' % code
    return 'failed', ledger.reason_for(HARNESS, text)


def mcp_reading(parts, absent, folder, held, record_key='tool_response', harness=HARNESS):
    """(outcome, outcome_reason, answer, result_size) of an MCP read from its list of parts `{type, text}`, or from
    an object holding that list as `content` (Codex: `{content, isError}`). `isError` true is failed, its class read
    from reasons.json against the text parts joined; otherwise as for a list. A part whose type is not text is not
    written to the answer; its type and count go into result_size. A value that is neither is read as failed, class
    unreadable, with an error line. `absent` names the key and event."""
    if isinstance(parts, str):
        try:
            parts = json.loads(parts)
        except ValueError:
            pass
    is_error = False
    if isinstance(parts, dict) and isinstance(parts.get('content'), list):
        is_error = parts.get('isError') is True
        parts = parts['content']
    if not isinstance(parts, list):
        why = '%s absent from %s' % (record_key, absent) if parts is None else (
            '%s in %s is not a list of parts' % (record_key, absent))
        held.error(folder, 'payload', why, record='return')
        return 'failed', {'class': 'unreadable', 'text': why}, None, 'unrecorded (%s)' % why
    texts = [part['text'] for part in parts if isinstance(part, dict) and part.get('type') == 'text'
             and isinstance(part.get('text'), str)]
    other = {}
    for part in parts:
        if not (isinstance(part, dict) and part.get('type') == 'text' and isinstance(part.get('text'), str)):
            kind = part.get('type') if isinstance(part, dict) and isinstance(part.get('type'), str) else 'unnamed'
            other[kind] = other.get(kind, 0) + 1
    size = {'parts': len(parts), 'text_characters': sum(len(text) for text in texts)}
    if other:
        size['not_text'] = other
    answer = '\n'.join(texts)
    if is_error:
        return 'failed', ledger.reason_for(harness, answer if answer.strip() else
                                           'the MCP tool reported isError true with no text'), None, size
    if any(text.strip() for text in texts):
        return 'served', 'none (served)', answer, size
    return 'empty', dict(EMPTY_REASON), answer, size


def mcp_kept(response, answer):
    """The MCP response as harness_payload keeps it once its answer has been copied: the answer in place of the parts,
    so the writer moves it to its file; an object's other keys (such as `isError`) kept beside it."""
    if isinstance(response, str):
        try:
            response = json.loads(response)
        except ValueError:
            return answer
    if isinstance(response, dict) and isinstance(response.get('content'), list):
        return dict(response, content=answer)
    return answer


def pre_outside(payload, folder, held, route):
    tool = payload.get('tool_name')
    given = payload.get('tool_input') if isinstance(payload.get('tool_input'), dict) else {}
    server = mcp_server_of(HARNESS, tool, payload.get('mcp_server')) if route == 'mcp' else None
    outside_call_dispatch(folder, held, HARNESS, route, given, dict(payload), 'tool_input',
                     common(payload, folder, route), 'PreToolUse', server)


def post_outside(event, payload, folder, held, route):
    """The return of a search, fetch or MCP read, from PostToolUse or PostToolUseFailure."""
    tool = payload.get('tool_name')
    given = payload.get('tool_input') if isinstance(payload.get('tool_input'), dict) else {}
    server = mcp_server_of(HARNESS, tool, payload.get('mcp_server')) if route == 'mcp' else None
    kept = dict(payload)
    if event == 'PostToolUseFailure':
        text = payload.get('error')
        reason = ledger.reason_for(HARNESS, text) if isinstance(text, str) and text else {
            'class': 'other', 'text': 'PostToolUseFailure carried no error text'}
        reading = ('failed', reason, None, 'unrecorded (PostToolUseFailure carries no tool_response)')
    elif route == 'mcp':
        reading = mcp_reading(payload.get('tool_response'), event, folder, held)
        if reading[2]:
            kept['tool_response'] = mcp_kept(payload.get('tool_response'), reading[2])
    else:
        response = payload.get('tool_response') if isinstance(payload.get('tool_response'), dict) else None
        reading = search_reading(response, event, folder, held) if route == 'search' else \
            fetch_reading(response, event, folder, held)
        if response is not None:
            kept['tool_response'] = dict(response)
            key = 'results' if route == 'search' else 'result'
            if reading[2] and key in response:
                kept['tool_response'][key] = reading[2]
    outside_call_return(folder, held, route, tool, given, kept, 'tool_input', common(payload, folder, route), reading,
                   server)


def search_reading(response, event, folder, held):
    """(outcome, outcome_reason, answer, result_size) of a web search: served where its results hold at least one
    title-and-URL item, empty where they hold none; the answer is the results as JSON."""
    results = response.get('results') if isinstance(response, dict) else None
    if not isinstance(results, list):
        why = 'tool_response.results absent from %s' % event
        held.error(folder, 'payload', why, record='return')
        return 'failed', {'class': 'unreadable', 'text': why}, None, 'unrecorded (%s)' % why
    items = search_items(results)
    answer = json.dumps(results, ensure_ascii=False)
    if items:
        return 'served', 'none (served)', answer, {'items': items}
    return 'empty', dict(EMPTY_REASON), answer, {'items': 0}


def fetch_reading(response, event, folder, held):
    """(outcome, outcome_reason, answer, result_size) of a web fetch: the outcome from its HTTP code (fetch_outcome),
    the answer its `result`, the size its `bytes`."""
    if not isinstance(response, dict):
        why = 'tool_response absent from %s' % event
        held.error(folder, 'payload', why, record='return')
        return 'failed', {'class': 'unreadable', 'text': why}, None, 'unrecorded (%s)' % why
    if not isinstance(response.get('code'), int) or isinstance(response.get('code'), bool):
        held.error(folder, 'payload', 'tool_response.code absent from %s' % event, record='return')
    outcome, reason = fetch_outcome(response)
    size = response.get('bytes')
    if isinstance(size, int) and not isinstance(size, bool):
        size = {'bytes': size}
    else:
        size = 'unrecorded (tool_response.bytes absent from %s)' % event
        held.error(folder, 'payload', 'tool_response.bytes absent from %s' % event, record='return')
    answer = response.get('result') if isinstance(response.get('result'), str) else None
    if answer is None:
        held.error(folder, 'payload', 'tool_response.result absent from %s' % event, record='return')
    return outcome, reason, answer, size


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
    command = triage_command_resolved(command, _path)
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


PLAIN_WORD = re.compile(r'^[A-Za-z0-9_.+@%:,=/-]+$')


def triage_command_resolved(command, config_path):
    """The command with a relative path at the start of its script argument resolved against the ledger
    folder, as grouping_table and kind_names are; anything else is left as written.

    The script argument is the command's first word where that word is a relative path holding a '/', and
    its second word otherwise (the first being the program that runs it, such as python3). It is resolved
    only where it is a plain relative path: no quotes, variables, '~' or leading '-', and either a '/' in it
    or a file of that name in the ledger folder. An absolute path is used as given."""
    words = list(re.finditer(r'\S+', command))
    if not words:
        return command
    first = words[0].group(0)
    if PLAIN_WORD.match(first) and '/' in first and not first.startswith('/'):
        found = words[0]
    else:
        found = words[1] if len(words) > 1 else None
    if found is None:
        return command
    word = found.group(0)
    if not PLAIN_WORD.match(word) or word.startswith('/') or word.startswith('-'):
        return command
    base = Path(config_path).parent
    if '/' not in word and not (base / word).is_file():
        return command
    resolved = os.path.normpath(str(base / word))
    return command[:found.start()] + shlex.quote(resolved) + command[found.end():]


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
    """The brief's fields for a subagent or call-script dispatch, with the triage's reading. An encrypted brief
    is never given to the triage: its triage_kind and act_kind say the harness passed it encrypted.

    Returns (persona-name, act_kind, triage_kind, task and grouping; the seconds the triage ran or None).
    """
    fields = optional_fields(folder, text, held)
    if is_ciphertext(text):
        # The harness passed the brief encrypted (Codex 0.162.x encrypts every one): the triage would read
        # noise, so it is not run.
        fields['triage_kind'] = ENCRYPTED_TRIAGE
        fields['act_kind'] = ENCRYPTED_KIND
        return fields, None
    triage_kind, seconds = run_triage(folder, text, held)
    fields['triage_kind'] = triage_kind
    fields['act_kind'] = act_kind_of(fields['act_kind'], triage_kind)
    return fields, seconds


ENCRYPTED_TRIAGE = 'unrecorded (the harness passed the brief encrypted)'
ENCRYPTED_KIND = 'unrecorded (the brief names no kind; the harness passed the brief encrypted)'
# A Fernet token, the form of the encrypted message Codex 0.162.x passed to its subagent: base64url text whose
# first decoded byte is 0x80, then a timestamp, an IV, the ciphertext and a 32-byte HMAC.
FERNET = re.compile(r'gAAAAA[A-Za-z0-9_-]{50,}={0,2}')


def is_ciphertext(text):
    """Whether a brief is a Fernet token, as Codex 0.162.x passed its subagent's message."""
    if not isinstance(text, str) or not FERNET.fullmatch(text.strip()):
        return False
    try:
        raw = base64.urlsafe_b64decode(text.strip() + '=' * (-len(text.strip()) % 4))
    except ValueError:
        return False
    return len(raw) >= 57 and raw[0] == 0x80


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
    wider than the ledger can show. A script's own request made for another call is not counted: its
    record names that call in `harness_payload.serves_call_id` (a workspace triage or labeller writes
    one), and it is written after the question it would otherwise hide, as the triage runs at the very
    dispatch this window is read for.
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
        if not isinstance(row, dict) or row.get('record') != 'dispatch' or serves_another_call(row):
            continue
        who = row.get('caller')
        if isinstance(who, str) and who and not who.startswith('unrecorded (') and who != caller:
            continue
        at = _time(row.get('dispatched_at'))
        if at is not None and (latest is None or at > latest):
            latest = at
    return latest


def serves_another_call(row):
    """Whether a dispatch record is a script's own request made for another call: its harness_payload
    names that call in `serves_call_id`."""
    payload = row.get('harness_payload')
    served = payload.get('serves_call_id') if isinstance(payload, dict) else None
    return isinstance(served, str) and bool(served)


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
