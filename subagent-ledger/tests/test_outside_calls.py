"""Tests for searches, fetches and MCP reads, recorded on the routes `search`, `fetch` and `mcp`.

These are calls that leave the session through a harness's own web tools or an MCP server.

Each control has a half that runs on the code as built and must pass, and, where the control names one, a half that
switches one part off and shows the fault. Before these routes were built every test here failed.

Fixtures, under fixtures/outside/, with machine paths as placeholders (${CONFIG}, ${WORK}):

  * cc-rerun-events.jsonl: a live Claude Code run's hook payloads, PreToolUse and PostToolUse for one WebSearch,
    two WebFetch calls (one served, one answered HTTP 404) and one MCP read from a local test server named `note`;
  * cc-control-events.jsonl: a live run's PostToolUseFailure for a WebFetch the network egress proxy refused. Its
    PreToolUse was not recorded; the tests build one from the failure's own tool_use_id and tool_input
    (reconstructed, not observed);
  * cc-rerun-tool-uses.jsonl: the tool_use blocks of the first run's transcript, names and ids only, one written
    twice as it would be while streaming;
  * oc-probe-events.jsonl and oc-fetchok-events.jsonl: a live OpenCode run's tool.execute.before and after on
    websearch, webfetch and the `note` server's tool, in the shape this skill's plugin hands on. The three refused
    calls reached `before` only;
  * oc-failed-fetch-events.jsonl: a live OpenCode run's before on a webfetch the sandbox refused, and the general
    event that carried its failure, a message.part.updated whose tool part has state.status "error".

Codex's MCP payloads are built from its hooks documentation: nothing was observed.

No test writes to a real ledger: SUBAGENT_LEDGER_DIR names a temporary folder.

Run from the skill's folder:  python3 -m unittest discover -s tests
"""

import copy
import importlib.util
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
FIXTURES = HERE / 'fixtures' / 'outside'
PLUGIN_JS = SCRIPTS / 'opencode-plugin' / 'subagent-ledger.js'

CC_SESSION = '2089523e-d6bf-4039-a489-88a16a172507'
SEARCH_ID = 'toolu_01SNTn5vWZzEzYXMw1vWG16c'
FETCH_ID = 'toolu_01VXhEb8BW7QUN1eJZYdT8ME'
MCP_ID = 'toolu_01MSuxBLhyqJzqgs9kB7hsXF'
MISSING_ID = 'toolu_017jDmDPbRxvW87eHpLuVogB'
TOOL_SEARCH_ID = 'toolu_01M386xVsNVUgCRDdsvVMxBe'
BLOCKED_ID = 'toolu_01TwK24fRxfi5dsuFFBk6e48'
OC_SESSION = 'ses_ecd512f66ffetXVwesVA4ajcQZ'
OC_FETCHOK = 'call_01a132afb2557727ac9cce6af7ec1370'
OC_MCP = 'call_01a132aeefc072f3ac810ab057f9d540'
OC_FAILED = 'call_01a132d5d85f771e9de1eb2b3bb374ec'
UNRECORDED = re.compile(r'^unrecorded \(.+\)$')
MOVED = re.compile(r'^moved to .+\.md$')


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


class World(unittest.TestCase):
    """A ledger folder with every field on, a configuration folder and a working folder for each test."""

    config = {'fields': 'all'}

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix='outside-calls-test-'))
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.ledger = self.tmp / 'ledger'
        self.home = self.tmp / 'config'
        self.work = self.tmp / 'work'
        for folder in (self.ledger, self.home, self.work):
            folder.mkdir()
        env = {'SUBAGENT_LEDGER_DIR': str(self.ledger), 'CLAUDE_CONFIG_DIR': str(self.home)}
        patcher = mock.patch.dict(os.environ, env)
        patcher.start()
        self.addCleanup(patcher.stop)
        if self.config is not None:
            (self.ledger / 'config.json').write_text(json.dumps(self.config), encoding='utf-8')
        self.capture = load(SCRIPTS / 'capture_claude_code.py', 'capture_claude_code_outside')
        self.ledger_module = self.capture.ledger

    def fill(self, text):
        return text.replace('${CONFIG}', str(self.home)).replace('${WORK}', str(self.work))

    def events(self, name):
        return [json.loads(self.fill(line)) for line in (FIXTURES / name).read_text(encoding='utf-8').splitlines()
                if line.strip()]

    def feed(self, rows, capture=None):
        for row in rows:
            (capture or self.capture).handle(row['event'], json.dumps(row['payload']), None)

    def records(self):
        found = []
        for path in sorted(self.ledger.glob('*.jsonl')):
            if path.name != 'capture-errors.jsonl':
                found.extend(lines_of(path))
        return found

    def of(self, call_id, kind):
        found = [r for r in self.records() if r.get('call_id') == call_id and r.get('record') == kind]
        self.assertEqual(len(found), 1, 'expected one %s record for %s, found %d' % (kind, call_id, len(found)))
        return found[0]

    def errors(self):
        return lines_of(self.ledger / 'capture-errors.jsonl')

    def text_at(self, shown):
        """The text of a brief or answer copy the record names, relative to the repository root or absolute."""
        path = Path(shown)
        return path.read_text(encoding='utf-8') if path.is_absolute() else None

    def pending(self, session):
        folder = self.ledger / '.pending' / session
        return sorted(p.name for p in folder.glob('*.json')) if folder.is_dir() else []


# ---------------------------------------------------------------------------
# Claude Code: the three routes from a live run's payloads
# ---------------------------------------------------------------------------

class ClaudeCodeRoutes(World):

    def setUp(self):
        World.setUp(self)
        self.feed(self.events('cc-rerun-events.jsonl'))

    def test_four_calls_each_with_both_records(self):
        routes = {}
        for call_id in (SEARCH_ID, FETCH_ID, MCP_ID, MISSING_ID):
            sent, back = self.of(call_id, 'dispatch'), self.of(call_id, 'return')
            self.assertEqual(sent['route'], back['route'])
            routes[call_id] = sent['route']
        self.assertEqual([routes[i] for i in (SEARCH_ID, FETCH_ID, MISSING_ID, MCP_ID)],
                         ['search', 'fetch', 'fetch', 'mcp'])
        self.assertEqual(self.errors(), [])
        self.assertEqual(self.pending(CC_SESSION), [], 'a pending file outlived its return')

    def test_the_search_is_served_with_ten_items(self):
        back = self.of(SEARCH_ID, 'return')
        self.assertEqual((back['outcome'], back['outcome_reason']), ('served', 'none (served)'))
        self.assertEqual(back['harness_payload']['result_size'], {'items': 10})
        self.assertIn('searchCount', back['harness_payload']['tool_response'])
        self.assertIn('durationSeconds', back['harness_payload']['tool_response'])

    def test_the_first_fetch_is_served_with_its_byte_count(self):
        back = self.of(FETCH_ID, 'return')
        self.assertEqual(back['outcome'], 'served')
        self.assertEqual(back['harness_payload']['result_size'], {'bytes': 4664})

    def test_the_404_is_failed_class_other_from_the_code_alone(self):
        back = self.of(MISSING_ID, 'return')
        self.assertEqual(back['outcome'], 'failed')
        self.assertEqual(back['outcome_reason'], {'class': 'other', 'text': 'HTTP 404 Not Found'})

    def test_the_mcp_read_is_served_from_server_note(self):
        sent, back = self.of(MCP_ID, 'dispatch'), self.of(MCP_ID, 'return')
        self.assertEqual(back['outcome'], 'served')
        self.assertEqual(back['harness_payload']['result_size'], {'parts': 1, 'text_characters': 52})
        for record in (sent, back):
            self.assertEqual(record['harness_payload']['server'], 'note')
            self.assertEqual(record['harness_payload']['mcp_server'], {'name': 'note', 'source': 'dynamic'})

    def test_every_field_reads_as_the_table_says(self):
        for call_id, route, tool in ((SEARCH_ID, 'search', 'WebSearch'), (FETCH_ID, 'fetch', 'WebFetch'),
                                     (MCP_ID, 'mcp', 'mcp__note__read_note')):
            sent, back = self.of(call_id, 'dispatch'), self.of(call_id, 'return')
            for record in (sent, back):
                self.assertEqual(record['agent_id'], 'unrecorded (no agent: %s call)' % route)
                self.assertEqual(record['caller'], 'parent')
                self.assertEqual(record['harness'], 'claude-code')
            self.assertEqual(sent['model_requested'], 'unrecorded (none asked)')
            self.assertEqual(back['model'], 'unrecorded (the %s response names no model)' % tool)
            self.assertEqual(back['effort'], 'unrecorded (a %s call reports no effort)' % route)
            self.assertEqual(sent['effort_assigned'],
                             'unrecorded (the harness lets the caller set no effort for this call)')
            self.assertEqual(back['tokens'], 'unrecorded (a %s call reports no counters)' % route)
            self.assertEqual(back['cost'], 'unrecorded (the harness reports no cost for this route)')
            self.assertEqual(sent['auth_route'], 'unrecorded (the payload names no sign-in for a %s call)' % route)
            self.assertEqual(sent['brief_source'], "unrecorded (the brief is the tool's input)")
            self.assertEqual(back['isolation'],
                             'unrecorded (the capture reads no record of what a %s call touched)' % route)
            self.assertEqual(back['spend_line'], 'unrecorded (not a call script)')
            self.assertEqual(sent['act_kind'], 'unrecorded (a %s call names no kind; no triage ran)' % route)
            self.assertEqual(sent['triage_kind'], 'unrecorded (no triage ran)')
            self.assertEqual(sent['user_answer'], 'none (not a user decision)')
            self.assertEqual(sent['persona-name'], 'unrecorded (the brief names no persona)')
            self.assertEqual(sent['task'], 'unrecorded (the brief names no task)')
            self.assertTrue(UNRECORDED.match(sent['grouping']), sent['grouping'])
            self.assertEqual(sent['harness_payload']['effort'], {'level': 'medium'})

    def test_the_brief_is_what_was_asked_and_no_input_stays_inline(self):
        payloads = dict((row['payload']['tool_use_id'], row['payload']) for row in self.events('cc-rerun-events.jsonl')
                        if row['event'] == 'PreToolUse')
        expected = {
            SEARCH_ID: payloads[SEARCH_ID]['tool_input']['query'],
            FETCH_ID: '%s\n\n%s' % (payloads[FETCH_ID]['tool_input']['url'], payloads[FETCH_ID]['tool_input']['prompt']),
            MCP_ID: json.dumps(payloads[MCP_ID]['tool_input'], ensure_ascii=False),
        }
        for call_id, brief in expected.items():
            sent = self.of(call_id, 'dispatch')
            self.assertEqual(self.text_at(sent['brief_path']), brief)
            kept = sent['harness_payload']['tool_input']
            if call_id == MCP_ID:
                self.assertTrue(MOVED.match(kept), kept)
            else:
                moved = [kept[key] for key in (('query',) if call_id == SEARCH_ID else ('url', 'prompt'))]
                self.assertTrue(all(MOVED.match(value) for value in moved), moved)
            self.assertNotIn(brief, json.dumps(self.of(call_id, 'return')))
        self.assertEqual(self.of(SEARCH_ID, 'dispatch')['harness_payload']['tool_input']['mode'], 'standard')

    def test_the_answer_is_what_came_back_and_not_inline(self):
        posts = dict((row['payload']['tool_use_id'], row['payload']) for row in self.events('cc-rerun-events.jsonl')
                     if row['event'] == 'PostToolUse')
        back = self.of(SEARCH_ID, 'return')
        self.assertEqual(json.loads(self.text_at(back['answer_path'])), posts[SEARCH_ID]['tool_response']['results'])
        self.assertTrue(MOVED.match(back['harness_payload']['tool_response']['results']))
        back = self.of(FETCH_ID, 'return')
        self.assertEqual(self.text_at(back['answer_path']), posts[FETCH_ID]['tool_response']['result'])
        self.assertTrue(MOVED.match(back['harness_payload']['tool_response']['result']))
        self.assertEqual(back['harness_payload']['tool_response']['url'], posts[FETCH_ID]['tool_response']['url'])
        back = self.of(MCP_ID, 'return')
        self.assertEqual(self.text_at(back['answer_path']), posts[MCP_ID]['tool_response'][0]['text'])

    def test_switched_off_with_no_outside_tools_nothing_is_written(self):
        shutil.rmtree(self.ledger)
        self.ledger.mkdir()
        (self.ledger / 'config.json').write_text(json.dumps(self.config), encoding='utf-8')
        with mock.patch.object(self.capture, 'outside_route', lambda harness, tool: None):
            self.feed(self.events('cc-rerun-events.jsonl'))
        self.assertEqual(self.records(), [])


class ClaudeCodeBlockedFetch(World):

    def failure(self):
        return self.events('cc-control-events.jsonl')[0]

    def pre_from_failure(self):
        """A PreToolUse built from the failure's own tool_use_id and tool_input: reconstructed, not observed."""
        payload = dict(self.failure()['payload'])
        for key in ('error', 'is_interrupt', 'duration_ms'):
            payload.pop(key, None)
        payload['hook_event_name'] = 'PreToolUse'
        return {'event': 'PreToolUse', 'payload': payload}

    def test_the_blocked_fetch_is_failed_class_harness_error(self):
        self.feed([self.pre_from_failure(), self.failure()])
        back = self.of(BLOCKED_ID, 'return')
        self.assertEqual(back['route'], 'fetch')
        self.assertEqual(back['outcome'], 'failed')
        self.assertEqual(back['outcome_reason'], {'class': 'harness_error', 'text': self.failure()['payload']['error']})
        self.assertIs(back['harness_payload']['is_interrupt'], False)
        self.assertEqual(self.pending(self.failure()['payload']['session_id']), [])

    def test_switched_off_a_capture_reading_only_the_event_reads_the_404_served(self):
        with mock.patch.object(self.capture, 'fetch_outcome', lambda response: ('served', 'none (served)')):
            self.feed(self.events('cc-rerun-events.jsonl'))
        self.assertEqual(self.of(MISSING_ID, 'return')['outcome'], 'served')


class ClaudeCodePairedFixtures(World):
    """M4: an empty payload is refused at the payload stage; a payload shaped right with `code` removed is read as
    failed, class unreadable, and never served."""

    def test_an_empty_payload_writes_an_error_line_and_no_record(self):
        self.capture.handle('PostToolUse', '', None)
        self.assertEqual(self.records(), [])
        errors = self.errors()
        self.assertEqual(len(errors), 1)
        self.assertEqual(errors[0]['stage'], 'payload')

    def test_a_fetch_return_without_code_is_failed_unreadable(self):
        rows = [row for row in self.events('cc-rerun-events.jsonl') if row['payload']['tool_use_id'] == FETCH_ID]
        del rows[1]['payload']['tool_response']['code']
        self.feed(rows)
        back = self.of(FETCH_ID, 'return')
        self.assertEqual(back['outcome'], 'failed')
        self.assertEqual(back['outcome_reason']['class'], 'unreadable')
        self.assertTrue(any('code' in line['reason'] for line in self.errors()), self.errors())


class EmptyOutcomes(World):
    """A search whose results hold no title-and-URL item, and an MCP read whose text parts are all empty, are
    `empty`, class empty_answer: served with nothing in it. Built from the live run's payloads, with the results or
    the parts emptied (constructed, not observed: no empty answer was observed)."""

    def rows(self, call_id, change):
        rows = [row for row in self.events('cc-rerun-events.jsonl') if row['payload']['tool_use_id'] == call_id]
        change(rows[1]['payload'])
        return rows

    def empty_search(self, payload):
        payload['tool_response']['results'] = [{'tool_use_id': 'srvtoolu_empty', 'content': []}, 'No results.']

    def empty_read(self, payload):
        payload['tool_response'] = [{'type': 'text', 'text': ''}, {'type': 'text', 'text': '  '}]

    def test_a_search_with_no_items_is_empty(self):
        self.feed(self.rows(SEARCH_ID, self.empty_search))
        back = self.of(SEARCH_ID, 'return')
        self.assertEqual(back['outcome'], 'empty')
        self.assertEqual(back['outcome_reason']['class'], 'empty_answer')
        self.assertEqual(back['harness_payload']['result_size'], {'items': 0})

    def test_an_mcp_read_with_only_empty_text_is_empty(self):
        self.feed(self.rows(MCP_ID, self.empty_read))
        back = self.of(MCP_ID, 'return')
        self.assertEqual(back['outcome'], 'empty')
        self.assertEqual(back['outcome_reason']['class'], 'empty_answer')
        self.assertEqual(back['harness_payload']['result_size'], {'parts': 2, 'text_characters': 2})

    def test_switched_off_reading_any_return_as_served_the_two_read_served(self):
        served = lambda *args, **kwargs: ('served', 'none (served)', 'x', {'items': 0})  # noqa: E731
        with mock.patch.object(self.capture, 'search_reading', served), \
                mock.patch.object(self.capture, 'mcp_reading', served):
            self.feed(self.rows(SEARCH_ID, self.empty_search) + self.rows(MCP_ID, self.empty_read))
        self.assertEqual([self.of(i, 'return')['outcome'] for i in (SEARCH_ID, MCP_ID)], ['served', 'served'])


class NoRunLabel(unittest.TestCase):

    def test_no_fixture_names_the_run_it_came_from(self):
        hits = [str(path.relative_to(FIXTURES)) for path in sorted(FIXTURES.glob('*'))
                if re.search(r'dr[0-9]+', path.read_text(encoding='utf-8'))]
        self.assertEqual(hits, [])


# ---------------------------------------------------------------------------
# mcp_not_calls
# ---------------------------------------------------------------------------

def mcp_rows(server, tool_use_id, session=CC_SESSION):
    base = {'session_id': session, 'cwd': '/', 'tool_name': 'mcp__%s__do' % server, 'tool_use_id': tool_use_id,
            'tool_input': {'x': 1}, 'mcp_server': {'name': server, 'source': 'config'}}
    return [{'event': 'PreToolUse', 'payload': dict(base, hook_event_name='PreToolUse')},
            {'event': 'PostToolUse', 'payload': dict(base, hook_event_name='PostToolUse',
                                                     tool_response=[{'type': 'text', 'text': 'done'}])}]


class McpNotCalls(World):

    config = {'fields': 'all', 'mcp_not_calls': ['drive_this_machine', 'host_*']}

    def test_a_listed_server_writes_nothing_and_another_both_records(self):
        self.feed(mcp_rows('drive_this_machine', 'toolu_listed') + mcp_rows('host_view', 'toolu_prefixed')
                  + mcp_rows('reader', 'toolu_counted'))
        self.assertEqual([r for r in self.records() if r.get('call_id') in ('toolu_listed', 'toolu_prefixed')], [])
        self.assertEqual(self.errors(), [])
        self.assertEqual(self.pending(CC_SESSION), [])
        self.assertEqual(self.of('toolu_counted', 'return')['outcome'], 'served')

    def test_switched_off_with_no_setting_both_are_recorded(self):
        (self.ledger / 'config.json').write_text(json.dumps({'fields': 'all'}), encoding='utf-8')
        self.feed(mcp_rows('drive_this_machine', 'toolu_listed') + mcp_rows('reader', 'toolu_counted'))
        self.of('toolu_listed', 'return')
        self.of('toolu_counted', 'return')


# ---------------------------------------------------------------------------
# The count check
# ---------------------------------------------------------------------------

class CountCheck(World):

    def setUp(self):
        World.setUp(self)
        self.feed(self.events('cc-rerun-events.jsonl'))
        self.transcript = self.tmp / ('%s.jsonl' % CC_SESSION)
        shutil.copy(str(FIXTURES / 'cc-rerun-tool-uses.jsonl'), str(self.transcript))

    def run_reader(self, harness='claude-code'):
        done = subprocess.run([sys.executable, str(SCRIPTS / 'calls.py'), '--session', CC_SESSION, '--ledger',
                               str(self.ledger), '--json', '--count-check', '--harness', harness, '--transcript',
                               str(self.transcript)], capture_output=True, text=True)
        return done.returncode, json.loads(done.stdout), done

    def remove_fetch(self):
        path = self.ledger / ('%s.jsonl' % CC_SESSION)
        kept = [line for line in path.read_text(encoding='utf-8').splitlines() if FETCH_ID not in line]
        path.write_text('\n'.join(kept) + '\n', encoding='utf-8')

    def test_the_full_ledger_agrees(self):
        code, out, done = self.run_reader()
        self.assertEqual(code, 0, done.stderr)
        check = out['count_check']
        self.assertEqual(check['difference'], 0)
        self.assertEqual(check['outside_by_caller'],
                         [{'caller': 'parent', 'transcript_count': 4, 'ledger_count': 4}])

    def test_a_missing_fetch_is_a_difference_of_one_and_exit_4(self):
        self.remove_fetch()
        code, out, done = self.run_reader()
        self.assertEqual(code, 4, done.stderr)
        self.assertEqual(out['count_check']['difference'], 1)
        self.assertIn('1 searches, fetches or MCP reads in the transcript have no record',
                      [a['reason'] for a in out['absences']])
        printed = json.dumps(out['count_check'])
        for call_id in (SEARCH_ID, FETCH_ID, MCP_ID, MISSING_ID, TOOL_SEARCH_ID):
            self.assertNotIn(call_id, printed)

    def test_a_listed_server_is_not_counted(self):
        config = dict(self.config, mcp_not_calls=['note'])
        (self.ledger / 'config.json').write_text(json.dumps(config), encoding='utf-8')
        path = self.ledger / ('%s.jsonl' % CC_SESSION)
        path.write_text(''.join(line + '\n' for line in path.read_text(encoding='utf-8').splitlines()
                                if MCP_ID not in line), encoding='utf-8')
        code, out, done = self.run_reader()
        self.assertEqual(code, 0, done.stderr)
        self.assertEqual(out['count_check']['outside_by_caller'][0]['transcript_count'], 3)

    def test_codex_reads_no_rollout_form_yet(self):
        code, out, done = self.run_reader('codex')
        self.assertEqual(out['count_check']['outside_by_caller'],
                         'unrecorded (no observed rollout form for an MCP call on codex)')


# ---------------------------------------------------------------------------
# OpenCode, through the plugin
# ---------------------------------------------------------------------------

DRIVER = r'''
import { pathToFileURL } from "url";
import { readFileSync } from "fs";
const mod = await import(pathToFileURL(process.argv[2]).href);
const factory = Object.values(mod).find((value) => typeof value === "function");
const hooks = await factory({ directory: process.argv[3] });
const rows = readFileSync(process.argv[4], "utf8").split("\n").filter((l) => l.trim()).map((l) => JSON.parse(l));
let escaped = null;
try {
  for (const row of rows) {
    if (row.event === "before") await hooks["tool.execute.before"](row.input, row.output);
    else if (row.event === "after") await hooks["tool.execute.after"](row.input, row.output);
    else if (row.event === "event") await hooks["event"]({ event: row.payload.event });
  }
} catch (err) {
  escaped = String(err);
}
process.stderr.write(JSON.stringify({ escaped }) + "\n");
'''


class OpenCodeWorld(unittest.TestCase):

    servers = {'note': {'type': 'local', 'command': ['python3', 'note.py'], 'enabled': True}}

    def setUp(self):
        if shutil.which('node') is None:
            self.skipTest('node is not installed')
        self.tmp = Path(tempfile.mkdtemp(prefix='outside-opencode-test-'))
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.ledger = self.tmp / 'ledger'
        self.work = self.tmp / 'work'
        self.xdg = self.tmp / 'xdg'
        for folder in (self.ledger, self.work, self.xdg):
            folder.mkdir()
        (self.ledger / 'config.json').write_text(json.dumps({'fields': 'all'}), encoding='utf-8')
        (self.work / 'opencode.json').write_text(json.dumps({'mcp': self.servers}), encoding='utf-8')
        (self.tmp / 'driver.mjs').write_text(DRIVER, encoding='utf-8')

    def run_plugin(self, rows, source=None, scripts=None):
        plugin = PLUGIN_JS
        if source is not None:
            (self.tmp / 'opencode-plugin').mkdir(exist_ok=True)
            plugin = self.tmp / 'opencode-plugin' / 'subagent-ledger.js'
            plugin.write_text(source, encoding='utf-8')
        events = self.tmp / 'events.jsonl'
        events.write_text(''.join(json.dumps(row) + '\n' for row in rows), encoding='utf-8')
        env = dict(os.environ, SUBAGENT_LEDGER_SCRIPTS=str(scripts or SCRIPTS), SUBAGENT_LEDGER_DIR=str(self.ledger),
                   XDG_CONFIG_HOME=str(self.xdg), XDG_DATA_HOME=str(self.tmp / 'data'))
        done = subprocess.run(['node', str(self.tmp / 'driver.mjs'), str(plugin), str(self.work), str(events)],
                              capture_output=True, text=True, env=env, cwd=str(self.tmp), timeout=120)
        seen = [line for line in done.stderr.splitlines() if line.startswith('{"escaped"')]
        self.assertTrue(seen, done.stderr)
        self.assertIsNone(json.loads(seen[-1])['escaped'])
        return done

    def rows(self, *names):
        out = []
        for name in names:
            out.extend(json.loads(line) for line in (FIXTURES / name).read_text(encoding='utf-8').splitlines()
                       if line.strip())
        return out

    def records(self):
        found = []
        for path in sorted(self.ledger.glob('*.jsonl')):
            if path.name != 'capture-errors.jsonl':
                found.extend(lines_of(path))
        return found

    def of(self, call_id, kind):
        return [r for r in self.records() if r.get('call_id') == call_id and r.get('record') == kind]


# The plugin's three lines that hand on searches, fetches and MCP reads, each with the line the plugin had before them.
# A test rewrites a copy with the earlier lines to show what the plugin handed on before; the plugin has no switch.
OUTSIDE_PARTS = (
    ('const outside = entry.outside_tools || {};', 'const outside = {};'),
    ('function configuredServers(directory) {', 'function configuredServers(directory) {\n  return [];'),
    ('const handed = (TOOLS.has(part.tool) && part.tool !== "bash") || server;', 'const handed = part.tool === "task";'),
)


class OpenCodeRoutes(OpenCodeWorld):

    def test_the_shipped_plugin_carries_no_test_switch(self):
        self.assertNotIn('OUTSIDE_ON', PLUGIN_JS.read_text(encoding='utf-8'))

    def test_dispatches_for_all_five_and_returns_for_the_mcp_read_and_the_fetch(self):
        self.run_plugin(self.rows('oc-probe-events.jsonl', 'oc-fetchok-events.jsonl'))
        sent = [r for r in self.records() if r['record'] == 'dispatch']
        self.assertEqual(sorted(r['route'] for r in sent), ['fetch', 'fetch', 'fetch', 'mcp', 'search'])
        back = dict((r['call_id'], r) for r in self.records() if r['record'] == 'return')
        self.assertEqual(sorted(back), sorted([OC_FETCHOK, OC_MCP]))
        self.assertEqual(back[OC_FETCHOK]['outcome'], 'served')
        self.assertEqual(back[OC_FETCHOK]['harness_payload']['result_size'], {'characters': 4664})
        self.assertEqual(back[OC_FETCHOK]['harness_payload']['output']['metadata'], {'truncated': False})
        self.assertEqual(back[OC_MCP]['outcome'], 'served')
        self.assertEqual(back[OC_MCP]['harness_payload']['server'], 'note')
        self.assertEqual(back[OC_MCP]['harness_payload']['result_size'], {'parts': 1, 'text_characters': 52})
        mcp_sent = [r for r in sent if r['route'] == 'mcp'][0]
        self.assertEqual(mcp_sent['agent_id'], 'unrecorded (no agent: mcp call)')
        self.assertEqual(mcp_sent['session'], OC_SESSION)

    def test_a_failed_fetch_gets_its_return_from_the_event(self):
        self.run_plugin(self.rows('oc-failed-fetch-events.jsonl'))
        back = self.of(OC_FAILED, 'return')
        self.assertEqual(len(back), 1, self.records())
        self.assertEqual(back[0]['route'], 'fetch')
        self.assertEqual(back[0]['outcome'], 'failed')
        self.assertIn('403 GET', back[0]['outcome_reason']['text'])
        self.assertEqual(back[0]['harness_payload']['event_type'], 'message.part.updated')

    def test_switched_off_the_task_and_bash_plugin_hands_none_on(self):
        source = PLUGIN_JS.read_text(encoding='utf-8')
        old = source
        for anchor, earlier in OUTSIDE_PARTS:
            self.assertIn(anchor, old)
            old = old.replace(anchor, earlier)
        self.run_plugin(self.rows('oc-probe-events.jsonl', 'oc-fetchok-events.jsonl', 'oc-failed-fetch-events.jsonl'),
                        source=old)
        self.assertEqual(self.records(), [])


class OpenCodeMcpNaming(OpenCodeWorld):

    servers = {'note': {'type': 'local'}, 'note_read': {'type': 'local'}}

    def recorder(self):
        """A scripts folder whose capture writes down what it was handed, with the real subagent-tools.json."""
        folder = self.tmp / 'scripts'
        folder.mkdir()
        shutil.copy(str(SCRIPTS / 'subagent-tools.json'), str(folder / 'subagent-tools.json'))
        seen = self.tmp / 'seen.jsonl'
        (folder / 'capture_opencode.py').write_text(
            'import json, sys\nopen(%r, "a").write(json.dumps({"argv": sys.argv[1:], "stdin": json.loads(sys.stdin.read())}) '
            '+ "\\n")\n' % str(seen), encoding='utf-8')
        return folder, seen

    def before(self, tool, call_id):
        return {'event': 'before', 'input': {'tool': tool, 'sessionID': 'ses_x', 'callID': call_id},
                'output': {'args': {'name': 'alpha'}}}

    def test_a_configured_server_is_handed_on_and_an_unknown_prefix_is_not(self):
        folder, seen = self.recorder()
        self.run_plugin([self.before('note_read_note', 'c1'), self.before('notebook_x', 'c2'),
                         self.before('note_read_x', 'c3')], scripts=folder)
        handed = lines_of(seen)
        self.assertEqual([h['stdin']['input']['callID'] for h in handed], ['c1', 'c3'])
        self.assertEqual([h['stdin']['mcp_server'] for h in handed], ['note_read', 'note_read'])

    def test_the_capture_records_the_server_from_the_configuration(self):
        self.run_plugin([self.before('note_read_note', 'c1'), self.before('notebook_x', 'c2')])
        sent = [r for r in self.records() if r['record'] == 'dispatch']
        self.assertEqual([(r['call_id'], r['route'], r['harness_payload']['server']) for r in sent],
                         [('c1', 'mcp', 'note_read')])


# ---------------------------------------------------------------------------
# Codex: MCP tools, from documentation-shaped payloads
# ---------------------------------------------------------------------------

class CodexMcp(World):

    def codex_rows(self):
        base = {'session_id': '019a0000-0000-7000-8000-00000000c0de', 'transcript_path': None, 'cwd': str(self.work),
                'model': 'a-model', 'tool_name': 'mcp__fs__read', 'tool_use_id': 'call_codex_mcp_1',
                'tool_input': {'path': 'notes.txt'}}
        return [{'event': 'PreToolUse', 'payload': dict(base, hook_event_name='PreToolUse')},
                {'event': 'PostToolUse', 'payload': dict(base, hook_event_name='PostToolUse',
                                                         tool_response=json.dumps([{'type': 'text', 'text': 'hello'}]))}]

    def test_both_records_route_mcp_server_fs(self):
        codex = load(SCRIPTS / 'capture_codex.py', 'capture_codex_outside')
        self.feed(self.codex_rows(), capture=codex)
        sent, back = self.of('call_codex_mcp_1', 'dispatch'), self.of('call_codex_mcp_1', 'return')
        self.assertEqual((sent['route'], back['route']), ('mcp', 'mcp'))
        self.assertEqual((sent['harness'], sent['harness_payload']['server']), ('codex', 'fs'))
        self.assertEqual(back['outcome'], 'served')
        self.assertEqual(sent['agent_id'], 'unrecorded (no agent: mcp call)')
        self.assertEqual(self.errors(), [])


# ---------------------------------------------------------------------------
# The schema
# ---------------------------------------------------------------------------

class Schema(unittest.TestCase):

    def record(self, route):
        record = json.loads((HERE / 'fixtures' / 'valid-dispatch.json').read_text(encoding='utf-8'))
        record['fields_not_chosen'].remove('route')
        record['fields_on'].append('route')
        record['route'] = route
        return record

    def test_the_three_routes_validate_and_web_does_not(self):
        ledger = load(SCRIPTS / 'ledger.py', 'ledger_outside_schema')
        for route in ('search', 'fetch', 'mcp'):
            self.assertEqual(ledger.validate(self.record(route), ref='#/$defs/dispatch'), [], route)
        self.assertNotEqual(ledger.validate(self.record('web'), ref='#/$defs/dispatch'), [])


if __name__ == '__main__':
    unittest.main()
