"""Tests for Codex's capture, `skill/scripts/capture_codex.py`, and the Codex half of `transcripts.py`.

Each control has a half
that runs on the code as built and must pass, and a half that switches one part off by a patch in
this file and shows the fault. Before the capture existed every test here failed, because the module
it loads was missing.

Fixtures, under fixtures/codex/, with every machine path a placeholder (${CODEX_HOME}, ${WORK},
${OUTSIDE}) that each test fills with a folder of its own:

  * dr3-events.jsonl: the four hook payloads of a live `spawn_agent` dispatch, in the order Codex
    0.142.5 sent them (PreToolUse, PostToolUse, SubagentStart, SubagentStop);
  * dr3-agent-rollout.jsonl and dr3-parent-rollout.jsonl: that run's two rollouts, with instruction
    text and encrypted reasoning cut;
  * p1-events.jsonl: a second live dispatch's payloads, and p1-agent-rollout-at-stop.jsonl and
    p1-agent-rollout-rest.jsonl: its subagent rollout as it stood when SubagentStop fired, and the row
    written after (task_complete, 32 milliseconds later).

No test writes to a real ledger: SUBAGENT_LEDGER_DIR and CODEX_HOME name temporary folders.

Run from the skill's folder:  python3 -m unittest discover -s tests
"""

import contextlib
import importlib.util
import io
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest import mock

HERE = Path(__file__).resolve().parent
SCRIPTS = HERE.parent / 'skill' / 'scripts'
FIXTURES = HERE / 'fixtures' / 'codex'
CAPTURE_PY = SCRIPTS / 'capture_codex.py'
TRANSCRIPTS_PY = SCRIPTS / 'transcripts.py'

DR3_AGENT = '01a11db6-1d6b-76c3-9686-35b19258798f'
DR3_CALL = 'call_yvp5gmmnJjgXdnrGrg3FS8Hj'
P1_AGENT = '01a11f5c-ee5e-76d3-ae6f-47b87c04f968'
PARENT_MODEL = 'gpt-5.5'
UNRECORDED = re.compile(r'^unrecorded \(.+\)$')


def load(path, name):
    """The module at `path`, loaded fresh. A missing file fails the test that needs it, saying so."""
    if not path.is_file():
        raise AssertionError('%s does not exist yet: the code this control tests is not built' % path.name)
    if str(SCRIPTS) not in sys.path:
        sys.path.insert(0, str(SCRIPTS))
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def lines_of(path):
    path = Path(path)
    if not path.is_file():
        return []
    return [json.loads(line) for line in path.read_text(encoding='utf-8').splitlines() if line.strip()]


class World(unittest.TestCase):
    """A ledger folder, a Codex home and a working folder for each test."""

    fields = None

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix='capture-codex-test-'))
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.ledger = self.tmp / 'ledger'
        self.home = self.tmp / 'codex-home'
        self.work = self.tmp / 'work'
        self.outside = self.tmp / 'outside'
        for folder in (self.ledger, self.home, self.work, self.outside):
            folder.mkdir()
        env = {'SUBAGENT_LEDGER_DIR': str(self.ledger), 'CODEX_HOME': str(self.home), 'OPENAI_API_KEY': ''}
        patcher = mock.patch.dict(os.environ, env)
        patcher.start()
        self.addCleanup(patcher.stop)
        if self.fields is not None:
            (self.ledger / 'config.json').write_text(json.dumps({'fields': self.fields}), encoding='utf-8')
        self.capture = load(CAPTURE_PY, 'capture_codex_under_test')
        self.transcripts = self.capture.transcripts

    def fill(self, text):
        return (text.replace('${CODEX_HOME}', str(self.home)).replace('${WORK}', str(self.work))
                .replace('${OUTSIDE}', str(self.outside)))

    def events(self, name):
        return [json.loads(self.fill(line)) for line in
                (FIXTURES / name).read_text(encoding='utf-8').splitlines() if line.strip()]

    def place(self, rows, *fixtures):
        """Write the subagent rollout where SubagentStop says it is, from one or more fixture parts."""
        for row in rows:
            path = (row.get('payload') or {}).get('agent_transcript_path')
            if path:
                Path(path).parent.mkdir(parents=True, exist_ok=True)
                Path(path).write_text(''.join(self.fill((FIXTURES / name).read_text(encoding='utf-8'))
                                              for name in fixtures), encoding='utf-8')
                return Path(path)
        raise AssertionError('no SubagentStop in the fixture names a rollout')

    def feed(self, rows):
        for row in rows:
            self.capture.handle(row['event'], json.dumps(row['payload']), None)

    def records(self):
        found = []
        for path in sorted(self.ledger.glob('*.jsonl')):
            if path.name != 'capture-errors.jsonl':
                found.extend(lines_of(path))
        return found

    def errors(self):
        return lines_of(self.ledger / 'capture-errors.jsonl')

    def dr3(self):
        rows = self.events('dr3-events.jsonl')
        self.place(rows, 'dr3-agent-rollout.jsonl')
        return rows


# ---------------------------------------------------------------------------
# Four recorded payloads give one dispatch, two witnesses and one return
# ---------------------------------------------------------------------------

class CB3_1Dispatch(World):

    def test_the_fixture_is_the_order_codex_sent(self):
        self.assertEqual([row['event'] for row in self.events('dr3-events.jsonl')],
                         ['PreToolUse', 'PostToolUse', 'SubagentStart', 'SubagentStop'])

    def test_c_b3_1_one_dispatch_two_witnesses_one_return_joined_by_call_id(self):
        self.feed(self.dr3())
        self.assertEqual(self.errors(), [])
        kinds = [(line['record'], line.get('event')) for line in self.records()]
        self.assertEqual(kinds, [('dispatch', None), ('witness', 'SubagentStart'),
                                 ('witness', 'SubagentStop'), ('return', None)])
        dispatch, back = self.records()[0], self.records()[-1]
        self.assertEqual(dispatch['call_id'], DR3_CALL)
        self.assertEqual(back['call_id'], DR3_CALL)
        self.assertEqual(back['agent_id'], DR3_AGENT)
        self.assertEqual(dispatch['agent_id'], 'unrecorded (not yet returned)')
        self.assertEqual(back['dispatched_at'], dispatch['dispatched_at'])

    def test_c_b3_1_the_return_comes_at_subagent_stop(self):
        rows = self.dr3()
        self.feed(rows[:3])
        self.assertEqual([line['record'] for line in self.records()], ['dispatch', 'witness'],
                         'PostToolUse fires when the spawn returns, so it writes no return')
        self.feed(rows[3:])
        self.assertEqual(self.records()[-1]['record'], 'return')

    def test_c_b3_1_model_requested_is_not_the_parents_model(self):
        self.feed(self.dr3())
        dispatch = self.records()[0]
        self.assertNotEqual(dispatch['model_requested'], PARENT_MODEL)
        self.assertEqual(dispatch['model_requested'], 'unrecorded (none asked)')

    def test_the_return_reads_the_rollout(self):
        self.feed(self.dr3())
        back = self.records()[-1]
        self.assertEqual(back['model'], 'gpt-5.5')
        self.assertEqual(back['outcome'], 'served')
        self.assertEqual(back['tokens']['input'], 59452 - 41088)
        self.assertEqual(back['tokens']['cache_read'], 41088)
        self.assertEqual(back['tokens']['output'], 215)
        self.assertRegex(back['tokens']['cache_write'], UNRECORDED)

    def test_c_b3_1_control_join_switched_off_gives_an_error_line_not_a_guess(self):
        with mock.patch.object(self.capture, 'store_join', lambda *a, **k: None):
            self.feed(self.dr3())
        self.assertNotIn('return', [line['record'] for line in self.records()],
                         'without the join no return may be guessed')
        reasons = [line['reason'] for line in self.errors()]
        self.assertEqual(len(reasons), 1, reasons)
        self.assertIn('no pending join', reasons[0])


class CB3_1AllFields(World):

    fields = 'all'

    def test_harness_route_auth_and_isolation_under_all(self):
        self.feed(self.dr3())
        dispatch, back = self.records()[0], self.records()[-1]
        self.assertEqual((dispatch['harness'], back['harness']), ('codex', 'codex'))
        self.assertEqual((dispatch['route'], back['route']), ('subagent', 'subagent'))
        self.assertIn('CODEX_HOME', dispatch['auth_route'])
        self.assertIn('OPENAI_API_KEY not set', dispatch['auth_route'])
        self.assertEqual(back['effort'], 'low')
        isolation = back['isolation']
        self.assertEqual(isolation['folder'], str(self.work))
        self.assertIn('a read inside a script it ran is not seen', isolation['limit'])
        outside = json.dumps(isolation['outside'])
        self.assertIn(str(self.outside), outside, 'the read outside the folder is listed')
        self.assertNotIn('cat brief.md', outside, 'a command inside the folder is not')

    def test_the_brief_and_answer_are_not_inline(self):
        self.feed(self.dr3())
        text = (self.ledger / ('%s.jsonl' % self.records()[0]['session'])).read_text(encoding='utf-8')
        self.assertNotIn('read brief.md and reply with only the token', text)
        self.assertNotIn('"kestrel-4417"', text)
        self.assertTrue(any(p.read_text(encoding='utf-8') == 'kestrel-4417'
                            for p in self.ledger.rglob('*.md')))


# ---------------------------------------------------------------------------
# The reader takes the last cumulative value, not a sum
# ---------------------------------------------------------------------------

class CB3_2Reader(unittest.TestCase):

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix='codex-reader-test-'))
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.transcripts = load(TRANSCRIPTS_PY, 'transcripts_codex_under_test')
        self.path = self.tmp / 'rollout.jsonl'
        self.path.write_text((FIXTURES / 'dr3-agent-rollout.jsonl').read_text(encoding='utf-8'),
                             encoding='utf-8')

    def test_c_b3_2_the_last_cumulative_value(self):
        reading = self.transcripts.read(self.path)
        self.assertIsNone(reading['error'])
        self.assertEqual(reading['harness'], 'codex')
        self.assertEqual(reading['models'], ['gpt-5.5'])
        self.assertEqual(reading['tokens']['input'], 18364)
        self.assertEqual(reading['tokens']['cache_read'], 41088)
        self.assertEqual(reading['tokens']['output'], 215)
        self.assertRegex(reading['tokens']['cache_write'], UNRECORDED)
        self.assertEqual(reading['effort'], 'low')

    def test_c_b3_2_control_summing_the_cumulative_values_gives_a_larger_count(self):
        def summed(rows):
            totals = {'input_tokens': 0, 'cached_input_tokens': 0, 'output_tokens': 0}
            for usage in rows:
                for key in totals:
                    totals[key] += usage.get(key, 0)
            return totals
        right = self.transcripts.read(self.path)['tokens']
        with mock.patch.object(self.transcripts, 'codex_usage', summed):
            wrong = self.transcripts.read(self.path)['tokens']
        self.assertGreater(wrong['output'], right['output'])
        self.assertGreater(wrong['cache_read'], right['cache_read'])

    def test_a_continued_rollout_is_unrecorded_not_short(self):
        sessions = self.tmp / 'sessions' / '2026' / '10' / '09'
        sessions.mkdir(parents=True)
        own = sessions / ('rollout-2026-10-09T09-50-36-%s.jsonl' % DR3_AGENT)
        shutil.copyfile(self.path, own)
        (sessions / ('rollout-2026-10-09T10-10-00-%s_01a11eee-0000-7000-8000-000000000000.jsonl'
                     % DR3_AGENT)).write_text('{}\n', encoding='utf-8')
        reading = self.transcripts.read(own)
        self.assertEqual(reading['tokens'], 'unrecorded (the session continues in another rollout)')


# ---------------------------------------------------------------------------
# The rollout is incomplete at SubagentStop, so the read waits on its content
# ---------------------------------------------------------------------------

def split_before_last_token_count(text):
    """The rollout cut before its final counter row: the case where the counters lag the stop."""
    lines = text.splitlines(keepends=True)
    last = max(i for i, line in enumerate(lines) if '"token_count"' in line)
    return ''.join(lines[:last]), ''.join(lines[last:])


class CB3_3Wait(World):

    fields = 'all'

    def full_counters(self):
        return {'input': 38098 - 21248, 'cache_read': 21248, 'output': 104}

    def late(self, path, rest, after):
        def append():
            time.sleep(after)
            with open(path, 'a', encoding='utf-8') as handle:
                handle.write(rest)
        worker = threading.Thread(target=append)
        worker.start()
        self.addCleanup(worker.join)
        return worker

    def test_p1_the_rollout_lacked_task_complete_when_subagent_stop_fired(self):
        at_stop = (FIXTURES / 'p1-agent-rollout-at-stop.jsonl').read_text(encoding='utf-8')
        rest = (FIXTURES / 'p1-agent-rollout-rest.jsonl').read_text(encoding='utf-8')
        self.assertNotIn('task_complete', at_stop)
        self.assertIn('task_complete', rest)

    def test_c_b3_3_the_observed_split_is_read_at_once_and_in_full(self):
        # When SubagentStop fired, the rollout already held the answer and its counter row; only
        # task_complete was missing, and Codex writes that after the hook returns. Waiting for it
        # would never end, so the read must not.
        rows = self.events('p1-events.jsonl')
        self.place(rows, 'p1-agent-rollout-at-stop.jsonl')
        self.feed(rows)
        back = self.records()[-1]
        self.assertEqual(back['record'], 'return')
        for key, value in self.full_counters().items():
            self.assertEqual(back['tokens'][key], value, key)
        self.assertLess(back['tokens']['read_after_seconds'], 5)

    def test_c_b3_3_counters_that_lag_the_stop_are_read_in_full(self):
        rows = self.events('p1-events.jsonl')
        whole = self.fill((FIXTURES / 'p1-agent-rollout-at-stop.jsonl').read_text(encoding='utf-8')
                          + (FIXTURES / 'p1-agent-rollout-rest.jsonl').read_text(encoding='utf-8'))
        first, rest = split_before_last_token_count(whole)
        path = self.place(rows, 'p1-agent-rollout-at-stop.jsonl')
        path.write_text(first, encoding='utf-8')
        self.late(path, rest, 0.4)
        self.feed(rows)
        back = self.records()[-1]
        for key, value in self.full_counters().items():
            self.assertEqual(back['tokens'][key], value, key)
        self.assertGreaterEqual(back['tokens']['read_after_seconds'], 0.3)

    def test_c_b3_3_control_reading_at_once_is_short(self):
        rows = self.events('p1-events.jsonl')
        whole = self.fill((FIXTURES / 'p1-agent-rollout-at-stop.jsonl').read_text(encoding='utf-8')
                          + (FIXTURES / 'p1-agent-rollout-rest.jsonl').read_text(encoding='utf-8'))
        first, rest = split_before_last_token_count(whole)
        path = self.place(rows, 'p1-agent-rollout-at-stop.jsonl')
        path.write_text(first, encoding='utf-8')
        self.late(path, rest, 0.4)
        with mock.patch.object(self.capture.transcripts, 'codex_complete', lambda *a, **k: True):
            self.feed(rows)
        back = self.records()[-1]
        self.assertLess(back['tokens']['output'], self.full_counters()['output'],
                        'read at once, before the last counter row, the count is short')


# ---------------------------------------------------------------------------
# Bad input exits 0, prints nothing and leaves one error line
# ---------------------------------------------------------------------------

class CB3_9BadInput(World):

    def run_capture(self, text, event='PreToolUse'):
        done = subprocess.run([sys.executable, str(CAPTURE_PY), event, '--ledger', str(self.ledger)],
                              input=text, capture_output=True, text=True, timeout=60)
        return done

    def bad_inputs(self):
        no_call = self.events('dr3-events.jsonl')[0]['payload']
        no_call.pop('tool_use_id')
        return [('not JSON', 'this is not json'), ('empty', ''), ('no call id', json.dumps(no_call))]

    def test_c_b3_9_each_exits_0_prints_nothing_and_leaves_one_error_line(self):
        if not CAPTURE_PY.is_file():
            raise AssertionError('capture_codex.py does not exist yet')
        for count, (name, text) in enumerate(self.bad_inputs(), start=1):
            with self.subTest(name=name):
                done = self.run_capture(text)
                self.assertEqual(done.returncode, 0)
                self.assertEqual(done.stdout, '')
                self.assertEqual(len(self.errors()), count)
                self.assertEqual(self.errors()[-1]['harness'], 'codex')
        self.assertEqual(self.records(), [])

    def test_c_b3_9_control_error_lines_switched_off_leave_nothing(self):
        with mock.patch.object(self.capture.ledger, 'error', lambda *a, **k: None):
            for _, text in self.bad_inputs():
                self.capture.handle('PreToolUse', text, None)
        self.assertEqual(self.errors(), [])
        self.assertEqual(self.records(), [])


if __name__ == '__main__':
    unittest.main()
