"""Controls for the disposition script and its record (R-36): the kinds, who decided, the closed command grammar, and
the pending file the capture turns into a disposition line at the shell call's PostToolUse.

Each refusal is paired with the nearest case the script accepts. They were committed before the script existed, and
each failed then.

Run from the skill's folder:  python3 -m unittest discover -s tests
"""

import json
import shutil
import tempfile
import time
import unittest
from pathlib import Path

import world
from world import GOOD_FRONT, report
import disposition


class Grammar(unittest.TestCase):
    """The closed grammar the gate lets through, read without running anything."""

    def args(self):
        return '--call toolu_a_1 --result r1-1 --kind accepted --reason "fine as it is" --decided-by parent'

    def test_the_script_and_its_arguments_with_or_without_python3_are_in_the_grammar(self):
        for command in ('python3 "%s" %s' % (world.DISPOSITION, self.args()), '"%s" %s' % (world.DISPOSITION,
                                                                                             self.args()),
                        'python3 %s %s --kind sent-back' % (world.DISPOSITION, self.args().replace(
                            '--kind accepted ', ''))):
            with self.subTest(command=command):
                parsed, why = disposition.parse_command(command, str(world.SKILL))
                self.assertIsNotNone(parsed, why)

    def test_likeness_separators_pipes_redirections_substitutions_and_second_lines_are_outside_it(self):
        base = 'python3 "%s" %s' % (world.DISPOSITION, self.args())
        for extra in (' ; ls', ' && ls', ' || ls', ' | cat', ' > f', ' < f', ' & ', ' $(ls)', ' `ls`', '\nls',
                      ' --reason "$HOME"'):
            with self.subTest(extra=extra):
                parsed, why = disposition.parse_command(base + extra, str(world.SKILL))
                self.assertIsNone(parsed)
                self.assertTrue(why)

    def test_likeness_another_script_or_an_unknown_flag_is_outside_it(self):
        for command in ('python3 "%s" %s' % (world.GATE, self.args()),
                        'python3 "%s" %s --force' % (world.DISPOSITION, self.args()),
                        'python3 "%s" --call toolu_a_1 --kind accepted --reason x --decided-by parent'
                        % world.DISPOSITION,
                        'python3 "%s" %s' % (world.DISPOSITION, self.args().replace('parent', 'nobody')),
                        'python3 "%s" %s' % (world.DISPOSITION, self.args().replace('accepted', 'ignored'))):
            with self.subTest(command=command):
                self.assertIsNone(disposition.parse_command(command, str(world.SKILL))[0])


class Script(unittest.TestCase):

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix='return-disposition-'))
        self.addCleanup(shutil.rmtree, str(self.tmp), True)
        w = self.w = world.World(self.tmp)
        w.start()
        self.m = w.member('writer', ['docs/'])
        w.dispatch(self.m)
        self.m.write('docs/out.md', GOOD_FRONT)
        w.handback(self.m, 'No section here.')
        w.stop(self.m)
        back = w.returns(self.m)[0]
        self.ids = [c['id'] for run in w.runs(back) for c in run['checks'] if c['result'] == 'fail']

    def run_script(self, *extra, ids=None, kind='accepted', by='parent'):
        args = ['--call', self.m.call_id, '--kind', kind, '--reason', 'read and decided', '--decided-by', by]
        for i in (self.ids if ids is None else ids):
            args += ['--result', i]
        return self.w.disposition(*(args + list(extra)))

    def pending_files(self):
        return sorted(self.w.pending().glob('disposition-*.json'))

    def test_an_accepted_disposition_writes_the_pending_file_and_the_capture_turns_it_into_a_line(self):
        done = self.run_script()
        self.assertEqual(done.returncode, 0, done.stderr)
        files = self.pending_files()
        self.assertEqual(len(files), 1)
        data = json.loads(files[0].read_text(encoding='utf-8'))
        self.assertEqual((data['call_id'], data['member'], data['attempt'], data['result_ids']),
                         (self.m.call_id, 'writer', 1, self.ids))
        post = self.w.parent_payload('Bash', {'command': 'python3 disposition.py'}, call_id='toolu_bash_9')
        post.update(hook_event_name='PostToolUse', tool_response={'stdout': done.stdout, 'stderr': ''})
        self.w.hook('PostToolUse', post)
        lines = [r for r in self.w.records() if r.get('record') == 'disposition']
        self.assertEqual(len(lines), 1)
        self.assertEqual((lines[0]['kind'], lines[0]['decided_by'], lines[0]['recorded_at_call']),
                         ('accepted', 'parent', 'toolu_bash_9'))
        self.assertEqual(self.pending_files(), [], 'no pending file outlives its record')

    def test_an_accepted_failed_writer_is_recorded_and_its_merge_is_still_asked_for_in_chat(self):
        done = self.run_script()
        self.assertEqual(done.returncode, 0, done.stderr)
        self.assertIn('asked for in chat', json.loads(done.stdout)['note'])

    def test_a_discarded_failed_writer_decided_by_the_parent_is_refused_and_nothing_is_written(self):
        done = self.run_script(kind='discarded')
        self.assertEqual(done.returncode, 1)
        self.assertIn('settled with the user', done.stderr)
        self.assertEqual(self.pending_files(), [])

    def test_likeness_a_discarded_failed_writer_decided_by_the_user_with_their_words_is_written(self):
        done = self.run_script('--quote', 'Drop it, we will redo this part.', kind='discarded', by='user')
        self.assertEqual(done.returncode, 0, done.stderr)
        self.assertEqual(json.loads(self.pending_files()[0].read_text())['quote'],
                         'Drop it, we will redo this part.')

    def test_a_user_decision_with_no_quote_is_refused(self):
        self.assertEqual(self.run_script(by='user').returncode, 1)
        self.assertEqual(self.pending_files(), [])

    def test_a_repaired_disposition_names_its_paths_or_is_refused(self):
        self.assertEqual(self.run_script(kind='repaired').returncode, 1)
        done = self.run_script('--path', 'docs/out.md', kind='repaired')
        self.assertEqual(done.returncode, 0, done.stderr)
        data = json.loads(self.pending_files()[0].read_text())
        self.assertEqual(data['paths'], ['docs/out.md'])
        self.assertEqual(Path(data['repository']).resolve(), self.w.repo.resolve())

    def test_a_result_id_the_call_does_not_carry_is_refused(self):
        done = self.run_script(ids=['ffffffff-1'])
        self.assertEqual(done.returncode, 1)
        self.assertIn('not a result of call', done.stderr)

    def test_empty_a_call_with_no_check_results_is_refused(self):
        done = self.w.disposition('--call', 'toolu_nothing', '--result', 'x-1', '--kind', 'accepted', '--reason',
                                  'r', '--decided-by', 'parent')
        self.assertEqual(done.returncode, 1)
        self.assertIn('no check result', done.stderr)

    def test_empty_no_session_id_cannot_run(self):
        env = dict(self.w.env(), SUBAGENT_LEDGER_DIR=str(self.w.ledger))
        env.pop('CLAUDE_CODE_SESSION_ID')
        done = world.subprocess.run([world.sys.executable, str(world.DISPOSITION), '--call', self.m.call_id,
                                     '--result', self.ids[0], '--kind', 'accepted', '--reason', 'r', '--decided-by',
                                     'parent'], capture_output=True, text=True, env=env, cwd=str(self.w.repo))
        self.assertEqual(done.returncode, 2)

    def test_two_dispositions_before_one_shell_call_each_get_a_file_and_a_line(self):
        self.assertEqual(self.run_script().returncode, 0)
        self.assertEqual(self.run_script(kind='sent-back').returncode, 0)
        self.assertEqual(len(self.pending_files()), 2)
        post = self.w.parent_payload('Bash', {'command': 'true'})
        post.update(hook_event_name='PostToolUse', tool_response={'stdout': '', 'stderr': ''})
        self.w.hook('PostToolUse', post)
        kinds = sorted(r['kind'] for r in self.w.records() if r.get('record') == 'disposition')
        self.assertEqual(kinds, ['accepted', 'sent back'])

    def test_likeness_a_malformed_pending_file_writes_an_error_line_and_no_disposition(self):
        self.w.pending().mkdir(parents=True, exist_ok=True)
        (self.w.pending() / 'disposition-bad.json').write_text('{"call_id": "x"}', encoding='utf-8')
        post = self.w.parent_payload('Bash', {'command': 'true'})
        post.update(hook_event_name='PostToolUse', tool_response={'stdout': '', 'stderr': ''})
        self.w.hook('PostToolUse', post)
        self.assertEqual([r for r in self.w.records() if r.get('record') == 'disposition'], [])
        errors = world.lines(self.w.ledger / 'capture-errors.jsonl')
        self.assertTrue([e for e in errors if 'disposition' in e.get('reason', '')], errors)
        self.assertEqual(self.pending_files(), [])

    def test_a_members_shell_call_writes_no_disposition_line(self):
        self.assertEqual(self.run_script().returncode, 0)
        post = self.m.base('PostToolUse')
        post.update(tool_name='Bash', tool_input={'command': 'true'}, tool_use_id='tm-bash',
                    tool_response={'stdout': '', 'stderr': ''})
        self.w.hook('PostToolUse', post)
        self.assertEqual([r for r in self.w.records() if r.get('record') == 'disposition'], [])
        self.assertEqual(len(self.pending_files()), 1, 'it waits for the parent\'s shell call')


class Repaired(unittest.TestCase):
    """TC-16's repaired fixture, through the script: no later commit changing its paths is a fault."""

    def test_a_repaired_disposition_with_and_without_a_later_commit(self):
        tmp = Path(tempfile.mkdtemp(prefix='return-repaired-'))
        self.addCleanup(shutil.rmtree, str(tmp), True)
        w = world.World(tmp)
        w.start()
        m = w.member('fixme', ['docs/'])
        w.dispatch(m)
        m.write('docs/fixme.md', world.BAD_FRONT)
        w.handback(m, report('docs/fixme.md'))
        w.stop(m)
        ids = [c['id'] for run in w.runs(w.returns(m)[0]) for c in run['checks'] if c['result'] == 'fail']
        command = ('python3 "%s" --call %s %s --kind repaired --reason "I fix the front matter" --decided-by parent '
                   '--path docs/fixme.md' % (world.DISPOSITION, m.call_id, ' '.join('--result %s' % i for i in ids)))
        _decision, done = w.disposition_call(command)
        self.assertEqual(done.returncode, 0, done.stderr)
        _code, out = w.count_check()
        self.assertEqual(out['count_check']['faults'].get(
            'a repaired disposition with no later commit changing its paths'), 1, out)
        time.sleep(1.2)  # a commit's time is read to the second; the repair comes after the decision
        (w.repo / 'docs' / 'fixme.md').write_text(GOOD_FRONT, encoding='utf-8')
        world.git(w.repo, 'add', 'docs/fixme.md')
        world.git(w.repo, 'commit', '-q', '-m', 'repair the front matter')
        _code, out = w.count_check()
        self.assertNotIn('a repaired disposition with no later commit changing its paths', out['count_check']['faults'])


if __name__ == '__main__':
    unittest.main()
