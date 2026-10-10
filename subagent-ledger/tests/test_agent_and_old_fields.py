"""Controls C-F-1 and C-F-2, public half: call.py's records carry an agent, and the reader names an old record's gaps.

C-F-1. A call made through call.py runs a whole agent session, so its records carry that run's session id as
`agent_id`: the dispatch reads `unrecorded (not yet returned)`, and the return carries the id the run's own record
names, or `unrecorded (the run's own record names no session: <why>)`. Neither ever reads
`unrecorded (no agent: script call)`, which stays the wording of a script's own single model request. Stand-in
harnesses, as in test_call.py: the Gemini CLI stand-in writes a chat whose first row names a session; the Cursor
stand-in writes a chat store whose meta.json names none; a failed run writes no record at all.

C-F-2. A record written before a field existed neither carries it nor names it in `fields_not_chosen`. The reader
prints such a field as `unrecorded (not on this record: written before the field existed)`, never null. The old
record here is the l1 session's call, written by the capture from its recorded hook payloads, with `act_kind` and
`user_answer` taken out of both records and their field lists, as a record written before those fields reads.

Each control fails before the code, for the reason its assertion names, and has a half that switches the change
off by a patch here and shows the fault.

Run from the skill's folder:  python3 -m unittest discover -s tests
"""

import contextlib
import io
import json
import os
import re
import unittest
from unittest import mock

import test_call
import test_calls

NO_AGENT = 'unrecorded (no agent: script call)'
NOT_YET = 'unrecorded (not yet returned)'
NO_SESSION = re.compile(r"^unrecorded \(the run's own record names no session: .+\)$")
GEMINI_SESSION = '08ed128a-0052-4138-8e16-7ccd7152056d'
OLD_FIELD = 'unrecorded (not on this record: written before the field existed)'
NEW_FIELDS = ('act_kind', 'user_answer')


# ---------------------------------------------------------------------------
# C-F-1: call.py has an agent
# ---------------------------------------------------------------------------

class CF1CallHasAnAgent(test_call.World):

    def test_c_f_1_a_run_record_naming_a_session_gives_its_id_on_the_return(self):
        done = self.run_call('gemini-cli')
        self.assertEqual(done.returncode, 0, done.stderr)
        dispatch, back = self.records()
        self.assertEqual(dispatch['agent_id'], NOT_YET)
        self.assertEqual(back['agent_id'], GEMINI_SESSION, 'the session the chat\'s first row names')
        self.assertEqual(self.errors(), [])

    def test_c_f_1_a_run_record_naming_no_session_says_why(self):
        done = self.run_call('cursor')
        self.assertEqual(done.returncode, 0, done.stderr)
        dispatch, back = self.records()
        self.assertEqual(dispatch['agent_id'], NOT_YET)
        self.assertRegex(back['agent_id'], NO_SESSION)
        self.assertIn('meta.json', back['agent_id'])

    def test_c_f_1_a_failed_run_says_why_and_never_no_agent(self):
        done = self.run_call('gemini-cli', env={'STANDIN_FAIL': 'Not logged in'})
        self.assertNotEqual(done.returncode, 0)
        dispatch, back = self.records()
        self.assertEqual(back['outcome'], 'failed')
        self.assertEqual(dispatch['agent_id'], NOT_YET)
        self.assertRegex(back['agent_id'], NO_SESSION)

    def test_c_f_1_a_run_that_never_reached_the_harness_says_why(self):
        done = self.run_call('gemini-cli', env={'PATH': str(self.tmp / 'empty-path')})
        self.assertNotEqual(done.returncode, 0)
        dispatch, back = self.records()
        self.assertEqual(dispatch['agent_id'], NOT_YET)
        self.assertRegex(back['agent_id'], NO_SESSION)

    def test_c_f_1_route_and_user_answer_are_unchanged(self):
        self.run_call('gemini-cli')
        dispatch, back = self.records()
        self.assertEqual((dispatch['route'], back['route']), ('script', 'script'))
        self.assertEqual(dispatch['user_answer'], 'none (not a user decision)')

    def test_c_f_1_control_switched_off_the_return_reads_no_agent(self):
        call = test_call.load(test_call.CALL_PY, 'call_agent_off_%d' % id(self))
        if not hasattr(call, 'NOT_YET'):
            raise AssertionError('call.py has no NOT_YET yet: its records still read no agent')
        merged = dict(os.environ, **self.env)
        here = os.getcwd()
        os.chdir(str(self.caller))
        try:
            with mock.patch.dict(os.environ, merged, clear=True), \
                    mock.patch.object(call, 'NOT_YET', NO_AGENT), \
                    mock.patch.object(call, 'session_of_run', lambda fields: NO_AGENT), \
                    contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
                call.main(['--harness', 'gemini-cli', '--brief', str(self.brief)])
        finally:
            os.chdir(here)
        dispatch, back = self.records()
        self.assertEqual(back['agent_id'], NO_AGENT, 'with the reading switched off the check sees no agent')
        self.assertNotEqual(back['agent_id'], GEMINI_SESSION)


# ---------------------------------------------------------------------------
# C-F-2: the reader names an old record's missing field
# ---------------------------------------------------------------------------

def as_written_before(record, names=NEW_FIELDS):
    """The record as it read before `names` existed: neither carried nor listed."""
    old = dict((key, value) for key, value in record.items() if key not in names)
    for listing in ('fields_on', 'fields_not_chosen'):
        if isinstance(old.get(listing), list):
            old[listing] = [name for name in old[listing] if name not in names]
    return old


class CF2OldRecord(test_calls.World):
    fields = 'all'

    def old_ledger(self, keep_not_chosen=()):
        """A copy of the ledger whose call records predate act_kind and user_answer. A name in `keep_not_chosen`
        stays listed in the records' `fields_not_chosen`, as a record that turned it off would list it."""
        self.feed(self.l1()[:4], pause=0.01)
        copy = self.copy_ledger(lambda line: False)
        rows = []
        for line in test_calls.lines_of(self.ledger_file(copy)):
            if line.get('record') in ('dispatch', 'return'):
                line = as_written_before(line)
                for name in keep_not_chosen:
                    line['fields_not_chosen'] = list(line.get('fields_not_chosen') or []) + [name]
            rows.append(line)
        self.ledger_file(copy).write_text(''.join(json.dumps(row) + '\n' for row in rows), encoding='utf-8')
        return copy

    def test_c_f_2_a_field_written_before_it_existed_says_so(self):
        copy = self.old_ledger()
        code, data, _ = self.run_reader(ledger=copy)
        self.assertEqual(code, 0)
        row = data['calls'][0]
        for name in NEW_FIELDS:
            self.assertEqual(row[name], OLD_FIELD, name)
        for row in data['calls']:
            nulls = [name for name, value in row.items() if value is None]
            self.assertEqual(nulls, [], 'no field prints as null')
        # A value held verbatim inside harness_payload is the harness's own and may be null; it is not a field.

    def test_c_f_2_a_field_named_not_chosen_still_prints_not_chosen(self):
        copy = self.old_ledger(keep_not_chosen=('act_kind',))
        _, data, _ = self.run_reader(ledger=copy)
        row = data['calls'][0]
        self.assertEqual(row['act_kind'], 'not chosen')
        self.assertEqual(row['user_answer'], OLD_FIELD)

    def test_c_f_2_a_field_carried_unrecorded_still_prints_as_carried(self):
        copy = self.old_ledger()
        _, data, _ = self.run_reader(ledger=copy)
        self.assertEqual(data['calls'][0]['effort_assigned'], 'unrecorded (no triage: slice B7 not built)')

    def test_c_f_2_control_switched_off_the_field_prints_null(self):
        copy = self.old_ledger()
        calls = self.reader()

        def as_before(record, name):
            if record is None:
                return None
            if name in (record.get('fields_not_chosen') or []):
                return calls.NOT_CHOSEN
            return record.get(name)

        with mock.patch.object(calls, 'field_value', as_before):
            _, data, text = self.run_reader(module=calls, ledger=copy)
        self.assertIsNone(data['calls'][0]['act_kind'], 'with the rule switched off the field prints null')
        self.assertIn('"act_kind": null', text)


if __name__ == '__main__':
    unittest.main()
