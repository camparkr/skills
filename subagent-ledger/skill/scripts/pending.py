#!/usr/bin/env python3
"""The pending triage file: its reader and remover, and the join a resumption reads.

A planning skill writes one pending triage file per member and attempt, before the dispatching agent issues the
dispatch: <ledger>/.pending/<session>/triage-<member>-<attempt>.json, its form defined once, in pending.schema.json.
At that dispatch's PreToolUse the capture calls take_triage() with the member and attempt the brief names. It
returns each value with its stamp, for the dispatch record, and the kind where the file carries one, so the capture
runs no triage of its own. A file that does not validate gives each value as `unrecorded (<why>)` and a problem the
capture writes as an error line; the dispatch record is still written. Once the record is written the capture calls
remove(), and no pending file outlives its record.

Nothing here follows a path a pending file names, and nothing is removed outside the session's pending folder:
the file name is made from the member and attempt through ledger.pending_name(), which keeps no separator, and
the file's own folder must be that folder.

take_planner() finds the planning skill's own pending file, planner-<plan-request-id>.json, whose id the brief of a
dispatch carrying no member names. The capture records that dispatch as the planner's own and removes the file.

continued_call() joins a resumption to the dispatch it continues, by agent id: through the join file a background
call's PostToolUse writes, or, once that is gone, through the return record that names the agent. It returns the
call id, member and attempt of that dispatch.

This module is imported by the capture; it has no command line. Standard library only.
"""

import json
import re
from pathlib import Path

HERE = Path(__file__).resolve().parent
SCHEMA_FILE = HERE / 'pending.schema.json'
TRIAGE_PREFIX = 'triage-'
# The planning skill's own dispatch: its pending file is planner-<plan-request-id>.json, and its brief names that id.
PLANNER_PREFIX = 'planner-'
# The values copied onto the dispatch record, in the schema's order. `kind` is not copied: it becomes triage_kind.
COPIED = ('effort_unaided', 'decision_records', 'triage_persona', 'persona_facts', 'kind_paired_grouping',
          'chosen_by', 'overrides', 'below_line', 'triage_failure')
KIND = 'kind'
UNREADABLE = 'unrecorded (the pending triage file %s could not be read: %s)'
REASON_LIMIT = 200
_SCHEMA = {}


class Taken(object):
    """What a pending triage file gave a dispatch: `values` for the record, the `kind` or None, the file's `name`,
    the `problem` an error line names or None, and `path`, the file to remove once the record is written."""

    def __init__(self, name, path, values=None, kind=None, problem=None):
        self.name = name
        self.path = path
        self.values = values or {}
        self.kind = kind
        self.problem = problem


def load_schema():
    if 'schema' not in _SCHEMA:
        _SCHEMA['schema'] = json.loads(SCHEMA_FILE.read_text(encoding='utf-8'))
    return _SCHEMA['schema']


def triage_file_name(member, attempt, safe):
    """The pending triage file's name for this member and attempt, made safe by `safe` (ledger.pending_name)."""
    return '%s.json' % safe('%s%s-%s' % (TRIAGE_PREFIX, member, attempt))


def _short(text):
    text = ' '.join(str(text).split())
    return text if len(text) <= REASON_LIMIT else text[:REASON_LIMIT - 3] + '...'


def take_triage(directory, member, attempt, safe, validate):
    """Read the pending triage file for this member and attempt in `directory`, the session's pending folder.

    `safe` names files as the capture does; `validate(instance, schema, ref)` is the ledger's validator. Returns
    None where there is no such file, else a Taken. The file is not removed here: remove() does that once the
    record is written.
    """
    directory = Path(directory)
    name = triage_file_name(member, attempt, safe)
    path = directory / name
    if path.parent != directory or not path.exists() and not path.is_symlink():
        return None
    if path.is_symlink():
        problem = 'it is a link, which the capture never follows'
        return Taken(name, path, values=_unreadable(name, problem), problem='%s: %s' % (name, problem))
    try:
        data = json.loads(path.read_text(encoding='utf-8'))
        problems = validate(data, load_schema(), ref='#/$defs/triage')
    except (OSError, ValueError) as exc:
        problems = ['%s: %s' % (type(exc).__name__, exc)]
    if problems:
        problem = _short('; '.join(problems))
        return Taken(name, path, values=_unreadable(name, problem), problem='%s: %s' % (name, problem))
    values = dict((key, data[key]) for key in COPIED if key in data)
    kind = data[KIND]['value'] if KIND in data else None
    return Taken(name, path, values=values, kind=kind)


def take_planner(directory, text):
    """The planning skill's own pending file whose plan-request id `text` names, as a Taken with `request_id`, or
    None. The id must stand alone in the text: one that only begins or ends with it is another id.

    The file's content is not read: its name is the evidence. It is removed by remove() once the record is written.
    """
    directory = Path(directory)
    if not isinstance(text, str) or not text or not directory.is_dir():
        return None
    for path in sorted(directory.glob(PLANNER_PREFIX + '*.json')):
        if path.parent != directory:
            continue
        request_id = path.name[len(PLANNER_PREFIX):-len('.json')]
        if request_id and re.search(r'(?<![A-Za-z0-9._-])%s(?![A-Za-z0-9_-]|\.[A-Za-z0-9])' % re.escape(request_id),
                                    text):
            taken = Taken(path.name, path)
            taken.request_id = request_id
            return taken
    return None


def _unreadable(name, problem):
    reason = UNREADABLE % (name, problem)
    return dict((key, reason) for key in COPIED)


def remove(directory, taken):
    """Remove the file `taken` names, only where it sits directly in `directory`. A link is removed, not followed."""
    if taken is None:
        return
    path = Path(taken.path)
    if path.parent != Path(directory):
        return
    try:
        path.unlink()
    except OSError:
        pass


def continued_call(read_join, ledger_file, agent):
    """(call id, member, attempt) of the dispatch a message to `agent` continues, or (None, reason, reason).

    `read_join(agent)` returns the join file a background call's PostToolUse wrote, or None. Failing that, the
    session's ledger file is read for the last return naming the agent, then for that call's dispatch record.
    """
    joined = read_join(agent)
    call_id = joined.get('call_id') if isinstance(joined, dict) else None
    rows = _rows(ledger_file)
    if not isinstance(call_id, str) or not call_id:
        returns = [row for row in rows if row.get('record') == 'return' and row.get('agent_id') == agent
                   and isinstance(row.get('call_id'), str)]
        call_id = returns[-1]['call_id'] if returns else None
    if not call_id:
        reason = 'unrecorded (no dispatch in this ledger is joined to agent %s)' % agent
        return None, reason, reason
    dispatches = [row for row in rows if row.get('record') == 'dispatch' and row.get('call_id') == call_id]
    if not dispatches:
        reason = 'unrecorded (the dispatch it continues, %s, is not in this ledger)' % call_id
        return call_id, reason, reason
    sent = dispatches[-1]
    absent = 'unrecorded (the dispatch it continues, %s, carries no %%s)' % call_id
    return (call_id, sent.get('member', absent % 'member'), sent.get('attempt', absent % 'attempt'))


def _rows(path):
    try:
        text = Path(path).read_text(encoding='utf-8', errors='replace') if Path(path).is_file() else ''
    except OSError:
        return []
    out = []
    for line in text.splitlines():
        try:
            row = json.loads(line)
        except ValueError:
            continue
        if isinstance(row, dict):
            out.append(row)
    return out
