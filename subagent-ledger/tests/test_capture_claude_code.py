"""Tests for Claude Code's capture, `skill/scripts/capture_claude_code.py`, and its transcript reader.

Each control has two halves. One runs on the capture as built and must pass. The
other switches one part of the capture off, by a patch in this file, and checks that the fault then
shows: a control that cannot fail proves nothing. Before the capture existed every test here failed,
because the module it loads was missing.

The payload fixtures under fixtures/claude-code/ are hook payloads captured from real `claude -p`
sessions, with every machine path replaced by a placeholder (${CONFIG}, ${WORK}, ${TASKROOT}) that
each test fills with a folder of its own. The subagent transcripts beside them are those sessions'
own, less their attachment rows. streamed-agent.jsonl is built from one of them: one message
written on three rows while it streamed, its output counter reading 1, 1 and 206.

No test writes to a real ledger: SUBAGENT_LEDGER_DIR and CLAUDE_CONFIG_DIR name temporary folders.

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
import unittest
from pathlib import Path
from unittest import mock

HERE = Path(__file__).resolve().parent
SCRIPTS = HERE.parent / 'skill' / 'scripts'
FIXTURES = HERE / 'fixtures' / 'claude-code'
CAPTURE_PY = SCRIPTS / 'capture_claude_code.py'
TRANSCRIPTS_PY = SCRIPTS / 'transcripts.py'

FOREGROUND_AGENT = 'a58f08dad7bb00cb6'
BACKGROUND_AGENT = 'a255c210648a689e4'
LANE_AGENT = 'ad2b6f68fbc67bdfa'
PLANTED = 'planted-key-value-0042'
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
    """A ledger folder, a Claude Code configuration folder and a working folder for each test."""

    fields = None

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix='capture-claude-code-test-'))
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.ledger = self.tmp / 'ledger'
        self.config = self.tmp / 'config'
        self.work = self.tmp / 'work'
        self.tasks = self.tmp / 'tasks'
        for folder in (self.ledger, self.config, self.work, self.tasks):
            folder.mkdir()
        env = {'SUBAGENT_LEDGER_DIR': str(self.ledger), 'CLAUDE_CONFIG_DIR': str(self.config)}
        for name in ('ANTHROPIC_API_KEY', 'CLAUDE_CODE_OAUTH_TOKEN', 'ANTHROPIC_AUTH_TOKEN',
                     'CLAUDE_CODE_USE_BEDROCK', 'CLAUDE_CODE_USE_VERTEX'):
            env[name] = ''
        patcher = mock.patch.dict(os.environ, env)
        patcher.start()
        self.addCleanup(patcher.stop)
        if self.fields is not None:
            (self.ledger / 'config.json').write_text(json.dumps({'fields': self.fields}), encoding='utf-8')
        self.capture = load(CAPTURE_PY, 'capture_claude_code_under_test')
        self.transcripts = self.capture.transcripts
        self.ledger_module = self.capture.ledger

    # -- fixtures --------------------------------------------------------------------------------

    def fill(self, text):
        return (text.replace('${CONFIG}', str(self.config)).replace('${WORK}', str(self.work))
                .replace('${TASKROOT}', str(self.tasks)))

    def events(self, name):
        return [json.loads(self.fill(line)) for line in
                (FIXTURES / name).read_text(encoding='utf-8').splitlines() if line.strip()]

    def place_transcript(self, fixture, event_rows):
        """Put a subagent transcript where its SubagentStop payload says it is."""
        for row in event_rows:
            path = (row.get('payload') or {}).get('agent_transcript_path')
            if path:
                Path(path).parent.mkdir(parents=True, exist_ok=True)
                Path(path).write_text(self.fill((FIXTURES / fixture).read_text(encoding='utf-8')),
                                      encoding='utf-8')
                return Path(path)
        raise AssertionError('no SubagentStop in the fixture names a transcript')

    def feed(self, rows):
        for row in rows:
            self.capture.handle(row['event'], json.dumps(row['payload']), None)

    def records(self, session=None):
        found = []
        for path in sorted(self.ledger.glob('*.jsonl')):
            if path.name == 'capture-errors.jsonl':
                continue
            found.extend(lines_of(path))
        return found

    def errors(self):
        return lines_of(self.ledger / 'capture-errors.jsonl')

    def kinds(self):
        return [(line['record'], line.get('event')) for line in self.records()]

    def every_byte_under_the_ledger(self):
        text = []
        for path in self.ledger.rglob('*'):
            if path.is_file():
                text.append(path.read_text(encoding='utf-8', errors='ignore'))
        return '\n'.join(text)

    def foreground(self):
        rows = self.events('foreground-events.jsonl')
        self.place_transcript('foreground-agent.jsonl', rows)
        (self.work / 'brief.md').write_text('q1-probe-brief: reply with the word "received" and nothing else.\n',
                                           encoding='utf-8')
        return rows


# ---------------------------------------------------------------------------
# A foreground call
# ---------------------------------------------------------------------------

class CB2_1Foreground(World):

    def test_c_b2_1_one_dispatch_two_witnesses_one_return_joined(self):
        self.feed(self.foreground())
        self.assertEqual(self.errors(), [])
        self.assertEqual([k for k, _ in self.kinds()], ['dispatch', 'witness', 'witness', 'return'])
        dispatch, start, stop, back = self.records()
        self.assertEqual((start['event'], stop['event']), ('SubagentStart', 'SubagentStop'))
        self.assertEqual(back['call_id'], dispatch['call_id'])
        self.assertEqual(back['agent_id'], FOREGROUND_AGENT)
        self.assertEqual(start['agent_id'], FOREGROUND_AGENT)
        self.assertEqual(back['dispatched_at'], dispatch['dispatched_at'])
        self.assertEqual(back['outcome'], 'served')
        self.assertEqual(back['model'], 'claude-haiku-5-5')
        self.assertEqual(back['tokens'], {'input': 4, 'cache_write': 24046, 'cache_read': 22442,
                                          'output': 165})
        self.assertEqual(list((self.ledger / '.pending').rglob('*.json')), [],
                         'pending files are removed when the return is written')

    def test_c_b2_1_dispatch_agent_id_carries_the_v35_wording(self):
        self.feed(self.foreground())
        self.assertEqual(self.records()[0]['agent_id'], 'unrecorded (not yet returned)')

    def test_c_b2_1_control_join_switched_off_leaves_a_return_with_no_dispatch(self):
        original = self.capture.post_agent

        def unjoined(payload, folder, held):
            # The join switched off: the return takes the agent id where the call id belongs.
            held.call_id = (payload.get('tool_response') or {}).get('agentId')
            return original(payload, folder, held)
        with mock.patch.object(self.capture, 'post_agent', unjoined):
            self.feed(self.foreground())
        dispatches = set(r['call_id'] for r in self.records() if r['record'] == 'dispatch')
        back = [r for r in self.records() if r['record'] == 'return'][0]
        self.assertNotIn(back['call_id'], dispatches, 'the check sees a return with no dispatch')


# ---------------------------------------------------------------------------
# A background call
# ---------------------------------------------------------------------------

class CB2_2Background(World):

    def background(self):
        rows = self.events('background-events.jsonl')
        self.place_transcript('background-agent.jsonl', rows)
        return rows

    def test_the_fixture_is_the_background_order(self):
        rows = self.events('background-events.jsonl')
        self.assertEqual([r['event'] for r in rows],
                         ['PreToolUse', 'SubagentStart', 'PostToolUse', 'SubagentStop'])
        self.assertNotIn('usage', rows[2]['payload']['tool_response'])

    def test_c_b2_2_the_return_comes_at_subagent_stop_joined_through_the_pending_file(self):
        self.feed(self.background())
        self.assertEqual(self.errors(), [])
        self.assertEqual([k for k, _ in self.kinds()], ['dispatch', 'witness', 'witness', 'return'])
        dispatch, back = self.records()[0], self.records()[-1]
        self.assertEqual(back['call_id'], dispatch['call_id'])
        self.assertEqual(back['agent_id'], BACKGROUND_AGENT)
        self.assertEqual(back['outcome'], 'served')
        self.assertEqual(back['model'], 'claude-haiku-5-5')
        self.assertIsInstance(back['tokens']['output'], int)

    def test_c_b2_2_control_pending_join_switched_off_gives_an_error_line_not_a_guess(self):
        with mock.patch.object(self.capture, 'write_join', lambda *a, **k: None):
            self.feed(self.background())
        self.assertNotIn('return', [k for k, _ in self.kinds()], 'no guessed record')
        reasons = [e['reason'] for e in self.errors()]
        self.assertTrue(any('no pending join' in r for r in reasons), reasons)


class FurtherStop(World):
    """A background agent resumed after its call returned can stop once more than it was called. With
    nothing pending and a call to the agent already on the ledger, the stop is a witness line and no
    error line; a stop for an agent the ledger has never named is still an error line."""

    def background(self):
        rows = self.events('background-events.jsonl')
        self.place_transcript('background-agent.jsonl', rows)
        return rows

    def test_a_further_stop_after_the_return_is_a_witness_line_only(self):
        rows = self.background()
        self.feed(rows + [rows[-1]])
        self.assertEqual(self.errors(), [])
        self.assertEqual([k for k, _ in self.kinds()], ['dispatch', 'witness', 'witness', 'return', 'witness'])

    def test_a_stop_for_an_agent_the_ledger_never_named_is_an_error_line(self):
        rows = self.background()
        stop = json.loads(json.dumps(rows[-1]).replace(BACKGROUND_AGENT, 'a0b10000000000001'))
        self.feed(rows + [stop])
        reasons = [e['reason'] for e in self.errors()]
        self.assertEqual(len(reasons), 1, reasons)
        self.assertTrue(reasons[0].startswith('no pending join for background agent a0b10000000000001:'), reasons)

    def test_a_ledger_that_cannot_be_read_keeps_the_error_line_with_the_read_error(self):
        rows = self.background()
        self.feed(rows)
        with mock.patch.object(self.capture, 'agent_called', lambda *a: (False, 'PermissionError: planted')):
            self.feed([rows[-1]])
        reasons = [e['reason'] for e in self.errors()]
        self.assertEqual(len(reasons), 1, reasons)
        self.assertIn('could not be read to find an earlier call to it: PermissionError: planted', reasons[0])

class StopAfterResume(World):
    """A stop read after the agent was resumed, when the resumed run is already in the same transcript: its
    final request is not this stop's. The wait still ends, and the counters are this stop's turn's."""

    LATER = [{'type': 'user', 'message': {'role': 'user', 'content': 'Go on, please.'}},
             {'type': 'assistant', 'message': {
                 'id': 'msg_later_run', 'role': 'assistant', 'model': 'claude-haiku-5-5', 'stop_reason': 'end_turn',
                 'content': [{'type': 'text', 'text': 'A later answer.'}],
                 'usage': {'input_tokens': 7, 'cache_creation_input_tokens': 11, 'cache_read_input_tokens': 13,
                           'output_tokens': 17}}}]

    def resumed(self):
        rows = self.events('background-events.jsonl')
        path = self.place_transcript('background-agent.jsonl', rows)
        first = self.transcripts.read(path)['tokens']
        with open(path, 'a', encoding='utf-8') as handle:
            for row in self.LATER:
                handle.write(json.dumps(row) + '\n')
        return rows, first

    def feed_once(self, rows):
        """Feed the rows with the wait's sleep made to stop the capture; returns how often it slept."""
        slept = []

        def sleep(seconds):
            slept.append(seconds)
            raise KeyboardInterrupt('the wait did not end at its first look')

        with mock.patch.object(self.capture.time, 'sleep', sleep):
            try:
                self.feed(rows)
            except KeyboardInterrupt:
                pass
        return slept

    def test_the_first_turn_is_read_though_a_resumed_run_follows_it(self):
        rows, first = self.resumed()
        self.assertEqual(self.feed_once(rows), [])
        back = self.records()[-1]
        self.assertEqual(back['record'], 'return')
        self.assertEqual(dict((k, back['tokens'][k]) for k in first), first)
        self.assertEqual(self.errors(), [])

    def test_control_without_the_turn_check_the_wait_does_not_end(self):
        rows, first = self.resumed()
        with mock.patch.object(self.capture, 'answer_in_turn', lambda *a: None):
            self.assertNotEqual(self.feed_once(rows), [])
        self.assertNotIn('return', [line['record'] for line in self.records()])


class PendingSwept(World):
    """A stop keeps a pending file only while its agent's call has no return record, and a return takes the
    pending files for its call and agent with it."""

    def pending(self):
        return sorted(p.name for p in (self.ledger / '.pending').rglob('*.json'))

    def test_a_foreground_call_stopped_twice_leaves_no_pending_file(self):
        rows = self.foreground()
        self.feed(rows + [rows[1], rows[2]])
        self.assertEqual(self.pending(), [])
        self.assertEqual(self.errors(), [])

    def test_a_background_call_stopped_twice_leaves_no_pending_file(self):
        rows = self.events('background-events.jsonl')
        self.place_transcript('background-agent.jsonl', rows)
        starts = [row for row in rows if row['event'] == 'SubagentStart']
        self.feed(rows + starts + [rows[-1]])
        self.assertEqual(self.pending(), [])


class QueuedMessage(World):
    """A message sent to a running agent is queued and may be answered by a later turn; a message to a stopped
    agent resumes it. Either way its return is written at the first stop after the message appears in the agent's
    transcript, with that turn's answer and counters; with no transcript, at the first stop of a turn that started
    after it was sent. No response wording is read to tell the two apart."""

    fields = 'all'
    MESSAGE = 'Please also count the files in the folder.'
    LATER_ANSWER = 'A later answer.'
    LATER = [{'type': 'user', 'isMeta': True, 'message': {'role': 'user', 'content': MESSAGE}},
             {'type': 'assistant', 'message': {
                 'id': 'msg_queued_turn', 'role': 'assistant', 'model': 'claude-haiku-5-5', 'stop_reason': 'end_turn',
                 'content': [{'type': 'text', 'text': LATER_ANSWER}],
                 'usage': {'input_tokens': 7, 'cache_creation_input_tokens': 11, 'cache_read_input_tokens': 13,
                           'output_tokens': 17}}}]
    LATER_TOKENS = {'input': 7, 'cache_write': 11, 'cache_read': 13, 'output': 17}

    def message_rows(self, rows, said='Message queued for delivery to %s at its next tool round.'):
        pre, post = json.loads(json.dumps(rows[0])), json.loads(json.dumps(rows[2]))
        for row in (pre, post):
            row['payload'].update(tool_name='SendMessage', tool_use_id='toolu_queued_message_0001',
                                  tool_input={'to': BACKGROUND_AGENT, 'message': self.MESSAGE})
        post['payload']['tool_response'] = {'success': True, 'message': said % BACKGROUND_AGENT}
        return [pre, post]

    def later_turn(self, rows):
        start = json.loads(json.dumps(rows[1]))
        stop = json.loads(json.dumps(rows[3]))
        stop['payload']['last_assistant_message'] = self.LATER_ANSWER
        return [start, stop]

    def session(self, transcript=True):
        """The background call, a message queued while it runs, its stop, then the turn the message starts."""
        rows = self.events('background-events.jsonl')
        path = self.place_transcript('background-agent.jsonl', rows)
        first = self.transcripts.read(path)['tokens']
        with open(path, 'a', encoding='utf-8') as handle:
            for row in self.LATER:
                handle.write(json.dumps(row) + '\n')
        if not transcript:
            path.unlink()
        return rows[:3] + self.message_rows(rows) + [rows[3]] + self.later_turn(rows), first

    def returns(self):
        return dict((line['call_id'], line) for line in self.records() if line['record'] == 'return')

    def answer(self, record):
        named = record['answer_path']
        found = [path for path in self.ledger.rglob('*') if path.is_file() and str(path).endswith(named)]
        return found[0].read_text(encoding='utf-8') if found else None

    def test_a_queued_message_returns_with_the_turn_it_was_delivered_in(self):
        rows, first = self.session()
        self.feed(rows[:6])
        self.assertNotIn('toolu_queued_message_0001', self.returns(), 'not at the first stop')
        self.feed(rows[6:])
        self.assertEqual(self.errors(), [])
        back = self.returns()['toolu_queued_message_0001']
        self.assertEqual(self.answer(back), self.LATER_ANSWER)
        self.assertEqual(dict((k, back['tokens'][k]) for k in self.LATER_TOKENS), self.LATER_TOKENS)
        call = self.returns()[rows[0]['payload']['tool_use_id']]
        self.assertEqual(dict((k, call['tokens'][k]) for k in first), first, 'the call keeps its own turn')
        self.assertEqual(sorted(p.name for p in (self.ledger / '.pending').rglob('*.json')), [])

    def test_with_no_transcript_it_returns_at_the_stop_of_a_turn_started_after_it(self):
        rows, _ = self.session(transcript=False)
        self.feed(rows[:6])
        self.assertNotIn('toolu_queued_message_0001', self.returns())
        self.feed(rows[6:])
        self.assertEqual(self.errors(), [])
        self.assertEqual(self.answer(self.returns()['toolu_queued_message_0001']), self.LATER_ANSWER)

    def resumed(self, transcript=True):
        """The background call and its stop, then a message to the stopped agent ('Resuming agent …') and the
        turn it starts."""
        rows, first = self.session(transcript)
        rows[4]['payload']['tool_response']['message'] = 'Resuming agent %s' % BACKGROUND_AGENT
        return rows[:3] + [rows[5]] + rows[3:5] + rows[6:], first

    def test_a_message_to_a_stopped_agent_returns_with_its_own_turns_counters(self):
        rows, first = self.resumed()
        self.feed(rows)
        self.assertEqual(self.errors(), [])
        back = self.returns()['toolu_queued_message_0001']
        self.assertEqual(self.answer(back), self.LATER_ANSWER)
        self.assertEqual(dict((k, back['tokens'][k]) for k in self.LATER_TOKENS), self.LATER_TOKENS,
                         'its own turn\'s counters, not the whole transcript\'s')
        self.assertEqual(sorted(p.name for p in (self.ledger / '.pending').rglob('*.json')), [])

    def test_with_no_transcript_a_message_to_a_stopped_agent_returns_at_its_turns_stop(self):
        rows, _ = self.resumed(transcript=False)
        self.feed(rows[:-2])
        self.assertNotIn('toolu_queued_message_0001', self.returns(), 'not before a turn has started')
        self.feed(rows[-2:])
        self.assertEqual(self.answer(self.returns()['toolu_queued_message_0001']), self.LATER_ANSWER)

    def reworded(self, response):
        """The queued message's session with its response replaced: a message is told by its delivery alone."""
        rows, _ = self.session()
        rows[4]['payload']['tool_response'] = response
        self.feed(rows[:6])
        self.assertNotIn('toolu_queued_message_0001', self.returns(), 'not at the first stop')
        self.feed(rows[6:])
        back = self.returns()['toolu_queued_message_0001']
        self.assertEqual(self.answer(back), self.LATER_ANSWER)
        self.assertEqual(dict((k, back['tokens'][k]) for k in self.LATER_TOKENS), self.LATER_TOKENS)

    def test_a_queued_message_said_to_resume_the_agent_still_waits_for_its_delivery(self):
        self.reworded({'success': True, 'message': 'Resuming agent %s' % BACKGROUND_AGENT})

    def test_a_queued_message_with_other_words_still_waits_for_its_delivery(self):
        self.reworded({'success': True, 'message': 'The message was passed on.'})

    def test_a_queued_message_with_no_response_text_still_waits_for_its_delivery(self):
        self.reworded({'success': True})


class AttachmentDeliveredMessage(QueuedMessage):
    """The same cases, with the message delivered as Claude Code also writes it: an attachment row of type
    queued_command, the text at attachment.prompt (subagent-tools.json, `delivery`)."""

    LATER = [{'type': 'attachment', 'isSidechain': True,
              'attachment': {'type': 'queued_command', 'prompt': QueuedMessage.MESSAGE, 'isMeta': True,
                             'origin': {'kind': 'coordinator'}},
              'rendered': [{'content': '[not read]'}], 'renderedRole': 'system'}] + QueuedMessage.LATER[1:]

    def test_an_attachment_of_a_type_not_listed_writes_no_return(self):
        self.LATER = [dict(self.LATER[0], attachment=dict(self.LATER[0]['attachment'], type='a_form_not_listed'))] \
            + self.LATER[1:]
        rows, _ = self.session()
        self.feed(rows[:6])
        self.feed(rows[6:])
        self.assertNotIn('toolu_queued_message_0001', self.returns(), 'a form not listed is not read as delivery')


class BackgroundTranscriptSettles(World):
    """Live control 1 found a background transcript with no usage row yet when SubagentStop fired.

    The capture waits for the transcript's last request to carry a stop reason before it reads a
    background call's counters. Here the transcript holds only its first row when SubagentStop
    arrives, and the rest is written during the capture's first wait.
    """

    def background_late(self):
        rows = self.events('background-events.jsonl')
        full = self.place_transcript('background-agent.jsonl', rows)
        text = full.read_text(encoding='utf-8')
        full.write_text(text.splitlines(True)[0], encoding='utf-8')
        return rows, full, text

    def test_the_counters_are_read_once_the_transcript_settles(self):
        rows, full, text = self.background_late()
        with mock.patch.object(self.capture.time, 'sleep', lambda seconds: full.write_text(text, encoding='utf-8')):
            self.feed(rows)
        back = self.records()[-1]
        self.assertEqual(back['model'], 'claude-haiku-5-5')
        self.assertIsInstance(back['tokens']['output'], int)

    def test_control_without_the_completion_test_the_counters_are_unrecorded(self):
        rows, full, text = self.background_late()
        with mock.patch.object(self.capture, 'transcript_complete', lambda *a, **k: True):
            with mock.patch.object(self.capture.time, 'sleep', lambda seconds: full.write_text(text, encoding='utf-8')):
                self.feed(rows)
        self.assertTrue(UNRECORDED.match(self.records()[-1]['tokens']))


# ---------------------------------------------------------------------------
# A background call read once its transcript holds the answer
# ---------------------------------------------------------------------------

L1_FULL = {'input': 4, 'cache_write': 31384, 'cache_read': 28892, 'output': 86}
L1_FIRST = {'input': 2, 'cache_write': 28892, 'cache_read': 0, 'output': 78}


class CRB2_1WaitOnContent(World):
    """A live background call (agent a2905ca0abf302cee) whose transcript held only its first request,
    ending tool_use, when SubagentStop fired. The test appends the second request after a delay while
    the capture handles SubagentStop. The full counters are close-cost.py's reading of the same run."""

    def replay(self, delay):
        import threading
        rows = self.events('l1-background-events.jsonl')
        path = Path(rows[3]['payload']['agent_transcript_path'])
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(self.fill((FIXTURES / 'l1-background-agent-first.jsonl').read_text(encoding='utf-8')),
                        encoding='utf-8')
        rest = self.fill((FIXTURES / 'l1-background-agent-rest.jsonl').read_text(encoding='utf-8'))

        def append():
            import time as clock
            clock.sleep(delay)
            with path.open('a', encoding='utf-8') as handle:
                handle.write(rest)
        self.feed(rows[:3])
        writer = threading.Thread(target=append)
        writer.start()
        try:
            self.feed(rows[3:])
        finally:
            writer.join()
        return [r for r in self.records() if r['record'] == 'return']

    def counters(self, record):
        return dict((k, record['tokens'][k]) for k in L1_FULL)

    def test_c_rb2_1a_the_second_request_after_a_third_of_a_second(self):
        back = self.replay(0.3)
        self.assertEqual(len(back), 1)
        self.assertEqual(self.counters(back[0]), L1_FULL)
        self.assertGreaterEqual(back[0]['tokens']['read_after_seconds'], 0.3)

    def test_c_rb2_1b_the_second_request_after_eight_seconds(self):
        back = self.replay(8)
        self.assertEqual(self.counters(back[0]), L1_FULL)
        self.assertGreaterEqual(back[0]['tokens']['read_after_seconds'], 8)

    def test_c_rb2_1c_control_completion_test_switched_off_reads_short(self):
        with mock.patch.object(self.capture, 'transcript_complete', lambda *a, **k: True):
            back = self.replay(0.3)
        self.assertEqual(self.counters(back[0]), L1_FIRST)


# ---------------------------------------------------------------------------
# A failed subagent call, and the command-line route's failures
# ---------------------------------------------------------------------------

class CRB2_2AgentFailure(World):

    def test_c_rb2_2_a_failed_agent_call_is_failed_with_its_class(self):
        rows = self.foreground()
        failure = json.loads(json.dumps(rows[3]))
        failure['event'] = 'PostToolUseFailure'
        failure['payload']['hook_event_name'] = 'PostToolUseFailure'
        failure['payload'].pop('tool_response')
        failure['payload']['error'] = 'Not logged in · Please run /login'
        self.feed([rows[0], failure])
        back = [r for r in self.records() if r['record'] == 'return']
        self.assertEqual(len(back), 1)
        self.assertEqual(back[0]['call_id'], self.records()[0]['call_id'])
        self.assertEqual(back[0]['outcome'], 'failed')
        self.assertEqual(back[0]['outcome_reason']['class'], 'not_signed_in')


class CRB2_3PromptKept(World):

    fields = 'all'

    def test_c_rb2_3_the_prompt_is_copied_beside_the_named_brief(self):
        rows = self.foreground()
        prompt = rows[0]['payload']['tool_input']['prompt']
        self.feed(rows[:1])
        dispatch = self.records()[0]
        copies = sorted((self.ledger / dispatch['session']).glob('*.md'))
        self.assertEqual(len(copies), 2, copies)
        shown = dispatch['harness_payload']['tool_input']['prompt']
        self.assertTrue(shown.startswith('moved to '), shown)
        target = Path(shown[len('moved to '):])
        target = target if target.is_absolute() else self.ledger.parent / target
        self.assertEqual(target.read_text(encoding='utf-8'), prompt)
        self.assertNotEqual(str(target), dispatch['brief_path'])


class CRB2_5RelativeBrief(World):

    fields = 'all'

    def test_c_rb2_5_a_brief_named_relative_to_the_working_folder_is_found(self):
        rows = self.foreground()
        rows[0]['payload']['tool_input']['prompt'] = 'Read brief.md in the working folder'
        self.feed(rows[:1])
        dispatch = self.records()[0]
        self.assertEqual(dispatch['brief_source'], 'brief.md')
        copy = Path(dispatch['brief_path'])
        copy = copy if copy.is_absolute() else self.ledger.parent / copy
        self.assertEqual(copy.read_text(encoding='utf-8'), (self.work / 'brief.md').read_text(encoding='utf-8'))


# ---------------------------------------------------------------------------
# Streamed rows grouped by message id
# ---------------------------------------------------------------------------

class CB2_3Streamed(unittest.TestCase):

    def setUp(self):
        self.transcripts = load(TRANSCRIPTS_PY, 'transcripts_under_test')

    def test_c_b2_3_three_streamed_rows_read_as_their_maximum(self):
        reading = self.transcripts.read(FIXTURES / 'streamed-agent.jsonl')
        self.assertEqual(reading['tokens']['output'], 206)
        self.assertEqual(reading['requests'], 1)

    def test_c_b2_3_control_summing_every_row_gives_208(self):
        with mock.patch.object(self.transcripts, '_group_key', lambda row, position: 'row-%d' % position):
            reading = self.transcripts.read(FIXTURES / 'streamed-agent.jsonl')
        self.assertEqual(reading['tokens']['output'], 208)


# ---------------------------------------------------------------------------
# The hook's usage disagrees with the transcript's last request
# ---------------------------------------------------------------------------

class CB2_4CounterCheck(World):

    def disagreeing(self):
        rows = self.foreground()
        rows[3]['payload']['tool_response']['usage']['output_tokens'] = 90
        return rows

    def test_c_b2_4_a_disagreement_is_flagged_and_tokens_stay_the_transcripts(self):
        self.feed(self.disagreeing())
        back = self.records()[-1]
        self.assertEqual(back['tokens']['output'], 165)
        self.assertEqual(back['tokens']['counter_check']['difference'], {'output': 6})

    def test_agreement_writes_no_check(self):
        self.feed(self.foreground())
        self.assertNotIn('counter_check', self.records()[-1]['tokens'])

    def test_c_b2_4_control_check_switched_off_writes_no_flag(self):
        with mock.patch.object(self.capture, 'COUNTER_NAMES', ()):
            self.feed(self.disagreeing())
        self.assertNotIn('counter_check', self.records()[-1]['tokens'])


# ---------------------------------------------------------------------------
# No credential value under the ledger
# ---------------------------------------------------------------------------

class CB2_5Credential(World):

    fields = 'all'

    def planted(self):
        rows = self.foreground()
        for row in rows:
            for key in ('tool_input', 'tool_response'):
                part = row['payload'].get(key)
                if isinstance(part, dict) and 'prompt' in part:
                    part['prompt'] = 'Reply with the word received. The key is %s.' % PLANTED
        return rows

    def test_c_b2_5_the_value_is_nowhere_and_auth_route_names_the_variable(self):
        with mock.patch.dict(os.environ, {'ANTHROPIC_API_KEY': PLANTED}):
            self.feed(self.planted())
        self.assertNotIn(PLANTED, self.every_byte_under_the_ledger())
        dispatch = self.records()[0]
        self.assertEqual(dispatch['auth_route'], 'environment: ANTHROPIC_API_KEY')
        self.assertGreater(dispatch['withheld'], 0)

    def test_c_b2_5_control_scrub_switched_off_shows_the_value(self):
        with mock.patch.dict(os.environ, {'ANTHROPIC_API_KEY': PLANTED}):
            with mock.patch.object(self.ledger_module, '_secrets', lambda: []):
                self.feed(self.planted())
        self.assertIn(PLANTED, self.every_byte_under_the_ledger())


# ---------------------------------------------------------------------------
# Bad input never stops the hook
# ---------------------------------------------------------------------------

class CB2_6BadInput(World):

    def run_command(self, text, event='PreToolUse'):
        return subprocess.run([sys.executable, str(CAPTURE_PY), event, '--ledger', str(self.ledger)],
                              input=text, capture_output=True, text=True, timeout=60)

    def no_call_id(self):
        payload = self.foreground()[0]['payload']
        payload.pop('tool_use_id')
        return json.dumps(payload)

    def test_c_b2_6_each_exits_0_prints_nothing_and_leaves_one_error_line(self):
        for n, text in enumerate(['this is not JSON', '', self.no_call_id()], start=1):
            with self.subTest(case=n):
                done = self.run_command(text)
                self.assertEqual(done.returncode, 0)
                self.assertEqual(done.stdout, '')
                self.assertEqual(len(self.errors()), n)
        self.assertEqual(self.records(), [])
        self.assertTrue(self.errors()[2]['reason'].startswith('no call_id'))
        self.assertEqual(self.errors()[2]['session'], self.foreground()[0]['payload']['session_id'])

    def test_c_b2_6_control_error_lines_switched_off_leave_nothing(self):
        with mock.patch.object(self.capture.Held, 'error', lambda *a, **k: None):
            for text in ['this is not JSON', '', self.no_call_id()]:
                self.capture.handle('PreToolUse', text, None)
        self.assertEqual(self.errors(), [], 'without the error line the failure is silent')


# ---------------------------------------------------------------------------
# The Bash route
# ---------------------------------------------------------------------------

class CB2_7Shell(World):

    def shell(self, command, stdout, call='toolu_shell_0001'):
        base = self.events('bash-cli-events.jsonl')
        rows = []
        for row in base:
            payload = json.loads(json.dumps(row['payload']))
            payload['tool_input']['command'] = command
            payload['tool_use_id'] = call
            if row['event'] == 'PostToolUse':
                payload['tool_response']['stdout'] = stdout
            rows.append({'event': row['event'], 'payload': payload})
        return rows

    def test_c_b2_7_claude_print_json_is_a_cli_call_with_the_model_from_model_usage(self):
        rows = self.events('bash-cli-events.jsonl')
        self.feed(rows)
        self.assertEqual(self.errors(), [])
        dispatch, back = self.records()
        self.assertEqual(dispatch['call_id'], back['call_id'])
        self.assertEqual(back['model'], 'claude-opus-5-5')
        self.assertEqual(back['outcome'], 'served')
        self.assertEqual(dispatch['agent_id'], 'unrecorded (no agent: cli call)')

    def test_c_b2_7_route_and_cost_under_all(self):
        (self.ledger / 'config.json').write_text(json.dumps({'fields': 'all'}), encoding='utf-8')
        self.feed(self.events('bash-cli-events.jsonl'))
        dispatch, back = self.records()
        self.assertEqual((dispatch['route'], back['route']), ('cli', 'cli'))
        self.assertEqual(back['cost']['field'], 'total_cost_usd')

    def test_c_b2_7_a_version_check_writes_nothing(self):
        self.feed(self.shell('codex --version', 'codex-cli 1.0.0\n'))
        self.assertEqual(self.records(), [])
        self.assertEqual(self.errors(), [])

    def test_c_b2_7_plain_output_names_no_model(self):
        self.feed(self.shell('gemini -p "x"', 'hello\n', call='toolu_shell_0002'))
        back = self.records()[-1]
        self.assertEqual(back['model'], "unrecorded (the command's output names no model)")
        self.assertEqual(back['outcome'], 'served')

    def test_a_non_zero_exit_is_failed(self):
        rows = self.shell('claude -p "x"', '', call='toolu_shell_0003')
        failure = dict(rows[1])
        failure['event'] = 'PostToolUseFailure'
        failure['payload'] = dict(rows[1]['payload'], hook_event_name='PostToolUseFailure',
                                  error='Exit code 1\nNot logged in · Please run /login')
        failure['payload'].pop('tool_response')
        self.feed([rows[0], failure])
        back = self.records()[-1]
        self.assertEqual(back['outcome'], 'failed')
        self.assertEqual(back['outcome_reason']['class'], 'not_signed_in')

    def test_c_b2_7_control_matching_switched_off_misses_the_call(self):
        with mock.patch.object(self.capture, 'match_command', lambda *a, **k: (None, None)):
            self.feed(self.events('bash-cli-events.jsonl'))
        self.assertEqual(self.records(), [], 'without the pattern match the call leaves no record')


# ---------------------------------------------------------------------------
# Briefs named by path, and inline
# ---------------------------------------------------------------------------

class CB2_8Brief(World):

    fields = 'all'

    def copied(self, record):
        return (self.ledger.parent / record['brief_path']).read_text(encoding='utf-8') \
            if not Path(record['brief_path']).is_absolute() else Path(record['brief_path']).read_text(encoding='utf-8')

    def test_c_b2_8_a_named_file_is_the_brief(self):
        rows = self.foreground()
        self.feed(rows[:1])
        dispatch = self.records()[0]
        self.assertEqual(dispatch['brief_source'], str(self.work / 'brief.md'))
        self.assertEqual(self.copied(dispatch), (self.work / 'brief.md').read_text(encoding='utf-8'))
        self.assertNotIn(rows[0]['payload']['tool_input']['prompt'], json.dumps(dispatch))

    def test_c_b2_8_an_inline_prompt_is_the_brief(self):
        rows = self.foreground()
        rows[0]['payload']['tool_input']['prompt'] = 'Reply with the word received and nothing else.'
        self.feed(rows[:1])
        dispatch = self.records()[0]
        self.assertTrue(UNRECORDED.match(dispatch['brief_source']))
        self.assertEqual(self.copied(dispatch), 'Reply with the word received and nothing else.')

    def test_c_b2_8_control_file_reading_switched_off_loses_the_source(self):
        with mock.patch.object(self.capture, 'brief_of', lambda prompt, cwd: (prompt, None)):
            self.feed(self.foreground()[:1])
        self.assertTrue(UNRECORDED.match(self.records()[0]['brief_source']))


# ---------------------------------------------------------------------------
# The optional fields from the brief's frontmatter
# ---------------------------------------------------------------------------

BRIEF_WITH_FRONTMATTER = """---
type: brief
meta:
  persona: builder
  character: build
  task: 2026-01-01-example-task
---

Reply with the word received and nothing else.
"""


class CB2_9Optional(World):

    def setting(self, fields, mapped=True):
        config = {'fields': fields}
        if mapped:
            config['frontmatter'] = {'persona-name': 'meta.persona', 'act_kind': 'meta.character',
                                     'task': 'meta.task'}
            config['grouping_table'] = 'grouping.json'
            (self.ledger / 'grouping.json').write_text(json.dumps({'grouping': {'builder': 'workshop'}}),
                                                       encoding='utf-8')
        (self.ledger / 'config.json').write_text(json.dumps(config), encoding='utf-8')

    def dispatch_of_brief(self):
        rows = self.foreground()
        (self.work / 'brief.md').write_text(BRIEF_WITH_FRONTMATTER, encoding='utf-8')
        self.feed(rows[:1])
        return self.records()[0]

    def test_c_b2_9_all_fills_the_four_fields(self):
        self.setting('all')
        dispatch = self.dispatch_of_brief()
        self.assertEqual((dispatch['persona-name'], dispatch['act_kind'], dispatch['task'],
                          dispatch['grouping']), ('builder', 'build', '2026-01-01-example-task', 'workshop'))

    def test_c_b2_9_frame_writes_none_of_them(self):
        self.setting('frame')
        dispatch = self.dispatch_of_brief()
        for name in ('persona-name', 'act_kind', 'task', 'grouping'):
            self.assertNotIn(name, dispatch)
            self.assertIn(name, dispatch['fields_not_chosen'])

    def test_c_b2_9_control_with_no_map_each_says_why(self):
        self.setting('all', mapped=False)
        dispatch = self.dispatch_of_brief()
        for name in ('persona-name', 'act_kind', 'task', 'grouping'):
            self.assertTrue(UNRECORDED.match(dispatch[name]), dispatch[name])


# ---------------------------------------------------------------------------
# Isolation evidence
# ---------------------------------------------------------------------------

class CB2_10Isolation(unittest.TestCase):

    def setUp(self):
        self.transcripts = load(TRANSCRIPTS_PY, 'transcripts_under_test')
        self.reading = {'path': 'x.jsonl', 'cwd': '/work/run', 'tool_uses': [
            {'name': 'Read', 'input': {'file_path': '/elsewhere/notes.md'}},
            {'name': 'Read', 'input': {'file_path': '/work/run/brief.md'}},
            {'name': 'Read', 'input': {'file_path': 'relative.md'}},
            {'name': 'Bash', 'input': {'command': 'cat /etc/hosts'}},
            {'name': 'Bash', 'input': {'command': 'ls /work/run'}},
        ]}

    def test_c_b2_10_outside_is_listed_inside_is_not(self):
        found = self.transcripts.isolation(self.reading)
        self.assertEqual(found['folder'], '/work/run')
        listed = json.dumps(found['outside'])
        self.assertIn('/elsewhere/notes.md', listed)
        self.assertIn('/etc/hosts', listed)
        self.assertNotIn('brief.md', listed)
        self.assertNotIn('relative.md', listed)
        self.assertNotIn('ls /work/run', listed)

    def test_c_b2_10_control_the_folder_test_switched_off_lists_nothing(self):
        with mock.patch.object(self.transcripts, '_inside', lambda path, folder: True):
            found = self.transcripts.isolation(self.reading)
        self.assertEqual(found['outside'], [])

    def test_a_live_lane_that_ran_one_command_inside_its_folder(self):
        reading = self.transcripts.read(FIXTURES / 'lane-bash-agent.jsonl')
        self.assertEqual(self.transcripts.isolation(reading)['outside'], [])


# ---------------------------------------------------------------------------
# The probes' findings, held as tests
# ---------------------------------------------------------------------------

class ProbeFindings(World):

    fields = 'all'

    def test_p1_effort_is_read_from_subagent_stop(self):
        rows = self.events('effort-events.jsonl')
        levels = dict((r['event'], (r['payload'].get('effort') or {}).get('level')) for r in rows)
        self.assertEqual((levels['PreToolUse'], levels['SubagentStop']), ('low', 'high'))
        path = rows[2]['payload']['agent_transcript_path']
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        Path(path).write_text(self.fill((FIXTURES / 'foreground-agent.jsonl').read_text(encoding='utf-8')),
                              encoding='utf-8')
        self.feed(rows)
        self.assertEqual(self.records()[-1]['effort'], 'high')

    def test_p4_a_lane_names_itself_as_caller(self):
        rows = self.events('lane-bash-events.jsonl')
        self.place_transcript('lane-bash-agent.jsonl', rows)
        self.feed(rows)
        self.assertEqual(self.errors(), [])
        back = [r for r in self.records() if r['record'] == 'return'][0]
        self.assertEqual(back['caller'], 'parent')
        self.assertEqual(back['agent_id'], LANE_AGENT)
        # A model call made by the lane would carry the lane's id; its own Bash command shows it.
        lane_bash = [r for r in rows if r['event'] == 'PreToolUse' and r['payload']['tool_name'] == 'Bash'][0]
        self.assertEqual(self.capture.common(lane_bash['payload'], self.ledger, 'cli')['caller'], LANE_AGENT)

    def test_the_answer_and_brief_are_not_inline(self):
        self.feed(self.foreground())
        back = self.records()[-1]
        self.assertTrue(back['harness_payload']['tool_response']['content'].startswith('moved to '))
        self.assertTrue(back['harness_payload']['tool_input']['prompt'].startswith('not kept: '))
        self.assertTrue(Path(back['answer_path']).name.endswith('.md'))


# ---------------------------------------------------------------------------
# A `claude -p` call through Bash reads its counters from its own transcript
# ---------------------------------------------------------------------------

INNER_SESSION = '005d0379-66fe-45ea-96d8-d013ce25b6b1'


class CB3_8InnerTranscript(World):
    """bash-cli-events.jsonl is a live Bash call of `claude -p --output-format json`; its envelope names
    session 005d0379. bash-cli-inner.jsonl is that inner session's own transcript, less its attachment
    rows. The test puts it where Claude Code wrote it, under the configuration folder's projects/."""

    fields = 'all'

    def place_inner(self, config):
        path = Path(config) / 'projects' / '-fixture-work' / ('%s.jsonl' % INNER_SESSION)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(self.fill((FIXTURES / 'bash-cli-inner.jsonl').read_text(encoding='utf-8')),
                        encoding='utf-8')
        return path

    def with_command(self, command):
        rows = self.events('bash-cli-events.jsonl')
        for row in rows:
            row['payload']['tool_input']['command'] = command
        return rows

    def test_c_b3_8_tokens_and_model_from_the_inner_transcript(self):
        self.place_inner(self.config)
        self.feed(self.events('bash-cli-events.jsonl'))
        self.assertEqual(self.errors(), [])
        back = self.records()[-1]
        self.assertEqual(back['tokens'], {'input': 2, 'cache_write': 14021, 'cache_read': 23691, 'output': 4})
        self.assertEqual(back['model'], 'claude-opus-5-5')
        self.assertEqual(back['isolation']['read_from'], str(Path(self.config) / 'projects' / '-fixture-work'
                                                                / ('%s.jsonl' % INNER_SESSION)))

    def test_c_b3_8_the_folder_the_command_set_is_searched(self):
        other = self.tmp / 'other-config'
        self.place_inner(other)
        self.feed(self.with_command('CLAUDE_CONFIG_DIR=%s claude -p --output-format json "Reply ok"' % other))
        back = self.records()[-1]
        self.assertEqual(back['tokens']['cache_read'], 23691)

    def test_c_b3_8_a_missing_transcript_reads_unrecorded(self):
        self.feed(self.events('bash-cli-events.jsonl'))
        back = self.records()[-1]
        self.assertRegex(back['tokens'], UNRECORDED)
        self.assertIn(INNER_SESSION, back['tokens'])
        self.assertRegex(back['isolation'], UNRECORDED)
        self.assertEqual(back['model'], 'claude-opus-5-5', 'the envelope still names the model')

    def test_c_b3_8_a_transcript_without_the_result_reads_unrecorded(self):
        path = self.place_inner(self.config)
        # The answer is 'ok', which the prompt 'Reply ok' also holds; both go, as in a transcript cut
        # short before the answer was written to a run whose prompt did not quote it.
        text = path.read_text(encoding='utf-8').replace('"text": "ok"', '"text": "something else"')
        path.write_text(text.replace('Reply ok', 'Reply'), encoding='utf-8')
        self.feed(self.events('bash-cli-events.jsonl'))
        self.assertIn('does not carry', self.records()[-1]['tokens'])

    def test_c_b3_8_control_inner_reading_switched_off_leaves_the_counters_unread(self):
        self.place_inner(self.config)
        with mock.patch.object(self.capture, 'inner_reading', lambda *a, **k: {}):
            self.feed(self.events('bash-cli-events.jsonl'))
        self.assertRegex(self.records()[-1]['tokens'], UNRECORDED)


if __name__ == '__main__':
    unittest.main()
