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


if __name__ == '__main__':
    unittest.main()
