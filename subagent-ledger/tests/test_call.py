"""Tests for the call script, `skill/scripts/call.py`, with stand-in harnesses.

No test starts a real harness: stand-in `gemini` and `cursor-agent`
programs on PATH print a recorded envelope, write the run's own record where the real harness writes
it (a Gemini chat under the configuration folder, a Cursor chat store), and log the configuration
variable and working folder they were started with.

Fixtures, under fixtures/call/:

  * gemini-envelope.json and gemini-chat.jsonl: a live `gemini -p -o json` run's printed envelope and
    its chat record, thoughts cut, paths as placeholders;
  * cursor-envelope.json: a recorded `cursor-agent -p --output-format json` envelope, its answer
    replaced by a short token; cursor-usage-limit.err and cursor-eperm.err: two recorded failures.

Run from the skill's folder:  python3 -m unittest discover -s tests
"""

import contextlib
import importlib.util
import io
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
FIXTURES = HERE / 'fixtures' / 'call'
CALL_PY = SCRIPTS / 'call.py'
UNRECORDED = re.compile(r'^unrecorded \(.+\)$')

GEMINI_STANDIN = r'''#!/usr/bin/env python3
import json, os, sys
from pathlib import Path
fixtures = Path(os.environ['STANDIN_FIXTURES'])
here = os.path.realpath(os.getcwd())
with open(os.environ['STANDIN_LOG'], 'a') as log:
    log.write(json.dumps({'harness': 'gemini', 'variable': os.environ.get('GEMINI_CLI_HOME'),
                          'cwd': here, 'argv': sys.argv[1:]}) + '\n')
if os.environ.get('STANDIN_FAIL'):
    print(os.environ['STANDIN_FAIL'], file=sys.stderr)
    sys.exit(1)
home = Path(os.environ.get('GEMINI_CLI_HOME') or Path.home()) / '.gemini'
project = home / 'tmp' / os.path.basename(here)
(project / 'chats').mkdir(parents=True, exist_ok=True)
(project / '.project_root').write_text(here)
chat = (fixtures / 'gemini-chat.jsonl').read_text().replace('${WORK}', here).replace('${HOME}', str(home.parent))
(project / 'chats' / 'session-2026-10-09T06-34-08ed128a.jsonl').write_text(chat)
sys.stdout.write((fixtures / 'gemini-envelope.json').read_text())
'''

CURSOR_STANDIN = r'''#!/usr/bin/env python3
import hashlib, json, os, sqlite3, sys
from pathlib import Path
fixtures = Path(os.environ['STANDIN_FIXTURES'])
here = os.path.realpath(os.getcwd())
with open(os.environ['STANDIN_LOG'], 'a') as log:
    log.write(json.dumps({'harness': 'cursor', 'variable': os.environ.get('CURSOR_CONFIG_DIR'),
                          'cwd': here, 'argv': sys.argv[1:]}) + '\n')
if os.environ.get('STANDIN_FAIL'):
    print(os.environ['STANDIN_FAIL'], file=sys.stderr)
    sys.exit(1)
envelope = json.loads((fixtures / 'cursor-envelope.json').read_text())
config = Path(os.environ.get('CURSOR_CONFIG_DIR') or Path.home() / '.cursor')
chat = config / 'chats' / hashlib.md5(here.encode()).hexdigest() / envelope['session_id']
chat.mkdir(parents=True, exist_ok=True)
(chat / 'meta.json').write_text(json.dumps({'schemaVersion': 1, 'hasConversation': True, 'cwd': here}))
db = sqlite3.connect(str(chat / 'store.db'))
db.execute('create table blobs (id text primary key, data blob)')
db.execute('create table meta (key text primary key, value text)')
db.execute('insert into meta values (?, ?)', ('0', json.dumps({'agentId': envelope['session_id'], 'mode': 'ask'}).encode().hex()))
rows = [
    {'role': 'user', 'content': 'Workspace Path: %s' % here, 'providerOptions': {'cursor': {'modelName': 'cursor-grok-4.5-high'}}},
    {'role': 'assistant', 'id': 'm1', 'content': [{'type': 'tool-call', 'toolCallId': 't1', 'toolName': 'Read', 'args': {'path': here + '/brief.md'}}]},
    {'role': 'assistant', 'id': 'm2', 'content': [{'type': 'tool-call', 'toolCallId': 't2', 'toolName': 'Shell', 'args': {'command': 'cat /elsewhere/notes.md'}}]},
]
for n, row in enumerate(rows):
    db.execute('insert into blobs values (?, ?)', ('b%d' % n, json.dumps(row).encode()))
db.commit()
sys.stdout.write(json.dumps(envelope))
'''


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

    def setUp(self):
        self.tmp = Path(os.path.realpath(tempfile.mkdtemp(prefix='call-test-')))
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.ledger = self.tmp / 'ledger'
        self.bin = self.tmp / 'bin'
        self.scratch = self.tmp / 'scratch'
        self.caller = self.tmp / 'caller'
        self.homes = {'gemini-cli': self.tmp / 'gemini-home', 'cursor': self.tmp / 'cursor-config'}
        for folder in [self.ledger, self.bin, self.scratch, self.caller] + list(self.homes.values()):
            folder.mkdir()
        for name, text in (('gemini', GEMINI_STANDIN), ('cursor-agent', CURSOR_STANDIN)):
            (self.bin / name).write_text(text, encoding='utf-8')
            (self.bin / name).chmod(0o755)
        self.log = self.tmp / 'standin.jsonl'
        (self.ledger / 'config.json').write_text(json.dumps({
            'fields': 'all', 'harness_homes': dict((key, str(value)) for key, value in self.homes.items())}),
            encoding='utf-8')
        self.brief = self.caller / 'brief.md'
        self.brief.write_text('Read brief.md and reply with only the token it holds.\n', encoding='utf-8')
        self.env = {'PATH': '%s%s%s' % (self.bin, os.pathsep, os.environ.get('PATH', '')),
                    'TMPDIR': str(self.scratch), 'SUBAGENT_LEDGER_DIR': str(self.ledger),
                    'STANDIN_FIXTURES': str(FIXTURES), 'STANDIN_LOG': str(self.log),
                    'CLAUDE_CODE_SESSION_ID': 'test-session-0001', 'CODEX_THREAD_ID': '',
                    'GEMINI_CLI_HOME': '', 'CURSOR_CONFIG_DIR': '', 'STANDIN_FAIL': ''}

    def run_call(self, harness, extra=None, env=None):
        merged = dict(os.environ, **self.env)
        merged.update(env or {})
        argv = [sys.executable, str(CALL_PY), '--harness', harness, '--brief', str(self.brief)] + (extra or [])
        return subprocess.run(argv, capture_output=True, text=True, env=merged, cwd=str(self.caller), timeout=120)

    def records(self):
        found = []
        for path in sorted(self.ledger.glob('*.jsonl')):
            if path.name != 'capture-errors.jsonl':
                found.extend(lines_of(path))
        return found

    def errors(self):
        return lines_of(self.ledger / 'capture-errors.jsonl')

    def standin(self):
        return lines_of(self.log)


# ---------------------------------------------------------------------------
# Both records; isolation's folder is the script's fresh folder; the variable reached the child
# ---------------------------------------------------------------------------

class CB3_6Gemini(World):

    def test_c_b3_6_both_records_and_the_fresh_folder(self):
        if not CALL_PY.is_file():
            raise AssertionError('call.py does not exist yet')
        done = self.run_call('gemini-cli')
        self.assertEqual(done.returncode, 0, done.stderr)
        self.assertEqual(self.errors(), [])
        dispatch, back = self.records()
        self.assertEqual((dispatch['record'], back['record']), ('dispatch', 'return'))
        self.assertEqual(dispatch['call_id'], back['call_id'])
        self.assertEqual((dispatch['route'], back['route']), ('script', 'script'))
        self.assertEqual(dispatch['harness'], 'claude-code', 'the calling session\'s harness')
        self.assertEqual(dispatch['session'], 'test-session-0001')
        self.assertEqual(dispatch['agent_id'], 'unrecorded (not yet returned)')
        self.assertEqual(back['agent_id'], '08ed128a-0052-4138-8e16-7ccd7152056d', 'the run\'s own session')
        seen = self.standin()[-1]
        self.assertEqual(seen['variable'], str(self.homes['gemini-cli']), 'the variable reached the child')
        self.assertNotEqual(seen['cwd'], str(self.caller))
        self.assertTrue(seen['cwd'].startswith(str(self.scratch)), seen['cwd'])
        self.assertEqual(back['isolation']['folder'], seen['cwd'])
        self.assertEqual(back['outcome'], 'served')
        self.assertEqual(back['model'], 'gemini-3.5-flash')
        self.assertEqual(back['tokens']['input'], 787 + 13228)
        self.assertEqual(back['tokens']['cache_read'], 4047)
        self.assertEqual(back['tokens']['output'], 21 + 47)
        self.assertRegex(back['tokens']['cache_write'], UNRECORDED)
        self.assertIn('GEMINI_CLI_HOME', dispatch['auth_route'])
        self.assertEqual(done.stdout.strip(), 'plover-5170')

    def test_c_b3_6_not_logged_in_is_failed_not_signed_in(self):
        done = self.run_call('gemini-cli', env={'STANDIN_FAIL': 'Not logged in'})
        self.assertNotEqual(done.returncode, 0)
        dispatch, back = self.records()
        self.assertEqual(back['outcome'], 'failed')
        self.assertEqual(back['outcome_reason']['class'], 'not_signed_in')


class CB3_6Cursor(World):

    def test_c_b3_6_both_records_and_the_fresh_folder(self):
        if not CALL_PY.is_file():
            raise AssertionError('call.py does not exist yet')
        done = self.run_call('cursor', ['--model', 'auto'])
        self.assertEqual(done.returncode, 0, done.stderr)
        self.assertEqual(self.errors(), [])
        dispatch, back = self.records()
        seen = self.standin()[-1]
        self.assertEqual(seen['variable'], str(self.homes['cursor']))
        self.assertIn('--model', seen['argv'])
        self.assertEqual(back['isolation']['folder'], seen['cwd'])
        self.assertTrue(seen['cwd'].startswith(str(self.scratch)))
        self.assertEqual(dispatch['model_requested'], 'auto')
        self.assertEqual(back['model'], 'cursor-grok-4.5-high')
        self.assertEqual(back['tokens'], {'input': 19298, 'cache_write': 0, 'cache_read': 73728, 'output': 2582})
        self.assertEqual([entry.get('command') for entry in back['isolation']['outside']],
                         ['cat /elsewhere/notes.md'])
        self.assertIn('CURSOR_CONFIG_DIR', dispatch['auth_route'])

    def test_c_b3_6_not_logged_in_is_failed_not_signed_in(self):
        self.run_call('cursor', env={'STANDIN_FAIL': 'Not logged in'})
        back = self.records()[-1]
        self.assertEqual(back['outcome'], 'failed')
        self.assertEqual(back['outcome_reason']['class'], 'not_signed_in')

    def test_a_usage_limit_is_failed_usage_limit(self):
        text = (FIXTURES / 'cursor-usage-limit.err').read_text(encoding='utf-8').strip()
        self.run_call('cursor', env={'STANDIN_FAIL': text})
        self.assertEqual(self.records()[-1]['outcome_reason']['class'], 'usage_limit')

    def test_the_sandbox_refusal_is_failed_harness_error(self):
        text = (FIXTURES / 'cursor-eperm.err').read_text(encoding='utf-8').strip()
        self.run_call('cursor', env={'STANDIN_FAIL': text})
        self.assertEqual(self.records()[-1]['outcome_reason']['class'], 'harness_error')


# ---------------------------------------------------------------------------
# The working-folder handling switched off shows the caller's folder in isolation
# ---------------------------------------------------------------------------

class CB3_7WorkingFolder(World):

    def run_in_process(self, harness, switched_off):
        call = load(CALL_PY, 'call_under_test')
        original = call.launch

        def inherit(argv, folder, env):
            return original(argv, None, env)

        merged = dict(os.environ, **self.env)
        here = os.getcwd()
        os.chdir(str(self.caller))
        try:
            with mock.patch.dict(os.environ, merged, clear=True), \
                    contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
                if switched_off:
                    with mock.patch.object(call, 'launch', inherit):
                        call.main(['--harness', harness, '--brief', str(self.brief)])
                else:
                    call.main(['--harness', harness, '--brief', str(self.brief)])
        finally:
            os.chdir(here)
        return self.records()[-1]

    def test_c_b3_7_built_the_fresh_folder(self):
        for harness in ('gemini-cli', 'cursor'):
            with self.subTest(harness=harness):
                back = self.run_in_process(harness, switched_off=False)
                self.assertNotEqual(back['isolation']['folder'], str(self.caller))

    def test_c_b3_7_control_switched_off_isolation_shows_the_callers_folder(self):
        for harness in ('gemini-cli', 'cursor'):
            with self.subTest(harness=harness):
                back = self.run_in_process(harness, switched_off=True)
                self.assertEqual(self.standin()[-1]['cwd'], str(self.caller))
                self.assertEqual(back['isolation']['folder'], str(self.caller))


if __name__ == '__main__':
    unittest.main()
