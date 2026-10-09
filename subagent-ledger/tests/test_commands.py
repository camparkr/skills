"""Tests for the command splitter, `skill/scripts/commands.py`, through the capture that uses it.

Control C-B6-8. Three commands made the capture's `Bash` route write a false `cli` dispatch when it
split commands with a regular expression: a here-document whose body holds a `claude -p` line, and a
`|` inside quotes, twice. With the splitter, they write nothing, and three true calls still write a
dispatch. The control's other half restores the old split, by a patch in this file, and shows the
false dispatches return. Before the splitter existed these tests failed, because the capture had
no splitter to use and still wrote the false dispatches.

fixtures/claude-code/b2-matcher-events.jsonl holds the PreToolUse payloads recorded for this fault,
with machine paths made placeholders. The first is recorded with `grep -E 'codex exec|gemini -p'`;
its command is replaced here by the form that reproduced the fault, `gemini -p "x"` inside the
quotes. The third is the same payload with its command replaced by `echo 'try: a | claude -p hi'`.
The true calls are the first payload with its command replaced. Each replacement is a
reconstruction, said so here.

Run from the skill's folder:  python3 -m unittest discover -s tests
"""

import importlib.util
import json
import os
import re
import shlex
import shutil
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

HERE = Path(__file__).resolve().parent
SCRIPTS = HERE.parent / 'skill' / 'scripts'
FIXTURES = HERE / 'fixtures' / 'claude-code'
CAPTURE_PY = SCRIPTS / 'capture_claude_code.py'
COMMANDS_PY = SCRIPTS / 'commands.py'

TRUE_CALLS = ('claude -p "x"', 'a && codex exec "y"', 'x=$(claude -p "z")')


def load(path, name):
    if not path.is_file():
        raise AssertionError('%s does not exist yet: the code this control tests is not built' % path.name)
    if str(SCRIPTS) not in sys.path:
        sys.path.insert(0, str(SCRIPTS))
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class OldPart:
    def __init__(self, words):
        self.words = words
        self.program = os.path.basename(words[0]) if words else None
        self.assigned = {}
        self.fed = []


def old_parts(command, skip=None):
    """The capture's split before the splitter: re.split at operators, quotes and here-documents unseen."""
    out = []
    for part in re.split(r'\|\||&&|;|\||\n', command):
        try:
            words = shlex.split(part)
        except ValueError:
            words = part.split()
        while words and (re.match(r'^[A-Za-z_][A-Za-z0-9_]*=', words[0]) or words[0] == 'env'):
            words.pop(0)
        out.append(OldPart(words))
    return out


class World(unittest.TestCase):

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix='commands-test-'))
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.ledger = self.tmp / 'ledger'
        self.ledger.mkdir()
        patcher = mock.patch.dict(os.environ, {'SUBAGENT_LEDGER_DIR': str(self.ledger),
                                               'CLAUDE_CONFIG_DIR': str(self.tmp / 'config')})
        patcher.start()
        self.addCleanup(patcher.stop)
        self.capture = load(CAPTURE_PY, 'capture_claude_code_for_commands_test')

    def payloads(self):
        rows = []
        for line in (FIXTURES / 'b2-matcher-events.jsonl').read_text(encoding='utf-8').splitlines():
            if line.strip():
                text = (line.replace('${CONFIG}', str(self.tmp / 'config')).replace('${WORK}', str(self.tmp))
                        .replace('${TASKROOT}', str(self.tmp / 'tasks')))
                rows.append(json.loads(text))
        return rows

    def with_command(self, command, call_id):
        row = json.loads(json.dumps(self.payloads()[0]))
        row['payload']['tool_input']['command'] = command
        row['payload']['tool_use_id'] = call_id
        return row

    def dispatches(self):
        found = []
        for path in self.ledger.glob('*.jsonl'):
            if path.name == 'capture-errors.jsonl':
                continue
            for line in path.read_text(encoding='utf-8').splitlines():
                row = json.loads(line)
                if row['record'] == 'dispatch':
                    found.append(row['call_id'])
        return found

    def feed(self, rows):
        for row in rows:
            self.capture.handle(row['event'], json.dumps(row['payload']), None)


class CB6_8Splitter(World):

    def test_c_b6_8_the_three_false_dispatch_commands_write_nothing(self):
        rows = self.payloads()
        self.assertEqual([r['payload']['tool_use_id'] for r in rows], ['toolu_grep', 'toolu_heredoc', 'toolu_echo'])
        self.feed(rows)
        self.assertEqual(self.dispatches(), [])

    def test_c_b6_8_true_calls_still_write_a_dispatch(self):
        rows = [self.with_command(command, 'toolu_true_%d' % n) for n, command in enumerate(TRUE_CALLS)]
        self.feed(rows)
        self.assertEqual(sorted(self.dispatches()), ['toolu_true_0', 'toolu_true_1', 'toolu_true_2'])

    def test_c_b6_8_the_capture_splits_through_the_public_module(self):
        commands = load(COMMANDS_PY, 'commands_under_test')
        self.assertTrue(hasattr(self.capture, 'commands'), 'the capture imports the splitter')
        self.assertEqual(os.path.realpath(self.capture.commands.__file__), os.path.realpath(commands.__file__))

    def test_c_b6_8_control_with_the_old_split_restored_the_false_dispatches_return(self):
        with mock.patch.object(self.capture.commands, 'parts', old_parts):
            self.feed(self.payloads())
        self.assertEqual(sorted(self.dispatches()), ['toolu_echo', 'toolu_grep', 'toolu_heredoc'])


class Parts(unittest.TestCase):
    """The splitter's own rule, on the cases the capture and the sorter rely on."""

    def setUp(self):
        self.commands = load(COMMANDS_PY, 'commands_parts_under_test')

    def programs(self, command, **kwargs):
        return [part.program for part in self.commands.parts(command, **kwargs) if part.words]

    def test_operators_outside_quotes_split(self):
        self.assertEqual(self.programs('a ; b && c || d | e & f\ng'), list('abcdefg'))

    def test_operators_inside_quotes_do_not(self):
        self.assertEqual(self.programs('echo "a | b; c && d"'), ['echo'])
        self.assertEqual(self.programs("grep -E 'x|y' f"), ['grep'])

    def test_a_here_document_body_is_set_aside_and_kept(self):
        parts = [p for p in self.commands.parts("cat > f <<'EOF'\nclaude -p x\nEOF\nls") if p.words]
        self.assertEqual([p.program for p in parts], ['cat', 'ls'])
        self.assertEqual(parts[0].fed, ['claude -p x'])

    def test_a_command_substitution_is_its_own_part(self):
        self.assertIn('claude', self.programs('x=$(claude -p "y")'))
        self.assertIn('claude', self.programs('echo $(claude -p z) done'))

    def test_assignments_env_and_listed_words_are_passed_over(self):
        parts = [p for p in self.commands.parts('A=1 env B=2 nohup claude -p x') if p.words]
        self.assertEqual(parts[0].program, 'claude')
        self.assertEqual(parts[0].assigned, {'A': '1', 'B': '2'})
        self.assertEqual(self.programs('nohup claude -p x', skip=()), ['nohup'])

    def test_the_program_is_the_base_name(self):
        self.assertEqual(self.programs('/usr/local/bin/claude -p x'), ['claude'])


if __name__ == '__main__':
    unittest.main()
