#!/usr/bin/env python3
"""Codex's capture: hook events on its subagent tool and its shell tool run it, and it writes the call records.

It writes them through ledger.py.

    python3 capture_codex.py <event> [--ledger <folder>]

with the hook's payload on standard input. It prints nothing on standard output and exits 0 on every
path, including a payload that is empty or is not JSON, so it never blocks or changes a call. It
imposes no time limit.

Tool names. Codex 0.142.5 named the subagent tool `spawn_agent` and the shell tool `exec_command` in its
hook events; Codex 0.162.1 names them `Agent` and `Bash` (its hooks documentation, 'Tool coverage'). The
Codex app (0.162.x, as a live run showed) names its collaboration tools with their namespace before the
name and no separator: `collaborationspawn_agent`, `collaborationsend_message`, `collaborationfollowup_task`,
`collaborationwait_agent`, `collaborationlist_agents`, `collaborationinterrupt_agent`. The capture takes the
names subagent-tools.json lists for Codex: `tools`, less `message_tools`, dispatch a subagent;
`message_tools` send one a message; `witness_tools` are seen but not recorded as calls; `shell_tools` run
commands.

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
  * PreToolUse on a message tool (`send_message`, `followup_task`): a dispatch record, as for a spawn,
    its target and message kept pending. PostToolUse keeps the tool response for the return. The return
    is written at the first SubagentStop of the target agent whose turn holds the message as delivered.
  * PreToolUse or PostToolUse on a witness tool (wait, list, interrupt): a witness line, its event
    '<event> on <tool>' and its call id the tool call's. Not a call.
  * SubagentStop: a witness line, then the return record of the spawn joined to the agent, and of each
    message delivered in the stop's turn. It never waits: no hook may wait on anything the harness
    does after the hook returns, and Codex writes `task_complete`, and on 0.162.x keeps the subagent
    running, until this hook returns (a live Codex run hung on such a wait). The answer is
    `last_assistant_message`. The subagent's rollout, at `agent_transcript_path`, is read once: the
    model, the effort and the isolation evidence from whatever it holds, and the counters of the
    stop's turn only where the rollout already holds the turn's answer and the counter row after it
    (transcripts.codex_complete); otherwise `unrecorded (<why>)`. The stop's turn is the one whose
    `task_started` row carries the payload's `turn_id`; where no row does, the rollout's last turn. The
    payload's own `model` stays in `harness_payload` and never stands for the model the rollout names.
  * PreToolUse on the shell tool subagent-tools.json names (`exec_command`, or `Bash` on 0.162.1): a
    dispatch record, route cli, when the command (`tool_input.cmd` on 0.142.5, `tool_input.command` on
    0.162.1) matches cli-patterns.json, as the Claude
    Code capture's shell route does. A command that makes no model call writes nothing.
  * PostToolUse on the shell tool: the matched command's return record. Codex sends no separate event
    for a command that fails: its exit code is read from the tool response, which is an object
    holding `exit_code` (0.142.5's rows), or text, or a list of text items. In text it is either the
    line 'Process exited with code <n>' (0.142.5) or, after the line 'Output:', a JSON object holding
    `exit_code` (0.162.x, after 'Script completed' and 'Wall time'). Where the response is the output
    alone (the Codex app, in a live run), the code is read once from the parent rollout's
    `item_completed` row for the call, if it already holds one; only for a command matched as a model
    call, so no other shell call reads the rollout. A non-zero code is a failed call;
    a response with no exit code readable is `failed`, class `unreadable`, never `served`.
  * PreToolUse and PostToolUse on an MCP tool (`mcp__<server>__<tool>`, by subagent-tools.json's `outside_tools`):
    the dispatch and return of an MCP read, route mcp, read as capture_claude_code.py reads Claude Code's. Codex's
    hooks documentation gives these events; none was observed. Its hosted web search fires no hook.
  * Any other PreToolUse or PostToolUse writes an error line naming its tool: a hook runs only for the
    tools its matcher admits, so a tool event that reaches the capture and is not recorded is a fault
    to see, never noise.

The shell tool's payloads were reconstructed from a rollout's `exec_command` rows, since Codex runs
no hook it does not trust; the shapes read here are those rows' (the tool name, `cmd` and `workdir`
in the input, the output text).

A failure at any stage writes one error line through ledger.error(), naming the session, call id and
event read from the raw payload before anything else.
"""

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
NO_TURN_COUNTERS = ('unrecorded (the rollout did not yet hold the counter row for this stop\'s turn when '
                    'SubagentStop fired)')
EXIT_LINE = re.compile(r'Process exited with code (-?\d+)')
OUTPUT_LINE = re.compile(r'(?m)^Output:[ \t]*$')
NO_EXIT_CODE = {'class': 'unreadable', 'text': 'the response carries no exit code'}
NOT_RECORDED = 'not a tool this capture records'
NO_SPAWN_EVENT = 'unrecorded (the harness sent no dispatch event for this subagent)'
ENCRYPTED = shared.ENCRYPTED_TRIAGE
MESSAGE = 'msg-'
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
    if event == 'PreToolUse' and tool in message_tools():
        return pre_spawn(payload, folder, held, message=True)
    if event == 'PostToolUse' and tool in message_tools():
        return post_message(payload, folder, held)
    if event in ('PreToolUse', 'PostToolUse') and tool in witness_tools():
        return ledger.witness(ledger=folder, event='%s on %s' % (event, tool), session=held.session,
                              agent_id='unrecorded (%s names no agent id)' % tool, call_id=held.call_id,
                              at=ledger.now())
    if event == 'PreToolUse' and tool in shared.shell_tools(HARNESS):
        return pre_shell(payload, folder, held)
    if event == 'PostToolUse' and tool in shared.shell_tools(HARNESS):
        return post_shell(payload, folder, held)
    if event == 'SubagentStart':
        return subagent_start(payload, folder, held)
    if event == 'SubagentStop':
        return subagent_stop(payload, folder, held)
    if event in ('PreToolUse', 'PostToolUse') and shared.outside_route(HARNESS, tool) == 'mcp':
        return mcp_event(event, payload, folder, held)
    if event in ('PreToolUse', 'PostToolUse'):
        # Never dropped silently: the hook ran because its matcher admitted the tool.
        held.error(folder, 'payload', '%s on %s: %s' % (event, tool if isinstance(tool, str) and tool else
                                                        'a tool the payload does not name', NOT_RECORDED))
    return None


def _names(key):
    names = shared.harness_entry(HARNESS).get(key)
    return tuple(name for name in names if isinstance(name, str)) if isinstance(names, list) else ()


def mcp_event(event, payload, folder, held):
    """An MCP tool's PreToolUse (the dispatch) or PostToolUse (the return), read as Claude Code's MCP route reads
    them: `tool_input` the brief, `tool_response` the MCP result, `{content: [parts], isError}` in a live Codex-app
    session (a bare list of parts is read too). The server is
    the payload's `mcp_server.name`, else the tool name's part after `mcp__`. A server config.json's mcp_not_calls
    lists writes nothing. Codex sends no failure event; a response that is not a list of parts is failed, class
    unreadable, with an error line."""
    tool = payload.get('tool_name')
    server = shared.mcp_server_of(HARNESS, tool, payload.get('mcp_server'))
    if shared.not_a_call(folder, server[0]):
        return None
    given = payload.get('tool_input') if isinstance(payload.get('tool_input'), dict) else {}
    if event == 'PreToolUse':
        return shared.outside_call_dispatch(folder, held, HARNESS, 'mcp', given, dict(payload), 'tool_input',
                                       common(payload, route='mcp'), event, server)
    kept = dict(payload)
    reading = shared.mcp_reading(payload.get('tool_response'), event, folder, held, harness=HARNESS)
    if reading[2]:
        kept['tool_response'] = shared.mcp_kept(payload.get('tool_response'), reading[2])
    return shared.outside_call_return(folder, held, 'mcp', tool, given, kept, 'tool_input', common(payload, route='mcp'),
                                 reading, server)


def subagent_tools():
    """The names of Codex's subagent dispatch tool, from subagent-tools.json: `tools` less `message_tools`."""
    return tuple(name for name in _names('tools') if name not in message_tools())


def message_tools():
    """The names of the tools that send a running subagent a message, from subagent-tools.json."""
    return _names('message_tools')


def witness_tools():
    """The names of the tools seen but not recorded as calls, from subagent-tools.json."""
    return _names('witness_tools')


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


def pre_spawn(payload, folder, held, message=False):
    if held.call_id.startswith('unrecorded ('):
        held.error(folder, 'payload', 'no call_id (tool_use_id absent from PreToolUse)', record='dispatch')
        return
    given = payload.get('tool_input') if isinstance(payload.get('tool_input'), dict) else {}
    message_text = given.get('message') if isinstance(given.get('message'), str) else ''
    if not message_text:
        held.error(folder, 'payload', 'tool_input.message absent from PreToolUse', record='dispatch')
    encrypted = is_ciphertext(message_text)
    brief, source = (message_text, None) if encrypted else shared.brief_of(message_text, payload.get('cwd'))
    asked = given.get('model')
    at = ledger.now()
    fields = common(payload)
    fields.update({
        'call_id': held.call_id,
        'agent_id': DISPATCH_AGENT,
        'dispatched_at': at,
        'model_requested': asked if isinstance(asked, str) and asked else None,
        'auth_route': auth_route(),
        'brief_source': ENCRYPTED if encrypted else (source or shared.inline_source(payload)),
        'effort_assigned': shared.effort_assigned_of(HARNESS, payload.get('tool_name'), payload),
    })
    found, seconds = shared.dispatch_kind(folder, brief if source else message_text, held)
    fields.update(found)
    fields['harness_payload'] = shared.with_triage_time(payload, seconds)
    fields['user_answer'] = shared.user_answer_of(folder, HARNESS, held.session, fields.get('caller'),
                                                  payload.get('transcript_path'), fields['act_kind'],
                                                  brief if source else message_text)
    with shared.pending_lock(folder, held.session):
        if message:
            target = given.get('target')
            shared.write_pending(folder, held.session, MESSAGE + held.call_id,
                                 {'call_id': held.call_id, 'dispatched_at': at, 'order': time.time_ns(),
                                  'target': target if isinstance(target, str) else None, 'message': message_text})
        else:
            shared.write_pending(folder, held.session, held.call_id,
                                 {'call_id': held.call_id, 'dispatched_at': at, 'awaiting_agent': True,
                                  'order': time.time_ns()})
    ledger.dispatch(ledger=folder, brief=brief or None,
                    prompt=message_text if source and message_text else None, **fields)


def post_message(payload, folder, held):
    """Keep a message tool's response for its return; a message whose PreToolUse was not seen is an error line."""
    with shared.pending_lock(folder, held.session):
        sent = shared.read_pending(folder, held.session, MESSAGE + held.call_id)
        if sent is None:
            held.error(folder, 'payload', 'PostToolUse on %s: its PreToolUse was not seen, so no message is '
                       'pending for it' % payload.get('tool_name'), record='return')
            return
        shared.write_pending(folder, held.session, MESSAGE + held.call_id,
                             dict(sent, tool_response=response_of(payload) or payload.get('tool_response')))


is_ciphertext = shared.is_ciphertext


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
    given = payload.get('tool_input') if isinstance(payload.get('tool_input'), dict) else {}
    workdir = given.get('workdir') if isinstance(given.get('workdir'), str) and given.get('workdir') else None
    shared.cli_dispatch(folder, held, command_of(payload), common(payload, route='cli'), payload, HARNESS,
                        auth_route, 'PreToolUse', cwd=workdir or payload.get('cwd'))


def post_shell(payload, folder, held):
    raw = payload.get('tool_response')
    if isinstance(raw, str):
        try:
            parsed = json.loads(raw)
        except ValueError:
            parsed = None
        raw = parsed if isinstance(parsed, (dict, list)) else raw
    output, code = shell_output(raw)
    if code is None and shared.read_pending(folder, held.session, 'cli-' + held.call_id) is not None:
        # Only for a command matched as a model call: any other shell call writes nothing, so its rollout is
        # never read.
        code = rollout_exit_code(payload.get('transcript_path'), payload.get('tool_use_id'))
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


def rollout_exit_code(path, call_id):
    """The exit code the parent rollout already holds for a shell call, or None. Read once, never waited for.

    The Codex app, in a live run, sent a Bash call's tool_response as the command's output alone, and wrote
    the exit code, before PostToolUse ran, in the parent rollout: an `item_completed` event whose item has the
    call's id and an integer `exit_code`."""
    if not isinstance(path, str) or not path or not isinstance(call_id, str) or not call_id:
        return None
    try:
        rows = transcripts.rows_of(path)
    except OSError:
        return None
    for row in reversed(rows):
        payload = row.get('payload') if isinstance(row.get('payload'), dict) else {}
        item = payload.get('item') if isinstance(payload.get('item'), dict) else {}
        if (row.get('type') == 'event_msg' and payload.get('type') == 'item_completed'
                and item.get('id') == call_id and _code(item.get('exit_code')) is not None):
            return item['exit_code']
    return None


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
        if path.name.startswith(('join-', 'cli-', 'stop-', shared.OUTSIDE_PENDING, MESSAGE)):
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
    answer = payload.get('last_assistant_message')
    path = payload.get('agent_transcript_path')
    path = path if isinstance(path, str) and path else None
    turn = payload.get('turn_id') if isinstance(payload.get('turn_id'), str) else None
    rows, unread = None, None
    if path:
        try:
            rows = transcripts.rows_of(path)  # the one read of the rollout: nothing here waits
        except OSError as exc:
            unread = 'the rollout could not be read: %s' % (exc.strerror or exc)
    with shared.pending_lock(folder, held.session):
        join = shared.read_join(folder, held.session, agent)
        messages = delivered_messages(folder, held.session, agent, rows, turn)
    if (not join or not join.get('call_id')) and not messages:
        # Nothing pending for this agent. If the ledger already holds a return naming it, this is a further
        # stop after its call returned, and the witness line above records it. Otherwise a call may be
        # missing. A dispatch alone does not count here: on Codex only a SubagentStart's own dispatch names
        # the agent, and it writes its join with it, so such a dispatch with no join and no return is a call
        # missing its return.
        called, unread_ledger = shared.agent_called(folder, held.session, agent, records=('return',))
        if called:
            return
        if unread_ledger:
            held.error(folder, 'payload', 'no pending join for agent %s, and the ledger could not be read to '
                       'find an earlier call to it: %s' % (agent, unread_ledger), record='return')
        else:
            held.error(folder, 'payload', 'no pending join for agent %s: its PostToolUse on the subagent tool '
                       'was not seen, so the return cannot be joined to a call' % agent, record='return')
        return
    if not isinstance(answer, str):
        held.error(folder, 'payload', 'last_assistant_message absent from SubagentStop', record='return')
        answer = ''
    if not path:
        held.error(folder, 'payload', 'agent_transcript_path absent from SubagentStop', record='return')
    waited = round(time.monotonic() - _ARRIVAL.get('at', time.monotonic()), 3)
    fields = common(payload)
    fields.update({'agent_id': agent, 'cost': SUBAGENT_COST, 'spend_line': NOT_A_SCRIPT})
    fields.update(from_rollout(path, rows, unread, answer, turn, waited))
    fields.update(dict(zip(('outcome', 'outcome_reason'), rollout_outcome(rows, answer))))
    calls = []
    if join and join.get('call_id'):
        calls.append((join['call_id'], join.get('tool_response'), [join['call_id'], 'join-' + agent]))
    for name, data in messages:
        calls.append((data['call_id'], data.get('tool_response'), [name]))
    with shared.pending_lock(folder, held.session):
        for call_id, response, cleared in calls:
            own = dict(fields, call_id=call_id)
            sent = shared.read_pending(folder, held.session, call_id)
            sent = sent or shared.read_pending(folder, held.session, MESSAGE + call_id)
            if sent and sent.get('dispatched_at'):
                own['dispatched_at'] = sent['dispatched_at']
            kept = dict(payload)
            kept['post_tool_use_response'] = response
            own['harness_payload'] = kept
            ledger.ret(ledger=folder, answer=answer, **own)
            shared.clear_pending(folder, held.session, cleared)


def agent_names(rows, agent):
    """The names by which a message may target this agent: its id, and its path, nickname and the path's last
    part as the rollout's session_meta row gives them."""
    names = {agent}
    meta = rows[0].get('payload') if rows and isinstance(rows[0].get('payload'), dict) else {}
    spawn = ((meta.get('source') or {}).get('subagent') or {}).get('thread_spawn') if isinstance(
        meta.get('source'), dict) else None
    for found in (meta.get('agent_path'), meta.get('agent_nickname'),
                  spawn.get('agent_path') if isinstance(spawn, dict) else None):
        if isinstance(found, str) and found:
            names.add(found)
            names.add(found.rstrip('/').rsplit('/', 1)[-1])
    return names


def delivered_text(row):
    """The text and ciphertext of a message delivered to the subagent in a rollout row, or None."""
    payload = row.get('payload') if isinstance(row.get('payload'), dict) else {}
    if row.get('type') == 'response_item' and payload.get('type') == 'agent_message':
        parts = payload.get('content') if isinstance(payload.get('content'), list) else []
        said = [part.get(key) for part in parts if isinstance(part, dict)
                for key in ('text', 'encrypted_content') if isinstance(part.get(key), str)]
        return '\n'.join(said)
    if row.get('type') == 'event_msg' and payload.get('type') == 'user_message':
        return payload.get('message') if isinstance(payload.get('message'), str) else None
    return None


def delivered_messages(folder, session, agent, rows, turn):
    """[(the pending file's name, its data)] for each message to this agent that the stop's turn holds as delivered,
    by dispatch order. Called under the pending lock. With no rollout read, none: the message stays pending."""
    if not rows:
        return []
    names = agent_names(rows, agent)
    started, ends = transcripts.codex_turn(rows, turn)
    texts = [text for text in (delivered_text(rows[at]) for at in range(started + 1, ends)) if text]
    found = []
    for path in shared.pending_dir(folder, session).glob(MESSAGE + '*.json'):
        try:
            data = json.loads(path.read_text(encoding='utf-8'))
        except (OSError, ValueError):
            continue
        if not isinstance(data, dict) or not data.get('call_id') or data.get('target') not in names:
            continue
        wanted = (data.get('message') or '').strip()
        if wanted and any(wanted in text for text in texts):
            found.append((path.stem, data))
    found.sort(key=lambda item: (str(item[1].get('dispatched_at') or ''), item[1].get('order') or 0))
    return found


def from_rollout(path, rows, unread, answer, turn, waited):
    """model, tokens, effort and isolation from the rollout's rows as read once; never a wait for more."""
    if not path:
        why = 'unrecorded (agent_transcript_path absent from SubagentStop)'
        return {'model': why, 'tokens': why, 'effort': why, 'isolation': why, 'answer_source': why}
    if rows is None:
        why = 'unrecorded (%s)' % unread
        return {'model': why, 'tokens': why, 'effort': why, 'isolation': why, 'answer_source': why}
    reading = transcripts.read(path, rows=rows)
    if not transcripts.is_codex(rows):
        why = 'unrecorded (%s)' % (reading['error'] or 'the rollout holds no session_meta row')
        return {'model': why, 'tokens': why, 'effort': why, 'isolation': why, 'answer_source': why}
    if reading['tokens'] == transcripts.CODEX_CONTINUED:
        tokens = reading['tokens']
    elif not transcripts.codex_complete(path, answer, turn, rows=rows):
        tokens = NO_TURN_COUNTERS
    else:
        usage = transcripts.codex_turn_usage(rows, turn)
        tokens = (dict(transcripts.codex_tokens(usage), read_after_seconds=waited) if usage is not None
                  else NO_TURN_COUNTERS)
    return {'model': reading['model'] or 'unrecorded (the rollout names no model)',
            'tokens': tokens,
            'effort': reading.get('effort') or 'unrecorded (the rollout records no effort)',
            'isolation': transcripts.isolation(reading), 'answer_source': str(path)}


def rollout_outcome(rows, answer):
    """served or empty from the answer; failed where the rollout's last turn was aborted."""
    aborted = None
    for row in rows or []:
        payload = row.get('payload') if isinstance(row.get('payload'), dict) else {}
        if row.get('type') == 'event_msg' and payload.get('type') == 'turn_aborted':
            aborted = payload
        elif row.get('type') == 'event_msg' and payload.get('type') == 'task_started':
            aborted = None
    if aborted is not None:
        text = aborted.get('reason') if isinstance(aborted.get('reason'), str) else json.dumps(aborted)
        return 'failed', ledger.reason_for(HARNESS, text, fallback='harness_error')
    return shared.agent_outcome('completed', answer)


if __name__ == '__main__':
    sys.exit(main())
