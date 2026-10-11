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
    written after (task_complete, 32 milliseconds later);
  * q16-agent-rollout-at-stop.jsonl: reconstructed. A subagent rollout in the row shapes the Codex app
    (0.162.x) had written when SubagentStop fired in Q16's second live run, every value made up: the
    answer as an `item_completed` AgentMessage and a `final_answer` message, then the counter row, and no
    `task_complete`.

The shapes a later Codex sends (LaterShapes) are built from these fixtures with their values made up.

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


class FurtherStop(World):
    """A stop after the agent's call has returned writes a witness line and no error line; a stop for an
    agent the ledger has never named still writes the error line."""

    def test_a_further_stop_after_the_return_is_a_witness_line_only(self):
        rows = self.dr3()
        self.feed(rows + [rows[-1]])
        self.assertEqual(self.errors(), [])
        stops = [line for line in self.records() if line.get('event') == 'SubagentStop']
        self.assertEqual(len(stops), 2)
        self.assertEqual([line['record'] for line in self.records()].count('return'), 1)

    def test_a_stop_for_an_agent_the_ledger_never_named_is_an_error_line(self):
        rows = self.dr3()
        stop = json.loads(json.dumps(rows[-1]).replace(DR3_AGENT, '01a10000-0000-7000-8000-000000000b10'))
        self.feed(rows + [stop])
        reasons = [line['reason'] for line in self.errors()]
        self.assertEqual(len(reasons), 1, reasons)
        self.assertIn('no pending join for agent 01a10000-0000-7000-8000-000000000b10', reasons[0])

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

    def test_counters_that_lag_the_stop_are_unrecorded_never_waited_for(self):
        # No hook waits on anything the harness does after the hook returns: counters the rollout does not
        # yet hold are unrecorded, and the return is written at once with the payload's answer.
        rows = self.events('p1-events.jsonl')
        whole = self.fill((FIXTURES / 'p1-agent-rollout-at-stop.jsonl').read_text(encoding='utf-8')
                          + (FIXTURES / 'p1-agent-rollout-rest.jsonl').read_text(encoding='utf-8'))
        first, rest = split_before_last_token_count(whole)
        path = self.place(rows, 'p1-agent-rollout-at-stop.jsonl')
        path.write_text(first, encoding='utf-8')
        started = time.monotonic()
        self.feed(rows)
        self.assertLess(time.monotonic() - started, 5)
        back = self.records()[-1]
        self.assertEqual(back['record'], 'return')
        self.assertRegex(back['tokens'], UNRECORDED)

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


# ---------------------------------------------------------------------------
# Codex 0.162.1's tool names: Agent and Bash, beside spawn_agent and exec_command
# ---------------------------------------------------------------------------

class NewToolNames(World):
    """The same recorded payloads with the tools named as Codex 0.162.1 names them in hook events."""

    fields = 'all'

    def renamed(self):
        rows = self.dr3()
        for row in rows:
            if row['event'] in ('PreToolUse', 'PostToolUse'):
                row['payload']['tool_name'] = 'Agent'
        return rows

    def test_an_agent_dispatch_is_recorded_and_joined(self):
        self.feed(self.renamed())
        self.assertEqual(self.errors(), [])
        kinds = [line['record'] for line in self.records()]
        self.assertEqual(kinds, ['dispatch', 'witness', 'witness', 'return'])
        self.assertEqual(self.records()[-1]['call_id'], DR3_CALL)
        self.assertEqual(self.records()[-1]['agent_id'], DR3_AGENT)

    def test_the_stop_payloads_model_stays_in_harness_payload(self):
        rows = self.renamed()
        rows[-1]['payload']['model'] = 'a-model-the-rollout-does-not-name'
        self.feed(rows)
        back = self.records()[-1]
        self.assertEqual(back['model'], 'gpt-5.5')
        self.assertEqual(back['harness_payload']['model'], 'a-model-the-rollout-does-not-name')

    def test_a_bash_command_is_read_at_tool_input_command(self):
        payload = {'session_id': 'shell-session', 'turn_id': 't', 'cwd': str(self.work), 'model': PARENT_MODEL,
                   'hook_event_name': 'PreToolUse', 'tool_name': 'Bash', 'tool_use_id': 'call_bash_model',
                   'tool_input': {'command': 'claude -p --model haiku "Reply with the word ok"'}}
        self.capture.handle('PreToolUse', json.dumps(payload), None)
        done = dict(payload, hook_event_name='PostToolUse',
                    tool_response='Chunk ID: x\nWall time: 1 seconds\nProcess exited with code 0\nOutput:\nok\n')
        self.capture.handle('PostToolUse', json.dumps(done), None)
        found = [(line['record'], line['route']) for line in self.records() if line.get('call_id') == 'call_bash_model']
        self.assertEqual(found, [('dispatch', 'cli'), ('return', 'cli')])
        self.assertEqual(self.records()[-1]['outcome'], 'served')

    def test_both_names_are_listed_for_codex(self):
        entry = json.loads((SCRIPTS / 'subagent-tools.json').read_text(encoding='utf-8'))['harnesses']['codex']
        self.assertEqual(sorted(set(entry['tools']) - set(entry['message_tools'])),
                         ['Agent', 'collaborationspawn_agent', 'spawn_agent'])
        self.assertEqual(sorted(entry['shell_tools']), ['Bash', 'exec_command'])


class StopTurnById(World):
    """The stop's turn is the one whose task_started row carries the stop's turn_id."""

    def later_turn(self, path):
        with Path(path).open('a', encoding='utf-8') as out:
            out.write(json.dumps({'type': 'event_msg', 'payload': {'type': 'task_started', 'turn_id': 'later'}}) + '\n')

    def test_a_later_turn_begun_does_not_hide_the_stops_own(self):
        rows = self.dr3()
        path = rows[-1]['payload']['agent_transcript_path']
        self.later_turn(path)
        turn = rows[-1]['payload']['turn_id']
        self.assertTrue(self.transcripts.codex_complete(path, 'kestrel-4417', turn))

    def test_without_the_turn_id_the_last_turn_is_read(self):
        rows = self.dr3()
        path = rows[-1]['payload']['agent_transcript_path']
        self.later_turn(path)
        self.assertFalse(self.transcripts.codex_complete(path, 'kestrel-4417'))
        self.assertFalse(self.transcripts.codex_complete(path, 'kestrel-4417', 'a turn no row carries'))

    def test_the_turn_ends_at_the_next_task_started(self):
        rows = self.dr3()
        path = rows[-1]['payload']['agent_transcript_path']
        text = Path(path).read_text(encoding='utf-8').splitlines()
        first = rows[-1]['payload']['turn_id']
        cut = [json.loads(line) for line in text[:2]]
        cut.append({'type': 'event_msg', 'payload': {'type': 'task_started', 'turn_id': 'second'}})
        cut.extend(json.loads(line) for line in text[2:])
        Path(path).write_text(''.join(json.dumps(row) + '\n' for row in cut), encoding='utf-8')
        self.assertFalse(self.transcripts.codex_complete(path, 'kestrel-4417', first),
                         'the answer stands in the next turn, not the stop\'s own')
        self.assertTrue(self.transcripts.codex_complete(path, 'kestrel-4417', 'second'))



class LaterShapes(World):
    """Payloads in the shapes a later Codex (0.162.x) sends, every value made up: the shell result as text with
    a JSON object after 'Output:', a spawn whose response holds only task_name, a subagent whose spawn sent no
    event, an encrypted brief, and a tool event the capture does not record."""

    fields = 'all'
    HEADER = 'Script completed\nWall time 0.4 seconds\nOutput:\n'

    def shell(self, call_id, response):
        payload = {'session_id': 'shell-session', 'turn_id': 't', 'cwd': str(self.work), 'model': PARENT_MODEL,
                   'hook_event_name': 'PreToolUse', 'tool_name': 'Bash', 'tool_use_id': call_id,
                   'tool_input': {'command': 'opencode run "Reply with the word ok"'}}
        self.capture.handle('PreToolUse', json.dumps(payload), None)
        done = dict(payload, hook_event_name='PostToolUse', tool_response=response)
        self.capture.handle('PostToolUse', json.dumps(done), None)
        found = [line for line in self.records() if line.get('call_id') == call_id]
        self.assertEqual([line['record'] for line in found], ['dispatch', 'return'])
        return found[-1]

    def result(self, code, output):
        return json.dumps({'chunk_id': 'x', 'wall_time_seconds': 0.4, 'exit_code': code,
                           'original_token_count': 1, 'output': output})

    def test_a_non_zero_exit_code_in_the_json_is_failed(self):
        back = self.shell('call_exit1', self.HEADER + self.result(1, 'Error: no such provider'))
        self.assertEqual(back['outcome'], 'failed')
        self.assertEqual(back['harness_payload']['tool_response']['exit_code'], 1)

    def test_a_zero_exit_code_in_the_json_is_served(self):
        back = self.shell('call_exit0', self.HEADER + self.result(0, 'ok'))
        self.assertEqual(back['outcome'], 'served')

    def test_a_list_of_text_items_is_read_the_same(self):
        items = [{'type': 'input_text', 'text': self.HEADER}, {'type': 'input_text', 'text': self.result(1, 'x')}]
        self.assertEqual(self.shell('call_list', items)['outcome'], 'failed')
        items = [{'type': 'input_text', 'text': self.HEADER}, {'type': 'input_text', 'text': self.result(0, 'ok')}]
        self.assertEqual(self.shell('call_list_ok', items)['outcome'], 'served')

    def test_no_exit_code_is_failed_unreadable_never_served(self):
        back = self.shell('call_nocode', self.HEADER + 'ok\n')
        self.assertEqual(back['outcome'], 'failed')
        self.assertEqual(back['outcome_reason'], {'class': 'unreadable', 'text': 'the response carries no exit code'})

    def control_rows(self, start_first=False, message=None):
        rows = self.dr3()
        for row in rows[:2]:
            row['payload']['tool_input'] = dict(row['payload']['tool_input'], task_name='a_task', fork_turns='none')
            if message is not None:
                row['payload']['tool_input']['message'] = message
        rows[1]['payload']['tool_response'] = json.dumps({'task_name': 'a_task'})
        return [rows[0], rows[2], rows[1], rows[3]] if start_first else rows

    def check_joined(self):
        self.assertEqual(self.errors(), [])
        found = [line for line in self.records() if line.get('call_id') == DR3_CALL]
        self.assertEqual([line['record'] for line in found], ['dispatch', 'return'])
        self.assertEqual(found[-1]['agent_id'], DR3_AGENT)
        self.assertEqual(found[-1]['harness_payload']['post_tool_use_response'], {'task_name': 'a_task'})
        return found

    def test_a_spawn_whose_response_names_no_agent_is_joined_at_subagent_start(self):
        self.feed(self.control_rows())
        self.check_joined()

    def test_the_join_holds_when_subagent_start_comes_before_the_spawns_response(self):
        self.feed(self.control_rows(start_first=True))
        self.check_joined()

    def test_switched_off_without_the_wait_for_a_start_the_spawn_has_no_return_joined(self):
        with mock.patch.object(self.capture, 'oldest_waiting', lambda *a: None):
            self.feed(self.control_rows())
        found = [line for line in self.records() if line.get('call_id') == DR3_CALL]
        self.assertEqual([line['record'] for line in found], ['dispatch'])

    def test_a_subagent_whose_spawn_sent_no_event_is_dispatched_from_its_start(self):
        rows = self.dr3()
        self.feed(rows[2:])
        self.assertEqual(self.errors(), [])
        found = [line for line in self.records() if line.get('call_id') == DR3_AGENT]
        self.assertEqual([line['record'] for line in found], ['dispatch', 'return'])
        none_sent = 'unrecorded (the harness sent no dispatch event for this subagent)'
        self.assertEqual(found[0]['brief_path'], none_sent)
        self.assertEqual(found[0]['brief_source'], none_sent)
        self.assertEqual(found[-1]['agent_id'], DR3_AGENT)

    def test_a_further_start_of_that_agent_writes_no_second_dispatch(self):
        rows = self.dr3()
        self.feed(rows[2:] + rows[2:])
        self.assertEqual([line['record'] for line in self.records()
                          if line.get('call_id') == DR3_AGENT].count('dispatch'), 1)

    def test_an_encrypted_brief_is_kept_and_named_encrypted(self):
        import base64
        token = base64.urlsafe_b64encode(bytes([0x80]) + (1791683558).to_bytes(8, 'big') +
                                         bytes(range(1, 113))).decode('ascii')
        self.assertTrue(self.capture.is_ciphertext(token))
        self.assertFalse(self.capture.is_ciphertext('Reply with only the word kestrel.'))
        self.feed(self.control_rows(message=token))
        sent = self.check_joined()[0]
        self.assertEqual(sent['brief_source'], 'unrecorded (the harness passed the brief encrypted)')
        kept = [path for path in self.ledger.rglob('*.md') if path.read_text(encoding='utf-8') == token]
        self.assertEqual(len(kept), 1)

    def test_a_tool_event_not_recorded_writes_one_error_line(self):
        payload = {'session_id': 'tool-session', 'turn_id': 't', 'cwd': str(self.work), 'model': PARENT_MODEL,
                   'hook_event_name': 'PostToolUse', 'tool_name': 'wait_agent', 'tool_use_id': 'call_wait',
                   'tool_input': {'timeout_ms': 1000}, 'tool_response': '{}'}
        self.capture.handle('PostToolUse', json.dumps(payload), None)
        errors = self.errors()
        self.assertEqual(len(errors), 1, errors)
        self.assertEqual(errors[0]['stage'], 'payload')
        self.assertEqual(errors[0]['reason'], 'PostToolUse on wait_agent: not a tool this capture records')
        self.assertEqual(errors[0]['payload_keys'], sorted(payload))
        self.assertEqual(self.records(), [])


class Q16Rollout(World):
    """The stop read against a rollout in the shapes the Codex app (0.162.x) had written when SubagentStop fired."""

    fields = 'all'
    TURN = '01a10000-0000-7000-8000-00000000q2l1'

    def rows(self):
        rows = self.dr3()
        stop = rows[-1]['payload']
        stop['turn_id'] = self.TURN
        stop['last_assistant_message'] = 'kestrel-q2l'
        Path(stop['agent_transcript_path']).write_text(
            self.fill((FIXTURES / 'q16-agent-rollout-at-stop.jsonl').read_text(encoding='utf-8')), encoding='utf-8')
        return rows

    def test_the_answer_forms_of_0162_complete_the_turn(self):
        rows = self.rows()
        path = rows[-1]['payload']['agent_transcript_path']
        self.assertTrue(self.transcripts.codex_complete(path, 'kestrel-q2l', self.TURN))

    def test_the_return_is_written_at_once_with_the_turns_counters(self):
        started = time.monotonic()
        self.feed(self.rows())
        self.assertLess(time.monotonic() - started, 5)
        back = self.records()[-1]
        self.assertEqual(back['record'], 'return')
        self.assertEqual(back['model'], 'stand-in-rollout-model')
        self.assertEqual({k: back['tokens'][k] for k in ('input', 'cache_read', 'output')},
                         {'input': 8000, 'cache_read': 12000, 'output': 6})
        self.assertEqual(self.errors(), [])

    def test_control_reading_only_agent_message_events_leaves_the_counters_unrecorded(self):
        old = self.transcripts.codex_answer_text
        only_events = lambda row: old(row) if (row.get('payload') or {}).get('type') == 'agent_message' else None
        with mock.patch.object(self.transcripts, 'codex_answer_text', only_events):
            self.feed(self.rows())
        self.assertRegex(self.records()[-1]['tokens'], UNRECORDED)


if __name__ == '__main__':
    unittest.main()
