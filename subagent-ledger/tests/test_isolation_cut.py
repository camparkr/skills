"""Fix note FN-16, second part: each command `isolation` lists is cut to its first 200 characters.

The cut keeps a record's outside list in proportion: a long here-document is listed by its first 200 characters,
its full length given as `command_chars` where it was cut, and `paths` is kept whole, so every outside path is
still named. The transcript named by `read_from` holds the full command. No record these tests write is over
64 KB (65,536 bytes as one JSON line; test_handback_turns.HandbackLane checks every line at cleanup), and one
turn here runs forty commands of 2,000 characters, which uncut would pass that.

Run from the skill's folder:  python3 -m unittest tests/test_isolation_cut.py
"""

import sys
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

import test_capture_claude_code as base  # noqa: E402
from test_handback_turns import MESSAGE_IDS, HandbackLane  # noqa: E402


class SizeLimit(HandbackLane):
    """Forty outside commands of 2,000 characters in the second turn: about 80 KB uncut."""

    def commands_of(self, turn):
        if turn != 2:
            return super().commands_of(turn)
        return ['cat /elsewhere/long-%02d.md && echo %s' % (at, 'x' * 1970) for at in range(40)]

    def test_fn16_no_record_passes_64_kb(self):
        self.run_lane()
        back = self.returns()[MESSAGE_IDS[2]]
        self.assertEqual(len(back['isolation']['outside']), 40)
        for entry in back['isolation']['outside']:
            self.assertEqual(len(entry['command']), 200)
        # check_record_size, run at cleanup, holds every line of the ledger to the limit.


class CutKeptToItsRule(unittest.TestCase):

    def setUp(self):
        self.transcripts = base.load(base.TRANSCRIPTS_PY, 'transcripts_under_test_fn16')

    def listed(self, command):
        reading = {'path': 'x.jsonl', 'cwd': '/work/run',
                   'tool_uses': [{'name': 'Bash', 'input': {'command': command}}]}
        found = self.transcripts.isolation(reading)['outside']
        self.assertEqual(len(found), 1)
        return found[0]

    def command(self, length):
        head = 'cat /elsewhere/notes.md '
        return head + 'y' * (length - len(head))

    def test_fn16_a_command_of_201_characters_is_cut_and_carries_its_length(self):
        command = self.command(201)
        entry = self.listed(command)
        self.assertEqual(entry['command'], command[:200])
        self.assertEqual(entry['command_chars'], 201)
        self.assertEqual(entry['paths'], ['/elsewhere/notes.md'])

    def test_fn16_a_command_of_200_characters_is_kept_whole(self):
        command = self.command(200)
        entry = self.listed(command)
        self.assertEqual(entry['command'], command)
        self.assertNotIn('command_chars', entry)
        self.assertEqual(entry['paths'], ['/elsewhere/notes.md'])

    def test_fn16_a_path_past_the_cut_is_still_listed_whole(self):
        command = 'echo %s /elsewhere/after-the-cut.md' % ('z' * 300)
        entry = self.listed(command)
        self.assertEqual(entry['paths'], ['/elsewhere/after-the-cut.md'])
        self.assertEqual(entry['command_chars'], len(command))

    def test_fn16_each_limit_text_says_so(self):
        opencode = base.load(base.SCRIPTS / 'capture_opencode.py', 'capture_opencode_under_test_fn16')
        for text in (self.transcripts.ISOLATION_LIMIT, self.transcripts.CODEX_LIMIT, opencode.LIMIT):
            self.assertIn('200 characters', text)
            self.assertIn('command_chars', text)


if __name__ == '__main__':
    unittest.main()
