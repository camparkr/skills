#!/usr/bin/env python3
"""The subagent ledger's one writer: every line in a ledger folder is written here.

A call to a subagent, or to another model through a command-line tool or a call script, leaves two
records: a dispatch record when it is sent and a return record when it comes back, joined by
`call_id`. A harness's subagent start and stop events may also leave witness lines, a roster labeller
leaves a label line beside a call it has labelled, and a capture that could not write its record
leaves an error line saying why.

Use it as a module:

    import ledger
    sent = ledger.dispatch(call_id=..., session=..., route='script', brief=<text>, ...)
    sent = ledger.dispatch(..., brief=<the named file's text>, prompt=<the prompt's own words>)
    back = ledger.ret(sent, session=..., outcome='served', answer=<text>, ...)
    ledger.witness(event='SubagentStart', session=..., agent_id=...)
    ledger.label(call_id=<the labelled call>, session=..., likelihoods={...}, ...)
    ledger.error(stage='payload', reason=..., session=..., event=...)

or as a command, with the fields as one JSON object on standard input:

    python3 ledger.py dispatch|return|witness|label|error [--ledger <folder>]

The command prints nothing on standard output and exits 0 on every path, so a harness hook that
runs it never blocks or changes a call.

Before a record is written the writer applies the field setting (a witness line and a label line
take none), validates the record against
`record.schema.json`, replaces every credential it can recognise with `[withheld]`, and copies the
brief and the answer into the ledger folder, recording their paths in place of the text. A record
that fails at any of these stages, or whose write fails, is not written: one line goes to
`<ledger>/capture-errors.jsonl` naming the stage, the session and call id the caller passed, the
reason, and the names (never the values) of the fields passed. If that line cannot be written
either, it goes to standard error. The writer never raises to its caller: each function returns a
`Result`, a string holding the call id with `.ok`, `.path` and `.error` beside it.

The ledger folder is, in order: the `ledger` argument; `$SUBAGENT_LEDGER_DIR`; `.subagent-ledger` in
the git top-level folder of the working folder. One file per session, `<ledger>/<session>.jsonl`;
a record whose session cannot be read goes to `<ledger>/unattributed.jsonl`.

Validation uses no package: the validator below implements exactly the JSON Schema 2020-12 keywords
the schema uses, and refuses a schema that uses any other.
"""

import contextlib
import datetime
import fcntl
import hashlib
import json
import os
import re
import socket
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
SCHEMA_FILE = HERE / 'record.schema.json'
REASONS_FILE = HERE / 'reasons.json'

RECORD_SCHEMA = 'subagent-ledger/1'
ERROR_SCHEMA = 'subagent-ledger-error/1'
ERRORS_FILE = 'capture-errors.jsonl'
UNATTRIBUTED = 'unattributed'
CONFIG_FILE = 'config.json'
FOLDER_VARIABLE = 'SUBAGENT_LEDGER_DIR'
DEFAULT_FOLDER_NAME = '.subagent-ledger'
REASON_LIMIT = 400
# An environment value shorter than this is not treated as a credential: a short value such as
# `1` or `true` would otherwise be replaced wherever it appears in a record.
SHORTEST_SECRET = 8
SECRET_NAME_PARTS = ('KEY', 'TOKEN', 'SECRET')

FRAME = ('call_id', 'agent_id', 'session', 'dispatched_at', 'returned_at', 'outcome')
STRUCTURAL = ('schema', 'record', 'fields_on', 'fields_not_chosen', 'withheld')
# The selectable fields in the schema's order; a test holds this list to the schema's.
SELECTABLE = (
    'model_requested', 'model', 'tokens', 'cost', 'outcome_reason', 'route', 'harness', 'machine',
    'caller', 'project', 'effort', 'effort_assigned', 'auth_route', 'brief_path', 'brief_source',
    'answer_path', 'isolation', 'harness_payload', 'spend_line', 'persona-name', 'characteristic',
    'grouping', 'task', 'failure_modes', 'roster_revision', 'labeller_model', 'recommended_harness',
    'recommended_model', 'triage_model',
)
DEFAULT_FIELDS = ('model_requested', 'model', 'tokens', 'cost', 'outcome_reason')
# Which record a selectable field belongs to. A field that is on and belongs to the other record
# reads `unrecorded (<reason>)` saying where it is.
DISPATCH_ONLY = {'model_requested', 'effort_assigned', 'auth_route', 'brief_path', 'brief_source',
                 'persona-name', 'characteristic', 'grouping', 'task', 'recommended_harness',
                 'recommended_model', 'triage_model'}
RETURN_ONLY = {'model', 'tokens', 'cost', 'outcome_reason', 'effort', 'answer_path', 'isolation',
               'spend_line', 'failure_modes', 'roster_revision', 'labeller_model'}
# Written beside a selectable field, and only when that field is on.
COMPANIONS = {'model_check': 'model'}
# A call's labels are written beside it, on a label line, and never on its own records.
ON_LABEL_LINE = 'unrecorded (labelled on the label line)'
# Why a field that is on has no value, where the capture gave none.
NOT_GIVEN = {
    'model_requested': 'unrecorded (none asked)',
    'effort_assigned': 'unrecorded (no triage: slice B7 not built)',
    'recommended_harness': 'unrecorded (no triage: slice B7 not built)',
    'recommended_model': 'unrecorded (no triage: slice B7 not built)',
    'triage_model': 'unrecorded (no triage: slice B7 not built)',
    'failure_modes': ON_LABEL_LINE,
    'roster_revision': ON_LABEL_LINE,
    'labeller_model': ON_LABEL_LINE,
    'brief_source': 'unrecorded (the prompt named no file)',
    'persona-name': 'unrecorded (the brief names no persona)',
    'grouping': 'unrecorded (the brief names no persona)',
    'characteristic': 'unrecorded (not given in the brief)',
    'task': 'unrecorded (the brief names no task)',
}
NO_VALUE = 'unrecorded (the capture supplied no value)'
ON_DISPATCH = 'unrecorded (carried on the dispatch record)'
ON_RETURN = 'unrecorded (filled on the return record)'
NOT_PASSED = 'unrecorded (not passed to the writer)'
# Special arguments: text the writer moves to a file, and where the ledger is. Never record fields.
SPECIAL = ('brief', 'answer', 'prompt', 'ledger')
# A label line's keys in §7's order, the writer's own `schema`, `record` and `withheld` among them.
LABEL_ORDER = ('schema', 'record', 'call_id', 'session', 'labelled_at', 'failure_modes', 'likelihoods', 'cutoff',
               'roster_revision', 'labeller_model', 'labeller_call_id', 'withheld')
# The line kinds that take no field setting.
UNSET_LINES = ('witness', 'label')


class UnknownKeyword(Exception):
    """The schema uses a keyword this validator does not implement. Raised, never ignored."""


class Result(str):
    """A writer's answer: the call id as a string, with whether the line was written."""

    def __new__(cls, value, ok, path=None, error=None):
        made = str.__new__(cls, value if isinstance(value, str) else '')
        made.ok = ok
        made.path = path
        made.error = error
        return made


# ---------------------------------------------------------------------------
# Public functions
# ---------------------------------------------------------------------------

def dispatch(ledger=None, brief=None, prompt=None, **fields):
    """Write the dispatch record of one call. Returns a Result holding the call id.

    `prompt` is a second text copied beside the brief under the same rules, for a prompt that
    named a brief file: it is scrubbed, named by its hash in the session's folder, and any string
    equal to it in harness_payload becomes `moved to <path>`. It adds no field to the record.
    """
    return _record('dispatch', ledger, fields, brief=brief, prompt=prompt)


def ret(call_id=None, ledger=None, answer=None, **fields):
    """Write the return record of the call `call_id`. Returns a Result holding the call id."""
    if call_id is not None:
        fields['call_id'] = str(call_id)
    return _record('return', ledger, fields, answer=answer)


def witness(ledger=None, **fields):
    """Write a witness line: a harness event seen for a call, which is not itself a call."""
    return _record('witness', ledger, fields)


def label(ledger=None, **fields):
    """Write a label line: one call's failure-mode labels, beside the call and never on its records.

    It takes no field setting and is always written, as a witness line is. `labelled_at` defaults to now.
    """
    return _record('label', ledger, fields)


def error(ledger=None, **fields):
    """Write an error line for a capture that could not write its record."""
    held = _held(fields, 'unknown', fields.get('record'))
    keys = fields.get('payload_keys')
    if not isinstance(keys, list):
        keys = sorted(k for k in fields if k not in ('stage', 'reason', 'payload_keys'))
    try:
        folder = Path(ledger_folder(ledger))
    except Exception as exc:  # the folder cannot even be named: standard error is all that is left
        folder = None
        held['reason_extra'] = str(exc)
    return _error_line(folder, fields.get('stage', 'payload'), fields.get('reason', ''), held, keys,
                       requested=True)


def ledger_folder(explicit=None):
    """The ledger folder: the argument, then $SUBAGENT_LEDGER_DIR, then <git top>/.subagent-ledger."""
    if explicit:
        return str(explicit)
    named = os.environ.get(FOLDER_VARIABLE)
    if named:
        return named
    top = _git_top(Path(os.getcwd()))
    return str((top or Path(os.getcwd())) / DEFAULT_FOLDER_NAME)


def reason_for(harness, *texts, fallback=None, fixed=None):
    """The reason class for a call that was not served, and the text it was read from.

    `fixed` is a class the caller already knows (a 429 is `rate_limited` whatever it says); otherwise
    the harness's patterns in reasons.json, then the default patterns, are tried against each text
    in order. No match gives `fallback`, or `other`.
    """
    texts = [t if isinstance(t, str) else json.dumps(t, ensure_ascii=False) for t in texts
             if t not in (None, '')]
    first = texts[0] if texts else 'no text came back with the failure'
    if fixed:
        return {'class': fixed, 'text': first[:REASON_LIMIT]}
    try:
        table = json.loads(REASONS_FILE.read_text(encoding='utf-8'))['patterns']
    except (OSError, ValueError, KeyError):
        table = {}
    for entry in list(table.get(harness) or []) + list(table.get('default') or []):
        for text in texts:
            if re.search(entry['pattern'], text, re.IGNORECASE):
                return {'class': entry['class'], 'text': text[:REASON_LIMIT]}
    return {'class': fallback or 'other', 'text': first[:REASON_LIMIT]}


def now():
    """The time, RFC 3339 in UTC, to the millisecond."""
    stamp = datetime.datetime.now(datetime.timezone.utc)
    return stamp.strftime('%Y-%m-%dT%H:%M:%S.') + '%03dZ' % (stamp.microsecond // 1000)


_SCHEMA = {}


def load_schema():
    """The record schema, read once per process. Callers that change it work on a copy."""
    stamp = SCHEMA_FILE.stat().st_mtime_ns
    if _SCHEMA.get('stamp') != stamp:
        _SCHEMA['schema'] = json.loads(SCHEMA_FILE.read_text(encoding='utf-8'))
        _SCHEMA['stamp'] = stamp
    return _SCHEMA['schema']


# ---------------------------------------------------------------------------
# The writer's stages
# ---------------------------------------------------------------------------

_DISPATCHED = {}


def _record(kind, explicit, fields, brief=None, answer=None, prompt=None):
    held = _held(fields, kind, kind)
    keys = sorted(list(fields) + [name for name, text in (('brief', brief), ('answer', answer),
                                                          ('prompt', prompt))
                                  if text is not None])
    try:
        folder = Path(ledger_folder(explicit))
    except Exception as exc:
        return _error_line(None, 'payload', 'the ledger folder could not be named: %s' % exc, held, keys)
    stage = 'payload'
    try:
        json.dumps(fields)
        if brief is not None and not isinstance(brief, str):
            raise TypeError('the brief is not text')
        if answer is not None and not isinstance(answer, str):
            raise TypeError('the answer is not text')
        if prompt is not None and not isinstance(prompt, str):
            raise TypeError('the prompt is not text')

        stage = 'setting'
        on = None if kind in UNSET_LINES else _fields_on(folder)

        stage = 'validate'
        record = _build(kind, folder, fields, on, brief, answer)
        problems = _validate_record(record, kind)
        if problems:
            return _error_line(folder, stage, '; '.join(problems), held, keys)

        stage = 'scrub'
        secrets, shapes = _secrets(), _shapes()
        record, count = _scrub(record, secrets, shapes)
        texts = {}
        for name, text in (('brief', brief), ('answer', answer), ('prompt', prompt)):
            if text is not None and not (name == 'prompt' and text == brief):
                texts[name], more = _scrub(text, secrets, shapes)
                count += more
        record['withheld'] = count

        stage = 'copy'
        _copy(record, folder, texts)
        problems = _validate_record(record, kind)
        if problems:
            return _error_line(folder, 'scrub', 'the record no longer validates after the scrub and '
                                                'copy: ' + '; '.join(problems), held, keys)

        stage = 'write'
        target = _session_file(folder, record['session'])
        _append(target, json.dumps(record, ensure_ascii=False) + '\n')
    except UnknownKeyword as exc:
        print('subagent-ledger: %s' % exc, file=sys.stderr)
        return _error_line(folder, 'validate', str(exc), held, keys)
    except Exception as exc:
        return _error_line(folder, stage, '%s: %s' % (type(exc).__name__, exc), held, keys)
    if kind == 'dispatch' and isinstance(record.get('call_id'), str):
        _DISPATCHED[record['call_id']] = record['dispatched_at']
    return Result(record.get('call_id', ''), True, path=str(target))


def _held(fields, kind, record_kind):
    """What an error line names, read from the raw arguments before any other work."""
    def text(name):
        value = fields.get(name)
        if value is None:
            return NOT_PASSED
        return value if isinstance(value, str) else 'unrecorded (%s passed was not text)' % name
    event = fields.get('event')
    if event is None and kind in ('dispatch', 'return'):
        event = NOT_PASSED
    return {'session': text('session'), 'call_id': text('call_id'), 'agent_id': text('agent_id'),
            'harness': text('harness'), 'event': event if isinstance(event, str) else NOT_PASSED,
            'record': record_kind if record_kind in ('dispatch', 'return', 'witness', 'label') else 'unknown'}


def _fields_on(folder):
    """The selectable fields the setting turns on, in the schema's order."""
    path = folder / CONFIG_FILE
    if not path.is_file():
        return set(DEFAULT_FIELDS)
    try:
        setting = json.loads(path.read_text(encoding='utf-8')).get('fields', 'default')
    except (OSError, ValueError, AttributeError) as exc:
        raise ValueError('%s could not be read: %s' % (path, exc))
    if setting == 'default':
        return set(DEFAULT_FIELDS)
    if setting == 'frame':
        return set()
    if setting == 'all':
        return set(SELECTABLE)
    if isinstance(setting, list) and all(isinstance(name, str) for name in setting):
        unknown = [name for name in setting if name not in SELECTABLE]
        if unknown:
            raise ValueError('%s names fields the record does not have: %s'
                             % (CONFIG_FILE, ', '.join(unknown)))
        return set(setting)
    raise ValueError('%s: fields must be "default", "frame", "all" or a list of field names'
                     % CONFIG_FILE)


def _build(kind, folder, fields, on, brief, answer):
    if kind == 'witness':
        record = {'schema': RECORD_SCHEMA, 'record': 'witness'}
        record.update(fields)
        record.setdefault('call_id', 'unrecorded (not carried by %s)' % fields.get('event', 'this event'))
        record.setdefault('session', 'unrecorded (no session in the payload)')
        record.setdefault('at', now())
        record['withheld'] = 0
        return record
    if kind == 'label':
        given = dict(fields, schema=RECORD_SCHEMA, record='label', withheld=0)
        given.setdefault('session', 'unrecorded (no session was passed)')
        given.setdefault('labelled_at', now())
        record = dict((name, given.pop(name)) for name in LABEL_ORDER if name in given)
        # Anything left is not a field of the line; it stays, so validation names it.
        record.update(given)
        return record
    record = {'schema': RECORD_SCHEMA, 'record': kind}
    given = dict(fields)
    # The harness event names the call on an error line; a call record has no field for it.
    given.pop('event', None)
    if 'call_id' in given:
        record['call_id'] = given.pop('call_id')
    session = given.pop('session', None)
    record['session'] = session if session is not None else 'unrecorded (no session in the payload)'
    if kind == 'dispatch':
        record['agent_id'] = given.pop('agent_id', 'unrecorded (assigned after dispatch)')
        record['dispatched_at'] = given.pop('dispatched_at', now())
        record['returned_at'] = given.pop('returned_at', 'unrecorded (not yet returned)')
        record['outcome'] = given.pop('outcome', 'unrecorded (not yet returned)')
    else:
        record['agent_id'] = given.pop('agent_id', 'unrecorded (the capture supplied no agent id)')
        record['dispatched_at'] = given.pop('dispatched_at', None) or _dispatched_at(
            folder, record.get('call_id'), record['session'])
        record['returned_at'] = given.pop('returned_at', now())
        if 'outcome' in given:
            record['outcome'] = given.pop('outcome')
    for name in SELECTABLE:
        value = given.pop(name, None)
        if name not in on:
            continue
        if value is None:
            value = _not_given(kind, name, brief, answer)
        record[name] = value
    for name, owner in COMPANIONS.items():
        value = given.pop(name, None)
        if value is not None and owner in on:
            record[name] = value
    # Anything left is not a field of the record; it stays, so validation names it.
    record.update(given)
    record['fields_on'] = [name for name in SELECTABLE if name in on]
    record['fields_not_chosen'] = [name for name in SELECTABLE if name not in on]
    record['withheld'] = 0
    return record


def _not_given(kind, name, brief, answer):
    if kind == 'dispatch' and name in RETURN_ONLY:
        return ON_RETURN
    if kind == 'return' and name in DISPATCH_ONLY:
        return ON_DISPATCH
    if name == 'machine':
        return socket.gethostname().split('.')[0] or 'unrecorded (the host gave no name)'
    if name == 'project':
        top = _git_top(Path(os.getcwd()))
        return top.name if top else 'unrecorded (the working folder is in no git repository)'
    if name == 'brief_path':
        return 'unrecorded (no brief was passed)' if brief is None else 'unrecorded (pending copy)'
    if name == 'answer_path':
        return 'unrecorded (no answer came back)' if answer is None else 'unrecorded (pending copy)'
    return NOT_GIVEN.get(name, NO_VALUE)


def _dispatched_at(folder, call_id, session):
    if call_id in _DISPATCHED:
        return _DISPATCHED[call_id]
    path = _session_file(folder, session) if isinstance(session, str) else None
    if call_id and path is not None and path.is_file():
        try:
            for line in path.read_text(encoding='utf-8').splitlines():
                try:
                    row = json.loads(line)
                except ValueError:
                    continue
                if row.get('record') == 'dispatch' and row.get('call_id') == call_id:
                    return row.get('dispatched_at')
        except OSError:
            pass
    return 'unrecorded (no dispatch record for this call was found)'


def _validate_record(record, kind):
    """Problems with the record against its part of the schema; an empty list if none."""
    schema = load_schema()
    return validate(record, schema, ref='#/$defs/%s' % kind)


def _secrets():
    values = set()
    for name, value in os.environ.items():
        if any(part in name.upper() for part in SECRET_NAME_PARTS) and len(value) >= SHORTEST_SECRET:
            values.add(value)
    return sorted(values, key=len, reverse=True)


def _shapes():
    data = json.loads(REASONS_FILE.read_text(encoding='utf-8'))
    return [re.compile(pattern) for pattern in data['credential_shapes']]


def _scrub(value, secrets, shapes):
    """The value with every credential replaced by [withheld], and how many were replaced."""
    if isinstance(value, str):
        count = 0
        for secret in secrets:
            found = value.count(secret)
            if found:
                value = value.replace(secret, '[withheld]')
                count += found
        for shape in shapes:
            value, found = shape.subn('[withheld]', value)
            count += found
        return value, count
    if isinstance(value, dict):
        out, count = {}, 0
        for key, item in value.items():
            key, a = _scrub(key, secrets, shapes)
            item, b = _scrub(item, secrets, shapes)
            out[key] = item
            count += a + b
        return out, count
    if isinstance(value, list):
        out, count = [], 0
        for item in value:
            item, found = _scrub(item, secrets, shapes)
            out.append(item)
            count += found
        return out, count
    return value, 0


def _copy(record, folder, texts):
    """Write the brief and the answer to <ledger>/<session>/<hash>.md, and name them on the record."""
    if not texts:
        return
    folder_out = _copy_dir(folder, record['session'])
    top = _git_top(folder)
    for name, text in texts.items():
        digest = hashlib.sha256(text.encode('utf-8')).hexdigest()[:16]
        target = folder_out / ('%s.md' % digest)
        target.parent.mkdir(parents=True, exist_ok=True)
        if not target.exists():
            target.write_text(text, encoding='utf-8')
        try:
            shown = str(target.resolve().relative_to(top.resolve())) if top else str(target)
        except ValueError:
            shown = str(target)
        field = '%s_path' % name
        if field in record:
            record[field] = shown
        payload = record.get('harness_payload')
        if isinstance(payload, dict):
            record['harness_payload'] = _moved(payload, text, 'moved to %s' % shown)


def _moved(node, text, marker):
    if isinstance(node, str):
        return marker if node == text else node
    if isinstance(node, dict):
        return dict((key, _moved(value, text, marker)) for key, value in node.items())
    if isinstance(node, list):
        return [_moved(value, text, marker) for value in node]
    return node


def _is_unrecorded(session):
    return not isinstance(session, str) or session.startswith('unrecorded (')


def _session_file(folder, session):
    if _is_unrecorded(session):
        return Path(folder) / ('%s.jsonl' % UNATTRIBUTED)
    return Path(folder) / ('%s.jsonl' % session)


def _copy_dir(folder, session):
    if _is_unrecorded(session):
        return Path(folder) / UNATTRIBUTED
    return Path(folder) / session


@contextlib.contextmanager
def _lock(handle):
    fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
    try:
        yield
    finally:
        fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


def _append(path, line):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open('a', encoding='utf-8') as handle:
        with _lock(handle):
            handle.write(line)
            handle.flush()


def _error_line(folder, stage, reason, held, keys, requested=False):
    """Write the error line; failing that, print it to standard error.

    Returns a failed Result, since the record it stands for was not written; when the error line
    itself was what the caller asked for (`requested`), a written line is a success.
    """
    reason = str(reason)
    if held.get('reason_extra'):
        reason = '%s (the ledger folder could not be named: %s)' % (reason, held['reason_extra'])
    line = {'schema': ERROR_SCHEMA, 'at': now(), 'session': held['session'],
            'call_id': held['call_id'], 'agent_id': held['agent_id'], 'record': held['record'],
            'harness': held['harness'], 'event': held['event'], 'stage': stage,
            'reason': reason[:REASON_LIMIT], 'payload_keys': [str(k) for k in keys]}
    try:
        line, _count = _scrub(line, _secrets(), _shapes())
    except Exception:
        line, _count = _scrub(line, _secrets(), [])
    line['reason'] = line['reason'][:REASON_LIMIT]
    text = json.dumps(line, ensure_ascii=False)
    call_id = held['call_id'] if not held['call_id'].startswith('unrecorded (') else ''
    if folder is None:
        print(text, file=sys.stderr)
        return Result(call_id, False, error=reason)
    try:
        problems = validate(line, load_schema(), ref='#/$defs/error')
        if problems:
            raise ValueError('the error line does not validate: %s' % '; '.join(problems))
        _append(Path(folder) / ERRORS_FILE, text + '\n')
        return Result(call_id, requested, path=str(Path(folder) / ERRORS_FILE),
                      error=None if requested else reason)
    except Exception as exc:
        print(text, file=sys.stderr)
        print('subagent-ledger: the error line above could not be written: %s' % exc, file=sys.stderr)
        return Result(call_id, False, error=reason)


def _git_top(start):
    for folder in [start] + list(start.parents):
        if (folder / '.git').exists():
            return folder
    return None


# ---------------------------------------------------------------------------
# The validator: JSON Schema 2020-12, the keywords record.schema.json uses and no others
# ---------------------------------------------------------------------------

IMPLEMENTED_KEYWORDS = ('$ref', '$defs', 'type', 'enum', 'const', 'pattern', 'minLength', 'maxLength',
                        'minimum', 'properties', 'required', 'additionalProperties', 'items',
                        'uniqueItems', 'contains', 'not', 'if', 'then', 'else', 'allOf', 'anyOf',
                        'oneOf')
# Keywords that describe and never validate.
ANNOTATION_KEYWORDS = ('$schema', '$id', '$comment', 'title', 'description', 'x-opentelemetry')
DRAFT = 'https://json-schema.org/draft/2020-12/schema'
SUBSCHEMA_MAPS = ('properties', '$defs')
SUBSCHEMA_LISTS = ('allOf', 'anyOf', 'oneOf')
SUBSCHEMA_ONE = ('items', 'contains', 'not', 'if', 'then', 'else', 'additionalProperties')


def validate(instance, schema=None, ref=None):
    """Problems with `instance` against `schema` (or its part at `ref`); an empty list if none.

    Raises UnknownKeyword if the schema uses a keyword this validator does not implement.
    """
    schema = load_schema() if schema is None else schema
    _check_keywords(schema)
    if schema.get('$schema') not in (None, DRAFT):
        raise UnknownKeyword('the schema declares %s; this validator implements %s only'
                             % (schema.get('$schema'), DRAFT))
    start = _resolve(schema, ref) if ref else schema
    return _validate(instance, start, schema, '$')


def _check_keywords(schema):
    unknown = set()

    def walk(node):
        if not isinstance(node, dict):
            return
        for key, value in node.items():
            if key not in IMPLEMENTED_KEYWORDS and key not in ANNOTATION_KEYWORDS:
                unknown.add(key)
            if key in SUBSCHEMA_MAPS and isinstance(value, dict):
                for sub in value.values():
                    walk(sub)
            elif key in SUBSCHEMA_LISTS and isinstance(value, list):
                for sub in value:
                    walk(sub)
            elif key in SUBSCHEMA_ONE:
                walk(value)
    walk(schema)
    if unknown:
        raise UnknownKeyword('the schema uses %s, which this validator does not implement; it '
                             'refuses the schema rather than ignore them' % ', '.join(sorted(unknown)))


def _resolve(root, ref):
    if not ref.startswith('#'):
        raise UnknownKeyword('only references inside the schema are implemented: %s' % ref)
    node = root
    for part in [p for p in ref[1:].split('/') if p]:
        part = part.replace('~1', '/').replace('~0', '~')
        node = node[part]
    return node


def _is_type(value, kind):
    if isinstance(kind, list):
        return any(_is_type(value, k) for k in kind)
    if kind == 'object':
        return isinstance(value, dict)
    if kind == 'array':
        return isinstance(value, list)
    if kind == 'string':
        return isinstance(value, str)
    if kind == 'integer':
        return isinstance(value, int) and not isinstance(value, bool) or (
            isinstance(value, float) and value.is_integer())
    if kind == 'number':
        return isinstance(value, (int, float)) and not isinstance(value, bool)
    if kind == 'boolean':
        return isinstance(value, bool)
    if kind == 'null':
        return value is None
    raise UnknownKeyword('type %r is not a JSON Schema type' % kind)


def _same(a, b):
    if isinstance(a, bool) or isinstance(b, bool):
        return isinstance(a, bool) and isinstance(b, bool) and a == b
    if isinstance(a, (int, float)) and isinstance(b, (int, float)):
        return a == b
    if isinstance(a, dict) and isinstance(b, dict):
        return a.keys() == b.keys() and all(_same(a[k], b[k]) for k in a)
    if isinstance(a, list) and isinstance(b, list):
        return len(a) == len(b) and all(_same(x, y) for x, y in zip(a, b))
    return type(a) is type(b) and a == b


def _show(schema_value):
    return json.dumps(schema_value, ensure_ascii=False)[:120]


def _validate(value, schema, root, at):
    """Messages name where a value failed and what the schema wanted, never the value itself."""
    if schema is True or schema == {}:
        return []
    if schema is False:
        return ['at %s: nothing is allowed here' % at]
    problems = []
    if '$ref' in schema:
        problems += _validate(value, _resolve(root, schema['$ref']), root, at)
    if 'type' in schema and not _is_type(value, schema['type']):
        return problems + ['at %s: not of type %s' % (at, schema['type'])]
    if 'enum' in schema and not any(_same(value, option) for option in schema['enum']):
        problems.append('at %s: not one of %s' % (at, _show(schema['enum'])))
    if 'const' in schema and not _same(value, schema['const']):
        problems.append('at %s: not %s' % (at, _show(schema['const'])))
    if isinstance(value, str):
        if 'pattern' in schema and not re.search(schema['pattern'], value):
            problems.append('at %s: does not match %s' % (at, schema['pattern']))
        if 'minLength' in schema and len(value) < schema['minLength']:
            problems.append('at %s: shorter than %d characters' % (at, schema['minLength']))
        if 'maxLength' in schema and len(value) > schema['maxLength']:
            problems.append('at %s: longer than %d characters' % (at, schema['maxLength']))
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        if 'minimum' in schema and value < schema['minimum']:
            problems.append('at %s: less than %s' % (at, schema['minimum']))
    if isinstance(value, dict):
        for name in schema.get('required', []):
            if name not in value:
                problems.append('at %s: no %s (required)' % (at, name))
        properties = schema.get('properties', {})
        for name, sub in properties.items():
            if name in value:
                problems += _validate(value[name], sub, root, '%s.%s' % (at, name))
        if 'additionalProperties' in schema:
            extra = [name for name in value if name not in properties]
            if schema['additionalProperties'] is False:
                for name in extra:
                    problems.append('at %s: %s is not a field of this record' % (at, name))
            else:
                for name in extra:
                    problems += _validate(value[name], schema['additionalProperties'], root,
                                          '%s.%s' % (at, name))
    if isinstance(value, list):
        if 'items' in schema:
            for n, item in enumerate(value):
                problems += _validate(item, schema['items'], root, '%s[%d]' % (at, n))
        if schema.get('uniqueItems'):
            for n, item in enumerate(value):
                if any(_same(item, other) for other in value[:n]):
                    problems.append('at %s[%d]: repeats an earlier item' % (at, n))
        if 'contains' in schema and not any(not _validate(item, schema['contains'], root, at)
                                            for item in value):
            problems.append('at %s: no item matches %s' % (at, _show(schema['contains'])))
    if 'not' in schema and not _validate(value, schema['not'], root, at):
        problems.append('at %s: matches %s, which is not allowed' % (at, _show(schema['not'])))
    if 'if' in schema:
        if not _validate(value, schema['if'], root, at):
            if 'then' in schema:
                problems += _validate(value, schema['then'], root, at)
        elif 'else' in schema:
            problems += _validate(value, schema['else'], root, at)
    for sub in schema.get('allOf', []):
        problems += _validate(value, sub, root, at)
    if 'anyOf' in schema:
        found = [_validate(value, sub, root, at) for sub in schema['anyOf']]
        if all(found):
            problems.append('at %s: matches none of its %d allowed forms (%s)'
                            % (at, len(found), ' | '.join(f[0] for f in found)))
    if 'oneOf' in schema:
        found = [_validate(value, sub, root, at) for sub in schema['oneOf']]
        passing = sum(1 for f in found if not f)
        if passing != 1:
            problems.append('at %s: matches %d of its %d forms, where exactly one must match%s'
                            % (at, passing, len(found),
                               '' if passing else ' (%s)' % ' | '.join(min(found, key=len))))
    return problems


# ---------------------------------------------------------------------------
# The command
# ---------------------------------------------------------------------------

COMMANDS = {'dispatch': 'dispatch', 'return': 'return', 'witness': 'witness', 'label': 'label', 'error': 'error'}


def main(argv=None):
    """Read one JSON object on standard input and write it. Prints nothing; exits 0 on every path."""
    argv = list(sys.argv[1:] if argv is None else argv)
    folder = None
    if '--ledger' in argv:
        at = argv.index('--ledger')
        folder = argv[at + 1] if at + 1 < len(argv) else None
        del argv[at:at + 2]
    kind = argv[0] if argv else None
    if kind not in COMMANDS:
        print('subagent-ledger: usage: ledger.py dispatch|return|witness|label|error [--ledger <folder>]',
              file=sys.stderr)
        return 0
    try:
        payload = json.loads(sys.stdin.read())
        if not isinstance(payload, dict):
            raise ValueError('the payload is not a JSON object')
    except ValueError as exc:
        error(ledger=folder, stage='payload', record=kind if kind != 'error' else 'unknown',
              reason='the payload on standard input could not be read: %s' % exc, payload_keys=[])
        return 0
    try:
        if kind == 'dispatch':
            dispatch(ledger=folder, **payload)
        elif kind == 'return':
            ret(ledger=folder, **payload)
        elif kind == 'witness':
            witness(ledger=folder, **payload)
        elif kind == 'label':
            label(ledger=folder, **payload)
        else:
            error(ledger=folder, **payload)
    except Exception as exc:  # a payload key colliding with an argument name, or worse
        error(ledger=folder, stage='payload', record=kind if kind != 'error' else 'unknown',
              reason='%s: %s' % (type(exc).__name__, exc), payload_keys=sorted(payload))
    return 0


if __name__ == '__main__':
    sys.exit(main())
