"""Tests for brief.py: a member's brief, written with its front matter, the opening instruction, the task, the write
set and the return skill's instruction, and stopped by any path that does not resolve (R-6, K-3; TC-5, and V-2's
control).

The ledger folder's config.json names the front matter keys (under `meta.`), a kind map and the return check's
settings, so the brief is written at the keys the capture reads. TC-5's rows are run through the ledger skill's own
capture, on a PreToolUse payload naming the brief, so the test shows what the record makes of the brief. Every
ledger folder and repository is a temporary folder, proved so before anything runs.

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
SCRIPTS = HERE.parent / 'skill' / 'scripts'
SCRIPT = SCRIPTS / 'brief.py'
FIXTURES = HERE / 'fixtures'
BRIEF_FIXTURES = FIXTURES / 'brief'
LEDGER_SCRIPTS = HERE.parent.parent / 'subagent-ledger' / 'skill' / 'scripts'
CAPTURE = LEDGER_SCRIPTS / 'capture_claude_code.py'
INSTRUCTION = HERE.parent.parent / 'subagent-return' / 'skill' / 'references' / 'brief-instruction.md'
SESSION = '0e0e0e0e-1111-4222-8333-555555555555'
PERSONA = BRIEF_FIXTURES / 'personas' / 'builder' / 'builder.md'
PLACEHOLDERS = ('<absolute path>', '<validator>', '<kinds>', '<probability>', '<line>', '<version>')

sys.path.insert(0, str(LEDGER_SCRIPTS))
import capture_claude_code as capture  # noqa: E402


def clean_env():
    env = dict(os.environ)
    for name in ('SUBAGENT_LEDGER_DIR', 'SUBAGENT_LEDGER_SCRIPTS'):
        env.pop(name, None)
    return env


def instruction_block():
    lines = INSTRUCTION.read_text(encoding='utf-8').splitlines()
    start = lines.index('## The instruction')
    begin = next(i for i in range(start, len(lines)) if lines[i].startswith('```'))
    end = next(i for i in range(begin + 1, len(lines)) if lines[i].startswith('```'))
    return '\n'.join(lines[begin + 1:end])


class BriefTests(unittest.TestCase):

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.ledger = self.tmp / 'ledger'
        shutil.copytree(str(BRIEF_FIXTURES / 'ledger'), str(self.ledger))
        self.repo = self.tmp / 'repo'
        self.repo.mkdir()
        subprocess.run(['git', 'init', '-q', str(self.repo)], check=True)
        for path in (self.ledger, self.repo):
            # Where every write lands, proved before anything runs: inside this test's own temporary folder.
            self.assertTrue(str(path.resolve()).startswith(str(Path(tempfile.gettempdir()).resolve())))

    def tearDown(self):
        shutil.rmtree(str(self.tmp), ignore_errors=True)

    def task(self, name):
        text = (BRIEF_FIXTURES / name).read_text(encoding='utf-8').replace('@FIXTURES@', str(FIXTURES))
        path = self.tmp / name
        path.write_text(text, encoding='utf-8')
        return path

    def write(self, out=None, member='m1', attempt='1', persona='builder', persona_file=PERSONA, kind='build',
              task_id='2026-01-15-report-refresh', body='task-plain.md', write_set=('src/export.py', 'tests/'),
              repository=None, pending=None, ledger=None):
        out = out or self.tmp / 'briefs' / ('%s-%s.md' % (member, attempt))
        arguments = ['--out', str(out), '--member', member, '--attempt', attempt, '--persona', persona,
                     '--persona-file', str(persona_file), '--kind', kind, '--task', task_id,
                     '--body', str(self.task(body)), '--ledger', str(ledger or self.ledger)]
        for path in write_set:
            arguments += ['--write-set', path]
        if write_set != ('none',):
            arguments += ['--repository', str(repository or self.repo)]
        if pending:
            arguments += ['--pending', str(BRIEF_FIXTURES / pending)]
        done = subprocess.run([sys.executable, str(SCRIPT)] + arguments, capture_output=True, text=True,
                              env=clean_env(), timeout=60)
        try:
            result = json.loads(done.stdout)
        except ValueError:
            self.fail('no JSON on stdout (exit %s): %s %s' % (done.returncode, done.stdout, done.stderr))
        return done.returncode, result, out

    def dispatch_record(self, prompt):
        payload = {'session_id': SESSION, 'hook_event_name': 'PreToolUse', 'tool_name': 'Agent',
                   'tool_use_id': 'toolu_brief_1', 'cwd': str(self.repo),
                   'tool_input': {'prompt': prompt, 'description': 'a member'}}
        done = subprocess.run([sys.executable, str(CAPTURE), 'PreToolUse', '--ledger', str(self.ledger)],
                              input=json.dumps(payload), capture_output=True, text=True, env=clean_env(), timeout=60)
        self.assertEqual(done.returncode, 0, done.stderr)
        rows = [json.loads(line) for line in (self.ledger / ('%s.jsonl' % SESSION)).read_text(
            encoding='utf-8').splitlines() if line.strip()]
        found = [row for row in rows if row.get('record') == 'dispatch']
        self.assertEqual(len(found), 1, rows)
        return found[0]

    # -- What the brief holds -----------------------------------------------------------------------------------------

    def test_a_brief_carries_its_front_matter_at_the_ledger_s_keys(self):
        code, out, path = self.write()
        self.assertEqual(code, 0, out)
        text = path.read_text(encoding='utf-8')
        meta = capture.frontmatter(text)['meta']
        self.assertEqual(meta, {'persona': 'builder', 'kind': 'making', 'task': '2026-01-15-report-refresh',
                                'member': 'm1', 'attempt': '1'})
        self.assertEqual(out['brief'], str(path))

    def test_the_body_opens_with_the_persona_file_and_memory_index_by_absolute_path(self):
        code, out, path = self.write()
        self.assertEqual(code, 0, out)
        body = text_after_front_matter(path.read_text(encoding='utf-8'))
        first = body.split('\n\n')[0]
        self.assertTrue(first.startswith('Before your first act, read your persona\'s file'), first)
        self.assertIn('`%s`' % PERSONA, first)
        self.assertIn('`%s`' % (PERSONA.parent / 'index.md'), first)

    def test_the_task_then_the_write_set_then_the_instruction_word_for_word(self):
        code, out, path = self.write()
        self.assertEqual(code, 0, out)
        text = path.read_text(encoding='utf-8')
        self.assertIn('as the settled design in `%s/input-present.txt` says' % FIXTURES, text)
        self.assertEqual(capture.write_set_of(text), ['src/export.py', 'tests/'])
        filled = instruction_block().replace('<validator>', '`python3 /opt/checker/validate.py`').replace(
            '<kinds>', 'Markdown (`docs/*.md`, `notes/*.md`)')
        self.assertTrue(text.rstrip('\n').endswith(filled), text[-600:])
        self.assertLess(text.index('## Write set'), text.index('## What your work is checked for'))
        self.assertLess(text.index('settled design'), text.index('## Write set'))
        for placeholder in PLACEHOLDERS:
            self.assertNotIn(placeholder, text)

    def test_a_read_only_member_s_write_set_reads_none(self):
        code, out, path = self.write(write_set=('none',))
        self.assertEqual(code, 0, out)
        self.assertEqual(capture.write_set_of(path.read_text(encoding='utf-8')), ['none'])
        self.assertFalse(capture.is_writer(path.read_text(encoding='utf-8')))

    def test_below_the_line_the_body_says_so_with_the_probability_and_line(self):
        code, out, path = self.write(pending='pending-below-line.json')
        self.assertEqual(code, 0, out)
        text = path.read_text(encoding='utf-8')
        self.assertIn('No persona was found adequate for this part. You were the closest, at 0.1 against a line '
                      'of 0.5\n(definition version 0).', text)
        self.assertLess(text.index('No persona was found adequate'), text.index('## Write set'))
        self.assertEqual(out['below_line'], {'probability': 0.1, 'line': 0.5, 'line_version': 0})

    def test_an_adequate_part_carries_no_below_the_line_sentence(self):
        code, out, path = self.write()
        self.assertEqual(code, 0, out)
        self.assertNotIn('No persona was found adequate', path.read_text(encoding='utf-8'))
        self.assertIsNone(out['below_line'])

    # -- TC-5: the brief on the record --------------------------------------------------------------------------------

    def test_tc5_the_brief_named_first_gives_the_record_its_member_and_attempt(self):
        code, out, path = self.write()
        self.assertEqual(code, 0, out)
        record = self.dispatch_record('Read %s and do what it says. Your persona file is %s.' % (path, PERSONA))
        self.assertEqual(record['member'], 'm1')
        self.assertEqual(record['attempt'], 1)
        self.assertEqual(record['persona-name'], 'builder')
        self.assertEqual(record['act_kind'], 'build')
        self.assertEqual(record['task'], '2026-01-15-report-refresh')

    def test_tc5_likeness_the_persona_file_named_before_the_brief_is_read_as_untriaged(self):
        code, out, path = self.write()
        self.assertEqual(code, 0, out)
        record = self.dispatch_record('Your persona file is %s. Read %s and do what it says.' % (PERSONA, path))
        self.assertEqual(record['member'], 'unrecorded (the first file the prompt names is not a brief: %s)'
                         % PERSONA)
        self.assertIn('kinds_read_from', record['harness_payload'])

    def test_tc5_empty_a_prompt_naming_no_file_records_member_unrecorded(self):
        record = self.dispatch_record('Add a dry-run flag to the export script.')
        self.assertEqual(record['member'], 'unrecorded (the prompt names no file)')

    # -- A path that does not resolve stops the brief (V-2's control) ------------------------------------------------

    def assert_stopped(self, code, out, path, words):
        self.assertEqual(code, 1, out)
        self.assertIn(words, out['error'])
        self.assertFalse(Path(path).exists())

    def test_v2_control_a_persona_file_that_does_not_resolve_stops_the_brief(self):
        missing = BRIEF_FIXTURES / 'personas' / 'ghost' / 'ghost.md'
        code, out, path = self.write(persona_file=missing)
        self.assert_stopped(code, out, path, str(missing))

    def test_a_memory_index_that_does_not_resolve_stops_the_brief(self):
        code, out, path = self.write(persona='orphan', persona_file=BRIEF_FIXTURES / 'personas' / 'orphan' / 'orphan.md')
        self.assert_stopped(code, out, path, str(BRIEF_FIXTURES / 'personas' / 'orphan' / 'index.md'))

    def test_an_input_that_does_not_resolve_stops_the_brief(self):
        code, out, path = self.write(body='task-missing-input.md')
        self.assert_stopped(code, out, path, str(FIXTURES / 'input-missing.txt'))

    def test_a_repository_that_does_not_exist_stops_the_brief(self):
        code, out, path = self.write(repository=self.tmp / 'no-such-repo')
        self.assert_stopped(code, out, path, str(self.tmp / 'no-such-repo'))

    def test_a_write_set_file_to_be_created_need_not_exist(self):
        code, out, path = self.write(write_set=('src/new_module.py',))
        self.assertEqual(code, 0, out)

    # -- What the brief refuses ---------------------------------------------------------------------------------------

    def test_a_write_set_path_from_the_main_checkout_is_refused(self):
        code, out, path = self.write(write_set=(str(self.repo / 'src' / 'export.py'),))
        self.assert_stopped(code, out, path, 'relative to the repository')

    def test_a_write_set_path_leaving_the_repository_is_refused(self):
        code, out, path = self.write(write_set=('../elsewhere/export.py',))
        self.assert_stopped(code, out, path, 'leaves the repository')

    def test_a_task_holding_its_own_write_set_section_is_refused(self):
        code, out, path = self.write(body='task-with-write-set.md')
        self.assert_stopped(code, out, path, '## Write set')

    def test_an_unknown_kind_is_refused(self):
        code, out, path = self.write(kind='poetry')
        self.assert_stopped(code, out, path, 'poetry')

    def test_a_member_id_the_pending_file_name_would_change_is_refused(self):
        code, out, path = self.write(member='m/1', out=self.tmp / 'briefs' / 'odd.md')
        self.assert_stopped(code, out, path, 'm/1')

    def test_a_pending_file_naming_another_persona_is_refused(self):
        code, out, path = self.write(pending='pending-other-persona.json')
        self.assert_stopped(code, out, path, 'cataloguer')

    def test_an_existing_brief_is_never_overwritten(self):
        code, out, path = self.write()
        self.assertEqual(code, 0, out)
        before = path.read_text(encoding='utf-8')
        code, out, _ = self.write(out=path)
        self.assertEqual(code, 1, out)
        self.assertIn('already exists', out['error'])
        self.assertEqual(path.read_text(encoding='utf-8'), before)

    def test_settings_naming_no_validator_stop_the_brief(self):
        bare = self.tmp / 'bare-ledger'
        bare.mkdir()
        code, out, path = self.write(ledger=bare)
        self.assert_stopped(code, out, path, 'validator')


def text_after_front_matter(text):
    end = text.find('\n---', 3)
    return text[end + 4:].lstrip('\n')


if __name__ == '__main__':
    unittest.main()
