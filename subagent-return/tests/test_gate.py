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
        self.fail_ids = w.fail_ids(back)
        self.assertTrue(self.fail_ids)

    def write(self):
        return self.w.parent('Write', {'file_path': str(self.w.repo / 'w.md'), 'content': 'w'})[1]

    def command(self, kind='accepted', ids=None, extra=''):
        return 'python3 "%s" --call %s %s --kind %s --reason "checked by hand" --decided-by parent %s%s' % (
            world.DISPOSITION, self.m.call_id, ' '.join('--result %s' % i for i in (ids or self.fail_ids)), kind,
            self.w.ledger_option(), extra)

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


class PrintedCommand(unittest.TestCase):
    """Dry run 11, H11.6: the disposition command the gate's refusal and the parent's context print is run exactly as
    printed, its placeholders filled, from a working folder outside any git repository, with no SUBAGENT_LEDGER_DIR in
    the parent's environment. It names the ledger with --ledger, so its record lands in the ledger the hooks name and
    the stop lifts. The likeness is the same command with its --ledger taken out: the script cannot find the ledger,
    and the stop stands, as H11.6 found."""

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix='return-printed-'))
        self.addCleanup(shutil.rmtree, str(self.tmp), True)
        w = self.w = world.World(self.tmp)
        w.start()
        self.m = w.member('faulty', ['docs/'])
        w.dispatch(self.m)
        w.handback(self.m, 'Done, but no section.')
        w.stop(self.m)
        self.fail_ids = w.fail_ids(w.returns(self.m)[0])
        self.assertTrue(self.fail_ids)

    def write(self):
        return self.w.parent('Write', {'file_path': str(self.w.repo / 'w.md'), 'content': 'w'})[1]

    def outside(self):
        """The parent's working folder: outside any git repository, in an environment with no SUBAGENT_LEDGER_DIR."""
        folder = self.w.outside
        found = world.subprocess.run(['git', '-C', str(folder), 'rev-parse', '--show-toplevel'], capture_output=True,
                                     text=True, env=self.w.parent_env(), timeout=60)
        self.assertNotEqual(found.returncode, 0, 'the folder sits inside a repository: %s' % found.stdout)
        self.assertNotIn('SUBAGENT_LEDGER_DIR', self.w.parent_env())
        return folder

    def refusal_command(self):
        printed = self.w.printed_commands(self.w.denied(self.write()))
        self.assertEqual(len(printed), 1, printed)
        return printed[0]

    def context_command(self):
        payload = {'session_id': world.SESSION, 'transcript_path': str(self.w.parent_transcript),
                   'cwd': str(self.w.repo), 'hook_event_name': 'UserPromptSubmit',
                   'prompt': '<task-notification>Agent %s completed.</task-notification>' % self.m.agent}
        _code, decision, _err = self.w.hook('UserPromptSubmit', payload)
        context = ((decision or {}).get('hookSpecificOutput') or {}).get('additionalContext')
        printed = self.w.printed_commands(context)
        self.assertEqual(len(printed), 1, context)
        return printed[0]

    def lifts(self, printed):
        w = self.w
        self.assertTrue(printed.endswith(' --ledger "%s"' % w.ledger), printed)
        folder = self.outside()
        decision, done = w.disposition_call(world.fill(printed), cwd=folder)
        self.assertIsNone(w.denied(decision), 'the printed command is in the grammar the gate lets through')
        self.assertEqual(done.returncode, 0, done.stderr)
        lines = [r for r in w.records() if r.get('record') == 'disposition']
        self.assertEqual([(r['call_id'], r['result_ids']) for r in lines], [(self.m.call_id, self.fail_ids)])
        self.assertEqual(list(w.pending().glob('disposition-*.json')), [], 'no pending file outlives its record')
        self.assertFalse((folder / '.subagent-ledger').exists(), 'nothing is written beside the parent')
        self.assertIsNone(w.denied(self.write()), 'the stop is lifted')

    def test_h11_6_the_refusals_command_run_as_printed_from_outside_any_repository_lifts_the_stop(self):
        self.lifts(self.refusal_command())

    def test_h11_6_the_contexts_command_run_as_printed_from_outside_any_repository_lifts_the_stop(self):
        self.lifts(self.context_command())

    def test_h11_6_likeness_the_same_command_without_its_ledger_leaves_the_stop_standing(self):
        w = self.w
        filled = world.fill(self.refusal_command())
        bare = filled.replace(' --ledger "%s"' % w.ledger, '')
        self.assertNotEqual(bare, filled)
        folder = self.outside()
        decision, done = w.disposition_call(bare, cwd=folder)
        self.assertIsNone(w.denied(decision))
        self.assertEqual(done.returncode, 1, done.stderr)
        self.assertIn('the ledger holds no check result', done.stderr)
        self.assertEqual([r for r in w.records() if r.get('record') == 'disposition'], [])
        self.assertTrue(w.denied(self.write()), 'the stop stands')


class GrammarFault(unittest.TestCase):
    """Dry run 12, r12-bg-gate2: the parent ran the disposition script with its own reason, which held a `;`. The
    grammar rejected it, and the gate refused it with the ordinary refusal, which never said the command broke the
    grammar; the parent took every Bash call to be held and stopped. A Bash call naming the disposition script that
    the grammar rejects is now refused with the grammar's fault first. A Bash call naming no disposition script gets
    the ordinary refusal, unchanged."""

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix='return-r12-'))
        self.addCleanup(shutil.rmtree, str(self.tmp), True)
        w = self.w = world.World(self.tmp)
        w.start()
        self.m = w.member('faulty', ['docs/'])
        w.dispatch(self.m)
        w.handback(self.m, 'Done, but no section.')
        w.stop(self.m)
        self.fail_ids = w.fail_ids(w.returns(self.m)[0])
        self.assertTrue(self.fail_ids)

    def printed(self):
        reason = self.w.denied(self.w.parent('Write', {'file_path': str(self.w.repo / 'w.md'), 'content': 'w'})[1])
        found = self.w.printed_commands(reason)
        self.assertEqual(len(found), 1, reason)
        return found[0]

    def test_r12_a_disposition_command_with_a_semicolon_in_its_reason_is_refused_naming_the_semicolon(self):
        command = world.fill(self.printed(), kind='sent-back', reason='not acceptable as-is; needs repair')
        decision, done = self.w.disposition_call(command, cwd=self.w.outside)
        reason = self.w.denied(decision)
        self.assertTrue(reason)
        self.assertIsNone(done)
        first = reason.split('\n')[0]
        self.assertIn('disposition script', first)
        self.assertIn("';'", first)
        self.assertIn('this Bash call', reason)
        self.assertEqual(len(self.w.printed_commands(reason)), 1, 'the ordinary refusal and its command follow')
        self.assertEqual([r for r in self.w.records() if r.get('record') == 'disposition'], [])

    def test_r12_likeness_the_same_command_corrected_is_let_through_and_lifts_the_stop(self):
        command = world.fill(self.printed(), kind='sent-back', reason='not acceptable as-is, needs repair')
        decision, done = self.w.disposition_call(command, cwd=self.w.outside)
        self.assertIsNone(self.w.denied(decision))
        self.assertEqual(done.returncode, 0, done.stderr)
        lines = [r for r in self.w.records() if r.get('record') == 'disposition']
        self.assertEqual([(r['call_id'], r['result_ids']) for r in lines], [(self.m.call_id, self.fail_ids)])
        self.assertIsNone(self.w.denied(self.w.parent('Bash', {'command': 'ls'})[1]), 'the stop is lifted')

    def test_r12_likeness_an_unrelated_bash_call_gets_the_ordinary_refusal_with_no_grammar_line(self):
        decision = self.w.parent('Bash', {'command': 'echo one; echo two'})[1]
        reason = self.w.denied(decision)
        self.assertTrue(reason)
        self.assertTrue(reason.startswith('The return check holds this Bash call'), reason)
        self.assertNotIn('disposition script', reason)
        self.assertNotIn('grammar', reason)


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
