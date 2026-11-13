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

Kept check results: a check the wrapper runs at a stop or a hand-back leaves its result in
<ledger>/.pending/<session>/check-<agent>-<n>.json, numbered in the order the checks ran (pending.schema.json,
`checkResult`). At each stop the capture takes that stop's result (take_stop_result): a refused stop writes no return.
Where the ledger folder's config.json switches a stop check on and a stop left no result, a placeholder is kept, so the
return reads `unrecorded (no check result when the return was written)` for it, never `pass`. The call's one return
carries every kept result, as it was found, in order (results_for_return); then they are removed. The stop's own
witness line carries the results the stop has not yet taken (unseen_stop_results), so the result is on the record at
the stop even where no return follows it.

Pending disposition files: the return check's disposition script writes <ledger>/.pending/<session>/disposition-<call
id>.json (pending.schema.json, `disposition`). At the PostToolUse of the parent's shell call the capture takes each
(take_dispositions), writes it as a disposition line and removes it.

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
COPIED = ('effort_unaided', 'decision_records', 'triage_persona', 'persona_facts', 'chosen_by', 'overrides',
          'below_line', 'triage_failure', 'harness_assigned', 'sender')
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


CHECK_PREFIX = 'check-'
NO_RESULT = 'unrecorded (no check result when the return was written)'
BAD_RESULT = 'unrecorded (a kept check result could not be read: %s)'
# Keys the capture adds to a kept result and removes before it goes on the return.
OWN_KEYS = ('seen', 'missing')


def _kept_paths(directory, agent, safe):
    directory = Path(directory)
    if not directory.is_dir():
        return []
    stem = safe('%s%s-' % (CHECK_PREFIX, agent))
    return sorted(path for path in directory.glob(stem + '*.json') if path.parent == directory
                  and path.name[len(stem):-len('.json')].isdigit())


def keep_result(directory, agent, data, safe):
    """Keep one check result for `agent`, numbered after the last. Returns its path."""
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    stem = safe('%s%s-' % (CHECK_PREFIX, agent))
    numbers = [int(path.name[len(stem):-len('.json')]) for path in _kept_paths(directory, agent, safe)]
    path = directory / ('%s%04d.json' % (stem, (max(numbers) if numbers else 0) + 1))
    path.write_text(json.dumps(data, ensure_ascii=False), encoding='utf-8')
    return path


def _read_result(path):
    if path.is_symlink():
        return None, 'it is a link, which the capture never follows'
    try:
        data = json.loads(path.read_text(encoding='utf-8'))
    except (OSError, ValueError) as exc:
        return None, '%s: %s' % (type(exc).__name__, exc)
    return data, None


def take_stop_result(directory, agent, safe, validate, check_on):
    """Mark the stop results not yet taken as taken, and return whether the newest of them refused the stop.

    With a stop check switched on (`check_on`) and no result left for this stop, a placeholder is kept for it.
    """
    unseen = []
    for path in _kept_paths(directory, agent, safe):
        data, problem = _read_result(path)
        if problem or validate(data, load_schema(), ref='#/$defs/checkResult'):
            continue
        if data.get('event') == 'SubagentStop' and not data.get('seen'):
            unseen.append((path, data))
    for path, data in unseen:
        data['seen'] = True
        path.write_text(json.dumps(data, ensure_ascii=False), encoding='utf-8')
    if not unseen:
        if check_on:
            keep_result(directory, agent, {'event': 'SubagentStop', 'missing': True, 'seen': True}, safe)
        return False
    return unseen[-1][1].get('refused') is True


def unseen_stop_results(directory, agent, safe, validate):
    """The stop results kept for `agent` that no stop has taken yet, in the order kept, as found. Marks nothing."""
    out = []
    for path in _kept_paths(directory, agent, safe):
        data, problem = _read_result(path)
        if problem or validate(data, load_schema(), ref='#/$defs/checkResult'):
            continue
        if data.get('event') == 'SubagentStop' and not data.get('seen') and not data.get('missing'):
            out.append(dict((key, value) for key, value in data.items() if key not in OWN_KEYS))
    return out


DISPOSITION_PREFIX = 'disposition-'


def take_dispositions(directory, validate):
    """[(path, the file's content or None, the problem or None)] for each pending disposition file in `directory`,
    in name order. Nothing is removed here: remove_paths() does that once each line is written."""
    directory = Path(directory)
    if not directory.is_dir():
        return []
    out = []
    for path in sorted(directory.glob(DISPOSITION_PREFIX + '*.json')):
        if path.parent != directory:
            continue
        data, problem = _read_result(path)
        if problem is None:
            found = validate(data, load_schema(), ref='#/$defs/disposition')
            problem = _short('; '.join(found)) if found else None
        out.append((path, None if problem else data, problem))
    return out


def results_for_return(directory, agent, safe, validate):
    """(every kept result for `agent`, in the order kept, as it was found; the paths to remove once the return is
    written). A result that cannot be read is `unrecorded (<why>)`; a placeholder is NO_RESULT."""
    entries, paths = [], []
    for path in _kept_paths(directory, agent, safe):
        paths.append(path)
        data, problem = _read_result(path)
        if problem is None:
            found = validate(data, load_schema(), ref='#/$defs/checkResult')
            problem = '; '.join(found) if found else None
        if problem:
            entries.append(BAD_RESULT % _short(problem))
        elif data.get('missing'):
            entries.append(NO_RESULT)
        else:
            entries.append(dict((key, value) for key, value in data.items() if key not in OWN_KEYS))
    return entries, paths


def remove_paths(directory, paths):
    """Remove each path that sits directly in `directory`."""
    for path in paths:
        if Path(path).parent == Path(directory):
            try:
                Path(path).unlink()
            except OSError:
                pass


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
