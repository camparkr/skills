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
never null. Nothing is filled in. A field no longer selectable is printed only where a record
carries it, as written. A return with no dispatch record still has its row, its dispatch side reading
`unrecorded (no dispatch record)`.

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
    above. Error lines naming the same call, stage and reason are one absence, whose `records` names
    each record that failed, such as ["dispatch", "return"].
  * `label for no call`: a label line whose `call_id` names no row.
  * `unattributed capture error`: an error line with no session, timed inside the session's span.
  * `record unattributed: <reason>`: a record in unattributed.jsonl, timed inside the session's span.
  * `<n> subagent dispatches in the transcript have no record`, or the reverse, and `<n> searches,
    fetches or MCP reads in the transcript have no record`, or the reverse, from the count check.

The session's span runs from its first ledger line to its last, or across --since and --until where
given.

Without --count-check the reader opens the ledger folder's own files only, and no transcript. With it,
it counts in each transcript given the distinct tool-call ids of the harness's subagent tools
(subagent-tools.json), and compares each caller's count with the ledger's: its subagent dispatch
records, its returns with no dispatch, and the error lines naming a call that has no row. It counts the
harness's searches, fetches and MCP reads (subagent-tools.json `outside_tools`, less the tools of a
server config.json's `mcp_not_calls` lists) the same way, as `outside_by_caller`, against the ledger's
search, fetch and mcp records; where the harness's transcript form for them is not known, that count reads
`unrecorded (<why>)`. `difference` sums the two. It prints
counts only, never an id or a tool input. A transcript it cannot read gives its caller's count as
`unrecorded (<why>)`, and the difference as `unrecorded (<n> transcripts could not be read)`, never a
number made over a count it did not make; where a readable caller still shows a difference, that
difference is printed and the exit is 4.

Exit codes: 0 listed; 1 refused on its input; 2 cannot run (the ledger folder, the schema or the
writer missing); 3 a declared absence, such as no ledger file for the session, or a transcript the
count check could not read; 4 the count check found a difference. No other.

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
NO_AGENT_ROUTES = ('unrecorded (no agent: cli call)', 'unrecorded (no agent: script call)',
                   'unrecorded (no agent: search call)', 'unrecorded (no agent: fetch call)',
                   'unrecorded (no agent: mcp call)')
# The routes of a call that leaves the session other than to a subagent: a search, a fetch or an MCP read. Their
# agent ids read `unrecorded (no agent: <route> call)`.
OUTSIDE_ROUTES = ('search', 'fetch', 'mcp')
OUTSIDE_AGENTS = dict(('unrecorded (no agent: %s call)' % route, route) for route in OUTSIDE_ROUTES)
NOT_CALLS_SETTING = 'mcp_not_calls'
NO_LABEL = 'unrecorded (no label line for this call)'
LABEL_FOR_NO_CALL = 'label for no call'
# What a row's `labels` shows of a label line, beside `earlier`.
LABEL_FIELDS = ('labelled_because', 'failure_modes', 'likelihoods', 'cutoff', 'roster_revision', 'question_revision',
                'labeller_model', 'labeller_call_ids', 'labelled_at')
REJECTED_STAGES = ('payload', 'setting', 'validate', 'scrub', 'copy')
SESSION_SHAPE = re.compile(r'^[A-Za-z0-9][A-Za-z0-9_.:-]*$')
FRAME = ('call_id', 'agent_id', 'session', 'dispatched_at', 'returned_at', 'outcome')
# The row's keys in the documented order; every other selectable field follows in the schema's order.
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


def pending_outside(folder, session, call_id):
    """Whether a search, fetch or MCP read's dispatch left its pending file for this call."""
    return (Path(folder) / PENDING / session / ('out-%s.json' % call_id)).is_file()


def not_calls(folder):
    """The MCP server names config.json's `mcp_not_calls` lists; a name ending in `*` covers each server whose name
    begins with what precedes it."""
    try:
        config = json.loads((Path(folder) / 'config.json').read_text(encoding='utf-8'))
    except (OSError, ValueError):
        return []
    names = config.get(NOT_CALLS_SETTING) if isinstance(config, dict) else None
    return [name for name in names if isinstance(name, str) and name] if isinstance(names, list) else []


def listed(server, names):
    return isinstance(server, str) and any(server.startswith(name[:-1]) if name.endswith('*') else server == name
                                           for name in names)


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
    retired = getattr(ledger, 'RETIRED', ())
    for name in retired:
        for record in (sent, back):
            if record is not None and name in record:
                row[name] = record[name]
                break
    on = set()
    for record in (sent, back):
        if record is not None:
            on.update(record.get('fields_on') or [])
    row['fields_on'] = [name for name in list(ledger.SELECTABLE) + list(retired) if name in on]
    ordered = dict((name, row[name]) for name in ROW_FIRST)
    for name in list(FRAME) + list(ledger.SELECTABLE) + list(retired) + ['fields_on']:
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

    def error_absences(lines):
        """One absence per call, stage and reason, naming every record that failed so. Lines naming no
        call are never merged: they may be different calls."""
        grouped, order = {}, []
        for number, line in enumerate(lines):
            call_id = line.get('call_id')
            named_call = isinstance(call_id, str) and not is_unrecorded(call_id)
            key = (call_id if named_call else number, line.get('stage'), line.get('reason'))
            if key not in grouped:
                grouped[key] = []
                order.append(key)
            grouped[key].append(line)
        out = []
        for key in order:
            group = grouped[key]
            line = group[0]
            prefix = 'write failed' if line.get('stage') == 'write' else 'record rejected'
            call_id = line.get('call_id')
            agent = agent_of(call_id) if isinstance(call_id, str) else None
            if agent is None:
                for each in group:
                    if not is_unrecorded(each.get('agent_id')) and each.get('record') == 'witness':
                        agent = each.get('agent_id')
                        break
            records = []
            for each in group:
                name = each.get('record') if isinstance(each.get('record'), str) else 'unknown'
                if name not in records:
                    records.append(name)
            out.append({'call_id': call_id, 'reason': '%s: %s' % (prefix, line.get('reason')),
                        'records': records, 'witnesses': witnesses_for(witness_lines, agent)})
        return out

    row_ids = [row['call_id'] for row in rows]
    lacking_return = set(missing_returns(sent, back))
    lacking_dispatch = set(record['call_id'] for record in orphan_returns(sent, back))
    for call_id in row_ids:
        if call_id in named:
            absences.extend(error_absences(named.pop(call_id)))
        elif call_id in lacking_return:
            absences.append({'call_id': call_id, 'reason': NO_RETURN,
                             'witnesses': witnesses_for(witness_lines, agent_of(call_id))})
        elif call_id in lacking_dispatch:
            absences.append({'call_id': call_id, 'reason': NO_DISPATCH,
                             'witnesses': witnesses_for(witness_lines, agent_of(call_id))})
    absences.extend(error_absences([line for line in own_errors if line.get('call_id') in named]))
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
# The count check
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
    """(caller, the tool-call ids in the transcript whose tool `tools` admits, in order, repeats kept). `tools` is a
    set of names, or a function of a name."""
    if not callable(tools):
        names = tools
        tools = lambda name: name in names  # noqa: E731
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
                            and tools(block.get('name')) and isinstance(block.get('id'), str)):
                        ids.append(block['id'])
        elif reader == 'codex':
            payload = row.get('payload') if isinstance(row.get('payload'), dict) else {}
            if row.get('type') == 'session_meta' and caller is None:
                caller = payload.get('id') if payload.get('parent_thread_id') else 'parent'
            if (row.get('type') == 'response_item' and payload.get('type') == 'function_call'
                    and tools(payload.get('name')) and isinstance(payload.get('call_id'), str)):
                ids.append(payload['call_id'])
    return caller or 'parent', ids


def is_subagent(row):
    route = row.get('route')
    if isinstance(route, str) and not is_unrecorded(route):
        return route == 'subagent'
    return row.get('agent_id') not in NO_AGENT_ROUTES


def is_outside(row):
    """Whether a row is a search, a fetch or an MCP read."""
    route = row.get('route')
    if isinstance(route, str) and not is_unrecorded(route):
        return route in OUTSIDE_ROUTES
    return row.get('agent_id') in OUTSIDE_AGENTS


def outside_callers(rows, errors, session, folder):
    """Each search, fetch or MCP read the ledger holds, as its caller, or None where the record does not say: its
    rows, and the error lines naming a call with no row whose dispatch left its pending file. An MCP read of a server
    `mcp_not_calls` lists is not counted, so a record written before the server was listed does not count."""
    names = not_calls(folder)
    found = []
    ids = set(row['call_id'] for row in rows)
    for row in rows:
        if not is_outside(row):
            continue
        payload = row.get('harness_payload')
        if row.get('route') == 'mcp' and isinstance(payload, dict) and listed(payload.get('server'), names):
            continue
        caller = row.get('caller')
        found.append(caller if isinstance(caller, str) and not is_unrecorded(caller) else None)
    seen = set()
    for line in errors:
        call_id = line.get('call_id')
        if (line.get('session') != session or is_unrecorded(call_id) or call_id in ids or call_id in seen
                or not pending_outside(folder, session, call_id)):
            continue
        seen.add(call_id)
        found.append(None)
    return found


def outside_tool(harness_entry, names):
    """A function telling whether a tool name is one of the harness's outside_tools, less a listed server's."""
    rules = harness_entry.get('outside_tools') if isinstance(harness_entry.get('outside_tools'), dict) else {}
    plain = set()
    for route in ('search', 'fetch'):
        plain.update(name for name in rules.get(route) or [] if isinstance(name, str))
    rule = rules.get('mcp') if isinstance(rules.get('mcp'), dict) else {}
    prefix, separator = rule.get('prefix'), rule.get('separator')

    def admits(name):
        if not isinstance(name, str):
            return False
        if name in plain:
            return True
        if isinstance(prefix, str) and prefix and name.startswith(prefix) and len(name) > len(prefix):
            rest = name[len(prefix):]
            server = rest.split(separator, 1)[0] if isinstance(separator, str) and separator in rest else None
            return not listed(server, names)
        return False
    return admits


def compared(order, seen_ids, unreadable, held, more, fewer):
    """(by caller, absences, difference) of one count: the transcripts' ids per caller against the ledger's callers.
    `more` and `fewer` word the absence where the transcript holds more calls than the ledger, or fewer."""
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
        if isinstance(count, int) and caller not in unreadable:
            difference += abs(count - kept)
            if count > kept:
                absences.append({'call_id': NO_CALL, 'witnesses': [], 'reason': more % (count - kept)})
            elif kept > count:
                absences.append({'call_id': NO_CALL, 'witnesses': [], 'reason': fewer % (kept - count)})
    return by_caller, absences, difference


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
                or pending_cli(folder, session, call_id) or pending_outside(folder, session, call_id)):
            continue
        seen.add(call_id)
        agent = line.get('agent_id')
        if line.get('record') == 'dispatch':
            found.append(agent if not is_unrecorded(agent) else 'parent')
        else:
            found.append(None)
    return found


def count_check(harness, paths, rows, errors, session, folder):
    """The count_check object, and the absences it adds. Subagent dispatches are counted as `by_caller`; searches,
    fetches and MCP reads (the harness's outside_tools, less a server mcp_not_calls lists) as `outside_by_caller`,
    where the harness's transcript form for them is known. `difference` is the two counts' differences summed."""
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
    # Only Claude Code's transcript form of a search, fetch or MCP read has been observed: a tool_use block under the
    # same name and id as its hook payload. Codex's rollout form of an MCP call is not.
    outside = outside_tool(table[harness], not_calls(folder)) if reader == 'claude-code' else None

    seen_ids, seen_outside, unreadable, order, unread_paths = {}, {}, {}, [], 0
    for path in paths:
        try:
            caller, ids = tool_call_ids(path, tools, reader)
            more = tool_call_ids(path, outside, reader)[1] if outside is not None else []
        except OSError as exc:
            caller = caller_from_name(path, reader) or 'unrecorded (%s could not be read)' % Path(path).name
            unreadable[caller] = 'unrecorded (the transcript could not be read: %s)' % (exc.strerror or exc)
            unread_paths += 1
            ids = more = None
        if caller not in order:
            order.append(caller)
        if ids is not None:
            seen_ids.setdefault(caller, []).extend(ids)
            seen_outside.setdefault(caller, []).extend(more)

    by_caller, absences, difference = compared(
        order, seen_ids, unreadable, ledger_callers(rows, errors, session, folder),
        '%d subagent dispatches in the transcript have no record',
        '%d subagent dispatch records have no dispatch in the transcript')
    if outside is not None:
        outside_by_caller, more_absences, more_difference = compared(
            order, seen_outside, unreadable, outside_callers(rows, errors, session, folder),
            '%d searches, fetches or MCP reads in the transcript have no record',
            '%d search, fetch or MCP read records have no call in the transcript')
        absences.extend(more_absences)
        difference += more_difference
    else:
        outside_by_caller = 'unrecorded (no observed rollout form for an MCP call on %s)' % harness
    if unread_paths and not difference:
        # A difference is never made over a count the reader did not make.
        difference = 'unrecorded (%d transcripts could not be read)' % unread_paths
    return {'harness': harness, 'transcripts': [str(p) for p in paths], 'by_caller': by_caller,
            'outside_by_caller': outside_by_caller, 'difference': difference}, absences


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
        if code == 0 and isinstance(check, dict) and isinstance(check['difference'], int) and check['difference']:
            code = 4
        elif code == 0 and isinstance(check, dict) and isinstance(check['difference'], str):
            code = 3
            declared = 'the count check could not read every transcript: %s' % check['difference']
    print(json.dumps(out, ensure_ascii=False))
    if declared:
        print('calls: %s' % declared, file=sys.stderr)
    return code


if __name__ == '__main__':
    sys.exit(main())
