"""Tests for witness.py: before a team's first dispatch, the session-start witness line is found in this session's
ledger file, or the skill stops and says why (TC-1).

The witness lines are written by the ledger skill's own capture, run on a SessionStart payload, so the check reads
what the capture writes. Every ledger folder is a temporary folder, proved so before anything runs.

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
SCRIPT = HERE.parent / 'skill' / 'scripts' / 'witness.py'
LEDGER_SCRIPTS = HERE.parent.parent / 'subagent-ledger' / 'skill' / 'scripts'
CAPTURE = LEDGER_SCRIPTS / 'capture_claude_code.py'
SESSION = '0e0e0e0e-1111-4222-8333-555555555555'
OTHER = '0f0f0f0f-1111-4222-8333-666666666666'


def clean_env(**extra):
    env = dict(os.environ)
    for name in ('SUBAGENT_LEDGER_DIR', 'SUBAGENT_LEDGER_SCRIPTS', 'CLAUDE_CODE_SESSION_ID'):
        env.pop(name, None)
    env.update(extra)
    return env


class WitnessTests(unittest.TestCase):

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.ledger = self.tmp / 'ledger'
        self.ledger.mkdir()
        # Where every write lands, proved before anything runs: inside this test's own temporary folder.
        self.assertTrue(str(self.ledger.resolve()).startswith(str(Path(tempfile.gettempdir()).resolve())))

    def tearDown(self):
        shutil.rmtree(str(self.tmp), ignore_errors=True)

    def session_start(self, session):
        payload = {'session_id': session, 'hook_event_name': 'SessionStart', 'source': 'startup',
                   'cwd': str(self.tmp)}
        done = subprocess.run([sys.executable, str(CAPTURE), 'SessionStart', '--ledger', str(self.ledger)],
                              input=json.dumps(payload), capture_output=True, text=True, env=clean_env(),
                              timeout=60)
        self.assertEqual(done.returncode, 0, done.stderr)

    def check(self, *arguments, env=None):
        done = subprocess.run([sys.executable, str(SCRIPT)] + list(arguments), capture_output=True, text=True,
                              env=env or clean_env(), timeout=60)
        try:
            out = json.loads(done.stdout)
        except ValueError:
            self.fail('no JSON on stdout (exit %s): %s %s' % (done.returncode, done.stdout, done.stderr))
        return done.returncode, out

    def test_the_capture_s_own_witness_line_is_found(self):
        self.session_start(SESSION)
        code, out = self.check('--ledger', str(self.ledger), '--session', SESSION)
        self.assertEqual(code, 0, out)
        self.assertFalse(out['stop'])
        self.assertEqual(out['session'], SESSION)
        self.assertEqual(out['witness']['event'], 'SessionStart')
        self.assertEqual(out['witness']['session'], SESSION)
        self.assertEqual(Path(out['ledger_file']), self.ledger / ('%s.jsonl' % SESSION))

    def test_tc1_empty_a_session_with_no_witness_line_stops(self):
        # The session's ledger file exists and holds a line, but no session-start witness line.
        (self.ledger / ('%s.jsonl' % SESSION)).write_text(json.dumps(
            {'schema': 'subagent-ledger/1', 'record': 'witness', 'event': 'SubagentStart', 'session': SESSION,
             'agent_id': 'a1', 'call_id': 'c1', 'at': '2026-01-01T00:00:00.000Z', 'withheld': 0}) + '\n',
            encoding='utf-8')
        code, out = self.check('--ledger', str(self.ledger), '--session', SESSION)
        self.assertEqual(code, 1, out)
        self.assertTrue(out['stop'])
        self.assertIsNone(out['witness'])
        self.assertIn('no session-start witness line', out['reason'])
        self.assertIn('send no member', out['reason'])

    def test_tc1_empty_a_session_with_no_ledger_file_stops(self):
        code, out = self.check('--ledger', str(self.ledger), '--session', SESSION)
        self.assertEqual(code, 1, out)
        self.assertTrue(out['stop'])
        self.assertIn('does not exist', out['reason'])

    def test_tc1_likeness_a_witness_line_from_another_session_s_file_is_refused(self):
        # Another session's file, with its own witness line, put in place of this session's file.
        self.session_start(OTHER)
        shutil.copy(str(self.ledger / ('%s.jsonl' % OTHER)), str(self.ledger / ('%s.jsonl' % SESSION)))
        code, out = self.check('--ledger', str(self.ledger), '--session', SESSION)
        self.assertEqual(code, 1, out)
        self.assertTrue(out['stop'])
        self.assertIsNone(out['witness'])
        self.assertIn('another session', out['reason'])
        self.assertIn(OTHER, out['reason'])

    def test_a_witness_line_in_another_session_s_own_file_does_not_count(self):
        self.session_start(OTHER)
        code, out = self.check('--ledger', str(self.ledger), '--session', SESSION)
        self.assertEqual(code, 1, out)
        self.assertTrue(out['stop'])

    def test_the_session_id_from_the_harness_variable(self):
        self.session_start(SESSION)
        code, out = self.check('--ledger', str(self.ledger), env=clean_env(CLAUDE_CODE_SESSION_ID=SESSION))
        self.assertEqual(code, 0, out)
        self.assertEqual(out['session_from'], 'CLAUDE_CODE_SESSION_ID')

    def test_no_session_id_stops(self):
        self.session_start(SESSION)
        code, out = self.check('--ledger', str(self.ledger))
        self.assertEqual(code, 1, out)
        self.assertTrue(out['stop'])
        self.assertIn('no session id', out['reason'])

    def test_the_ledger_folder_from_its_variable(self):
        self.session_start(SESSION)
        code, out = self.check('--session', SESSION, env=clean_env(SUBAGENT_LEDGER_DIR=str(self.ledger)))
        self.assertEqual(code, 0, out)


if __name__ == '__main__':
    unittest.main()
