#!/usr/bin/env python3
"""OpenCode's capture: the plugin `opencode-plugin/subagent-ledger.js` runs it on each `task` call.

    python3 capture_opencode.py before|after [--ledger <folder>]

with `{"input": ..., "output": ..., "directory": ...}` on standard input: the two arguments OpenCode
passed to the plugin's `tool.execute.before` or `tool.execute.after`, and the plugin's folder. It
prints nothing on standard output and exits 0 on every path, so it never blocks or changes a call.
It imposes no time limit.

  * before, on `task`: the dispatch record. `input.callID` is the call id, `input.sessionID` the
    calling session, `output.args.prompt` the brief; `args.subagent_type` is kept.
  * after, on `task`: the return record. `output.metadata.sessionId` is the subagent's id, its
    `model.providerID` and `modelID` the model, and `output.output` the answer. OpenCode has no
    declaration of where its counters live, so they read unrecorded. The isolation evidence is read
    from OpenCode's own database, opened read-only: the child session's `directory`, and the input
    of each tool call it made.

    python3 capture_opencode.py event <event type> [--ledger <folder>]

with `{"event": ..., "directory": ...}` on standard input: one event from the plugin's general
`event` hook. OpenCode 1.18.30 sends no `after` for a `task` whose subagent fails. Its parent
session's `message.part.updated` then carries the task part with `state.status` "error", the error
text in `state.error`, the `callID` the `before` carried, and the subagent's session in
`state.metadata.sessionId`. That event writes the pending dispatch's return: `failed`, its class
read from reasons.json against the error text, and `harness_payload.event_type` naming the event.
The tie is the call id, never timing. An error event whose call id is not pending and has no return
writes one error line naming every pending call id, and no return. A call that already has a return
gets no second one. Every other event is passed over.

Any other tool is passed over.

A failure at any stage writes one error line through ledger.error(), naming the session, call id and
event read from the raw payload before anything else.
"""

import contextlib
import io
import json
import os
import re
import sqlite3
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

import capture_claude_code as shared  # noqa: E402
import ledger  # noqa: E402
import transcripts  # noqa: E402

HARNESS = 'opencode'
DISPATCH_AGENT = 'unrecorded (not yet returned)'
NO_COUNTERS = 'unrecorded (no declaration for opencode)'
SUBAGENT_COST = 'unrecorded (the harness reports no cost for a subagent)'
NOT_A_SCRIPT = 'unrecorded (not a call script)'
NO_PROVIDER = 'unrecorded (tool.execute.before names no model, so no provider)'
NO_EFFORT = 'unrecorded (OpenCode reports no effort level to a plugin)'
LIMIT = ('each tool call is listed as the model wrote it, when it names an absolute path outside the '
         'folder; a read inside a script its shell tool ran is not seen')
STATE = re.compile(r'<task\b[^>]*\bstate="([^"]*)"')
RESULT = re.compile(r'<task_result>(.*?)</task_result>', re.S)


def is_subagent_tool(tool):
    return tool == 'task'


class Held(shared.Held):
    """What an error line names, read from the raw payload before any other work."""

    def __init__(self, event, payload):
        payload = payload if isinstance(payload, dict) else {}
        given = payload.get('input') if isinstance(payload.get('input'), dict) else {}
        output = payload.get('output') if isinstance(payload.get('output'), dict) else {}
        metadata = output.get('metadata') if isinstance(output.get('metadata'), dict) else {}
        self.event = event or 'unrecorded (no event named on the command line)'
        self.session = shared._text(given.get('sessionID'), 'unrecorded (sessionID absent from %s)' % self.event)
        self.call_id = shared._text(given.get('callID'), 'unrecorded (callID absent from %s)' % self.event)
        self.agent_id = shared._text(metadata.get('sessionId'), 'unrecorded (no agent id in %s)' % self.event)
        self.keys = sorted(str(key) for key in payload)

    def error(self, folder, stage, reason, record='unknown'):
        ledger.error(ledger=folder, stage=stage, reason=reason, session=self.session,
                     call_id=self.call_id, agent_id=self.agent_id, harness=HARNESS, event=self.event,
                     record=record, payload_keys=self.keys)


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    folder = None
    if '--ledger' in argv:
        at = argv.index('--ledger')
        folder = argv[at + 1] if at + 1 < len(argv) else None
        del argv[at:at + 2]
    event = argv[0] if argv else None
    if event == 'event' and len(argv) > 1:
        event = 'event:%s' % argv[1]
    try:
        text = sys.stdin.read()
    except Exception as exc:
        text = None
        Held(event, None).error(folder, 'payload', 'standard input could not be read: %s' % exc)
    if text is not None:
        with contextlib.redirect_stdout(io.StringIO()):
            handle(event, text, folder)
    return 0


def handle(event, text, folder=None):
    """Handle one plugin event's payload text. Never raises; every failure is an error line."""
    try:
        payload = json.loads(text)
        if not isinstance(payload, dict):
            raise ValueError('the payload is not a JSON object')
    except (TypeError, ValueError) as exc:
        shown = 'empty' if not (text or '').strip() else 'not JSON'
        Held(event, None).error(folder, 'payload', 'the payload on standard input is %s: %s' % (shown, exc))
        return
    if (event or '').split(':')[0] == 'event':
        return handle_event(payload, folder)
    held = Held(event, payload)
    try:
        folder = ledger.ledger_folder(folder)
        given = payload.get('input') if isinstance(payload.get('input'), dict) else {}
        if not is_subagent_tool(given.get('tool')):
            return
        if event == 'before':
            return before(payload, folder, held)
        if event == 'after':
            return after(payload, folder, held)
    except Exception as exc:  # the capture's own fault: recorded, never raised to the plugin
        held.error(folder, 'payload', 'the capture failed: %s: %s' % (type(exc).__name__, exc))


# ---------------------------------------------------------------------------
# The general event hook: a failed task's return
# ---------------------------------------------------------------------------

class EventHeld(Held):
    """What an error line names for an event: read from the task part before any other work."""

    def __init__(self, event_type, part):
        part = part if isinstance(part, dict) else {}
        state = part.get('state') if isinstance(part.get('state'), dict) else {}
        metadata = state.get('metadata') if isinstance(state.get('metadata'), dict) else {}
        self.event = 'event:%s' % event_type
        self.session = shared._text(part.get('sessionID'), 'unrecorded (sessionID absent from %s)' % self.event)
        self.call_id = shared._text(part.get('callID'), 'unrecorded (callID absent from %s)' % self.event)
        self.agent_id = shared._text(metadata.get('sessionId'), 'unrecorded (no agent id in %s)' % self.event)
        self.keys = sorted(str(key) for key in part)


def task_part(payload):
    """The event's type, and its task part where it is a task's tool part, else None."""
    event = payload.get('event') if isinstance(payload.get('event'), dict) else {}
    event_type = event.get('type') if isinstance(event.get('type'), str) else 'unrecorded (no event type)'
    properties = event.get('properties') if isinstance(event.get('properties'), dict) else {}
    part = properties.get('part') if isinstance(properties.get('part'), dict) else None
    if part is None or part.get('type') != 'tool' or not is_subagent_tool(part.get('tool')):
        return event_type, None
    return event_type, part


def handle_event(payload, folder=None):
    event_type, part = task_part(payload)
    if part is None:
        return
    state = part.get('state') if isinstance(part.get('state'), dict) else {}
    if state.get('status') != 'error':
        return
    held = EventHeld(event_type, part)
    try:
        folder = ledger.ledger_folder(folder)
        on_event(event_type, part, payload, folder, held)
    except Exception as exc:  # the capture's own fault: recorded, never raised to the plugin
        held.error(folder, 'payload', 'the capture failed: %s: %s' % (type(exc).__name__, exc), record='return')


def pending_calls(folder, session):
    """The call ids of the session's dispatches still waiting for a return."""
    folder = shared.pending_dir(folder, session)
    return sorted(path.stem for path in folder.glob('*.json') if not path.stem.startswith('join-'))


def already_returned(folder, session, call_id):
    """Whether the session's ledger file already holds a return for the call."""
    path = Path(folder) / ('%s.jsonl' % session)
    try:
        lines = path.read_text(encoding='utf-8', errors='replace').splitlines()
    except OSError:
        return False
    for line in lines:
        try:
            row = json.loads(line)
        except ValueError:
            continue
        if isinstance(row, dict) and row.get('record') == 'return' and row.get('call_id') == call_id:
            return True
    return False


def tie(pending, call_id):
    """The pending dispatch the event names: its call id, exactly. No guess by time or order."""
    return call_id if call_id in pending else None


def on_event(event_type, part, payload, folder, held):
    """A task part in state "error": the failed return of its pending dispatch."""
    if held.session.startswith('unrecorded ('):
        held.error(folder, 'payload', 'a task error event named no session', record='return')
        return
    with shared.pending_lock(folder, held.session):
        call_id = None if held.call_id.startswith('unrecorded (') else held.call_id
        if call_id and already_returned(folder, held.session, call_id):
            return
        pending = pending_calls(folder, held.session)
        tied = tie(pending, call_id)
        if tied is None:
            held.error(folder, 'payload', 'a task error event (%s) could not be tied to a pending dispatch: '
                       'it names %s; pending: %s' % (event_type, call_id or 'no call id',
                                                    ', '.join(pending) or 'none'), record='return')
            return
        state = part.get('state') if isinstance(part.get('state'), dict) else {}
        metadata = state.get('metadata') if isinstance(state.get('metadata'), dict) else {}
        text = state.get('error') if isinstance(state.get('error'), str) and state.get('error') else \
            'the task part reported status error with no error text'
        model = metadata.get('model') if isinstance(metadata.get('model'), dict) else {}
        provider, name = model.get('providerID'), model.get('modelID')
        fields = common(payload, held)
        fields.update({
            'call_id': tied,
            'agent_id': held.agent_id if not held.agent_id.startswith('unrecorded (') else
            'unrecorded (state.metadata.sessionId absent from %s)' % event_type,
            'outcome': 'failed',
            'outcome_reason': ledger.reason_for(HARNESS, text, fallback='harness_error'),
            'model': '%s/%s' % (provider, name) if isinstance(provider, str) and isinstance(name, str)
            and provider and name else 'unrecorded (model absent from %s)' % event_type,
            'tokens': NO_COUNTERS, 'cost': SUBAGENT_COST, 'spend_line': NOT_A_SCRIPT, 'effort': NO_EFFORT,
            'isolation': isolation_from_db(held.agent_id),
        })
        given = state.get('input') if isinstance(state.get('input'), dict) else {}
        kept = {'event_type': event_type, 'event': payload.get('event'), 'directory': payload.get('directory')}
        fields['harness_payload'] = shared.without_texts(kept, given.get('prompt'), shared.ON_DISPATCH_BRIEF)
        sent = shared.read_pending(folder, held.session, tied)
        if sent and sent.get('dispatched_at'):
            fields['dispatched_at'] = sent['dispatched_at']
        ledger.ret(ledger=folder, **fields)
        shared.clear_pending(folder, held.session, [tied])


def common(payload, held):
    directory = payload.get('directory')
    return {'session': held.session, 'harness': HARNESS, 'route': 'subagent', 'caller': 'parent',
            'project': shared.project_of(directory)}


def args_of(payload):
    given = payload.get('input') if isinstance(payload.get('input'), dict) else {}
    output = payload.get('output') if isinstance(payload.get('output'), dict) else {}
    args = output.get('args') if isinstance(output.get('args'), dict) else given.get('args')
    return args if isinstance(args, dict) else {}


def before(payload, folder, held):
    if held.call_id.startswith('unrecorded ('):
        held.error(folder, 'payload', 'no call_id (callID absent from tool.execute.before)', record='dispatch')
        return
    args = args_of(payload)
    prompt = args.get('prompt') if isinstance(args.get('prompt'), str) else ''
    if not prompt:
        held.error(folder, 'payload', 'args.prompt absent from tool.execute.before', record='dispatch')
    brief, source = shared.brief_of(prompt, payload.get('directory'))
    asked = args.get('model')
    at = ledger.now()
    fields = common(payload, held)
    fields.update({
        'call_id': held.call_id,
        'agent_id': DISPATCH_AGENT,
        'dispatched_at': at,
        'model_requested': asked if isinstance(asked, str) and asked else None,
        'auth_route': NO_PROVIDER,
        'brief_source': source,
        'harness_payload': {'input': payload.get('input'), 'args': args,
                            'directory': payload.get('directory')},
    })
    fields.update(shared.optional_fields(folder, brief if source else prompt))
    with shared.pending_lock(folder, held.session):
        shared.write_pending(folder, held.session, held.call_id, {'call_id': held.call_id, 'dispatched_at': at})
    ledger.dispatch(ledger=folder, brief=brief or None, prompt=prompt if source and prompt else None, **fields)


def after(payload, folder, held):
    if held.call_id.startswith('unrecorded ('):
        held.error(folder, 'payload', 'no call_id (callID absent from tool.execute.after)', record='return')
        return
    output = payload.get('output') if isinstance(payload.get('output'), dict) else {}
    metadata = output.get('metadata') if isinstance(output.get('metadata'), dict) else {}
    answer = output.get('output') if isinstance(output.get('output'), str) else ''
    if 'output' not in output:
        held.error(folder, 'payload', 'output.output absent from tool.execute.after', record='return')
    model = metadata.get('model') if isinstance(metadata.get('model'), dict) else {}
    provider, name = model.get('providerID'), model.get('modelID')
    if isinstance(provider, str) and isinstance(name, str) and provider and name:
        model_name = '%s/%s' % (provider, name)
    else:
        model_name = 'unrecorded (model absent from tool.execute.after)'
    outcome, reason = task_outcome(answer)
    fields = common(payload, held)
    fields.update({
        'call_id': held.call_id,
        'agent_id': held.agent_id if not held.agent_id.startswith('unrecorded (') else
        'unrecorded (output.metadata.sessionId absent from tool.execute.after)',
        'outcome': outcome, 'outcome_reason': reason,
        'model': model_name, 'tokens': NO_COUNTERS, 'cost': SUBAGENT_COST, 'spend_line': NOT_A_SCRIPT,
        'effort': NO_EFFORT,
        'isolation': isolation_from_db(held.agent_id),
    })
    kept_output = dict(output)
    kept_output['output'] = answer
    kept = {'input': payload.get('input'), 'output': kept_output, 'directory': payload.get('directory')}
    fields['harness_payload'] = shared.without_texts(kept, args_of(payload).get('prompt'), shared.ON_DISPATCH_BRIEF)
    with shared.pending_lock(folder, held.session):
        sent = shared.read_pending(folder, held.session, held.call_id)
        if sent and sent.get('dispatched_at'):
            fields['dispatched_at'] = sent['dispatched_at']
        ledger.ret(ledger=folder, answer=answer, **fields)
        shared.clear_pending(folder, held.session, [held.call_id])


def task_outcome(text):
    """served, empty or failed, from the task tool's output: `<task ... state="completed">`."""
    state = STATE.search(text or '')
    if state is not None and state.group(1) != 'completed':
        return 'failed', ledger.reason_for(HARNESS, text, fallback='harness_error')
    found = RESULT.search(text or '')
    body = found.group(1) if found else (text or '')
    if body.strip():
        return 'served', 'none (served)'
    return 'empty', {'class': 'empty_answer', 'text': 'the call was served and its answer was empty'}


def database():
    """OpenCode's database: <XDG_DATA_HOME or ~/.local/share>/opencode/opencode.db."""
    base = os.environ.get('XDG_DATA_HOME') or str(Path.home() / '.local' / 'share')
    return Path(base) / 'opencode' / 'opencode.db'


def isolation_from_db(agent_id):
    """The child session's folder and its tool calls' inputs, read from the database read-only (§3h)."""
    if not isinstance(agent_id, str) or agent_id.startswith('unrecorded ('):
        return 'unrecorded (no subagent session id to look up)'
    path = database()
    if not path.is_file():
        return 'unrecorded (OpenCode\'s database was not found at %s)' % path
    try:
        db = sqlite3.connect('file:%s?mode=ro' % path, uri=True)
        try:
            row = db.execute('select directory from session where id = ?', (agent_id,)).fetchone()
            parts = db.execute('select data from part where session_id = ? order by time_created',
                               (agent_id,)).fetchall()
        finally:
            db.close()
    except sqlite3.Error as exc:
        return 'unrecorded (OpenCode\'s database could not be read: %s)' % exc
    if row is None:
        return 'unrecorded (session %s is not in OpenCode\'s database)' % agent_id
    uses = []
    for (data,) in parts:
        try:
            part = json.loads(data)
        except (TypeError, ValueError):
            continue
        if not isinstance(part, dict) or part.get('type') != 'tool':
            continue
        state = part.get('state') if isinstance(part.get('state'), dict) else {}
        uses.append({'name': part.get('tool'), 'input': state.get('input')})
    reading = {'cwd': row[0], 'tool_uses': uses, 'path': str(path), 'isolation_limit': LIMIT}
    return transcripts.isolation(reading)


if __name__ == '__main__':
    sys.exit(main())
