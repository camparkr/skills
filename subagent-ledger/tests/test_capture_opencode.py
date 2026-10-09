"""Tests for OpenCode's capture: `skill/scripts/capture_opencode.py` and the plugin that feeds it,
`skill/scripts/opencode-plugin/subagent-ledger.js`.

Controls C-B3-4, C-B3-5 and the OpenCode half of C-B3-9. Each has a half that runs on the code as
built and must pass, and a half that switches one part off and shows the fault. Before the capture
existed every test here failed, because the files it loads were missing.

Fixtures, under fixtures/opencode/, with machine paths as placeholders (${WORK}):

  * dr3-events.jsonl: a live run's plugin events, `tool.execute.before` and `after` on `task`, and the
    subagent's own `read`. Dry run 3's recording plugin wrote `args: output.args` for `before`; the
    lines are put here in the shape this skill's plugin sends, `{event, input, output}`, nothing else
    changed;
  * p2-failed-events.jsonl: a live run whose subagent failed (its read was refused). OpenCode 1.18.30
    sent `before` on `task` and no `after`;
  * db-rows.json: the two child sessions' rows from OpenCode's database, read read-only: the session's
    `directory` and each tool part's input. The tests build a database of the same columns from it.

The plugin control runs Node.

Run from the skill's folder:  python3 -m unittest discover -s tests
"""

import importlib.util
import json
import os
import re
import shutil
import sqlite3
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

HERE = Path(__file__).resolve().parent
SCRIPTS = HERE.parent / 'skill' / 'scripts'
FIXTURES = HERE / 'fixtures' / 'opencode'
CAPTURE_PY = SCRIPTS / 'capture_opencode.py'
PLUGIN_JS = SCRIPTS / 'opencode-plugin' / 'subagent-ledger.js'

CHILD = 'ses_ee2492402ffeIl7h0yS59kU4o6'
PARENT = 'ses_ee24931b0ffekK53kq8231SmSB'
CALL = 'call_01a11db6d9ff740e929677c845d87f71'
UNRECORDED = re.compile(r'^unrecorded \(.+\)$')


def load(path, name):
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


def build_database(path, rows, work):
    """A database with the columns the capture reads, filled from db-rows.json."""
    db = sqlite3.connect(str(path))
    db.execute('create table session (id text primary key, parent_id text, directory text, agent text, model text)')
    db.execute('create table part (id text primary key, message_id text, session_id text, time_created integer, data text)')
    for row in rows['session']:
        db.execute('insert into session values (?, ?, ?, ?, ?)',
                   (row['id'], row['parent_id'], row['directory'].replace('${WORK}', work), row['agent'],
                    row['model']))
    for number, row in enumerate(rows['part']):
        db.execute('insert into part values (?, ?, ?, ?, ?)',
                   (row['id'], 'msg', row['session_id'], number,
                    json.dumps(row['data']).replace('${WORK}', work)))
    db.commit()
    db.close()


class World(unittest.TestCase):

    fields = None

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix='capture-opencode-test-'))
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.ledger = self.tmp / 'ledger'
        self.work = self.tmp / 'work'
        self.data = self.tmp / 'data' / 'opencode'
        for folder in (self.ledger, self.work, self.data):
            folder.mkdir(parents=True)
        rows = json.loads((FIXTURES / 'db-rows.json').read_text(encoding='utf-8'))
        build_database(self.data / 'opencode.db', rows, str(self.work))
        env = {'SUBAGENT_LEDGER_DIR': str(self.ledger), 'XDG_DATA_HOME': str(self.tmp / 'data')}
        patcher = mock.patch.dict(os.environ, env)
        patcher.start()
        self.addCleanup(patcher.stop)
        if self.fields is not None:
            (self.ledger / 'config.json').write_text(json.dumps({'fields': self.fields}), encoding='utf-8')
        self.capture = load(CAPTURE_PY, 'capture_opencode_under_test')

    def events(self, name):
        return [json.loads(line.replace('${WORK}', str(self.work))) for line in
                (FIXTURES / name).read_text(encoding='utf-8').splitlines() if line.strip()]

    def feed(self, rows):
        for row in rows:
            if 'input' not in row:
                continue  # the recording plugin's own start line, not a tool event
            self.capture.handle(row['event'], json.dumps({'input': row['input'], 'output': row['output']}), None)

    def records(self):
        found = []
        for path in sorted(self.ledger.glob('*.jsonl')):
            if path.name != 'capture-errors.jsonl':
                found.extend(lines_of(path))
        return found

    def errors(self):
        return lines_of(self.ledger / 'capture-errors.jsonl')


# ---------------------------------------------------------------------------
# C-B3-4: before and after on task give both records
# ---------------------------------------------------------------------------

class CB3_4Task(World):

    def test_c_b3_4_both_records_joined_by_call_id(self):
        self.feed(self.events('dr3-events.jsonl'))
        self.assertEqual(self.errors(), [])
        dispatch, back = self.records()
        self.assertEqual((dispatch['record'], back['record']), ('dispatch', 'return'))
        self.assertEqual((dispatch['call_id'], back['call_id']), (CALL, CALL))
        self.assertEqual(back['agent_id'], CHILD)
        self.assertEqual(dispatch['session'], PARENT)
        self.assertEqual(back['model'], 'opencode/muse-spark-1.3-contributor-free')
        self.assertEqual(back['tokens'], 'unrecorded (no declaration for opencode)')
        self.assertEqual(back['outcome'], 'served')
        self.assertEqual(dispatch['model_requested'], 'unrecorded (none asked)')

    def test_c_b3_4_a_before_on_read_writes_nothing(self):
        reads = [row for row in self.events('dr3-events.jsonl') if row['input']['tool'] == 'read']
        self.assertEqual(len(reads), 2)
        self.feed(reads)
        self.assertEqual(self.records(), [])
        self.assertEqual(self.errors(), [])

    def test_c_b3_4_control_tool_filter_switched_off_records_the_read(self):
        reads = [row for row in self.events('dr3-events.jsonl') if row['input']['tool'] == 'read']
        with mock.patch.object(self.capture, 'is_subagent_tool', lambda tool: True):
            self.feed(reads[:1])
        self.assertEqual([line['record'] for line in self.records()], ['dispatch'],
                         'without the filter a read is taken for a subagent call')

    def test_a_failed_task_leaves_a_dispatch_and_no_return(self):
        self.feed(self.events('p2-failed-events.jsonl'))
        self.assertEqual([line['record'] for line in self.records()], ['dispatch'])


class CB3_4AllFields(World):

    fields = 'all'

    def test_isolation_from_the_database(self):
        self.feed(self.events('dr3-events.jsonl'))
        dispatch, back = self.records()
        self.assertEqual((dispatch['harness'], back['harness']), ('opencode', 'opencode'))
        self.assertEqual(dispatch['harness_payload']['args']['subagent_type'], 'general')
        isolation = back['isolation']
        self.assertEqual(isolation['folder'], str(self.work))
        self.assertEqual(isolation['outside'], [])
        self.assertIn('shell tool', isolation['limit'])
        self.assertTrue(isolation['read_from'].endswith('opencode.db'))

    def test_a_read_outside_the_folder_is_listed(self):
        db = sqlite3.connect(str(self.data / 'opencode.db'))
        db.execute('insert into part values (?, ?, ?, ?, ?)', (
            'prt_planted', 'msg', CHILD, 99, json.dumps({'type': 'tool', 'tool': 'read', 'state': {
                'status': 'completed', 'input': {'filePath': '/elsewhere/notes.md'}}})))
        db.commit()
        db.close()
        self.feed(self.events('dr3-events.jsonl'))
        outside = self.records()[-1]['isolation']['outside']
        self.assertEqual([entry.get('filePath') for entry in outside], ['/elsewhere/notes.md'])

    def test_the_brief_and_answer_are_not_inline(self):
        self.feed(self.events('dr3-events.jsonl'))
        text = ''.join(path.read_text(encoding='utf-8') for path in self.ledger.glob('*.jsonl'))
        self.assertNotIn('reply with the token it holds', text)
        self.assertNotIn('<task_result>', text)


# ---------------------------------------------------------------------------
# C-B3-5: the plugin never throws, never prints and never changes the call
# ---------------------------------------------------------------------------

DRIVER = r'''
import { pathToFileURL } from "url";
const mod = await import(pathToFileURL(process.argv[2]).href);
const factory = Object.values(mod).find((value) => typeof value === "function");
const hooks = await factory({ directory: process.cwd() });
const input = { tool: "task", sessionID: "ses_parent", callID: "call_1" };
const output = { args: { description: "d", prompt: "read brief.md", subagent_type: "general" } };
const before = JSON.stringify(output);
let escaped = null;
try {
  await hooks["tool.execute.before"](input, output);
  const after = { title: "t", output: "<task_result>x</task_result>", metadata: { sessionId: "ses_child" } };
  await hooks["tool.execute.after"]({ ...input, args: output.args }, after);
} catch (err) {
  escaped = String(err);
}
process.stderr.write(JSON.stringify({ escaped, unchanged: JSON.stringify(output) === before }) + "\n");
'''


class CB3_5Plugin(unittest.TestCase):

    def setUp(self):
        if not PLUGIN_JS.is_file():
            raise AssertionError('subagent-ledger.js does not exist yet: the code this control tests is not built')
        if shutil.which('node') is None:
            self.skipTest('node is not installed')
        self.tmp = Path(tempfile.mkdtemp(prefix='opencode-plugin-test-'))
        self.addCleanup(shutil.rmtree, self.tmp, True)
        (self.tmp / 'opencode-plugin').mkdir()
        self.failing = self.tmp / 'capture_opencode.py'
        self.failing.write_text('import sys\nprint("noise on stdout")\nprint("noise on stderr", file=sys.stderr)\n'
                                'sys.exit(1)\n', encoding='utf-8')
        (self.tmp / 'driver.mjs').write_text(DRIVER, encoding='utf-8')

    def run_plugin(self, source):
        plugin = self.tmp / 'opencode-plugin' / 'subagent-ledger.js'
        plugin.write_text(source, encoding='utf-8')
        env = dict(os.environ, SUBAGENT_LEDGER_SCRIPTS=str(self.tmp), SUBAGENT_LEDGER_DIR=str(self.tmp / 'ledger'))
        done = subprocess.run(['node', str(self.tmp / 'driver.mjs'), str(plugin)], capture_output=True,
                              text=True, env=env, cwd=str(self.tmp), timeout=60)
        lines = [line for line in done.stderr.splitlines() if line.startswith('{"escaped"')]
        return done, (json.loads(lines[-1]) if lines else None)

    def source(self):
        return PLUGIN_JS.read_text(encoding='utf-8')

    def test_c_b3_5_a_failing_capture_changes_nothing_and_prints_nothing(self):
        done, seen = self.run_plugin(self.source())
        self.assertEqual(done.returncode, 0, done.stderr)
        self.assertIsNotNone(seen, done.stderr)
        self.assertIsNone(seen['escaped'])
        self.assertTrue(seen['unchanged'])
        self.assertEqual(done.stdout, '')
        self.assertNotIn('noise', done.stderr)

    def test_c_b3_5_control_output_passed_through_prints(self):
        source = self.source()
        self.assertIn("stdio: ['pipe', 'ignore', 'ignore']", source)
        done, _ = self.run_plugin(source.replace("stdio: ['pipe', 'ignore', 'ignore']", "stdio: ['pipe', 'inherit', 'inherit']"))
        self.assertIn('noise on stdout', done.stdout)

    def test_c_b3_5_control_the_guard_switched_off_lets_an_error_escape(self):
        source = self.source()
        self.assertIn('/* guard */ catch (err) {}', source)
        broken = source.replace('/* guard */ catch (err) {}', '/* guard */ catch (err) { throw err; }')
        broken = broken.replace('spawnSync(', 'mustSpawn(')
        broken = 'function mustSpawn(...a) { throw new Error("spawn failed"); }\n' + broken
        done, seen = self.run_plugin(broken)
        self.assertIsNotNone(seen, done.stderr)
        self.assertIsNotNone(seen['escaped'])


# ---------------------------------------------------------------------------
# C-B3-9: bad input exits 0, prints nothing and leaves one error line
# ---------------------------------------------------------------------------

class CB3_9BadInput(World):

    def bad_inputs(self):
        row = self.events('dr3-events.jsonl')[0]
        row['input'].pop('callID')
        return [('not JSON', 'this is not json'), ('empty', ''),
                ('no call id', json.dumps({'input': row['input'], 'output': row['output']}))]

    def test_c_b3_9_each_exits_0_prints_nothing_and_leaves_one_error_line(self):
        if not CAPTURE_PY.is_file():
            raise AssertionError('capture_opencode.py does not exist yet')
        for count, (name, text) in enumerate(self.bad_inputs(), start=1):
            with self.subTest(name=name):
                done = subprocess.run([sys.executable, str(CAPTURE_PY), 'before', '--ledger', str(self.ledger)],
                                      input=text, capture_output=True, text=True, timeout=60)
                self.assertEqual(done.returncode, 0)
                self.assertEqual(done.stdout, '')
                self.assertEqual(len(self.errors()), count)
                self.assertEqual(self.errors()[-1]['harness'], 'opencode')
        self.assertEqual(self.records(), [])

    def test_c_b3_9_control_error_lines_switched_off_leave_nothing(self):
        with mock.patch.object(self.capture.ledger, 'error', lambda *a, **k: None):
            for _, text in self.bad_inputs():
                self.capture.handle('before', text, None)
        self.assertEqual(self.errors(), [])
        self.assertEqual(self.records(), [])



# ---------------------------------------------------------------------------
# C-RB3-1 to C-RB3-4: a failed subagent's return from OpenCode's general event stream (B3 rework)
#
# Fixtures, from the rework's probe of 9 October 2026 (OpenCode 1.18.30), every event the recording
# plugin saw, in the shape this skill's plugin sends. Tool hooks are {event, input, output}; the
# general event hook is {event: "event", type, payload: {event}}. Bulk events with no session or
# tool state (plugin.added, catalog, reference and integration updates, message.part.delta) are
# left out. Machine paths are placeholders (${RUN}, ${WORK}):
#
#   * rb3-failed-events.jsonl: a `task` whose subagent's read of /etc/hosts was refused. No `after`
#     on `task`; the parent session's `message.part.updated` carries the task part with
#     state.status "error", its error text, the same callID as `before`, and the child session in
#     state.metadata.sessionId;
#   * rb3-served-events.jsonl: a `task` whose subagent read brief.md. `after` on `task` came first,
#     then the part's state.status "completed".
# ---------------------------------------------------------------------------

FAILED_PARENT = 'ses_edffb5415ffeWq4Y3lzMs2IXXS'
FAILED_CHILD = 'ses_edffb461affejItzaRmKfeV6Pg'
FAILED_CALL = 'call_01a12004b78f72c59d5bd4838ca593c3'
SERVED_PARENT = 'ses_edffa919cffeqPklyk5MgA6OHF'
SERVED_CALL = 'call_01a120057972743d92020359545b7b79'
EVENT_TYPE = 'message.part.updated'


class EventStream(World):

    fields = 'all'

    def stream(self, name):
        text = (FIXTURES / name).read_text(encoding='utf-8')
        text = text.replace('${WORK_RELATIVE}', str(self.work).lstrip('/'))
        text = text.replace('${WORK}', str(self.work)).replace('${RUN}', str(self.tmp))
        return [json.loads(line) for line in text.splitlines() if line.strip()]

    def replay(self, rows):
        for row in rows:
            if row['event'] == 'event':
                self.capture.handle('event', json.dumps(dict(row['payload'], directory=str(self.work))), None)
            else:
                self.capture.handle(row['event'], json.dumps({'input': row['input'], 'output': row['output'],
                                                              'directory': str(self.work)}), None)

    def task_error_event(self, session, call_id, text='Subagent failed (task_id: ses_x): planted failure'):
        return {'event': 'event', 'type': EVENT_TYPE, 'payload': {'event': {
            'id': 'evt_planted', 'type': EVENT_TYPE, 'properties': {'sessionID': session, 'part': {
                'type': 'tool', 'tool': 'task', 'callID': call_id, 'sessionID': session,
                'state': {'status': 'error', 'error': text, 'input': {'prompt': 'planted'},
                          'metadata': {'sessionId': 'ses_planted_child'}}}}}}}

    def task_before(self, session, call_id):
        return {'event': 'before', 'input': {'tool': 'task', 'sessionID': session, 'callID': call_id},
                'output': {'args': {'description': 'd', 'prompt': 'planted brief %s' % call_id,
                                    'subagent_type': 'general'}}}

    def kinds(self):
        return [(line['record'], line['call_id']) for line in self.records()]


class CRB3_1FailedFromEvents(EventStream):

    def test_c_rb3_1_a_failed_task_gets_a_failed_return_with_its_class(self):
        self.replay(self.stream('rb3-failed-events.jsonl'))
        self.assertEqual(self.errors(), [])
        self.assertEqual(self.kinds(), [('dispatch', FAILED_CALL), ('return', FAILED_CALL)])
        dispatch, back = self.records()
        self.assertEqual(back['outcome'], 'failed')
        self.assertEqual(back['outcome_reason']['class'], 'harness_error')
        self.assertIn('rejected permission', back['outcome_reason']['text'])
        self.assertEqual(back['agent_id'], FAILED_CHILD)
        self.assertEqual(back['session'], FAILED_PARENT)
        self.assertEqual(back['dispatched_at'], dispatch['dispatched_at'])
        self.assertEqual(back['model'], 'opencode/muse-spark-1.3-contributor-free')
        self.assertEqual(back['harness_payload']['event_type'], EVENT_TYPE)
        self.assertEqual(list(self.ledger.glob('.pending/*/call_*.json')), [], 'the dispatch is no longer pending')

    def test_c_rb3_1_control_event_handling_switched_off_leaves_the_dispatch_alone(self):
        with mock.patch.object(self.capture, 'on_event', lambda *args, **kwargs: None):
            self.replay(self.stream('rb3-failed-events.jsonl'))
        self.assertEqual(self.kinds(), [('dispatch', FAILED_CALL)], 'as at 0a3fdf3: a dispatch and no return')


class CRB3_2NoSecondReturn(EventStream):

    def test_c_rb3_2_a_served_task_has_one_return_from_after(self):
        rows = self.stream('rb3-served-events.jsonl')
        rows.append(self.task_error_event(SERVED_PARENT, SERVED_CALL))  # a later event for the same call
        self.replay(rows)
        self.assertEqual(self.kinds(), [('dispatch', SERVED_CALL), ('return', SERVED_CALL)])
        self.assertEqual(self.records()[1]['outcome'], 'served')
        self.assertEqual(self.errors(), [])

    def test_c_rb3_2_control_the_return_check_switched_off_gives_a_second_return(self):
        rows = self.stream('rb3-served-events.jsonl')
        rows.append(self.task_error_event(SERVED_PARENT, SERVED_CALL))
        with mock.patch.object(self.capture, 'already_returned', lambda *args: False), \
                mock.patch.object(self.capture.shared, 'clear_pending', lambda *args: None):
            self.replay(rows)
        self.assertEqual([kind for kind, _ in self.kinds()], ['dispatch', 'return', 'return'])


class CRB3_3NoGuess(EventStream):

    def test_c_rb3_3_an_event_tied_to_neither_pending_dispatch_gives_one_error_line_and_no_return(self):
        self.replay([self.task_before('ses_two', 'call_first'), self.task_before('ses_two', 'call_second'),
                     self.task_error_event('ses_two', 'call_neither')])
        self.assertEqual([kind for kind, _ in self.kinds()], ['dispatch', 'dispatch'])
        errors = self.errors()
        self.assertEqual(len(errors), 1)
        self.assertIn('call_first', errors[0]['reason'])
        self.assertIn('call_second', errors[0]['reason'])
        self.assertEqual(errors[0]['harness'], 'opencode')

    def test_c_rb3_3_control_a_guessing_tie_writes_a_return(self):
        self.replay([self.task_before('ses_two', 'call_first'), self.task_before('ses_two', 'call_second')])
        guess = lambda pending, call_id: sorted(pending)[0]  # noqa: E731
        with mock.patch.object(self.capture, 'tie', guess):
            self.replay([self.task_error_event('ses_two', 'call_neither')])
        self.assertIn('return', [kind for kind, _ in self.kinds()])


EVENT_DRIVER = r'''
import { pathToFileURL } from "url";
const mod = await import(pathToFileURL(process.argv[2]).href);
const factory = Object.values(mod).find((value) => typeof value === "function");
const hooks = await factory({ directory: process.cwd() });
const part = { type: "tool", tool: "task", callID: "call_1", sessionID: "ses_parent",
               state: { status: "error", error: "Subagent failed", metadata: { sessionId: "ses_child" } } };
const events = [
  { event: { id: "e1", type: "message.part.delta", properties: { sessionID: "ses_parent", delta: "x" } } },
  { event: { id: "e2", type: "message.part.updated", properties: { sessionID: "ses_parent", part } } },
];
const before = JSON.stringify(events);
let escaped = null;
try {
  for (const e of events) await hooks["event"](e);
} catch (err) {
  escaped = String(err);
}
process.stderr.write(JSON.stringify({ escaped, unchanged: JSON.stringify(events) === before }) + "\n");
'''


class CRB3_4PluginEvent(unittest.TestCase):

    setUp = CB3_5Plugin.setUp
    source = CB3_5Plugin.source

    def run_event(self, source, capture=None):
        if capture is not None:
            self.failing.write_text(capture, encoding='utf-8')
        plugin = self.tmp / 'opencode-plugin' / 'subagent-ledger.js'
        plugin.write_text(source, encoding='utf-8')
        (self.tmp / 'event-driver.mjs').write_text(EVENT_DRIVER, encoding='utf-8')
        env = dict(os.environ, SUBAGENT_LEDGER_SCRIPTS=str(self.tmp), SUBAGENT_LEDGER_DIR=str(self.tmp / 'ledger'))
        done = subprocess.run(['node', str(self.tmp / 'event-driver.mjs'), str(plugin)], capture_output=True,
                              text=True, env=env, cwd=str(self.tmp), timeout=60)
        lines = [line for line in done.stderr.splitlines() if line.startswith('{"escaped"')]
        return done, (json.loads(lines[-1]) if lines else None)

    def test_c_rb3_4_a_failing_capture_on_an_event_throws_nothing_and_prints_nothing(self):
        done, seen = self.run_event(self.source())
        self.assertEqual(done.returncode, 0, done.stderr)
        self.assertIsNotNone(seen, done.stderr)
        self.assertIsNone(seen['escaped'])
        self.assertTrue(seen['unchanged'])
        self.assertEqual(done.stdout, '')
        self.assertNotIn('noise', done.stderr)

    def test_c_rb3_4_only_the_task_part_event_reaches_the_capture(self):
        seen_file = self.tmp / 'seen.txt'
        recorder = ('import sys\nopen(%r, "a").write(" ".join(sys.argv[1:]) + "\\n")\n' % str(seen_file))
        self.run_event(self.source(), capture=recorder)
        self.assertTrue(seen_file.is_file(), 'the capture was never run for an event')
        self.assertEqual(seen_file.read_text(encoding='utf-8').splitlines()[0].split()[:2],
                         ['event', 'message.part.updated'])
        self.assertEqual(len(seen_file.read_text(encoding='utf-8').splitlines()), 1)

    def test_c_rb3_4_control_the_guard_switched_off_lets_an_event_error_escape(self):
        source = self.source()
        self.assertIn('/* event guard */ catch (err) {}', source)
        broken = source.replace('/* event guard */ catch (err) {}', '/* event guard */ catch (err) { throw err; }')
        broken = broken.replace('spawnSync(', 'mustSpawn(')
        broken = 'function mustSpawn(...a) { throw new Error("spawn failed"); }\n' + broken
        done, seen = self.run_event(broken)
        self.assertIsNotNone(seen, done.stderr)
        self.assertIsNotNone(seen['escaped'])

if __name__ == '__main__':
    unittest.main()
