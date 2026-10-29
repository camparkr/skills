"""TC-23: the gate holds the parent while a `fail` stands with no disposition record, and only a disposition lifts it.

Each test starts from one failing member: a writer whose hand-back has no output section, so check 1 fails. The
parent's tool calls are then run through the ledger's wrapper as the harness runs them. The control is the same world
with the gate switched off. The gate made to raise follows the rule for a check's own error: it refuses nothing, and
its result reads `not_checkable`. The disposition script's own refusals are in test_disposition.py.

They were committed before the gate existed, and each failed then.

Run from the skill's folder:  python3 -m unittest discover -s tests
"""

import shutil
import sys
import tempfile
import unittest
from pathlib import Path

import world
from world import GOOD_FRONT, report


class Held(unittest.TestCase):

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix='return-gate-'))
        self.addCleanup(shutil.rmtree, str(self.tmp), True)
        w = self.w = world.World(self.tmp)
        w.start()
        self.m = w.member('faulty', ['docs/'])
        w.dispatch(self.m)
        w.handback(self.m, 'Done, but no section.')
        w.stop(self.m)
        back = w.returns(self.m)[0]
        self.fail_ids = [c['id'] for run in w.runs(back) for c in run['checks'] if c['result'] == 'fail']
        self.assertTrue(self.fail_ids)

    def write(self):
        return self.w.parent('Write', {'file_path': str(self.w.repo / 'w.md'), 'content': 'w'})[1]

    def command(self, kind='accepted', ids=None, extra=''):
        return 'python3 "%s" --call %s %s --kind %s --reason "checked by hand" --decided-by parent%s' % (
            world.DISPOSITION, self.m.call_id, ' '.join('--result %s' % i for i in (ids or self.fail_ids)), kind,
            extra)

    def test_tc23_empty_with_the_gate_off_the_parents_write_runs(self):
        self.w.configure(checks=('stop', 'handback', 'context'))
        self.assertIsNone(self.w.denied(self.write()))

    def test_tc23_write_edit_bash_and_an_agent_call_are_each_refused_naming_the_call_check_and_repair(self):
        w = self.w
        other = w.member('other', ['docs/'])
        calls = [('Write', {'file_path': 'a', 'content': 'a'}), ('Edit', {'file_path': 'a'}),
                 ('Bash', {'command': 'ls'}),
                 ('Agent', {'prompt': other.prompt, 'run_in_background': True})]
        for tool, given in calls:
            with self.subTest(tool=tool):
                reason = w.denied(w.parent(tool, given)[1])
                self.assertTrue(reason, '%s ran while a fail stands' % tool)
                self.assertIn('this %s call' % tool, reason)
                self.assertIn(self.m.call_id, reason)
                self.assertIn('check 1: fail (no output section)', reason)
                self.assertIn('Recommended repair', reason)

    def test_tc23_likeness_read_grep_glob_taskstop_and_askuserquestion_are_let_through(self):
        w = self.w
        for tool, given in (('Read', {'file_path': 'a'}), ('Grep', {'pattern': 'x'}), ('Glob', {'pattern': '*'}),
                            ('TaskStop', {'task_id': 'nothing-running'}),
                            ('AskUserQuestion', {'questions': []})):
            with self.subTest(tool=tool):
                self.assertIsNone(w.denied(w.parent(tool, given)[1]))

    def test_tc23_the_disposition_call_runs_its_record_is_written_and_the_next_write_runs(self):
        decision, done = self.w.disposition_call(self.command())
        self.assertIsNone(self.w.denied(decision))
        self.assertEqual(done.returncode, 0, done.stderr)
        lines = [r for r in self.w.records() if r.get('record') == 'disposition']
        self.assertEqual(len(lines), 1)
        self.assertEqual((lines[0]['kind'], lines[0]['decided_by'], lines[0]['result_ids']),
                         ('accepted', 'parent', self.fail_ids))
        self.assertIsNone(self.w.denied(self.write()))

    def test_tc23_likeness_the_same_call_with_a_command_appended_is_refused(self):
        for extra in (' ; touch x', ' && touch x', ' | cat', ' > out.txt', ' $(touch x)', ' `touch x`',
                      '\ntouch x'):
            with self.subTest(extra=extra):
                decision, done = self.w.disposition_call(self.command(extra=extra))
                self.assertTrue(self.w.denied(decision))
                self.assertIsNone(done)
        self.assertFalse((self.w.repo / 'x').exists())

    def test_tc23_likeness_a_disposition_naming_another_calls_result_leaves_the_stop_standing(self):
        decision, done = self.w.disposition_call(self.command(ids=['00000000-1']))
        self.assertIsNone(self.w.denied(decision), 'the call is in the grammar; the script refuses it')
        self.assertEqual(done.returncode, 1)
        self.assertTrue(self.w.denied(self.write()))

    def test_tc23_a_disposition_line_naming_this_fail_on_another_call_does_not_lift_the_stop(self):
        w = self.w
        # A pending file written past the script, naming this call's result ids against another call.
        w.pending().mkdir(parents=True, exist_ok=True)
        (w.pending() / 'disposition-toolu_other.json').write_text(world.json.dumps({
            'call_id': 'toolu_other', 'result_ids': self.fail_ids, 'kind': 'accepted', 'reason': 'forged',
            'decided_by': 'parent', 'decided_at': '2026-10-29T00:00:00.000Z'}), encoding='utf-8')
        post = w.parent_payload('Bash', {'command': 'true'})
        post.update(hook_event_name='PostToolUse', tool_response={'stdout': '', 'stderr': ''})
        w.hook('PostToolUse', post)
        self.assertEqual([r['call_id'] for r in w.records() if r.get('record') == 'disposition'], ['toolu_other'])
        self.assertTrue(w.denied(self.write()), 'only a disposition on the failing call settles its fail')
        _code, out = w.count_check()
        self.assertEqual(out['count_check']['faults'].get('a disposition names a result its call does not carry'),
                         len(self.fail_ids), out)

    def test_tc23_an_agent_call_re_dispatching_the_member_before_any_disposition_is_refused(self):
        w = self.w
        again = w.member('faulty', ['docs/'], attempt=2)
        decision = w.dispatch(again)
        self.assertTrue(w.denied(decision))
        sent = [r for r in w.records() if r.get('call_id') == again.call_id]
        self.assertEqual(sorted(r['record'] for r in sent), ['dispatch', 'return'])
        back = [r for r in sent if r['record'] == 'return'][0]
        self.assertEqual((back['outcome'], back['outcome_reason']['class']), ('failed', 'refused_by_check'))

    def test_tc23_after_a_re_dispatched_disposition_the_next_attempt_runs_and_is_checked_afresh(self):
        w = self.w
        decision, done = w.disposition_call(self.command(kind='re-dispatched'))
        self.assertEqual(done.returncode, 0, done.stderr)
        again = w.member('faulty', ['docs/'], attempt=2)
        self.assertIsNone(w.denied(w.dispatch(again)))
        sent = [r for r in w.records() if r.get('record') == 'dispatch' and r.get('call_id') == again.call_id][0]
        self.assertEqual((sent['member'], sent['attempt']), ('faulty', 2))
        again.write('docs/fixed.md', GOOD_FRONT)
        w.handback(again, report('docs/fixed.md'))
        w.stop(again)
        found = w.results(w.returns(again)[0])
        self.assertEqual(found[1]['result'], 'pass')
        self.assertNotIn(found[1]['id'], self.fail_ids, 'checked afresh, with ids of its own')
        self.assertIsNone(w.denied(self.write()))

    def test_tc23_a_reply_with_no_tool_call_is_not_stopped_and_the_count_check_reports_the_undecided_fail(self):
        code, out = self.w.count_check()
        self.assertEqual(out['count_check']['faults'].get('a fail no disposition settles'), len(self.fail_ids), out)
        self.assertEqual(code, 4)

    def test_tc23_the_gate_made_to_raise_refuses_nothing_and_reads_not_checkable(self):
        broken = '"%s" -c "raise SystemExit(\'the gate broke\')"' % sys.executable
        self.w.configure(gate=broken)
        self.assertIsNone(self.w.denied(self.write()))
        gates = [r for r in self.w.records() if r.get('record') == 'witness' and r.get('check_results')
                 and r['check_results'][0].get('check') == 'gate']
        self.assertEqual(len(gates), 1)
        self.assertTrue(gates[0]['check_results'][0]['result'].startswith('not_checkable (check error'))

    def test_tc23_a_member_call_is_never_refused_while_the_parent_is_held(self):
        w = self.w
        payload = self.m.base('PreToolUse')
        payload.update(tool_name='Write', tool_input={'file_path': 'z'}, tool_use_id='tm1')
        self.assertIsNone(w.denied(w.hook('PreToolUse', payload)[1]))


class Passing(unittest.TestCase):

    def test_tc23_a_session_in_which_every_check_passes_refuses_nothing_and_asks_nothing(self):
        tmp = Path(tempfile.mkdtemp(prefix='return-gate-pass-'))
        self.addCleanup(shutil.rmtree, str(tmp), True)
        w = world.World(tmp)
        w.start()
        m = w.member('good', ['docs/'])
        w.dispatch(m)
        m.write('docs/good.md', GOOD_FRONT)
        w.handback(m, report('docs/good.md'))
        w.stop(m)
        for tool, given in (('Write', {'file_path': 'a'}), ('Bash', {'command': 'ls'}),
                            ('Agent', {'prompt': 'Another task.'})):
            with self.subTest(tool=tool):
                self.assertIsNone(w.denied(w.parent(tool, given)[1]))
        self.assertEqual([r for r in w.records() if r.get('record') == 'disposition'], [])


if __name__ == '__main__':
    unittest.main()
