"""SI-5's team of four, run end to end through the ledger's wrapper, and the routes a result takes to the record.

The team: one member claims a file it never wrote, one writes bad front matter, one writes outside its write set, and
one is clean. Each hands back by the hand-back tool, in the background, and then stops. The three faulty members give
`fail` with a recommended repair, the clean one passes, nothing is refused at a member, and the gate holds the parent
until a disposition settles each `fail` (R-18, R-36; TC-8, TC-10, TC-23).

TC-10's routes follow: a member without the hand-back tool, a hand-back member that stops before it hands back (on
both launch routes), a hand-back another hook refuses, and a failing member then stopped by TaskStop. TC-10's
deferred-write control, the witness line's time against the moment the report is queued at the parent, needs a live
harness and is left to the live run.

They were committed before the checks, the gate and the disposition script existed, and each failed then.

Run from the skill's folder:  python3 -m unittest discover -s tests
"""

import shutil
import tempfile
import unittest
from pathlib import Path

import world
from world import BAD_FRONT, GOOD_FRONT, report


class Team(unittest.TestCase):
    """The team of four, built once; each test reads what it left."""

    @classmethod
    def setUpClass(cls):
        cls.tmp = Path(tempfile.mkdtemp(prefix='return-team-'))
        w = cls.w = world.World(cls.tmp)
        w.start()
        cls.claimer = w.member('claimer', ['docs/'])
        cls.scribe = w.member('scribe', ['docs/'])
        cls.stray = w.member('stray', ['docs/'])
        cls.clean = w.member('clean', ['docs/'])
        cls.decisions = {}
        for m in (cls.claimer, cls.scribe, cls.stray, cls.clean):
            cls.decisions[m.name] = [w.dispatch(m)]
        cls.scribe.write('docs/scribe.md', BAD_FRONT)
        cls.stray.write('src/stray.py', 'print(4)\n')
        cls.stray.write('docs/stray.md', GOOD_FRONT)
        cls.clean.write('docs/clean.md', GOOD_FRONT)
        messages = {'claimer': report('docs/existing.md'), 'scribe': report('docs/scribe.md'),
                    'stray': report('docs/stray.md'), 'clean': report('docs/clean.md')}
        for m in (cls.claimer, cls.scribe, cls.stray, cls.clean):
            cls.decisions[m.name].append(w.handback(m, messages[m.name]))
            cls.decisions[m.name].append(w.stop(m))

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(str(cls.tmp), True)

    def test_si5_nothing_is_refused_at_any_member(self):
        for name, decisions in self.decisions.items():
            with self.subTest(member=name):
                self.assertEqual(decisions, [None, None, None])

    def test_si5_the_three_faulty_members_fail_with_a_repair_and_the_clean_one_passes(self):
        expected = {'claimer': {1: 'fail'}, 'scribe': {2: 'fail'}, 'stray': {4: 'fail'}, 'clean': {}}
        for m in (self.claimer, self.scribe, self.stray, self.clean):
            with self.subTest(member=m.name):
                found = self.w.results(self.w.returns(m)[0])
                failing = dict((n, r['result']) for n, r in found.items() if r['result'] == 'fail')
                self.assertEqual(failing, expected[m.name], found)
                for n in failing:
                    self.assertTrue(found[n]['repair'], found[n])
                if m is self.clean:
                    self.assertEqual([found[n]['result'] for n in (1, 2, 3, 4)], ['pass', 'pass', 'pass', 'pass'])

    def test_tc10_each_hand_back_result_is_on_its_witness_line_and_again_on_the_return(self):
        for m in (self.claimer, self.scribe, self.stray, self.clean):
            with self.subTest(member=m.name):
                line = self.w.witnesses(m, 'PreToolUse')[-1]
                back = self.w.returns(m)[0]
                ids = [c['id'] for c in self.w.runs(line)[0]['checks']]
                on_return = [[c['id'] for c in run['checks']] for run in self.w.runs(back)]
                self.assertIn(ids, on_return)
                self.assertEqual(self.w.runs(line)[0]['report'], 'hand-back message')

    def test_tc10_the_stop_carries_its_result_on_its_witness_line_and_the_return_is_written_there(self):
        back = self.w.returns(self.claimer)[0]
        self.assertEqual(back['harness_payload']['hook_event_name'], 'SubagentStop')
        stop = self.w.witnesses(self.claimer, 'SubagentStop')[-1]
        self.assertEqual(self.w.results(stop)[1]['result'], 'fail')
        self.assertEqual(len(self.w.runs(back)), 2, 'the hand-back run, then the stop run, in order')

    def test_tc10_the_answer_is_the_hand_back_message_and_no_kept_result_is_left(self):
        for m in (self.claimer, self.clean):
            back = self.w.returns(m)[0]
            self.assertEqual(back['harness_payload']['answer_from'], 'hand-back message')
            self.assertEqual(back['answer_fingerprint']['sha256'], self.w.runs(back)[-1]['sha256'])
        self.assertEqual(list(self.w.pending().glob('check-*.json')), [])

    def test_r36_the_gate_holds_the_parent_until_a_disposition_settles_each_fail(self):
        w = self.w
        denied = w.denied(w.parent('Write', {'file_path': str(w.repo / 'merge.md'), 'content': 'x'})[1])
        self.assertTrue(denied, 'a fail stands: the parent is held')
        for name in ('claimer', 'scribe', 'stray'):
            self.assertIn('member %s attempt 1' % name, denied)
        self.assertNotIn('member clean', denied)
        self.assertIn('Recommended repair', denied)
        settled = []
        for m in (self.claimer, self.scribe, self.stray):
            back = w.returns(m)[0]
            ids = [c['id'] for run in w.runs(back) for c in run['checks'] if c['result'] == 'fail']
            command = 'python3 "%s" --call %s %s --kind accepted --reason "seen and accepted" --decided-by parent' % (
                world.DISPOSITION, m.call_id, ' '.join('--result %s' % i for i in ids))
            decision, done = w.disposition_call(command)
            self.assertIsNone(w.denied(decision), 'the disposition call runs while the parent is held')
            self.assertEqual(done.returncode, 0, done.stderr)
            settled.append(m.name)
            still = w.denied(w.parent('Write', {'file_path': str(w.repo / 'merge.md'), 'content': 'x'})[1])
            if len(settled) < 3:
                self.assertTrue(still, 'held while %s stands' % ', '.join(
                    n for n in ('claimer', 'scribe', 'stray') if n not in settled))
            else:
                self.assertIsNone(still, 'every fail settled: the parent runs on')
        lines = [r for r in w.records() if r.get('record') == 'disposition']
        self.assertEqual(sorted(r['call_id'] for r in lines), sorted(m.call_id for m in (
            self.claimer, self.scribe, self.stray)))
        self.assertEqual(list(w.pending().glob('disposition-*.json')), [], 'no pending file outlives its record')


class Routes(unittest.TestCase):
    """TC-10: every hand-back's and stop's result reaches the record, by each route a call can take."""

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix='return-routes-'))
        self.addCleanup(shutil.rmtree, str(self.tmp), True)
        self.w = world.World(self.tmp)
        self.w.start()

    def test_tc10_empty_a_member_whose_every_result_passes_refuses_no_parent_call(self):
        w = self.w
        m = w.member('fine', ['docs/'])
        w.dispatch(m)
        m.write('docs/fine.md', GOOD_FRONT)
        w.handback(m, report('docs/fine.md'))
        w.stop(m)
        results = [c['result'] for run in w.runs(w.returns(m)[0]) for c in run['checks']]
        self.assertNotIn('fail', results)
        self.assertIsNone(w.denied(w.parent('Write', {'file_path': str(w.repo / 'a.md'), 'content': 'a'})[1]))

    def test_tc10_a_member_without_the_hand_back_tool_failing_at_its_stop_is_not_refused(self):
        w = self.w
        m = w.member('plain', ['docs/'], mode='default')
        w.dispatch(m)
        self.assertIsNone(w.stop(m, closing='I did it.'))
        back = w.returns(m)
        self.assertEqual(len(back), 1, 'the return is written at that stop')
        found = w.results(back[0])
        self.assertEqual(found[1]['result'], 'fail')
        self.assertTrue(found[1]['repair'])

    def test_tc10_a_hand_back_member_stopping_before_it_hands_back_has_no_return_there_background(self):
        w = self.w
        m = w.member('early', ['docs/'])
        w.dispatch(m)
        self.assertIsNone(w.stop(m, closing='Plain text instead of a hand-back.'))
        self.assertEqual(w.returns(m), [], 'no report reached the parent: no return at that stop')
        stop = w.witnesses(m, 'SubagentStop')[-1]
        self.assertEqual(w.results(stop)[1]['reason'], 'no report at this stop')
        self.assertEqual(w.runs(stop)[0]['report'], 'final message')
        self.assertEqual(w.runs(stop)[0]['sha256'], world.sha('Plain text instead of a hand-back.'))
        m.write('docs/early.md', GOOD_FRONT)
        w.handback(m, report('docs/early.md'))
        w.stop(m, active=True)
        back = w.returns(m)
        self.assertEqual(len(back), 1)
        self.assertEqual(back[0]['harness_payload']['answer_from'], 'hand-back message')
        self.assertEqual(back[0]['answer_fingerprint']['sha256'], world.sha(report('docs/early.md')))
        self.assertEqual(len(w.runs(back[0])), 3, 'the early stop, the hand-back and the last stop')

    def test_tc10_a_hand_back_member_stopping_before_it_hands_back_foreground(self):
        w = self.w
        m = w.member('early-fg', ['docs/'], background=False)
        w.dispatch(m)
        w.stop(m, closing='Plain text first.')
        m.write('docs/fg.md', GOOD_FRONT)
        w.handback(m, report('docs/fg.md'))
        w.stop(m, active=True)
        self.assertEqual(w.returns(m), [], 'a foreground return waits for the Agent call to finish')
        decision = w.foreground_post(m, handback_text=report('docs/fg.md'))
        back = w.returns(m)
        self.assertEqual(len(back), 1)
        self.assertEqual(back[0]['harness_payload']['hook_event_name'], 'PostToolUse')
        self.assertEqual(back[0]['answer_fingerprint']['sha256'], world.sha(report('docs/fg.md')))
        self.assertEqual(w.results(back[0], 0)[1]['reason'], 'no report at this stop')
        context = (decision or {}).get('hookSpecificOutput', {}).get('additionalContext', '')
        self.assertIn('member early-fg attempt 1', context, 'the foreground call carries its results to the parent')

    def test_tc10_a_hand_back_another_hook_refuses_stays_undelivered_and_the_next_is_the_answer(self):
        w = self.w
        m = w.member('classified', ['docs/'])
        w.dispatch(m)
        m.write('docs/one.md', GOOD_FRONT)
        w.handback(m, report('docs/one.md', prose='First try.'), refused_by_other=True)
        w.handback(m, report('docs/one.md', prose='Second try.'))
        w.stop(m)
        back = w.returns(m)[0]
        self.assertEqual(back['answer_fingerprint']['sha256'], world.sha(report('docs/one.md', prose='Second try.')))
        first = w.runs(back)[0]
        self.assertNotIn('delivered', first, 'no PostToolUse: the first hand-back stays undelivered')
        self.assertIs(w.runs(back)[1].get('delivered'), True)

    def test_tc10_a_failing_member_stopped_by_taskstop_has_a_failed_return_carrying_that_result(self):
        w = self.w
        m = w.member('stopped', ['docs/'])
        w.dispatch(m)
        w.handback(m, 'No section at all.')
        stop_given = {'task_id': m.agent}
        _code, decision, _err = w.parent('TaskStop', stop_given, call_id='toolu_stop_1')
        self.assertIsNone(w.denied(decision), 'TaskStop is let through while a fail stands')
        payload = w.parent_payload('TaskStop', stop_given, 'toolu_stop_1')
        payload.update(hook_event_name='PostToolUse', tool_response={'success': True})
        w.hook('PostToolUse', payload)
        back = w.returns(m)
        self.assertEqual(len(back), 1)
        self.assertEqual(back[0]['outcome'], 'failed')
        self.assertEqual(w.results(back[0], 0)[1]['result'], 'fail')

    def test_tc23_a_background_members_fail_while_a_second_member_runs_still_lets_the_second_record(self):
        w = self.w
        first, second = w.member('first', ['docs/']), w.member('second', ['docs/'])
        w.dispatch(first)
        w.dispatch(second)
        w.handback(first, 'No section.')
        w.stop(first)
        self.assertTrue(w.denied(w.parent('Edit', {'file_path': 'x'})[1]), 'the parent is held')
        second.write('docs/second.md', GOOD_FRONT)
        self.assertIsNone(w.denied(w.handback(second, report('docs/second.md'))), 'a member is never held')
        self.assertIsNone(w.stop(second))
        self.assertEqual(len(w.witnesses(second, 'PreToolUse')), 1)
        self.assertEqual(len(w.returns(second)), 1)

    def test_tc23_a_fail_on_a_members_own_dispatch_holds_the_parent_and_not_the_member(self):
        w = self.w
        outer = w.member('outer', None)
        w.dispatch(outer)
        inner = w.member('inner', None)
        # The member's own dispatch: its PreToolUse carries the member's agent id.
        given = {'prompt': inner.prompt, 'run_in_background': True}
        payload = outer.base('PreToolUse')
        payload.update(tool_name='Agent', tool_input=given, tool_use_id=inner.call_id)
        w.hook('PreToolUse', payload)
        w.handback(inner, 'Nothing to report and no section.')
        self.assertTrue(w.denied(w.parent('Write', {'file_path': 'y'})[1]), 'the session\'s parent is held')
        read = outer.base('PreToolUse')
        read.update(tool_name='Write', tool_input={'file_path': str(w.scratchpad / 'n.txt')}, tool_use_id='tw1')
        self.assertIsNone(w.denied(w.hook('PreToolUse', read)[1]), 'the member is not')


if __name__ == '__main__':
    unittest.main()
