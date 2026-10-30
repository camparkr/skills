"""Tests for worktree_check.py: before a writer's dispatch, each write-set file's state in the main checkout is
compared with its state at the commit the worktree will branch from, and the dispatch is refused with the reason where
they differ or where the write set spans two repositories (R-17; TC-12).

Each test builds its own repositories in a temporary folder: a seed, a bare remote cloned from it, and the main
checkout cloned from the remote, so the remote's default branch is known. Nothing outside the temporary folder is
written; that is proved before anything runs.

Run from the skill's folder:  python3 -m unittest discover -s tests
"""

import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
SCRIPT = HERE.parent / 'skill' / 'scripts' / 'worktree_check.py'
GIT_ENV = {'GIT_AUTHOR_NAME': 'Test', 'GIT_AUTHOR_EMAIL': 'test@example.invalid', 'GIT_COMMITTER_NAME': 'Test',
           'GIT_COMMITTER_EMAIL': 'test@example.invalid', 'GIT_CONFIG_GLOBAL': os.devnull,
           'GIT_CONFIG_NOSYSTEM': '1'}


def env():
    out = dict(os.environ)
    for name in ('SUBAGENT_LEDGER_DIR', 'SUBAGENT_LEDGER_SCRIPTS'):
        out.pop(name, None)
    out.update(GIT_ENV)
    return out


def git(folder, *arguments):
    done = subprocess.run(['git', '-C', str(folder)] + list(arguments), capture_output=True, text=True, env=env())
    if done.returncode != 0:
        raise AssertionError('git %s: %s' % (' '.join(arguments), done.stderr))
    return done.stdout


class WorktreeCheckTests(unittest.TestCase):

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        # Where every write lands, proved before anything runs: inside this test's own temporary folder.
        self.assertTrue(str(self.tmp.resolve()).startswith(str(Path(tempfile.gettempdir()).resolve())))
        seed = self.tmp / 'seed'
        seed.mkdir()
        git(seed, 'init', '-q', '-b', 'main')
        (seed / 'src').mkdir()
        (seed / 'src' / 'a.py').write_text('a = 1\n', encoding='utf-8')
        (seed / 'docs').mkdir()
        (seed / 'docs' / 'x.md').write_text('# x\n', encoding='utf-8')
        (seed / '.gitignore').write_text('*.log\n', encoding='utf-8')
        git(seed, 'add', '.')
        git(seed, 'commit', '-q', '-m', 'seed')
        subprocess.run(['git', 'clone', '-q', '--bare', str(seed), str(self.tmp / 'remote.git')], check=True,
                       env=env())
        self.main = self.tmp / 'main'
        subprocess.run(['git', 'clone', '-q', str(self.tmp / 'remote.git'), str(self.main)], check=True, env=env())
        self.briefs = self.tmp / 'briefs'
        self.briefs.mkdir()

    def tearDown(self):
        shutil.rmtree(str(self.tmp), ignore_errors=True)

    def brief(self, *write_set):
        path = self.briefs / ('brief-%d.md' % len(list(self.briefs.iterdir())))
        path.write_text('---\nmember: m1\nattempt: 1\n---\n\nThe task.\n\n## Write set\n\n%s\n\n## What your work is '
                        'checked for\n\nThe instruction.\n' % '\n'.join(write_set), encoding='utf-8')
        return path

    def check(self, brief, base=None, repository=None):
        arguments = ['--brief', str(brief), '--repository', str(repository or self.main)]
        if base:
            arguments += ['--base', base]
        done = subprocess.run([sys.executable, str(SCRIPT)] + arguments, capture_output=True, text=True, env=env(),
                              timeout=60)
        try:
            out = json.loads(done.stdout)
        except ValueError:
            self.fail('no JSON on stdout (exit %s): %s %s' % (done.returncode, done.stdout, done.stderr))
        return done.returncode, out

    def test_an_unchanged_write_set_passes_on_the_remote_default_branch(self):
        code, out = self.check(self.brief('src/a.py', 'docs/'))
        self.assertEqual(code, 0, out)
        self.assertFalse(out['refuse'])
        self.assertEqual(out['base']['ref'], 'origin/HEAD')
        self.assertEqual(out['differences'], [])

    def test_tc12_empty_a_writer_whose_write_set_names_no_existing_file_is_passed(self):
        code, out = self.check(self.brief('src/new_module.py', 'reports/'))
        self.assertEqual(code, 0, out)
        self.assertFalse(out['refuse'])

    def test_tc12_likeness_a_file_committed_locally_and_not_pushed_is_refused_on_the_default_base(self):
        (self.main / 'src' / 'a.py').write_text('a = 2\n', encoding='utf-8')
        git(self.main, 'commit', '-q', '-am', 'local only')
        code, out = self.check(self.brief('src/a.py'))
        self.assertEqual(code, 1, out)
        self.assertTrue(out['refuse'])
        self.assertIn('src/a.py', out['reason'])
        self.assertIn('origin/HEAD', out['reason'])
        # Control: with the worktree branching from local HEAD, the same file passes.
        code, out = self.check(self.brief('src/a.py'), base='head')
        self.assertEqual(code, 0, out)

    def test_tc12_likeness_a_file_changed_and_not_committed_is_refused_with_the_reason(self):
        (self.main / 'src' / 'a.py').write_text('a = 3\n', encoding='utf-8')
        code, out = self.check(self.brief('src/a.py'), base='head')
        self.assertEqual(code, 1, out)
        self.assertIn('src/a.py', out['reason'])
        self.assertIn('commit', out['reason'])
        self.assertEqual([d['path'] for d in out['differences']], ['src/a.py'])

    def test_an_untracked_file_under_a_write_set_folder_is_refused(self):
        (self.main / 'src' / 'b.py').write_text('b = 1\n', encoding='utf-8')
        code, out = self.check(self.brief('src/'), base='head')
        self.assertEqual(code, 1, out)
        self.assertEqual([d['path'] for d in out['differences']], ['src/b.py'])

    def test_an_ignored_file_under_a_write_set_folder_is_not_compared(self):
        (self.main / 'src' / 'debug.log').write_text('noise\n', encoding='utf-8')
        code, out = self.check(self.brief('src/'), base='head')
        self.assertEqual(code, 0, out)

    def test_a_file_deleted_and_not_committed_is_refused(self):
        (self.main / 'docs' / 'x.md').unlink()
        code, out = self.check(self.brief('docs/x.md'), base='head')
        self.assertEqual(code, 1, out)
        self.assertEqual(out['differences'][0]['main'], 'absent')

    def test_a_write_set_spanning_two_repositories_is_refused(self):
        nested = self.main / 'vendor' / 'lib'
        nested.mkdir(parents=True)
        git(nested, 'init', '-q')
        code, out = self.check(self.brief('src/a.py', 'vendor/lib/x.py'), base='head')
        self.assertEqual(code, 1, out)
        self.assertIn('two repositories', out['reason'])
        self.assertIn('vendor/lib/x.py', out['reason'])

    def test_a_write_set_path_given_absolute_or_leaving_the_repository_is_refused(self):
        code, out = self.check(self.brief(str(self.main / 'src' / 'a.py')), base='head')
        self.assertEqual(code, 1, out)
        code, out = self.check(self.brief('../seed/src/a.py'), base='head')
        self.assertEqual(code, 1, out)
        self.assertIn('leaves the repository', out['reason'])

    def test_a_read_only_member_is_not_checked(self):
        code, out = self.check(self.brief('none'))
        self.assertEqual(code, 0, out)
        self.assertIn('not a writer', out['reason'])

    def test_a_base_that_cannot_be_read_is_refused(self):
        lone = self.tmp / 'lone'
        lone.mkdir()
        git(lone, 'init', '-q', '-b', 'main')
        (lone / 'a.py').write_text('a = 1\n', encoding='utf-8')
        git(lone, 'add', '.')
        git(lone, 'commit', '-q', '-m', 'lone')
        code, out = self.check(self.brief('a.py'), repository=lone)
        self.assertEqual(code, 1, out)
        self.assertIn('cannot be read', out['reason'])
        code, out = self.check(self.brief('a.py'), repository=lone, base='head')
        self.assertEqual(code, 0, out)


if __name__ == '__main__':
    unittest.main()
