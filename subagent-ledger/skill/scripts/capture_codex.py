#!/usr/bin/env python3
"""Codex's capture: hook events on `spawn_agent` and its shell tool run it, and it writes the call records.

It writes them through ledger.py.

    python3 capture_codex.py <event> [--ledger <folder>]

with the hook's payload on standard input. It prints nothing on standard output and exits 0 on every
path, including a payload that is empty or is not JSON, so it never blocks or changes a call. It
imposes no time limit.

What each event does (Codex 0.142.5, as observed):

  * PreToolUse on spawn_agent: the dispatch record. The brief is `tool_input.message`. The payload's
    own `model` is the parent session's, so it is never taken as the model asked for: that is
    `tool_input.model` where the tool is given one, and otherwise none was asked.
  * PostToolUse on spawn_agent: fires when the spawn returns, before the subagent has run. It stores
    the join of `tool_use_id` to the `agent_id` in `tool_response` and writes nothing else. A spawn
    whose response names no agent is a failed call, and its return is written here.
  * SubagentStart: a witness line.
  * SubagentStop: a witness line, then the return record, joined to its call through the stored
    join. The subagent's rollout, at `agent_transcript_path`, is read once it holds the answer
    SubagentStop reports and the counter row written after it, or the turn's end. Codex writes
    `task_complete` only after this hook returns, so the capture never waits for that row. There is
    no limit on the wait beyond the harness's own time-out on hooks. The model, the
    four counters, the effort and the isolation evidence come from the rollout; the answer from
    `last_assistant_message`.
  * PreToolUse on the shell tool subagent-tools.json names (`exec_command`): a dispatch record, route
    cli, when the command (`tool_input.cmd`, or `command`) matches cli-patterns.json, as the Claude
    Code capture's shell route does. A command that makes no model call writes nothing.
  * PostToolUse on the shell tool: the matched command's return record. Codex sends no separate event
    for a command that fails: its exit code is read from the tool response, an object's `exit_code`
    or the text's 'Process exited with code <n>', and a non-zero code is a failed call.

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
SUBAGENT_TOOLS = ('spawn_agent',)
DISPATCH_AGENT = 'unrecorded (not yet returned)'
SUBAGENT_COST = 'unrecorded (the harness reports no cost for a subagent)'
NOT_A_SCRIPT = 'unrecorded (not a call script)'
ON_DISPATCH_BRIEF = shared.ON_DISPATCH_BRIEF
# How often the rollout is re-read while its last turn has not ended. No limit is set on the wait.
REREAD_SECONDS = 0.1
EXIT_LINE = re.compile(r'Process exited with code (-?\d+)')
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
    if event == 'PreToolUse' and tool in SUBAGENT_TOOLS:
        return pre_spawn(payload, folder, held)
    if event == 'PostToolUse' and tool in SUBAGENT_TOOLS:
        return post_spawn(payload, folder, held)
    if event == 'PreToolUse' and tool in shared.shell_tools(HARNESS):
        return pre_shell(payload, folder, held)
    if event == 'PostToolUse' and tool in shared.shell_tools(HARNESS):
        return post_shell(payload, folder, held)
    if event == 'SubagentStart':
        return subagent_start(payload, folder, held)
    if event == 'SubagentStop':
        return subagent_stop(payload, folder, held)
    return None


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
    brief, source = shared.brief_of(message, payload.get('cwd'))
    asked = given.get('model')
    at = ledger.now()
    fields = common(payload)
    fields.update({
        'call_id': held.call_id,
        'agent_id': DISPATCH_AGENT,
        'dispatched_at': at,
        'model_requested': asked if isinstance(asked, str) and asked else None,
        'auth_route': auth_route(),
        'brief_source': source,
        'harness_payload': payload,
    })
    fields.update(shared.optional_fields(folder, brief if source else message, held))
    fields['user_answer'] = shared.user_answer_of(folder, HARNESS, held.session, fields.get('caller'),
                                                  payload.get('transcript_path'), fields['act_kind'],
                                                  brief if source else message)
    with shared.pending_lock(folder, held.session):
        shared.write_pending(folder, held.session, held.call_id,
                             {'call_id': held.call_id, 'dispatched_at': at})
    ledger.dispatch(ledger=folder, brief=brief or None, prompt=message if source and message else None,
                    **fields)


def command_of(payload):
    """The shell command a payload carries: `tool_input.cmd` or `command`, a string or an argument list."""
    given = payload.get('tool_input') if isinstance(payload.get('tool_input'), dict) else {}
    command = given.get('cmd') if given.get('cmd') is not None else given.get('command')
    if isinstance(command, list) and all(isinstance(word, str) for word in command):
        if len(command) >= 3 and command[1] in ('-c', '-lc'):
            return command[2]
        return ' '.join(shlex.quote(word) for word in command)
    return command if isinstance(command, str) else None


def shell_output(response):
    """(the command's output, its exit code or None) from the shell tool's response."""
    if isinstance(response, dict):
        code = response.get('exit_code', response.get('exitCode'))
        for key in ('output', 'aggregated_output', 'stdout', 'formatted_output'):
            if isinstance(response.get(key), str):
                return response[key], code if isinstance(code, int) else None
        return json.dumps(response, ensure_ascii=False), code if isinstance(code, int) else None
    if not isinstance(response, str):
        return '', None
    found = EXIT_LINE.search(response)
    code = int(found.group(1)) if found else None
    output = response.split('\nOutput:\n', 1)[1] if '\nOutput:\n' in response else response
    return output, code


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
        raw = parsed if isinstance(parsed, dict) else raw
    output, code = shell_output(raw)
    kept = dict(payload)
    if isinstance(raw, str) and '\nOutput:\n' in raw:
        # Split so the output, which is the answer, is moved to its file like any other answer.
        kept['tool_response'] = {'header': raw.split('\nOutput:\n', 1)[0], 'output': output}
    shared.cli_return(folder, held, common(payload, route='cli'), command_of(payload), output, code, kept)


def store_join(folder, session, agent, data):
    """Keep the join of call id to agent id for the SubagentStop that writes the return."""
    shared.write_join(folder, session, agent, data)


def post_spawn(payload, folder, held):
    response = response_of(payload)
    agent = response.get('agent_id')
    if isinstance(agent, str) and agent:
        with shared.pending_lock(folder, held.session):
            store_join(folder, held.session, agent, {'call_id': held.call_id,
                                                     'tool_response': response})
        return
    # A spawn that named no agent did not start one: its return is written now, as failed.
    raw = payload.get('tool_response')
    text = raw if isinstance(raw, str) and raw else json.dumps(raw)
    with shared.pending_lock(folder, held.session):
        sent = shared.read_pending(folder, held.session, held.call_id)
        fields = common(payload)
        fields.update({
            'call_id': held.call_id,
            'agent_id': 'unrecorded (the spawn named no agent)',
            'outcome': 'failed',
            'outcome_reason': ledger.reason_for(HARNESS, text, fallback='harness_error'),
            'cost': SUBAGENT_COST, 'spend_line': NOT_A_SCRIPT,
            'model': 'unrecorded (no subagent ran)', 'tokens': 'unrecorded (no subagent ran)',
            'effort': 'unrecorded (no subagent ran)', 'isolation': 'unrecorded (no subagent ran)',
            'harness_payload': shared.without_texts(payload, (payload.get('tool_input') or {}).get('message')
                                                    if isinstance(payload.get('tool_input'), dict) else None,
                                                    ON_DISPATCH_BRIEF),
        })
        if sent and sent.get('dispatched_at'):
            fields['dispatched_at'] = sent['dispatched_at']
        ledger.ret(ledger=folder, **fields)
        shared.clear_pending(folder, held.session, [held.call_id])


def subagent_start(payload, folder, held):
    if held.agent_id.startswith('unrecorded ('):
        held.error(folder, 'payload', 'agent_id absent from SubagentStart', record='witness')
    ledger.witness(ledger=folder, event='SubagentStart', session=held.session, agent_id=held.agent_id,
                   call_id='unrecorded (not carried by SubagentStart)', at=ledger.now())


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
        # Nothing pending for this agent. If the ledger already holds a call to it, this is a further stop
        # after its call returned, and the witness line above records it. Otherwise a call may be missing.
        called, unread = shared.agent_called(folder, held.session, agent)
        if called:
            return
        if unread:
            held.error(folder, 'payload', 'no pending join for agent %s, and the ledger could not be read to '
                       'find an earlier call to it: %s' % (agent, unread), record='return')
        else:
            held.error(folder, 'payload', 'no pending join for agent %s: its PostToolUse on spawn_agent was '
                       'not seen, so the return cannot be joined to a call' % agent, record='return')
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
    wait_for_rollout(path, answer)
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


def wait_for_rollout(path, answer):
    """Re-read the rollout until it holds the answer and the counter row after it.

    No limit of the capture's own: the harness's time-out on hooks is the only bound.
    """
    if not path:
        return
    while not transcripts.codex_complete(path, answer):
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
