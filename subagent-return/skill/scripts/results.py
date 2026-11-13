#!/usr/bin/env python3
"""The check results and dispositions a session's ledger holds, read for the gate, the disposition script, the
context the parent is given and the merge plan.

Results sit on the ledger in two places, written by the capture: the witness line at each hand-back and each stop, and
the call's one return, as `check_results`. Each kept run there carries `key` (agent id, call id, member, attempt),
`report`, `sha256` and `checks`, one result per check, each with its `id`, unique in its call. A run the check could
not finish carries no `checks`, and its `result` reads `not_checkable (...)`. A result may sit on a witness line and
again on the return; it is one result, known by its call and its id. A stop's run that finds the hand-back's fault
again carries the hand-back's id for it (return_check.stable_ids()), so that fault too is one result.

A disposition record (`record: disposition`) settles the results it names, by id, on the call it names. A `fail` stands
until a disposition on its own call names its id. Nothing here reads a pending file. Standard library only.
"""

import json
from pathlib import Path

FAIL = 'fail'
DISPOSITION = 'disposition'


def rows(folder, session):
    """(the session's ledger rows, problem)."""
    path = Path(folder) / ('%s.jsonl' % session)
    try:
        text = path.read_text(encoding='utf-8', errors='replace') if path.exists() else ''
    except OSError as exc:
        return None, 'the ledger file could not be read: %s' % exc
    out = []
    for line in text.splitlines():
        try:
            row = json.loads(line)
        except ValueError:
            continue
        if isinstance(row, dict):
            out.append(row)
    return out, None


def is_real(value):
    return isinstance(value, str) and value and not value.startswith('unrecorded (')


class Run(object):
    """One check run as the ledger holds it: where it sits, its key and its results."""

    def __init__(self, data, record):
        self.data = data
        self.record = record
        key = data.get('key') if isinstance(data.get('key'), dict) else {}
        self.agent_id = key.get('agent_id') if is_real(key.get('agent_id')) else record.get('agent_id')
        call = key.get('call_id')
        if not is_real(call) and record.get('record') == 'return':
            call = record.get('call_id')
        self.call_id = call if is_real(call) else 'agent:%s' % self.agent_id
        self.member = key.get('member')
        self.attempt = key.get('attempt')
        checks = data.get('checks')
        self.checks = [c for c in checks if isinstance(c, dict)] if isinstance(checks, list) else []


def runs(records):
    """Every check run on the session's witness lines and returns, in ledger order."""
    out = []
    for record in records:
        if record.get('record') not in ('witness', 'return'):
            continue
        found = record.get('check_results')
        for data in found if isinstance(found, list) else []:
            if isinstance(data, dict):
                out.append(Run(data, record))
    return out


def dispositions(records):
    return [record for record in records if record.get('record') == DISPOSITION]


def settled(records):
    """{(call id, result id)} every disposition settles."""
    out = set()
    for record in dispositions(records):
        call = record.get('call_id')
        for result_id in record.get('result_ids') or []:
            out.add((call, result_id))
    return out


class Fail(object):
    """One `fail` result: its call, its run's key and the result itself."""

    def __init__(self, run, found):
        self.call_id = run.call_id
        self.agent_id = run.agent_id
        self.member = run.member
        self.attempt = run.attempt
        self.result = found
        self.id = found.get('id')


def fails(records):
    """Every `fail` in the session, each (call, id) once, in the order first seen."""
    out, seen = [], set()
    for run in runs(records):
        for found in run.checks:
            if found.get('result') != FAIL:
                continue
            key = (run.call_id, found.get('id'))
            if key in seen:
                continue
            seen.add(key)
            out.append(Fail(run, found))
    return out


def standing(records):
    """The fails no disposition settles."""
    done = settled(records)
    return [item for item in fails(records) if (item.call_id, item.id) not in done]


def results_of(records, call_id):
    """{result id: result} for every result the session holds on `call_id`."""
    out = {}
    for run in runs(records):
        if run.call_id == call_id:
            for found in run.checks:
                if isinstance(found.get('id'), str):
                    out.setdefault(found['id'], found)
    return out


def call_ids(records):
    return sorted(set(run.call_id for run in runs(records)))


def key_of(records, call_id):
    """(agent id, member, attempt) the runs of `call_id` carry."""
    for run in runs(records):
        if run.call_id == call_id:
            return run.agent_id, run.member, run.attempt
    return None, None, None


def dispatch_of(records, call_id):
    for record in records:
        if record.get('record') == 'dispatch' and record.get('call_id') == call_id:
            return record
    return None


def is_writer(records, call_id):
    """Whether the call's dispatch record carries a baseline commit: the capture records one for a writer only."""
    found = (dispatch_of(records, call_id) or {}).get('baseline')
    return isinstance(found, dict) and isinstance(found.get('commit'), str)


def shown(found):
    reason = found.get('reason')
    return '%s (%s)' % (found.get('result'), reason) if reason else str(found.get('result'))
