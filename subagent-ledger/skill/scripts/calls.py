#!/usr/bin/env python3
"""List a session's calls from its ledger, and name every call the ledger cannot show.

    python3 calls.py --session <id> [--ledger <folder>] [--since <RFC 3339>] [--until <RFC 3339>] --json
    python3 calls.py --session <id> ... --count-check --harness <name> --transcript <path> [--transcript <path> ...]

It prints one JSON object on standard output:

    {"session", "ledger", "read_at", "calls": [...], "absences": [...], "count_check": ...}

`calls` holds one row per call, in dispatch order, merging the call's dispatch and return records:
the frame from the return record where there is one, and each selectable field from the record that
carries it. Where both records carry a field and one fills it while the other reads `unrecorded
(<reason>)`, the row shows the filled value; where both fill it, the return's. A field the record names
in `fields_not_chosen` prints `not chosen`; a field on and unfilled prints as the record holds it,
`unrecorded (<reason>)`. A field neither record carries nor names, because the record was written
before the field existed, prints `unrecorded (not on this record: written before the field existed)`,
never null. Nothing is filled in. A return with no dispatch record still has its row, its
dispatch side reading `unrecorded (no dispatch record)`.

Each row also carries `labels`, joined from the session's label lines by `call_id`: `labelled_because`,
`failure_modes`, `likelihoods`, `cutoff`, `roster_revision`, `question_revision`, `labeller_model`,
`labeller_call_ids` and `labelled_at` from the newest label line for the call, and `earlier`, the number of
older ones. A call with no label line reads
`unrecorded (no label line for this call)`.

`absences` names each call, or each failed capture, the rows cannot show, with the witness lines
(`SubagentStart`, `SubagentStop`) the ledger holds for its subagent:

  * `no return record`: a dispatch with no return. With a `SubagentStop` witness the return capture
    failed; without one, the subagent had not stopped when the ledger was read. A dispatch is tied to
    its subagent by its return record, or by the join a background call's PostToolUse left in
    `<ledger>/.pending/<session>/`; a foreground call whose PostToolUse never came has no such tie,
    so its absence carries no witnesses.
  * `no dispatch record`: a return whose dispatch was never written.
  * `record rejected: <reason>` and `write failed: <reason>`: an error line in capture-errors.jsonl
    naming the session. One naming a call with a row is listed beside that row, in place of the two
    above.
  * `label for no call`: a label line whose `call_id` names no row.
  * `unattributed capture error`: an error line with no session, timed inside the session's span.
  * `record unattributed: <reason>`: a record in unattributed.jsonl, timed inside the session's span.
  * `<n> subagent dispatches in the transcript have no record`, or the reverse, from the count check.

The session's span runs from its first ledger line to its last, or across --since and --until where
given.

Without --count-check the reader opens the ledger folder's own files only, and no transcript. With it,
it counts in each transcript given the distinct tool-call ids of the harness's subagent tools
(subagent-tools.json), and compares each caller's count with the ledger's: its subagent dispatch
records, its returns with no dispatch, and the error lines naming a call that has no row. It prints
counts only, never an id or a tool input.

Exit codes: 0 listed; 1 refused on its input; 2 cannot run (the ledger folder, the schema or the
writer missing); 3 a declared absence, such as no ledger file for the session; 4 the count check found
a difference. No other.

The ledger folder is --ledger, then $SUBAGENT_LEDGER_DIR, then .subagent-ledger in the git top-level
folder of the working folder. The reader makes no model call and writes nothing.
"""

import argparse
import datetime
import json
import os
import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

try:
    import ledger
    MISSING_WRITER = None
except Exception as exc:  # the writer, whose names and folder rule the reader shares
    ledger = None
    MISSING_WRITER = '%s: %s' % (type(exc).__name__, exc)

SCHEMA_FILE = HERE / 'record.schema.json'
TOOLS_FILE = HERE / 'subagent-tools.json'
PENDING = '.pending'

NOT_CHOSEN = 'not chosen'
NOT_ON_RECORD = 'unrecorded (not on this record: written before the field existed)'
NO_DISPATCH_SIDE = 'unrecorded (no dispatch record)'
NO_RETURN = 'no return record'
NO_DISPATCH = 'no dispatch record'
UNATTRIBUTED_ERROR = 'unattributed capture error'
NO_CALL = 'unrecorded (a count names no call)'
NO_TRANSCRIPT = 'unrecorded (no transcript was given for this caller)'
NO_AGENT_ROUTES = ('unrecorded (no agent: cli call)', 'unrecorded (no agent: script call)')
NO_LABEL = 'unrecorded (no label line for this call)'
LABEL_FOR_NO_CALL = 'label for no call'
# What a row's `labels` shows of a label line, beside `earlier`.
LABEL_FIELDS = ('labelled_because', 'failure_modes', 'likelihoods', 'cutoff', 'roster_revision', 'question_revision',
                'labeller_model', 'labeller_call_ids', 'labelled_at')
REJECTED_STAGES = ('payload', 'setting', 'validate', 'scrub', 'copy')
SESSION_SHAPE = re.compile(r'^[A-Za-z0-9][A-Za-z0-9_.:-]*$')
FRAME = ('call_id', 'agent_id', 'session', 'dispatched_at', 'returned_at', 'outcome')
# The row's keys in §8's order; every other selectable field follows in the schema's order.
ROW_FIRST = ('call_id', 'route', 'harness', 'caller', 'agent_id', 'dispatched_at', 'returned_at',
             'model_requested', 'model', 'outcome', 'outcome_reason', 'brief_path', 'answer_path',
             'spend_line', 'auth_route')


class Refused(Exception):
    """The input cannot be read: exit 1."""


class CannotRun(Exception):
    """A file the reader needs is missing: exit 2."""


def now():
    """The time, RFC 3339 in UTC, to the millisecond."""
    stamp = datetime.datetime.now(datetime.timezone.utc)
    return stamp.strftime('%Y-%m-%dT%H:%M:%S.') + '%03dZ' % (stamp.microsecond // 1000)


def parse_time(text):
    if not isinstance(text, str) or not text or text.startswith('unrecorded ('):
        return None
    try:
        when = datetime.datetime.fromisoformat(text.replace('Z', '+00:00'))
    except ValueError:
        return None
    return when if when.tzinfo else when.replace(tzinfo=datetime.timezone.utc)


def is_unrecorded(value):
    return not isinstance(value, str) or value.startswith('unrecorded (') or value == NOT_CHOSEN


def inner(reason):
    """The text inside `unrecorded (<text>)`."""
    if isinstance(reason, str) and reason.startswith('unrecorded (') and reason.endswith(')'):
        return reason[len('unrecorded ('):-1]
    return str(reason)


# ---------------------------------------------------------------------------
# Reading the ledger folder
# ---------------------------------------------------------------------------

def jsonl(path):
    """The JSON lines of a file, and the line numbers that could not be read."""
    rows, bad = [], []
    with open(path, encoding='utf-8', errors='replace') as handle:
        for number, line in enumerate(handle, 1):
            if not line.strip():
                continue
            try:
                row = json.loads(line)
            except ValueError:
                bad.append(number)
                continue
            if isinstance(row, dict):
                rows.append(row)
            else:
                bad.append(number)
    return rows, bad


def error_lines(folder):
    path = Path(folder) / ledger.ERRORS_FILE
    return jsonl(path)[0] if path.is_file() else []


def unattributed_lines(folder):
    path = Path(folder) / ('%s.jsonl' % ledger.UNATTRIBUTED)
    return jsonl(path)[0] if path.is_file() else []


def pending_joins(folder, session):
    """call id -> agent id, from the joins a background call's PostToolUse left pending."""
    joins = {}
    where = Path(folder) / PENDING / session
    if not where.is_dir():
        return joins
    for path in sorted(where.glob('join-*.json')):
        try:
            data = json.loads(path.read_text(encoding='utf-8'))
        except (OSError, ValueError):
            continue
        if isinstance(data, dict) and isinstance(data.get('call_id'), str):
            joins[data['call_id']] = path.stem[len('join-'):]
    return joins


def pending_cli(folder, session, call_id):
    return (Path(folder) / PENDING / session / ('cli-%s.json' % call_id)).is_file()


# ---------------------------------------------------------------------------
# Rows
# ---------------------------------------------------------------------------

def field_value(record, name):
    """A field as the record holds it, `not chosen` where the record names it so, or, where the record neither
    carries nor names it, why: it was written before the field existed."""
    if record is None:
        return None
    if name in (record.get('fields_not_chosen') or []):
        return NOT_CHOSEN
    if name not in record:
        return NOT_ON_RECORD
    return record.get(name)


def is_filled(value):
    """A value a record holds: neither absent, `not chosen`, nor `unrecorded (<reason>)`."""
    if isinstance(value, str):
        return not is_unrecorded(value)
    return value is not None


def shared_value(sent, back, name):
    """A field both records may carry: the return's, unless only the dispatch fills it."""
    if back is None:
        return field_value(sent, name)
    value = field_value(back, name)
    if not is_filled(value) and value != NOT_CHOSEN and sent is not None and is_filled(field_value(sent, name)):
        return field_value(sent, name)
    if value == NOT_ON_RECORD and sent is not None:
        return field_value(sent, name)
    return value


def newest_label(lines):
    """The newest of one call's label lines: the latest `labelled_at`, the later line among equals."""
    stamped = [(parse_time(line.get('labelled_at')) or datetime.datetime.min.replace(tzinfo=datetime.timezone.utc),
                number, line) for number, line in enumerate(lines)]
    return max(stamped, key=lambda item: (item[0], item[1]))[2]


def labels_of(lines):
    """A row's `labels`, from the call's label lines in the ledger's order."""
    if not lines:
        return NO_LABEL
    newest = newest_label(lines)
    shown = dict((name, newest.get(name)) for name in LABEL_FIELDS)
    shown['earlier'] = len(lines) - 1
    return shown


def labels_for_no_call(labels, row_ids):
    """An absence for each label line whose call has no row, in the ledger's order."""
    return [{'call_id': call_id, 'reason': LABEL_FOR_NO_CALL, 'witnesses': []}
            for call_id, lines in labels.items() if call_id not in row_ids for _line in lines]


def row_of(sent, back):
    """One call's row from its dispatch record and its return record, either of which may be absent."""
    frame = back if back is not None else sent
    row = {}
    for name in FRAME:
        if name != 'session':
            row[name] = frame.get(name)
    for name in ledger.SELECTABLE:
        if name in ledger.DISPATCH_ONLY:
            if sent is not None:
                row[name] = field_value(sent, name)
            else:
                row[name] = NOT_CHOSEN if field_value(back, name) == NOT_CHOSEN else NO_DISPATCH_SIDE
        elif name in ledger.RETURN_ONLY:
            row[name] = field_value(back if back is not None else sent, name)
        else:
            row[name] = shared_value(sent, back, name)
    on = set()
    for record in (sent, back):
        if record is not None:
            on.update(record.get('fields_on') or [])
    row['fields_on'] = [name for name in ledger.SELECTABLE if name in on]
    ordered = dict((name, row[name]) for name in ROW_FIRST)
    for name in list(FRAME) + list(ledger.SELECTABLE) + ['fields_on']:
        if name in row and name not in ordered:
            ordered[name] = row[name]
    return ordered


def missing_returns(sent, back):
    """The call ids of dispatches with no return record, in dispatch order."""
    return [call_id for call_id in sent if call_id not in back]


def orphan_returns(sent, back):
    """The return records whose dispatch record is absent, in the ledger's order."""
    return [record for call_id, record in back.items() if call_id not in sent]


def witnesses_for(witness_lines, agent):
    """The witness lines the ledger holds for one subagent, in order."""
    if not isinstance(agent, str) or is_unrecorded(agent):
        return []
    return [{'event': line.get('event'), 'at': line.get('at')} for line in witness_lines
            if line.get('agent_id') == agent]


def order_key(row):
    return parse_time(row.get('dispatched_at')) or parse_time(row.get('returned_at')) or \
        datetime.datetime.max.replace(tzinfo=datetime.timezone.utc)


# ---------------------------------------------------------------------------
# The listing
# ---------------------------------------------------------------------------

def listing(session, folder, records, bad_lines, errors, unattributed, joins, since=None, until=None):
    """The output object, less the count check."""
    sent, back, witness_lines, labels = {}, {}, [], {}
    for record in records:
        kind = record.get('record')
        if kind == 'dispatch' and isinstance(record.get('call_id'), str):
            sent.setdefault(record['call_id'], record)
        elif kind == 'return' and isinstance(record.get('call_id'), str):
            back.setdefault(record['call_id'], record)
        elif kind == 'witness':
            witness_lines.append(record)
        elif kind == 'label' and isinstance(record.get('call_id'), str):
            labels.setdefault(record['call_id'], []).append(record)

    rows = [row_of(record, back.get(call_id)) for call_id, record in sent.items()]
    rows += [row_of(None, record) for record in orphan_returns(sent, back)]
    rows.sort(key=order_key)
    for row in rows:
        row['labels'] = labels_of(labels.get(row['call_id'], []))

    def agent_of(call_id):
        record = back.get(call_id)
        if record is not None and not is_unrecorded(record.get('agent_id')):
            return record['agent_id']
        return joins.get(call_id)

    own_errors = [line for line in errors if line.get('session') == session]
    named = {}
    for line in own_errors:
        named.setdefault(line.get('call_id'), []).append(line)

    absences = []

    def error_absence(line):
        stage = line.get('stage')
        prefix = 'write failed' if stage == 'write' else 'record rejected'
        call_id = line.get('call_id')
        agent = agent_of(call_id) if isinstance(call_id, str) else None
        if agent is None and not is_unrecorded(line.get('agent_id')) and line.get('record') == 'witness':
            agent = line.get('agent_id')
        return {'call_id': call_id, 'reason': '%s: %s' % (prefix, line.get('reason')),
                'witnesses': witnesses_for(witness_lines, agent)}

    row_ids = [row['call_id'] for row in rows]
    lacking_return = set(missing_returns(sent, back))
    lacking_dispatch = set(record['call_id'] for record in orphan_returns(sent, back))
    for call_id in row_ids:
        if call_id in named:
            absences.extend(error_absence(line) for line in named.pop(call_id))
        elif call_id in lacking_return:
            absences.append({'call_id': call_id, 'reason': NO_RETURN,
                             'witnesses': witnesses_for(witness_lines, agent_of(call_id))})
        elif call_id in lacking_dispatch:
            absences.append({'call_id': call_id, 'reason': NO_DISPATCH,
                             'witnesses': witnesses_for(witness_lines, agent_of(call_id))})
    for line in own_errors:
        if line.get('call_id') in named:
            absences.append(error_absence(line))
    absences.extend(labels_for_no_call(labels, set(row_ids)))

    for number in bad_lines:
        absences.append({'call_id': 'unrecorded (the line could not be read)',
                         'reason': 'record rejected: line %d of the session\'s ledger file is not a JSON '
                                   'object' % number, 'witnesses': []})

    start, end = span(records, since, until)
    for line in errors:
        if is_unrecorded(line.get('session')) and inside(line.get('at'), start, end):
            absences.append({'call_id': line.get('call_id'), 'reason': UNATTRIBUTED_ERROR, 'witnesses': []})
    for record in unattributed:
        if record.get('record') not in ('dispatch', 'return'):
            continue
        if inside(record.get('dispatched_at'), start, end) or inside(record.get('returned_at'), start, end):
            absences.append({'call_id': record.get('call_id'),
                             'reason': 'record unattributed: %s' % inner(record.get('session')),
                             'witnesses': []})

    return {'session': session, 'ledger': shown(folder), 'read_at': now(), 'calls': rows,
            'absences': absences}


def span(records, since, until):
    times = []
    for record in records:
        for name in ('dispatched_at', 'returned_at', 'at'):
            when = parse_time(record.get(name))
            if when is not None:
                times.append(when)
    start = since if since is not None else (min(times) if times else None)
    end = until if until is not None else (max(times) if times else None)
    return start, end


def inside(text, start, end):
    when = parse_time(text)
    return when is not None and start is not None and end is not None and start <= when <= end


def shown(folder):
    folder = Path(folder).resolve()
    for parent in [folder] + list(folder.parents):
        if (parent / '.git').exists():
            return str(folder.relative_to(parent))
    return str(folder)


# ---------------------------------------------------------------------------
# The count check (§8a, Gap 3)
# ---------------------------------------------------------------------------

def count_of(ids):
    """How many calls a list of tool-call ids holds: rows repeated while streaming count once."""
    return len(set(ids))


def caller_from_name(path, reader):
    name = Path(path).name
    if reader == 'claude-code':
        found = re.match(r'^agent-(.+)\.jsonl$', name)
        return found.group(1) if found else 'parent'
    return None


def tool_call_ids(path, tools, reader):
    """(caller, the subagent tool-call ids in the transcript, in order, repeats kept)."""
    rows, _ = jsonl(path)
    ids, caller = [], None
    for row in rows:
        if reader == 'claude-code':
            if caller is None and row.get('isSidechain') is True and isinstance(row.get('agentId'), str):
                caller = row['agentId']
            message = row.get('message') if isinstance(row.get('message'), dict) else {}
            content = message.get('content')
            if isinstance(content, list):
                for block in content:
                    if (isinstance(block, dict) and block.get('type') == 'tool_use'
                            and block.get('name') in tools and isinstance(block.get('id'), str)):
                        ids.append(block['id'])
        elif reader == 'codex':
            payload = row.get('payload') if isinstance(row.get('payload'), dict) else {}
            if row.get('type') == 'session_meta' and caller is None:
                caller = payload.get('id') if payload.get('parent_thread_id') else 'parent'
            if (row.get('type') == 'response_item' and payload.get('type') == 'function_call'
                    and payload.get('name') in tools and isinstance(payload.get('call_id'), str)):
                ids.append(payload['call_id'])
    return caller or 'parent', ids


def is_subagent(row):
    route = row.get('route')
    if isinstance(route, str) and not is_unrecorded(route):
        return route == 'subagent'
    return row.get('agent_id') not in NO_AGENT_ROUTES


def ledger_callers(rows, errors, session, folder):
    """Each subagent call the ledger holds, as its caller, or None where the record does not say."""
    found = []
    ids = set(row['call_id'] for row in rows)
    for row in rows:
        if is_subagent(row):
            caller = row.get('caller')
            found.append(caller if isinstance(caller, str) and not is_unrecorded(caller) else None)
    seen = set()
    for line in errors:
        call_id = line.get('call_id')
        if (line.get('session') != session or line.get('record') not in ('dispatch', 'return')
                or is_unrecorded(call_id) or call_id in ids or call_id in seen
                or pending_cli(folder, session, call_id)):
            continue
        seen.add(call_id)
        agent = line.get('agent_id')
        if line.get('record') == 'dispatch':
            found.append(agent if not is_unrecorded(agent) else 'parent')
        else:
            found.append(None)
    return found


def count_check(harness, paths, rows, errors, session, folder):
    """The count_check object, and the absences it adds."""
    try:
        table = json.loads(TOOLS_FILE.read_text(encoding='utf-8'))['harnesses']
    except (OSError, ValueError, KeyError) as exc:
        raise CannotRun('%s could not be read: %s' % (TOOLS_FILE.name, exc))
    if harness not in table:
        raise Refused('%s names no harness %r' % (TOOLS_FILE.name, harness))
    reader = table[harness].get('transcript')
    if not reader:
        return 'unrecorded (no declaration for %s)' % harness, []
    tools = set(table[harness].get('tools') or [])

    seen_ids, unreadable, order = {}, {}, []
    for path in paths:
        try:
            caller, ids = tool_call_ids(path, tools, reader)
        except OSError as exc:
            caller = caller_from_name(path, reader) or 'unrecorded (%s could not be read)' % Path(path).name
            unreadable[caller] = 'unrecorded (the transcript could not be read: %s)' % (exc.strerror or exc)
            ids = None
        if caller not in order:
            order.append(caller)
        if ids is not None:
            seen_ids.setdefault(caller, []).extend(ids)

    held = ledger_callers(rows, errors, session, folder)
    by_caller, absences, difference = [], [], 0
    if any(caller is None for caller in held):
        readable = [caller for caller in order if caller not in unreadable]
        total = (sum(count_of(seen_ids.get(c, [])) for c in readable) if not unreadable else
                 'unrecorded (a transcript could not be read: %s)' % '; '.join(sorted(set(unreadable.values()))))
        entries = [('unrecorded (not every record names its caller, so the totals are compared)', total, len(held))]
    else:
        callers = list(order) + sorted(set(held) - set(order))
        entries = []
        for caller in callers:
            if caller in unreadable:
                count = unreadable[caller]
            elif caller in order:
                count = count_of(seen_ids.get(caller, []))
            else:
                count = NO_TRANSCRIPT
            entries.append((caller, count, held.count(caller)))
    for caller, count, kept in entries:
        by_caller.append({'caller': caller, 'transcript_count': count, 'ledger_count': kept})
        if isinstance(count, int):
            difference += abs(count - kept)
            if count > kept:
                absences.append({'call_id': NO_CALL, 'witnesses': [],
                                 'reason': '%d subagent dispatches in the transcript have no record' % (count - kept)})
            elif kept > count:
                absences.append({'call_id': NO_CALL, 'witnesses': [],
                                 'reason': '%d subagent dispatch records have no dispatch in the transcript'
                                           % (kept - count)})
    return {'harness': harness, 'transcripts': [str(p) for p in paths], 'by_caller': by_caller,
            'difference': difference}, absences


# ---------------------------------------------------------------------------
# The command
# ---------------------------------------------------------------------------

def arguments(argv):
    parser = argparse.ArgumentParser(description='List a session\'s calls from its ledger.', add_help=True)
    parser.add_argument('--session', required=True)
    parser.add_argument('--ledger')
    parser.add_argument('--since')
    parser.add_argument('--until')
    parser.add_argument('--json', action='store_true')
    parser.add_argument('--count-check', action='store_true')
    parser.add_argument('--harness')
    parser.add_argument('--transcript', action='append', default=[])
    try:
        args = parser.parse_args(argv)
    except SystemExit as exc:
        raise Refused('the arguments could not be read') if exc.code else exc
    if not SESSION_SHAPE.match(args.session):
        raise Refused('%r is not a session id' % args.session)
    for name in ('since', 'until'):
        value = getattr(args, name)
        if value is not None and parse_time(value) is None:
            raise Refused('--%s is not an RFC 3339 time: %r' % (name, value))
    if args.since and args.until and parse_time(args.since) > parse_time(args.until):
        raise Refused('--until precedes --since')
    if args.count_check and (not args.harness or not args.transcript):
        raise Refused('--count-check needs --harness and at least one --transcript')
    if not args.count_check and (args.harness or args.transcript):
        raise Refused('--harness and --transcript belong to --count-check')
    return args


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    try:
        args = arguments(argv)
    except Refused as exc:
        print('calls: refused: %s' % exc, file=sys.stderr)
        return 1
    except SystemExit:
        return 0  # --help, printed by argparse
    try:
        if ledger is None:
            raise CannotRun('the writer, ledger.py, could not be imported: %s' % MISSING_WRITER)
        if not SCHEMA_FILE.is_file():
            raise CannotRun('the record schema is missing: %s' % SCHEMA_FILE)
        folder = Path(ledger.ledger_folder(args.ledger))
        if not folder.is_dir():
            raise CannotRun('the ledger folder is missing: %s' % folder)
    except CannotRun as exc:
        print('calls: cannot run: %s' % exc, file=sys.stderr)
        return 2

    session = args.session
    path = folder / ('%s.jsonl' % session)
    declared = None
    if path.is_file():
        records, bad = jsonl(path)
    else:
        records, bad = [], []
        declared = 'no ledger file for session %s under %s' % (session, folder)
    out = listing(session, folder, records, bad, error_lines(folder), unattributed_lines(folder),
                  pending_joins(folder, session), parse_time(args.since), parse_time(args.until))
    code = 3 if declared else 0
    if args.count_check:
        try:
            check, more = count_check(args.harness, args.transcript, out['calls'], error_lines(folder), session,
                                      folder)
        except Refused as exc:
            print('calls: refused: %s' % exc, file=sys.stderr)
            return 1
        except CannotRun as exc:
            print('calls: cannot run: %s' % exc, file=sys.stderr)
            return 2
        out['count_check'] = check
        out['absences'].extend(more)
        if code == 0 and isinstance(check, dict) and check['difference']:
            code = 4
    print(json.dumps(out, ensure_ascii=False))
    if declared:
        print('calls: %s' % declared, file=sys.stderr)
    return code


if __name__ == '__main__':
    sys.exit(main())
