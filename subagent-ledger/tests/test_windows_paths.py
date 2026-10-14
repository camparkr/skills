"""Controls for Windows-style paths, run on macOS or Linux: what a run touched outside its folder, judged with
Windows paths, the configuration folder found from a transcript path written with backslashes, and the names of
pending files, which must be valid on Windows.

A Windows path counts as absolute when it starts with a drive letter or is a network path (two slashes and a
server), with either slash. It is compared case-insensitively, as Windows compares it. A macOS or Linux path is
judged exactly as before: the old rule is copied here and every case is checked against it.

Run from the skill's folder:  python3 -m unittest tests/test_windows_paths.py
"""

import os
import posixpath
import re
import shutil
import sys
import tempfile
import unittest
from unittest import mock
from pathlib import Path

HERE = Path(__file__).resolve().parent
SCRIPTS = HERE.parent / 'skill' / 'scripts'
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

import calls  # noqa: E402
import capture_claude_code  # noqa: E402
import transcripts  # noqa: E402


def old_inside(path, folder):
    path = posixpath.normpath(path)
    folder = posixpath.normpath(folder)
    return path == folder or path.startswith(folder.rstrip('/') + '/')


def old_absolute(value, folder):
    if value.startswith('~'):
        value = os.path.expanduser(value)
    if value.startswith('/'):
        return value
    return posixpath.join(folder, value)


def inside(value, folder):
    return transcripts._inside(transcripts._absolute(value, folder), folder)


class WindowsPaths(unittest.TestCase):

    def test_a_drive_folder(self):
        folder = 'C:\\Users\\me\\work'
        for value, expected in (
                ('C:\\Users\\me\\work\\a.txt', True),
                ('C:\\Users\\me\\work', True),
                ('c:/users/ME/Work/b.txt', True),
                ('C:\\Users\\me\\work\\sub\\..\\c.txt', True),
                ('notes\\d.txt', True),
                ('notes/e.txt', True),
                ('C:\\Users\\me\\workshop\\x.txt', False),
                ('C:\\Users\\me\\work\\..\\other\\y.txt', False),
                ('..\\other\\z.txt', False),
                ('D:\\Users\\me\\work\\a.txt', False),
                ('\\\\server\\share\\f.txt', False),
                ('//server/share/f.txt', False),
                ('\\Windows\\system32', False),
                ('/etc/hosts', False)):
            with self.subTest(value=value):
                self.assertIs(inside(value, folder), expected)

    def test_a_drive_folder_written_with_forward_slashes(self):
        folder = 'C:/Users/me/work'
        self.assertTrue(inside('C:\\Users\\me\\work\\a.txt', folder))
        self.assertTrue(inside('a.txt', folder))
        self.assertFalse(inside('C:\\Users\\me\\a.txt', folder))

    def test_a_network_folder(self):
        folder = '\\\\server\\share\\work'
        for value, expected in (
                ('\\\\server\\share\\work\\a.txt', True),
                ('//SERVER/share/work/b.txt', True),
                ('c.txt', True),
                ('\\\\server\\share\\other\\a.txt', False),
                ('\\\\other\\share\\work\\a.txt', False),
                ('C:\\work\\a.txt', False)):
            with self.subTest(value=value):
                self.assertIs(inside(value, folder), expected)

    def test_the_root_of_a_drive(self):
        self.assertTrue(inside('C:\\anything\\a.txt', 'C:\\'))
        self.assertFalse(inside('D:\\anything\\a.txt', 'C:\\'))

    def test_isolation_lists_only_the_outside_paths(self):
        reading = {'cwd': 'C:\\Users\\me\\work', 'path': 'transcript.jsonl', 'tool_uses': [
            {'name': 'Read', 'input': {'file_path': 'C:\\Users\\me\\work\\in.txt'}},
            {'name': 'Read', 'input': {'file_path': 'c:/users/me/work/in-too.txt'}},
            {'name': 'Write', 'input': {'file_path': 'C:\\Users\\me\\elsewhere\\out.txt'}},
            {'name': 'Bash', 'input': {'command': 'dir', 'workdir': 'D:\\other'}}]}
        outside = transcripts.isolation(reading)['outside']
        self.assertEqual(outside, [{'tool': 'Write', 'file_path': 'C:\\Users\\me\\elsewhere\\out.txt'},
                                   {'tool': 'Bash', 'workdir': 'D:\\other'}])


class MacPathsUnchanged(unittest.TestCase):
    """Every macOS or Linux case reads as the old rule read it, including the odd ones."""

    FOLDERS = ('/Users/me/work', '/Users/me/work/', '/', '//server/share', '/Users/Me/Work')
    VALUES = ('/Users/me/work/a.txt', '/Users/me/work', '/Users/me/workshop/x', '/Users/ME/work/a.txt',
              'a.txt', 'sub/../b.txt', '../other/c.txt', '~/notes.txt', '~', '//server/share/x', '//x',
              'a\\b.txt', '\\\\server\\share\\x', 'C:\\x', 'c:/x', '/Users/me/work/../work/d.txt', '.', '')

    def test_each_case_reads_as_before(self):
        for folder in self.FOLDERS:
            for value in self.VALUES:
                with self.subTest(folder=folder, value=value):
                    self.assertEqual(transcripts._absolute(value, folder), old_absolute(value, folder))
                    self.assertIs(inside(value, folder), old_inside(old_absolute(value, folder), folder))



class ConfigFromTranscriptPath(unittest.TestCase):
    """A `claude -p` run's transcript is looked for under the calling session's configuration folder, which is read
    from the hook's transcript_path. On Windows that path is written with backslashes."""

    SESSION = 'inner-0001'

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix='subagent-ledger-winpath-'))
        self.addCleanup(shutil.rmtree, self.tmp, True)
        empty = self.tmp / 'default-config'
        empty.mkdir()
        patcher = mock.patch.dict(os.environ, {'CLAUDE_CONFIG_DIR': str(empty)})
        patcher.start()
        self.addCleanup(patcher.stop)

    def reading(self, transcript_path):
        return capture_claude_code.inner_reading({'session_id': self.SESSION, 'result': 'done'}, 'claude -p hi',
                                                 {'transcript_path': transcript_path})

    def test_a_backslash_path_names_the_folder_searched(self):
        why = self.reading('C:\\Users\\me\\.claude\\projects\\C--work\\parent.jsonl')['tokens']
        self.assertIn(str(Path('C:\\Users\\me\\.claude') / 'projects'), why)

    def test_a_transcript_under_a_backslash_path_is_found(self):
        config = self.tmp / 'config'
        found = config / 'projects' / 'C--work' / ('%s.jsonl' % self.SESSION)
        found.parent.mkdir(parents=True)
        found.write_text('', encoding='utf-8')
        why = self.reading('%s\\projects\\C--work\\parent.jsonl' % config)['tokens']
        self.assertIn('does not carry the envelope', why)

    def test_a_forward_slash_path_is_found_as_before(self):
        config = self.tmp / 'config'
        found = config / 'projects' / '-work' / ('%s.jsonl' % self.SESSION)
        found.parent.mkdir(parents=True)
        found.write_text('', encoding='utf-8')
        why = self.reading('%s/projects/-work/parent.jsonl' % config)['tokens']
        self.assertIn('does not carry the envelope', why)



# What Windows refuses in a file name: these characters, control characters, and the names it keeps for devices.
WINDOWS_FORBIDDEN = re.compile(r'[<>:"/\\|?*\x00-\x1f]')
WINDOWS_DEVICE = re.compile(r'^(?:con|prn|aux|nul|com[0-9]|lpt[0-9])(?:\.|$)', re.I)


def old_safe(name):
    return re.sub(r'[^A-Za-z0-9._:-]', '_', name)[:200]


class PendingNames(unittest.TestCase):
    """A pending file's name is valid on Windows; a name already valid on both systems is kept as it was; and a
    pending file written under an older name, which macOS and Linux allow, is still found."""

    AWKWARD = ('a:b', 'mcp:server:tool', 'x<y>z', 'quote"d', 'back\\slash', 'pipe|q?star*', 'tab\tnew\nline',
               'con', 'CON', 'nul', 'Com1', 'lpt9', 'aux.json', 'prn.x', 'unrecorded (no id)', 'é')
    ALREADY_VALID = ('toolu_01ABCdef', '3f2a6c1e-9b7d-4e5f-8a0b-1c2d3e4f5a6b', 'join-a1b2c3d4', 'out-call_xyz',
                     'cli-toolu_9', 'resume-toolu_1', 'stopped-a9f', 'msg-019a.b', 'console', 'com', 'com10',
                     'lpt', 'nul_x', 'connect', 'a.b-c_d', 'x' * 250)

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix='subagent-ledger-pending-'))
        self.addCleanup(shutil.rmtree, self.tmp, True)

    def test_every_name_is_valid_on_windows(self):
        for name in self.AWKWARD + self.ALREADY_VALID:
            with self.subTest(name=name):
                safe = capture_claude_code._safe(name)
                self.assertIsNone(WINDOWS_FORBIDDEN.search(safe), safe)
                self.assertIsNone(WINDOWS_DEVICE.match(safe), safe)
                self.assertIsNone(WINDOWS_DEVICE.match(safe + '.json'), safe)

    def test_a_name_valid_on_both_is_unchanged(self):
        for name in self.ALREADY_VALID:
            with self.subTest(name=name):
                self.assertEqual(capture_claude_code._safe(name), old_safe(name))

    def test_a_file_under_the_older_name_is_still_found(self):
        folder, session, call = self.tmp / 'ledger', 'sess:one', 'mcp:call:1'
        old_dir = folder / '.pending' / old_safe(session)
        old_dir.mkdir(parents=True)
        (old_dir / ('%s.json' % old_safe(call))).write_text('{"call_id": "mcp:call:1"}', encoding='utf-8')
        (old_dir / ('join-%s.json' % old_safe('agent:1'))).write_text('{"call_id": "c"}', encoding='utf-8')
        self.assertEqual(capture_claude_code.read_pending(folder, session, call), {'call_id': 'mcp:call:1'})
        self.assertTrue(capture_claude_code.agent_known(folder, session, 'agent:1'))
        capture_claude_code.clear_pending(folder, session, [call])
        self.assertIsNone(capture_claude_code.read_pending(folder, session, call))

    def test_the_reader_finds_a_pending_file_under_either_name(self):
        folder, session = self.tmp / 'ledger', 's-0001'
        capture_claude_code.write_pending(folder, session, 'out-mcp:call:2', {'call_id': 'mcp:call:2'})
        capture_claude_code.write_pending(folder, session, 'cli-mcp:call:3', {'call_id': 'mcp:call:3'})
        self.assertTrue(calls.pending_outside(folder, session, 'mcp:call:2'))
        self.assertTrue(calls.pending_cli(folder, session, 'mcp:call:3'))
        old = folder / '.pending' / session / 'out-mcp:call:4.json'
        old.write_text('{}', encoding='utf-8')
        self.assertTrue(calls.pending_outside(folder, session, 'mcp:call:4'))


if __name__ == '__main__':
    unittest.main()
