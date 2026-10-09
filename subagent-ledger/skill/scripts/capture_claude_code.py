#!/usr/bin/env python3
"""Claude Code's capture: every hook event runs it, and it writes the call records through ledger.py.

    python3 capture_claude_code.py <event> [--ledger <folder>]

with the hook's payload on standard input. It prints nothing on standard output and exits 0 on every
path, including a payload that is empty or is not JSON, so it never blocks or changes a call. It
imposes no time limit.

What each event does:

  * PreToolUse on Agent or Task: the dispatch record. A pending file,
    <ledger>/.pending/<session>/<tool_use_id>.json, holds what the return needs.
  * SubagentStart: a witness line, and a pending file keyed by the agent id.
  * PostToolUse on Agent or Task, a foreground call: the return record. The tool response is the one
    payload carrying both the call id and the agent id. The model, the four counters and the
    isolation evidence are read from the subagent's own transcript, at the path SubagentStop stored
    or at <CLAUDE_CONFIG_DIR or ~/.claude>/projects/*/<session>/subagents/agent-<id>.jsonl.
  * PostToolUse on Agent or Task, a background call: only the join of call id to agent id, since
    the subagent is still running.
  * SubagentStop: a witness line. For a background call, the return record, joined through the
    pending files; for a foreground call, the transcript path and effort level are stored for the
    PostToolUse that follows.
  * PreToolUse on Bash: a dispatch record, route cli, when the command matches cli-patterns.json.
  * PostToolUse on Bash: the return record for a matched command, which exited 0. Claude Code sends
    a command that exits non-zero to PostToolUseFailure instead, which writes a failed return. Where
    the command printed a `claude -p --output-format json` envelope naming its session, the inner
    session's own transcript is read for the model, the four counters and the isolation evidence:
    under the CLAUDE_CONFIG_DIR the command set, or else the calling session's configuration folder.
    A transcript that is absent, or that does not carry the envelope's result, leaves each of them
    unrecorded, saying why.

A failure at any stage writes one error line through ledger.error(), naming the session, call id
and event read from the raw payload before anything else.
"""

import contextlib
import fcntl
import glob
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

import ledger  # noqa: E402
import transcripts  # noqa: E402

HARNESS = 'claude-code'
SUBAGENT_TOOLS = ('Agent', 'Task')
SHELL_TOOL = 'Bash'
PATTERNS_FILE = HERE / 'cli-patterns.json'
PENDING = '.pending'
AUTH_VARIABLES = ('ANTHROPIC_API_KEY', 'CLAUDE_CODE_OAUTH_TOKEN', 'ANTHROPIC_AUTH_TOKEN',
                  'CLAUDE_CODE_USE_BEDROCK', 'CLAUDE_CODE_USE_VERTEX')
FRONTMATTER_FIELDS = ('persona-name', 'characteristic', 'task')
DISPATCH_AGENT = 'unrecorded (not yet returned)'
CLI_AGENT = 'unrecorded (no agent: cli call)'
SUBAGENT_COST = 'unrecorded (the harness reports no cost for a subagent)'
NOT_A_SCRIPT = 'unrecorded (not a call script)'
EMPTY_REASON = {'class': 'empty_answer', 'text': 'the call was served and its answer was empty'}
COUNTER_NAMES = (('input', 'input_tokens'), ('cache_write', 'cache_creation_input_tokens'),
                 ('cache_read', 'cache_read_input_tokens'), ('output', 'output_tokens'))
ABSENT_FROM_BRIEF = {
    'persona-name': 'unrecorded (the brief names no persona)',
    'characteristic': 'unrecorded (not given in the brief)',
    'task': 'unrecorded (the brief names no task)',
}
# A background call's transcript may still be written when SubagentStop fires, so its counters are
# read only once the transcript holds the answer SubagentStop reports, in a final request whose stop
# reason is not tool_use. The capture sets no limit on that wait: the harness's own time-out on hooks
# is the only bound. This is how often it re-reads.
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
    if event == 'PostToolUseFailure' and tool in SUBAGENT_TOOLS:
        return post_agent_failure(payload, folder, held)
    if event == 'SubagentStart':
        return subagent_start(payload, folder, held)
    if event == 'SubagentStop':
        return subagent_stop(payload, folder, held)
    if event == 'PreToolUse' and tool == SHELL_TOOL:
        return pre_shell(payload, folder, held)
    if event in ('PostToolUse', 'PostToolUseFailure') and tool == SHELL_TOOL:
        return post_shell(event, payload, folder, held)
    return None


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
        'harness_payload': payload,
    })
    fields.update(optional_fields(folder, brief if source else prompt))
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
        clear_pending(folder, held.session, [held.call_id])


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
        if join is not None:
            write_background_return(folder, held, agent, stop, join=join)
            return
        if agent in background_ids(payload):
            # A background call whose PostToolUse join was never written: no guessed record.
            held.error(folder, 'payload', 'no pending join for background agent %s: its PostToolUse '
                       'was not seen, so the return cannot be joined to a call' % agent, record='return')
            return
        # A foreground call: keep what the PostToolUse that follows needs; never the answer text.
        kept = dict(stop)
        kept.pop('last_assistant_message', None)
        kept.pop('payload', None)
        write_pending(folder, held.session, 'stop-' + agent, kept)


def write_background_return(folder, held, agent, stop, join=None):
    """The return record of a background call, at SubagentStop. Called under the pending lock."""
    join = join if join is not None else read_join(folder, held.session, agent)
    payload = stop.get('payload') or {}
    call_id = join.get('call_id') if join else None
    if not call_id:
        held.error(folder, 'payload', 'no pending join for background agent %s' % agent, record='return')
        return
    response = join.get('tool_response') or {}
    sent = read_pending(folder, held.session, call_id)
    answer = stop.get('last_assistant_message')
    answer = answer if isinstance(answer, str) else ''
    if 'last_assistant_message' not in payload and payload:
        held.error(folder, 'payload', 'last_assistant_message absent from SubagentStop', record='return')
    outcome, reason = agent_outcome('completed', answer)
    path = stop.get('agent_transcript_path')
    if not path:
        if payload:
            held.error(folder, 'payload', 'agent_transcript_path absent from SubagentStop', record='return')
        path = transcripts.lane_path(held.session, agent)
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
    wait_for_transcript(path, answer)
    fields.update(from_transcript(path, response.get('resolvedModel'), None))
    if isinstance(fields.get('tokens'), dict):
        fields['tokens']['read_after_seconds'] = round(time.monotonic() - _ARRIVAL.get('at', time.monotonic()), 3)
    kept = dict(payload)
    kept['post_tool_use_response'] = response
    if isinstance(kept.get('last_assistant_message'), str):
        kept['last_assistant_message'] = answer
    fields['harness_payload'] = without_texts(kept, response.get('prompt'), ON_DISPATCH_BRIEF)
    ledger.ret(ledger=folder, answer=answer, **fields)
    clear_pending(folder, held.session, [call_id, 'agent-' + agent, 'stop-' + agent, 'join-' + agent])


def wait_for_transcript(path, answer):
    """Re-read the transcript until it is complete. No limit of the capture's own (specification §3e)."""
    if not path:
        return
    while not transcript_complete(path, answer):
        time.sleep(REREAD_SECONDS)


def transcript_complete(path, answer):
    """True when the final request carries `answer` and stopped for a reason other than tool_use."""
    try:
        rows = transcripts.rows_of(path)
    except OSError:
        return False
    groups, order = {}, []
    for position, row in enumerate(row for row in rows if transcripts._usage(row) is not None):
        key = transcripts._group_key(row, position)
        if key not in groups:
            groups[key] = []
            order.append(key)
        groups[key].append(row)
    if not order:
        return False
    last = groups[order[-1]]
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
    for part in re.split(r'\|\||&&|;|\||\n', command):
        try:
            words = shlex.split(part)
        except ValueError:
            words = part.split()
        while words and (re.match(r'^[A-Za-z_][A-Za-z0-9_]*=', words[0]) or words[0] == 'env'):
            words.pop(0)
        if not words:
            continue
        program = os.path.basename(words[0])
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
    command = given.get('command')
    entry, words = match_command(command)
    if entry is None:
        return
    if held.call_id.startswith('unrecorded ('):
        held.error(folder, 'payload', 'no call_id (tool_use_id absent from PreToolUse)', record='dispatch')
        return
    at = ledger.now()
    fields = common(payload, folder, route='cli')
    fields.update({
        'call_id': held.call_id,
        'agent_id': CLI_AGENT,
        'dispatched_at': at,
        'model_requested': requested_model(words, entry),
        'auth_route': auth_route() if entry['harness'] == HARNESS else
        'unrecorded (the command runs %s, whose sign-in this capture does not read)' % entry['program'],
        'brief_source': 'unrecorded (the brief is the command itself)',
        'harness_payload': payload,
    })
    fields.update(optional_fields(folder, None))
    with pending_lock(folder, held.session):
        write_pending(folder, held.session, 'cli-' + held.call_id,
                      {'call_id': held.call_id, 'dispatched_at': at, 'program': entry['program']})
    ledger.dispatch(ledger=folder, brief=command, **fields)


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
    """tokens, model and isolation from the inner `claude -p` session's own transcript (§5b, B3).

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


def optional_fields(folder, brief):
    """persona-name, characteristic, task and grouping, from the brief's frontmatter (§3b)."""
    config, path = read_config(folder)
    keys = config.get('frontmatter')
    out = {}
    if not isinstance(keys, dict):
        for name in FRONTMATTER_FIELDS:
            out[name] = 'unrecorded (no frontmatter map in %s)' % ledger.CONFIG_FILE
    else:
        front = frontmatter(brief) if isinstance(brief, str) else {}
        for name in FRONTMATTER_FIELDS:
            value = lookup(front, keys.get(name)) if keys.get(name) else None
            if not keys.get(name):
                out[name] = 'unrecorded (%s names no frontmatter key for %s)' % (ledger.CONFIG_FILE, name)
            elif isinstance(value, str) and value:
                out[name] = value
            else:
                out[name] = ABSENT_FROM_BRIEF[name]
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
