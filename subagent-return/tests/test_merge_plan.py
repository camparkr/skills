"""TC-20: the merge plan reaches only passed worktrees, and never a path another session changed after the baseline
(R-35).

The plan is read-only: it says which paths may come home without asking, which need the parent to ask, and that a
merge is committed by path and never pushed. Merging and committing stay the parent's acts. They were committed before
the plan existed, and each failed then.

Run from the skill's folder:  python3 -m unittest discover -s tests
"""

import json
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

import world
from world import BAD_FRONT, GOOD_FRONT, report


class MergePlan(unittest.TestCase):

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix='return-merge-'))
        self.addCleanup(shutil.rmtree, str(self.tmp), True)
        self.w = world.World(self.tmp)
        self.w.start()

    def plan(self, member):
        done = subprocess.run([sys.executable, str(world.RETURN_CHECK), '--merge-plan', '--call', member.call_id,
                               '--worktree', str(member.root), '--main', str(self.w.repo), '--session', world.SESSION,
                               '--ledger', str(self.w.ledger)], capture_output=True, text=True, env=self.w.env(),
                              timeout=60)
        self.assertEqual(done.returncode, 0, done.stderr)
        return json.loads(done.stdout)

    def finish(self, member, *claims):
        self.w.handback(member, report(*claims))
        self.w.stop(member)

    def test_tc20_empty_a_worktree_whose_member_wrote_nothing_merges_nothing(self):
        m = self.w.member('idle', ['docs/'])
        self.w.dispatch(m)
        self.finish(m)
        plan = self.plan(m)
        self.assertEqual((plan['merge'], plan['ask'], plan['ask_all']), ([], [], None))

    def test_tc20_a_passed_worktree_on_unchanged_paths_is_merged_by_path_and_not_pushed(self):
        m = self.w.member('ready', ['docs/'])
        self.w.dispatch(m)
        m.write('docs/ready.md', GOOD_FRONT)
        self.finish(m, 'docs/ready.md')
        plan = self.plan(m)
        self.assertEqual((plan['merge'], plan['ask']), (['docs/ready.md'], []))
        self.assertIn('by path', plan['commit'])
        self.assertIn('never', plan['push'])

    def test_tc20_likeness_a_path_another_session_changed_after_the_baseline_is_not_merged_and_the_parent_asks(self):
        m = self.w.member('raced', ['docs/'])
        self.w.dispatch(m)
        m.write('docs/existing.md', GOOD_FRONT + '\nThe member\'s edit.\n')
        m.write('docs/own.md', GOOD_FRONT)
        self.finish(m, 'docs/existing.md', 'docs/own.md')
        (self.w.repo / 'docs' / 'existing.md').write_text(GOOD_FRONT + '\nA peer\'s edit.\n', encoding='utf-8')
        plan = self.plan(m)
        self.assertEqual(plan['merge'], ['docs/own.md'])
        self.assertEqual([a['path'] for a in plan['ask']], ['docs/existing.md'])
        self.assertIn('changed it after the baseline', plan['ask'][0]['why'])

    def test_tc20_likeness_a_worktree_with_a_not_checkable_result_has_its_merge_asked_for(self):
        self.w.configure(settings={'validator': ''})
        m = self.w.member('unchecked', ['docs/'])
        self.w.dispatch(m)
        m.write('docs/unchecked.md', GOOD_FRONT)
        self.finish(m, 'docs/unchecked.md')
        plan = self.plan(m)
        self.assertEqual(plan['merge'], [])
        self.assertIn('not_checkable', plan['ask_all'])

    def test_tc20_likeness_a_worktree_with_an_unrecorded_result_has_its_merge_asked_for(self):
        m = self.w.member('gap', ['docs/'])
        self.w.dispatch(m)
        m.write('docs/gap.md', GOOD_FRONT)
        self.w.handback(m, report('docs/gap.md'))
        # The stop's wrapper never ran its check (killed, as in the dry run): the capture alone writes the return,
        # and with the stop check switched on the stop's entry reads unrecorded.
        m.closing()
        payload = m.base('SubagentStop')
        payload.update(stop_hook_active=False, agent_transcript_path=str(m.lane), last_assistant_message=world.CLOSING,
                       background_tasks=[{'id': m.agent, 'type': 'subagent'}])
        subprocess.run([sys.executable, str(world.LEDGER_SCRIPTS / 'capture_claude_code.py'), 'SubagentStop',
                        '--ledger', str(self.w.ledger)], input=json.dumps(payload), capture_output=True, text=True,
                       env=self.w.env(), cwd=str(m.root), timeout=60, check=True)
        found = self.w.returns(m)[0]['check_results']
        self.assertIn('unrecorded (no check result when the return was written)', found)
        plan = self.plan(m)
        self.assertEqual(plan['merge'], [])
        self.assertIn('unrecorded', plan['ask_all'])

    def test_tc20_likeness_a_failed_worktree_has_its_merge_asked_for(self):
        m = self.w.member('failed', ['docs/'])
        self.w.dispatch(m)
        m.write('docs/failed.md', BAD_FRONT)
        self.finish(m, 'docs/failed.md')
        plan = self.plan(m)
        self.assertEqual(plan['merge'], [])
        self.assertIn('check 2 fail', plan['ask_all'])

    def test_tc20_a_passed_shell_using_writer_is_merged_like_any_passed_writer(self):
        m = self.w.member('shelly', ['src/'])
        self.w.dispatch(m)
        m.shell("printf 'print(5)\\n' > src/shelly.py")
        self.finish(m, 'src/shelly.py')
        plan = self.plan(m)
        self.assertEqual((plan['merge'], plan['ask_all']), (['src/shelly.py'], None))


if __name__ == '__main__':
    unittest.main()
