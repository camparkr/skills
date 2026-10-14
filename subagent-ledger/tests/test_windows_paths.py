"""Controls for Windows-style paths, run on macOS or Linux: what a run touched outside its folder, judged with
Windows paths.

A Windows path counts as absolute when it starts with a drive letter or is a network path (two slashes and a
server), with either slash. It is compared case-insensitively, as Windows compares it. A macOS or Linux path is
judged exactly as before: the old rule is copied here and every case is checked against it.

Run from the skill's folder:  python3 -m unittest tests/test_windows_paths.py
"""

import os
import posixpath
import sys
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
SCRIPTS = HERE.parent / 'skill' / 'scripts'
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

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


if __name__ == '__main__':
    unittest.main()
