"""Tests for the call reader, `skill/scripts/calls.py`, and its count check.

Controls C-B6-1 to C-B6-5. Each has a half that runs on the reader as built and must pass, and a half
that switches one part of the reader off, by a patch in this file, and shows the fault: a control
that cannot fail proves nothing. Before the reader existed every test here failed, because the
module it loads was missing.

Every ledger here is written at test time by the captures and ledger.py, from recorded hook payloads,
so the records are the shape the captures write. Fixtures, under fixtures/calls/, with every machine
path a placeholder (${CONFIG}, ${WORK}, ${TASKROOT}) each test fills with a folder of its own:

  * l1-events.jsonl: the eight hook payloads of a live `claude -p` session that made two `Agent`
    calls, one in the foreground and one in the background, in the order Claude Code sent them;
  * l1-foreground-agent.jsonl and l1-background-agent.jsonl: those two subagents' transcripts, less
    their attachment rows;
  * l1-parent.jsonl: the session's own transcript, cut to the two rows that carry its `Agent` tool
    calls.

The third call of C-B6-1 is the PreToolUse payload of fixtures/claude-code/foreground-events.jsonl,
moved into the l1 session; its other three payloads are never sent, so it has no return. A stream
of three rows for one call is the l1 parent's first `Agent` row written three times, as Claude Code
writes a message while it streams. Each is a reconstruction from recorded payloads, said so here.

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
import stat
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

HERE = Path(__file__).resolve().parent
SCRIPTS = HERE.parent / 'skill' / 'scripts'
FIXTURES = HERE / 'fixtures'
CALLS_PY = SCRIPTS / 'calls.py'
CAPTURE_PY = SCRIPTS / 'capture_claude_code.py'
CODEX_PY = SCRIPTS / 'capture_codex.py'

SESSION = '23fd2e70-b836-41ab-b856-8537405a9f64'
FOREGROUND_CALL = 'toolu_013Vjp8FE3ALqynt1VjM7RdM'
FOREGROUND_AGENT = 'aed1a52f6dc904ef1'
BACKGROUND_CALL = 'toolu_015hemvAekVqG1SbwbMwtS9b'
BACKGROUND_AGENT = 'a2905ca0abf302cee'
THIRD_CALL = 'toolu_0155cHsftXAqUz1zgy3SCvkM'
THIRD_SESSION = '6449f88e-c7fa-40ca-8065-7558230a320d'
FIXED_NOW = '2026-10-09T09:00:00.000Z'
UNRECORDED = re.compile(r'^unrecorded \(.+\)$')
SELECTABLE = (
    'model_requested', 'model', 'tokens', 'cost', 'outcome_reason', 'route', 'harness', 'machine',
    'caller', 'project', 'effort', 'effort_assigned', 'auth_route', 'brief_path', 'brief_source',
    'answer_path', 'isolation', 'harness_payload', 'spend_line', 'persona-name', 'act_kind', 'user_answer',
    'grouping', 'task', 'failure_modes', 'roster_revision', 'labeller_model', 'recommended_harness',
    'recommended_model', 'triage_model',
)


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

    fields = 'all'

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix='calls-test-'))
        self.addCleanup(self._cleanup)
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
        self.capture = load(CAPTURE_PY, 'capture_claude_code_for_calls_test')

    def _cleanup(self):
        for path in self.tmp.rglob('*'):
            with contextlib.suppress(OSError):
                os.chmod(path, stat.S_IRWXU)
        shutil.rmtree(self.tmp, True)

    # -- fixtures --------------------------------------------------------------------------------

    def fill(self, text):
        return (text.replace('${CONFIG}', str(self.config)).replace('${WORK}', str(self.work))
                .replace('${TASKROOT}', str(self.tasks)))

    def events(self, name, folder='calls'):
        return [json.loads(self.fill(line)) for line in
                (FIXTURES / folder / name).read_text(encoding='utf-8').splitlines() if line.strip()]

    def l1(self):
        """The l1 session's payloads, with both subagents' transcripts and its own placed."""
        rows = self.events('l1-events.jsonl')
        for row in rows:
            path = (row['payload'] or {}).get('agent_transcript_path')
            if path:
                agent = row['payload']['agent_id']
                name = 'l1-foreground-agent.jsonl' if agent == FOREGROUND_AGENT else 'l1-background-agent.jsonl'
                Path(path).parent.mkdir(parents=True, exist_ok=True)
                Path(path).write_text(self.fill((FIXTURES / 'calls' / name).read_text(encoding='utf-8')),
                                      encoding='utf-8')
        parent = Path(rows[0]['payload']['transcript_path'])
        parent.parent.mkdir(parents=True, exist_ok=True)
        parent.write_text(self.fill((FIXTURES / 'calls' / 'l1-parent.jsonl').read_text(encoding='utf-8')),
                          encoding='utf-8')
        return rows

    def third(self):
        """The PreToolUse of a third call, moved into the l1 session."""
        row = self.events('foreground-events.jsonl', 'claude-code')[0]
        text = json.dumps(row['payload']).replace(THIRD_SESSION, SESSION)
        return {'event': 'PreToolUse', 'payload': json.loads(text)}

    def feed(self, rows, pause=0.0):
        for row in rows:
            self.capture.handle(row['event'], json.dumps(row['payload']), None)
            if pause:
                time.sleep(pause)

    def parent_transcript(self):
        return self.config / 'projects' / '-fixture-work' / ('%s.jsonl' % SESSION)

    def lane_transcripts(self):
        folder = self.config / 'projects' / '-fixture-work' / SESSION / 'subagents'
        return sorted(folder.glob('agent-*.jsonl'))

    def ledger_file(self, folder=None):
        return Path(folder or self.ledger) / ('%s.jsonl' % SESSION)

    def copy_ledger(self, drop):
        """A copy of the ledger folder whose session file lacks every line `drop` returns true for."""
        copy = self.tmp / ('ledger-copy-%d' % len(list(self.tmp.glob('ledger-copy-*'))))
        shutil.copytree(self.ledger, copy)
        kept = [line for line in lines_of(self.ledger_file(copy)) if not drop(line)]
        self.ledger_file(copy).write_text(''.join(json.dumps(line) + '\n' for line in kept), encoding='utf-8')
        return copy

    # -- the reader ------------------------------------------------------------------------------

    def reader(self):
        return load(CALLS_PY, 'calls_under_test')

    def run_reader(self, *args, module=None, ledger=None):
        """Run the reader in this process. Returns (exit code, the output object or None, stdout)."""
        calls = module or self.reader()
        argv = ['--session', SESSION, '--ledger', str(ledger or self.ledger), '--json'] + list(args)
        out, err = io.StringIO(), io.StringIO()
        with mock.patch.object(calls, 'now', lambda: FIXED_NOW), \
                contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = calls.main(argv)
        text = out.getvalue()
        try:
            data = json.loads(text) if text.strip() else None
        except ValueError:
            data = None
        return code, data, text

    @staticmethod
    def reasons(data):
        return [absence['reason'] for absence in data['absences']]


# ---------------------------------------------------------------------------
# C-B6-1: three calls, one without a return
# ---------------------------------------------------------------------------

class CB6_1Reader(World):

    def three(self):
        self.feed(self.l1() + [self.third()], pause=0.01)

    def test_c_b6_1_rows_equal_the_ledger_with_one_absence(self):
        self.three()
        code, data, _ = self.run_reader()
        self.assertEqual(code, 0)
        self.assertEqual(data['session'], SESSION)
        self.assertEqual(data['read_at'], FIXED_NOW)
        self.assertNotIn('count_check', data, 'no count check was asked for')
        records = lines_of(self.ledger_file())
        sent = [r for r in records if r['record'] == 'dispatch']
        back = dict((r['call_id'], r) for r in records if r['record'] == 'return')
        self.assertEqual([row['call_id'] for row in data['calls']], [r['call_id'] for r in sent],
                         'one row per call, in dispatch order')
        for row, dispatch in zip(data['calls'], sent):
            source = back.get(dispatch['call_id'], dispatch)
            for name in ('agent_id', 'dispatched_at', 'returned_at', 'outcome'):
                self.assertEqual(row[name], source[name], name)
            for name in ('model_requested', 'brief_path', 'auth_route'):
                self.assertEqual(row[name], dispatch[name], name)
            for name in ('model', 'outcome_reason', 'answer_path', 'spend_line'):
                self.assertEqual(row[name], source[name], name)
        self.assertEqual(data['calls'][0]['model'], 'claude-haiku-5-5')
        self.assertEqual(self.reasons(data), ['no return record'])
        self.assertEqual(data['absences'][0]['call_id'], THIRD_CALL)

    def test_c_b6_1_unreadable_transcripts_leave_the_output_byte_for_byte_the_same(self):
        self.three()
        _, _, before = self.run_reader()
        locked = []
        for path in self.config.rglob('*'):
            if path.is_file():
                os.chmod(path, 0)
                locked.append(path)
        self.assertGreaterEqual(len(locked), 3, 'the parent and both subagent transcripts are locked')
        code, _, after = self.run_reader()
        self.assertEqual(code, 0)
        self.assertEqual(after, before)

    def test_c_b6_1_no_ledger_file_for_the_session_exits_3(self):
        self.three()
        calls = self.reader()
        out = io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(io.StringIO()):
            code = calls.main(['--session', '00000000-0000-4000-8000-000000000000', '--ledger',
                               str(self.ledger), '--json'])
        self.assertEqual(code, 3)

    def test_c_b6_1_control_without_the_return_check_the_missing_return_is_silent(self):
        self.three()
        calls = self.reader()
        with mock.patch.object(calls, 'missing_returns', lambda *args, **kwargs: []):
            code, data, _ = self.run_reader(module=calls)
        self.assertEqual(self.reasons(data), [], 'the check sees the absence only through missing_returns')
        self.assertEqual(code, 0)

    def test_c_b6_1_control_a_reader_that_opens_transcripts_changes_when_they_are_locked(self):
        self.three()
        calls = self.reader()
        original = calls.listing

        def reads_transcripts(*args, **kwargs):
            out = original(*args, **kwargs)
            try:
                out['calls'][0]['peeked'] = self.parent_transcript().read_text(encoding='utf-8')[:10]
            except OSError as exc:
                out['calls'][0]['peeked'] = type(exc).__name__
            return out
        with mock.patch.object(calls, 'listing', reads_transcripts):
            _, _, before = self.run_reader(module=calls)
            os.chmod(self.parent_transcript(), 0)
            _, _, after = self.run_reader(module=calls)
        self.assertNotEqual(after, before, 'the byte comparison sees a reader that opens a transcript')


# ---------------------------------------------------------------------------
# C-B6-2: Gap 1, a record rejected, a write that failed, and unattributed lines
# ---------------------------------------------------------------------------

class CB6_2Gap1(World):

    def planted(self):
        rows = self.l1()
        foreground, background = rows[:4], rows[4:]
        no_call = json.loads(json.dumps(foreground[0]))
        del no_call['payload']['tool_use_id']
        nothing = json.loads(json.dumps(foreground[0]))
        del nothing['payload']['tool_use_id']
        del nothing['payload']['session_id']
        no_session = self.third()
        del no_session['payload']['session_id']
        self.feed(foreground, pause=0.01)
        self.feed([no_call, nothing, no_session], pause=0.01)
        # The ledger file read-only for one write: the background call's dispatch.
        os.chmod(self.ledger_file(), stat.S_IRUSR)
        self.feed(background[:1], pause=0.01)
        os.chmod(self.ledger_file(), stat.S_IRUSR | stat.S_IWUSR)
        self.feed(background[1:], pause=0.01)
        time.sleep(0.02)
        self.feed([nothing])  # after the session's last record: outside its span

    def test_c_b6_2_each_planted_failure_is_an_absence_once(self):
        self.planted()
        code, data, text = self.run_reader()
        self.assertEqual(code, 0)
        reasons = self.reasons(data)
        self.assertEqual(reasons.count('record rejected: no call_id (tool_use_id absent from PreToolUse)'), 1,
                         reasons)
        failed = [a for a in data['absences'] if a['reason'].startswith('write failed: ')]
        self.assertEqual(len(failed), 1, reasons)
        self.assertEqual(failed[0]['call_id'], BACKGROUND_CALL)
        self.assertIn('Permission', failed[0]['reason'])
        self.assertEqual(reasons.count('unattributed capture error'), 1, reasons)
        self.assertEqual(reasons.count('record unattributed: session_id absent from the payload'), 1, reasons)
        background = [row for row in data['calls'] if row['call_id'] == BACKGROUND_CALL]
        self.assertEqual(len(background), 1, 'the call whose dispatch failed shows once, from its return')
        self.assertEqual(background[0]['model_requested'], 'unrecorded (no dispatch record)')
        self.assertNotIn('no dispatch record', reasons, 'merged with the write failure, not listed twice')
        prompt = self.l1()[0]['payload']['tool_input']['prompt']
        self.assertNotIn(prompt, (self.ledger / 'capture-errors.jsonl').read_text(encoding='utf-8'),
                         'no error line holds a payload value')

    def test_c_b6_2_an_error_with_no_session_outside_the_span_is_not_listed(self):
        self.planted()
        errors = lines_of(self.ledger / 'capture-errors.jsonl')
        unattributed = [e for e in errors if e['session'].startswith('unrecorded (')]
        self.assertEqual(len(unattributed), 2, 'one inside the span and one after it were written')
        _, data, _ = self.run_reader()
        self.assertEqual(self.reasons(data).count('unattributed capture error'), 1)

    def test_c_b6_2_since_and_until_set_the_span(self):
        self.planted()
        _, data, _ = self.run_reader('--since', '2000-01-01T00:00:00Z', '--until', '2099-01-01T00:00:00Z')
        self.assertEqual(self.reasons(data).count('unattributed capture error'), 2)
        _, data, _ = self.run_reader('--since', '2000-01-01T00:00:00Z', '--until', '2000-01-02T00:00:00Z')
        self.assertEqual(self.reasons(data).count('unattributed capture error'), 0)
        self.assertFalse([r for r in self.reasons(data) if r.startswith('record unattributed')])

    def test_c_b6_2_control_with_error_line_reading_off_none_appears(self):
        self.planted()
        calls = self.reader()
        with mock.patch.object(calls, 'error_lines', lambda folder: []), \
                mock.patch.object(calls, 'unattributed_lines', lambda folder: []):
            code, data, _ = self.run_reader(module=calls)
        reasons = self.reasons(data)
        for prefix in ('record rejected', 'write failed', 'unattributed capture error', 'record unattributed'):
            self.assertFalse([r for r in reasons if r.startswith(prefix)], prefix)
        self.assertEqual(code, 0, 'revision 2: silent, exit 0')


# ---------------------------------------------------------------------------
# C-B6-3: Gap 2, a return with no dispatch, and a dispatch with no return
# ---------------------------------------------------------------------------

class CB6_3Gap2(World):

    def test_c_b6_3_a_return_with_no_dispatch_is_a_row_and_an_absence_with_its_witnesses(self):
        self.feed(self.l1()[:4], pause=0.01)
        copy = self.copy_ledger(lambda line: line['record'] == 'dispatch' and line['call_id'] == FOREGROUND_CALL)
        code, data, _ = self.run_reader(ledger=copy)
        self.assertEqual(code, 0)
        self.assertEqual(len(data['calls']), 1)
        row = data['calls'][0]
        self.assertEqual(row['call_id'], FOREGROUND_CALL)
        back = [r for r in lines_of(self.ledger_file(copy)) if r['record'] == 'return'][0]
        self.assertEqual(row['dispatched_at'], back['dispatched_at'], 'the frame is the return record\'s')
        for name in ('model_requested', 'brief_path', 'brief_source', 'auth_route', 'task'):
            self.assertEqual(row[name], 'unrecorded (no dispatch record)', name)
        self.assertEqual(row['outcome'], 'served')
        self.assertEqual(self.reasons(data), ['no dispatch record'])
        witnesses = data['absences'][0]['witnesses']
        start = [w for w in lines_of(self.ledger_file()) if w['record'] == 'witness' and w['event'] == 'SubagentStart']
        self.assertEqual(witnesses[0], {'event': 'SubagentStart', 'at': start[0]['at']})
        self.assertEqual([w['event'] for w in witnesses], ['SubagentStart', 'SubagentStop'])

    def test_c_b6_3_a_dispatch_whose_subagent_stopped_reads_as_a_failed_return_capture(self):
        rows = self.l1()
        background = rows[4:]
        self.feed(background[:3], pause=0.01)
        stop = background[3]
        # The transcript as it stood part-written, so the capture waits, and the harness's time-out
        # stops it after its witness line: the case §3e names.
        path = Path(stop['payload']['agent_transcript_path'])
        path.write_text(''.join(path.read_text(encoding='utf-8').splitlines(True)[:2]), encoding='utf-8')
        with self.assertRaises(subprocess.TimeoutExpired):
            subprocess.run([sys.executable, str(CAPTURE_PY), 'SubagentStop', '--ledger', str(self.ledger)],
                           input=json.dumps(stop['payload']), text=True, capture_output=True, timeout=3)
        code, data, _ = self.run_reader()
        self.assertEqual(code, 0)
        self.assertEqual([row['call_id'] for row in data['calls']], [BACKGROUND_CALL])
        self.assertEqual(self.reasons(data), ['no return record'])
        self.assertEqual([w['event'] for w in data['absences'][0]['witnesses']], ['SubagentStart', 'SubagentStop'])

    def test_c_b6_3_a_dispatch_whose_subagent_has_not_stopped_has_no_stop_witness(self):
        self.feed(self.l1()[4:7], pause=0.01)
        _, data, _ = self.run_reader()
        self.assertEqual(self.reasons(data), ['no return record'])
        self.assertEqual([w['event'] for w in data['absences'][0]['witnesses']], ['SubagentStart'])

    def test_c_b6_3_control_without_orphan_returns_the_call_has_no_row(self):
        self.feed(self.l1()[:4], pause=0.01)
        copy = self.copy_ledger(lambda line: line['record'] == 'dispatch' and line['call_id'] == FOREGROUND_CALL)
        calls = self.reader()
        with mock.patch.object(calls, 'orphan_returns', lambda *args, **kwargs: []):
            _, data, _ = self.run_reader(module=calls, ledger=copy)
        self.assertEqual(data['calls'], [], 'revision 2: the return with no dispatch is not shown')
        self.assertNotIn('no dispatch record', self.reasons(data))

    def test_c_b6_3_control_without_the_witnesses_the_absence_cannot_say_which(self):
        self.feed(self.l1()[4:7], pause=0.01)
        calls = self.reader()
        with mock.patch.object(calls, 'witnesses_for', lambda *args, **kwargs: []):
            _, data, _ = self.run_reader(module=calls)
        self.assertEqual(data['absences'][0]['witnesses'], [])


# ---------------------------------------------------------------------------
# C-B6-4: Gap 3, the count check
# ---------------------------------------------------------------------------

class CB6_4Count(World):

    def setUp(self):
        World.setUp(self)
        self.feed(self.l1(), pause=0.01)

    def transcripts(self, parent=None):
        args = ['--count-check', '--harness', 'claude-code', '--transcript', str(parent or self.parent_transcript())]
        for path in self.lane_transcripts():
            args += ['--transcript', str(path)]
        return args

    def streamed(self):
        """The parent transcript with its first Agent row written three times."""
        rows = self.parent_transcript().read_text(encoding='utf-8').splitlines(True)
        path = self.tmp / 'streamed-parent.jsonl'
        path.write_text(rows[0] * 3 + ''.join(rows[1:]), encoding='utf-8')
        return path

    def cut(self):
        return self.copy_ledger(lambda line: line['record'] in ('dispatch', 'return')
                                and line.get('call_id') == BACKGROUND_CALL)

    def test_c_b6_4_one_dispatch_missing_from_the_ledger_is_a_difference_of_one(self):
        code, data, text = self.run_reader(*self.transcripts(), ledger=self.cut())
        self.assertEqual(code, 4)
        check = data['count_check']
        self.assertEqual(check['harness'], 'claude-code')
        self.assertEqual(check['difference'], 1)
        parent = [entry for entry in check['by_caller'] if entry['caller'] == 'parent'][0]
        self.assertEqual((parent['transcript_count'], parent['ledger_count']), (2, 1))
        self.assertIn('1 subagent dispatches in the transcript have no record', self.reasons(data))
        self.assertNotIn(BACKGROUND_CALL, text, 'the output names no tool-call id the ledger lacks')
        prompt = self.l1()[4]['payload']['tool_input']['prompt']
        self.assertNotIn(prompt, text, 'the output holds no tool input')
        self.assertNotIn('toolu_', json.dumps(check), 'the count holds no tool-call id')

    def test_c_b6_4_the_unchanged_ledger_has_no_difference(self):
        code, data, _ = self.run_reader(*self.transcripts())
        self.assertEqual(code, 0)
        self.assertEqual(data['count_check']['difference'], 0)
        callers = sorted(entry['caller'] for entry in data['count_check']['by_caller'])
        self.assertEqual(callers, sorted(['parent', FOREGROUND_AGENT, BACKGROUND_AGENT]))

    def test_c_b6_4_a_call_on_three_streamed_rows_counts_once(self):
        code, data, _ = self.run_reader(*self.transcripts(parent=self.streamed()))
        self.assertEqual(code, 0)
        parent = [entry for entry in data['count_check']['by_caller'] if entry['caller'] == 'parent'][0]
        self.assertEqual(parent['transcript_count'], 2)

    def test_c_b6_4_an_unreadable_transcript_is_unrecorded_for_its_caller(self):
        os.chmod(self.parent_transcript(), 0)
        code, data, _ = self.run_reader(*self.transcripts())
        parent = [entry for entry in data['count_check']['by_caller'] if entry['caller'] == 'parent'][0]
        self.assertRegex(parent['transcript_count'], UNRECORDED)
        self.assertEqual(code, 0)

    def test_c_b6_4_opencode_has_no_transcript_reader(self):
        code, data, _ = self.run_reader('--count-check', '--harness', 'opencode', '--transcript',
                                        str(self.parent_transcript()))
        self.assertEqual(data['count_check'], 'unrecorded (no declaration for opencode)')
        self.assertEqual(code, 0)

    def test_c_b6_4_an_unknown_harness_is_refused(self):
        code, _, _ = self.run_reader('--count-check', '--harness', 'no-such-harness', '--transcript',
                                     str(self.parent_transcript()))
        self.assertEqual(code, 1)

    def test_c_b6_4_control_rows_counted_not_ids_the_stream_counts_three(self):
        calls = self.reader()
        with mock.patch.object(calls, 'count_of', len):
            code, data, _ = self.run_reader(*self.transcripts(parent=self.streamed()), module=calls)
        self.assertEqual(data['count_check']['difference'], 2)
        self.assertEqual(code, 4)

    def test_c_b6_4_control_without_the_count_check_the_missing_call_is_silent(self):
        code, data, text = self.run_reader(ledger=self.cut())
        self.assertEqual(code, 0, 'revision 2: no count, exit 0')
        self.assertNotIn(BACKGROUND_CALL, text)
        self.assertEqual(self.reasons(data), [])


class CB6_4CodexCount(unittest.TestCase):
    """The count check on Codex: dry run 3's parent rollout against the ledger its capture wrote."""

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix='calls-codex-test-'))
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.ledger, self.home, self.work, self.outside = (self.tmp / n for n in ('ledger', 'home', 'work', 'outside'))
        for folder in (self.ledger, self.home, self.work, self.outside):
            folder.mkdir()
        patcher = mock.patch.dict(os.environ, {'SUBAGENT_LEDGER_DIR': str(self.ledger), 'CODEX_HOME': str(self.home),
                                               'OPENAI_API_KEY': ''})
        patcher.start()
        self.addCleanup(patcher.stop)
        (self.ledger / 'config.json').write_text(json.dumps({'fields': 'all'}), encoding='utf-8')

    def fill(self, text):
        return (text.replace('${CODEX_HOME}', str(self.home)).replace('${WORK}', str(self.work))
                .replace('${OUTSIDE}', str(self.outside)))

    def test_codex_parent_rollout_counts_its_spawn_agent_calls(self):
        capture = load(CODEX_PY, 'capture_codex_for_calls_test')
        rows = [json.loads(self.fill(line)) for line in
                (FIXTURES / 'codex' / 'dr3-events.jsonl').read_text(encoding='utf-8').splitlines() if line.strip()]
        for row in rows:
            path = (row['payload'] or {}).get('agent_transcript_path')
            if path:
                Path(path).parent.mkdir(parents=True, exist_ok=True)
                Path(path).write_text(self.fill((FIXTURES / 'codex' / 'dr3-agent-rollout.jsonl').read_text(
                    encoding='utf-8')), encoding='utf-8')
        for row in rows:
            capture.handle(row['event'], json.dumps(row['payload']), None)
        session = rows[0]['payload']['session_id']
        parent = self.tmp / 'parent-rollout.jsonl'
        parent.write_text(self.fill((FIXTURES / 'codex' / 'dr3-parent-rollout.jsonl').read_text(encoding='utf-8')),
                          encoding='utf-8')
        calls = load(CALLS_PY, 'calls_codex_under_test')
        out = io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(io.StringIO()):
            code = calls.main(['--session', session, '--ledger', str(self.ledger), '--json', '--count-check',
                               '--harness', 'codex', '--transcript', str(parent)])
        data = json.loads(out.getvalue())
        self.assertEqual(code, 0)
        self.assertEqual(data['count_check']['by_caller'],
                         [{'caller': 'parent', 'transcript_count': 1, 'ledger_count': 1}])


# ---------------------------------------------------------------------------
# C-B6-5: a field not chosen, and a field on and unfilled
# ---------------------------------------------------------------------------

class CB6_5Frame(World):
    fields = 'frame'

    def test_c_b6_5_under_frame_every_selectable_field_prints_not_chosen(self):
        self.feed(self.l1()[:4], pause=0.01)
        code, data, _ = self.run_reader()
        self.assertEqual(code, 0)
        row = data['calls'][0]
        for name in SELECTABLE:
            self.assertEqual(row[name], 'not chosen', name)
        self.assertEqual(row['fields_on'], [])

    def test_c_b6_5_control_printing_the_record_as_held_loses_not_chosen(self):
        self.feed(self.l1()[:4], pause=0.01)
        calls = self.reader()
        with mock.patch.object(calls, 'field_value', lambda record, name: record.get(name) if record else None):
            _, data, _ = self.run_reader(module=calls)
        self.assertIsNone(data['calls'][0]['model'], 'without the rule a field not chosen reads as nothing')


class CB6_5All(World):
    fields = 'all'

    def test_c_b6_5_under_all_an_unfilled_field_prints_its_unrecorded_reason(self):
        self.feed(self.l1()[:4], pause=0.01)
        _, data, _ = self.run_reader()
        row = data['calls'][0]
        self.assertEqual(row['effort_assigned'], 'unrecorded (no triage: slice B7 not built)')
        self.assertEqual(row['fields_on'], list(SELECTABLE))
        for name in SELECTABLE:
            self.assertNotEqual(row[name], 'not chosen', name)


if __name__ == '__main__':
    unittest.main()
