"""Controls for the ledger's file lock where Python has no fcntl, as on Windows, and for setup.sh's check of it.

The writer and Claude Code's capture lock a file through one helper, `ledger.lock_file`. It uses fcntl where fcntl
imports and msvcrt where it does not. These tests run on macOS or Linux, so they reach the msvcrt branch by making
fcntl unimportable in a child process and giving it a stand-in msvcrt that records each call. The stand-in proves the
helper calls msvcrt as msvcrt requires; it cannot prove that Windows locks the file. Only a run on Windows can.

Run from the skill's folder:  python3 -m unittest tests/test_windows_lock.py
"""

import json
import os
import shutil
import subprocess
import sys
import tempfile
import textwrap
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
SCRIPTS = ROOT / 'skill' / 'scripts'
SETUP = ROOT / 'setup.sh'
SESSION = 's-win-0001'

# Imported first in each child: fcntl cannot be imported, and a stand-in msvcrt writes each call it gets to the file
# STAND_IN_LOG names, as one JSON line: the mode, the byte count and where the file stood. Its first lock call fails
# as msvcrt's does after ten tries, so the helper must try again. subprocess is imported before the stand-in arrives:
# it takes msvcrt's presence to mean Windows, and would then load Windows-only modules.
STAND_IN = textwrap.dedent('''
    import errno, json, os, subprocess, sys, types
    sys.modules['fcntl'] = None
    fake = types.ModuleType('msvcrt')
    fake.LK_UNLCK, fake.LK_LOCK, fake.LK_NBLCK, fake.LK_RLCK, fake.LK_NBRLCK = 0, 1, 2, 3, 4
    tries = {'lock': 0}
    def locking(fd, mode, nbytes):
        where = os.lseek(fd, 0, os.SEEK_CUR)
        failed = mode == fake.LK_LOCK and tries['lock'] == 0
        if mode == fake.LK_LOCK:
            tries['lock'] += 1
        with open(os.environ['STAND_IN_LOG'], 'a') as log:
            log.write(json.dumps({'mode': mode, 'nbytes': nbytes, 'at': where, 'failed': failed}) + '\\n')
        if failed:
            raise OSError(getattr(errno, 'EDEADLOCK', errno.EDEADLK), 'Resource deadlock avoided')
    fake.locking = locking
    sys.modules['msvcrt'] = fake
''')

LEDGER_CHILD = textwrap.dedent('''
    import importlib.util, sys
    spec = importlib.util.spec_from_file_location('ledger', sys.argv[1])
    ledger = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(ledger)
    result = ledger.witness(event='WindowsLock', session=sys.argv[2], agent_id='agent-win', call_id='call-win')
    if not result.ok:
        sys.exit('not written: %s' % result.error)
''')

CAPTURE_CHILD = textwrap.dedent('''
    import runpy, sys
    script = sys.argv[1]
    sys.path.insert(0, str(__import__('pathlib').Path(script).parent))
    sys.argv = [script] + sys.argv[2:]
    runpy.run_path(script, run_name='__main__')
''')


class Scratch(unittest.TestCase):

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix='subagent-ledger-winlock-'))
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.folder = self.tmp / 'ledger'
        self.folder.mkdir()
        self.log = self.tmp / 'stand-in.jsonl'

    def child(self, body, args, stdin=''):
        script = self.tmp / 'child.py'
        script.write_text(STAND_IN + body, encoding='utf-8')
        env = dict(os.environ, SUBAGENT_LEDGER_DIR=str(self.folder), STAND_IN_LOG=str(self.log),
                   PYTHONDONTWRITEBYTECODE='1')
        return subprocess.run([sys.executable, str(script)] + [str(a) for a in args], input=stdin,
                              capture_output=True, text=True, env=env, cwd=str(self.tmp), timeout=120)

    def records(self):
        path = self.folder / ('%s.jsonl' % SESSION)
        if not path.is_file():
            return []
        return [json.loads(line) for line in path.read_text(encoding='utf-8').splitlines() if line.strip()]

    def calls(self):
        if not self.log.is_file():
            return []
        return [json.loads(line) for line in self.log.read_text(encoding='utf-8').splitlines() if line.strip()]

    def assert_msvcrt_calls_paired(self):
        """Every lock is msvcrt's blocking lock on the first byte, tried again after a failure, then unlocked."""
        calls = self.calls()
        self.assertTrue(calls, 'the stand-in msvcrt was never called')
        self.assertEqual(calls[0], {'mode': 1, 'nbytes': 1, 'at': 0, 'failed': True})
        self.assertEqual(calls[1], {'mode': 1, 'nbytes': 1, 'at': 0, 'failed': False})
        held = 0
        for call in calls[1:]:
            self.assertEqual((call['nbytes'], call['at']), (1, 0), call)
            held += 1 if call['mode'] == 1 else -1
            self.assertIn(held, (0, 1), 'a lock taken twice, or released untaken: %s' % calls)
        self.assertEqual(held, 0, 'a lock never released: %s' % calls)


class WithoutFcntl(Scratch):
    """Control 1: with fcntl unimportable and msvcrt standing in, the writer and the capture import and append."""

    def test_the_writer_appends_a_record_through_msvcrt(self):
        done = self.child(LEDGER_CHILD, [SCRIPTS / 'ledger.py', SESSION])
        self.assertEqual(done.returncode, 0, done.stderr)
        self.assertEqual([r['call_id'] for r in self.records()], ['call-win'])
        self.assert_msvcrt_calls_paired()

    def test_the_claude_code_capture_appends_a_dispatch_through_msvcrt(self):
        payload = {'session_id': SESSION, 'hook_event_name': 'PreToolUse', 'tool_name': 'Agent',
                   'tool_use_id': 'toolu_win_0001', 'cwd': str(self.tmp),
                   'tool_input': {'description': 'a check', 'prompt': 'Count the files.',
                                  'subagent_type': 'general-purpose'}}
        done = self.child(CAPTURE_CHILD, [SCRIPTS / 'capture_claude_code.py', 'PreToolUse',
                                          '--ledger', self.folder], stdin=json.dumps(payload))
        self.assertEqual((done.returncode, done.stdout), (0, ''), done.stderr)
        self.assertEqual([(r['call_id'], r['record']) for r in self.records()], [('toolu_win_0001', 'dispatch')])
        self.assertTrue((self.folder / '.pending' / SESSION / '.lock').exists()
                        or list(self.folder.rglob('.lock')), 'the pending lock file was never opened')
        self.assert_msvcrt_calls_paired()
        self.assertGreaterEqual(sum(1 for c in self.calls() if c['mode'] == 1 and not c['failed']), 2,
                                'both the pending lock and the ledger lock go through msvcrt')


RACER = textwrap.dedent('''
    import contextlib, importlib.util, os, sys
    spec = importlib.util.spec_from_file_location('ledger', sys.argv[1])
    ledger = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(ledger)
    lock = ledger.lock_file if sys.argv[4] == 'locked' else (lambda handle: contextlib.nullcontext())
    tag, count = sys.argv[3], int(sys.argv[5])
    for n in range(count):
        with open(sys.argv[2], 'a', encoding='utf-8') as handle:
            with lock(handle):
                # One line written in ten pieces, each flushed: without the lock the other writer gets between them.
                for piece in range(10):
                    handle.write('%s-%05d-%d:%s' % (tag, n, piece, 'x' * 200))
                    handle.flush()
                handle.write('\\n')
                handle.flush()
''')


class TwoWriters(Scratch):
    """Control 2: on macOS or Linux the helper holds fcntl's lock, so two writers' lines never interleave."""

    def race(self, mode, count=1500):
        racer = self.tmp / 'racer.py'
        racer.write_text(RACER, encoding='utf-8')
        target = self.tmp / 'shared.txt'
        procs = [subprocess.Popen([sys.executable, str(racer), str(SCRIPTS / 'ledger.py'), str(target), tag, mode,
                                   str(count)], stderr=subprocess.PIPE, text=True) for tag in ('a', 'b')]
        for proc in procs:
            _out, err = proc.communicate(timeout=600)
            self.assertEqual(proc.returncode, 0, err)
        lines = target.read_text(encoding='utf-8').split('\n')[:-1]
        whole = sum(1 for line in lines if line == self.line_of(line[:1], line[2:7]))
        return len(lines), whole

    @staticmethod
    def line_of(tag, n):
        """The line writer `tag` wrote for number `n`, as it reads when no other writer got between its pieces."""
        return ''.join('%s-%s-%d:%s' % (tag, n, piece, 'x' * 200) for piece in range(10))

    def test_two_writers_leave_only_whole_lines(self):
        count, whole = self.race('locked')
        self.assertEqual((count, whole), (3000, 3000))

    def test_control_without_the_lock_reported(self):
        """Interleaving is not certain without the lock, so the result is printed, not asserted."""
        count, whole = self.race('unlocked')
        print('\nWINLOCK-UNLOCKED lines=%d whole=%d' % (count, whole), file=sys.stderr)


class Setup(Scratch):
    """Control 3: setup.sh runs on a Windows shell when the lock helper imports, and refuses when it cannot."""

    def run_setup(self, blocked=()):
        """setup.sh in a dry run, with `uname -s` reporting Git Bash on Windows and python3 this interpreter.

        Each module in `blocked` is made unimportable for every python3 the script starts; when fcntl is blocked, the
        stand-in msvcrt is given instead unless msvcrt is blocked too.
        """
        bin_dir = self.tmp / 'bin'
        bin_dir.mkdir()
        uname = bin_dir / 'uname'
        uname.write_text('#!/bin/sh\necho MINGW64_NT-10.0-19045\n', encoding='utf-8')
        python = bin_dir / 'python3'
        python.write_text('#!/bin/sh\nexec "%s" "$@"\n' % sys.executable, encoding='utf-8')
        for path in (uname, python):
            path.chmod(0o755)
        site = self.tmp / 'site'
        site.mkdir()
        lines = []
        if 'fcntl' in blocked and 'msvcrt' not in blocked:
            lines.append(STAND_IN)
        lines += ["import sys\nsys.modules[%r] = None\n" % name for name in blocked]
        (site / 'sitecustomize.py').write_text(''.join(lines), encoding='utf-8')
        home = self.tmp / 'home'
        home.mkdir()
        env = dict(os.environ, PATH='%s:%s' % (bin_dir, os.environ.get('PATH', '')), HOME=str(home),
                   PYTHONPATH=str(site), STAND_IN_LOG=str(self.log), PYTHONDONTWRITEBYTECODE='1')
        env.pop('CODEX_HOME', None)
        env.pop('XDG_CONFIG_HOME', None)
        return subprocess.run(['bash', str(SETUP), '--dry-run'], capture_output=True, text=True, env=env,
                              cwd=str(self.tmp), timeout=120)

    def test_a_windows_shell_with_fcntl_is_not_refused(self):
        done = self.run_setup()
        self.assertEqual(done.returncode, 0, done.stderr)
        self.assertIn('Dry run: nothing was changed.', done.stdout)

    def test_a_windows_shell_with_msvcrt_alone_is_not_refused(self):
        done = self.run_setup(blocked=('fcntl',))
        self.assertEqual(done.returncode, 0, done.stderr)
        self.assertIn('Dry run: nothing was changed.', done.stdout)

    def test_no_lock_to_import_is_refused_and_names_the_lock(self):
        done = self.run_setup(blocked=('fcntl', 'msvcrt'))
        self.assertEqual(done.returncode, 1, done.stdout)
        self.assertIn('lock', done.stderr)
        self.assertIn('Nothing was changed.', done.stderr)
        self.assertNotIn('Dry run', done.stdout)


if __name__ == '__main__':
    unittest.main()
