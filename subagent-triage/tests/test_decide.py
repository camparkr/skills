"""Tests for decide.py: the act decision (D-1) and the persona decision (D-3) for one part, asked of a stand-in for
Jev, with every request recorded through the ledger's writer and the pending triage file written.

The stand-in answers from marks in the fixtures, never from the live service:
- the act Choice reads `build` at 0.8 when the part carries MARK-BUILD;
- each act Noul gives 0.9 for the build test on a MARK-BUILD part, and 0.05 otherwise;
- the persona Choice gives most weight to a persona whose goal carries MARK-ADEQUATE;
- the adequacy Noul gives 0.9 when the persona's goal carries MARK-ADEQUATE, and 0.1 otherwise.

The fixtures name no real persona, group or path. The pending file is checked against the ledger's
pending.schema.json where SUBAGENT_LEDGER_PENDING_SCHEMA names it or it sits beside ledger.py; otherwise that one check
is skipped.

Run from the skill's folder:  python3 -m unittest discover -s tests
"""

import http.server
import json
import os
import subprocess
import sys
import tempfile
import threading
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
SCRIPT = HERE.parent / 'skill' / 'scripts' / 'decide.py'
FIXTURES = HERE / 'fixtures'
LEDGER_SCRIPTS = HERE.parent.parent / 'subagent-ledger' / 'skill' / 'scripts'
SESSION = '0e0e0e0e-1111-4222-8333-555555555555'
KINDS = ['verdict-or-review', 'deliberation', 'build', 'inquiry', 'archiving', 'transfer', 'conversion',
         'user-decision']
RECORD_FIELDS = {'question', 'definition_version', 'subject', 'quote', 'answer', 'uncertainty_basis',
                 'decision_point_classification', 'exact_evidence', 'lane', 'delegated_authority', 'evidence_state',
                 'decided_by', 'final_disposition'}
KEYS = ['--rows-key', 'rows', '--name-key', 'name', '--group-key', 'group', '--file-key', 'file',
        '--goal-key', 'meta.declaration.goal', '--ratified-key', 'meta.declaration-ratified', '--user', 'the-user']


class StandIn:
    """A stand-in for Jev on a local port. `fail` names question types answered with HTTP 500."""

    def __init__(self):
        self.fail = set()
        self.seen = []
        owner = self

        class Handler(http.server.BaseHTTPRequestHandler):
            def log_message(self, *args):
                pass

            def do_POST(self):
                body = json.loads(self.rfile.read(int(self.headers['Content-Length'])))
                owner.seen.append(body)
                (qid, question), = body['questions'].items()
                if question['type'] in owner.fail:
                    self.send_response(500)
                    self.end_headers()
                    self.wfile.write(b'stand-in told to fail')
                    return
                state = body['state']
                part = state.get('part', '')
                if question['type'] == 'choice':
                    criteria = question['criteria']
                    if 'none' in criteria:
                        best = 'build' if 'MARK-BUILD' in part else 'none'
                        rest = 0.2 / (len(criteria) - 1)
                        probs = dict((label, 0.8 if label == best else rest) for label in criteria)
                    else:
                        weights = dict((label, 7.0 if 'MARK-ADEQUATE' in text else 1.0)
                                       for label, text in criteria.items())
                        total = sum(weights.values())
                        probs = dict((label, weight / total) for label, weight in weights.items())
                    answer = {'type': 'choice', 'choice': max(probs, key=probs.get), 'confidence': 0.9,
                              'probabilities': probs}
                elif 'goal' in state:
                    answer = {'type': 'noul', 'noul': 0.9 if 'MARK-ADEQUATE' in state['goal'] else 0.1}
                else:
                    build = 'change what a program' in question['criteria']['true']
                    answer = {'type': 'noul', 'noul': 0.9 if build and 'MARK-BUILD' in part else 0.05}
                out = json.dumps({'model': 'jev-1.13.0', 'answers': {qid: answer},
                                  'usage': {'input_tokens': 100, 'output_tokens': 10}}).encode()
                self.send_response(200)
                self.send_header('Content-Type', 'application/json')
                self.send_header('Content-Length', str(len(out)))
                self.end_headers()
                self.wfile.write(out)

        self.server = http.server.ThreadingHTTPServer(('127.0.0.1', 0), Handler)
        self.url = 'http://127.0.0.1:%d/v1/systemone' % self.server.server_address[1]
        threading.Thread(target=self.server.serve_forever, daemon=True).start()

    def stop(self):
        self.server.shutdown()
        self.server.server_close()


def pending_schema():
    named = os.environ.get('SUBAGENT_LEDGER_PENDING_SCHEMA')
    path = Path(named) if named else LEDGER_SCRIPTS / 'pending.schema.json'
    return json.loads(path.read_text(encoding='utf-8')) if path.is_file() else None


class DecideTests(unittest.TestCase):

    def setUp(self):
        self.jev = StandIn()
        self.tmp = Path(tempfile.mkdtemp())
        self.ledger = self.tmp / 'ledger'
        self.ledger.mkdir()

    def tearDown(self):
        self.jev.stop()

    def run_decide(self, roster, part='part-build.md', member='m1', attempt='1'):
        env = dict(os.environ, JEV_API_KEY='stand-in-key', SUBAGENT_TRIAGE_JEV_URL=self.jev.url,
                   SUBAGENT_TRIAGE_RETRY_WAIT='0')
        env.pop('SUBAGENT_LEDGER_SCRIPTS', None)
        done = subprocess.run([sys.executable, str(SCRIPT), '--delegation', str(FIXTURES / part),
                               '--roster', str(FIXTURES / roster), '--ledger', str(self.ledger),
                               '--session', SESSION, '--member', member, '--attempt', attempt] + KEYS,
                              capture_output=True, text=True, env=env, timeout=120)
        try:
            out = json.loads(done.stdout)
        except ValueError:
            self.fail('no JSON on stdout (exit %s): %s %s' % (done.returncode, done.stdout, done.stderr))
        return done.returncode, out

    def records(self):
        path = self.ledger / ('%s.jsonl' % SESSION)
        return [json.loads(line) for line in path.read_text(encoding='utf-8').splitlines() if line.strip()]

    def pending(self, member='m1', attempt='1'):
        path = self.ledger / '.pending' / SESSION / ('triage-%s-%s.json' % (member, attempt))
        self.assertTrue(path.is_file(), 'no pending file at %s' % path)
        return json.loads(path.read_text(encoding='utf-8'))

    def check_records(self, out):
        for record in out['decision_records']:
            self.assertLessEqual(set(record) - {'disposed_by', 'override', 'home'}, RECORD_FIELDS)
            for name in ('question', 'definition_version', 'subject', 'answer', 'uncertainty_basis',
                         'decision_point_classification', 'lane', 'evidence_state', 'decided_by',
                         'final_disposition'):
                self.assertIn(name, record)
            self.assertEqual(record['final_disposition'], 'pending')
            self.assertEqual('delegated_authority' in record, record['lane'] == 'delivered')

    def check_schema(self, data):
        schema = pending_schema()
        if schema is None:
            return
        sys.path.insert(0, str(LEDGER_SCRIPTS))
        import ledger
        self.assertEqual(ledger.validate(data, schema, ref='#/$defs/triage'), [])

    def test_a_build_part_goes_to_the_adequate_persona(self):
        code, out = self.run_decide('roster-two.yaml')
        self.assertEqual(code, 0, out)
        self.assertEqual(sorted(out['act']['nouls']), sorted(KINDS))
        self.assertEqual(out['act']['nouls']['build'], 0.9)
        self.assertIsNone(out['act']['lines'])
        self.assertEqual(sorted(out['act']['choice']['probabilities']), sorted(KINDS + ['none']))
        self.assertEqual(out['act']['kind'], 'build')
        self.assertEqual(out['persona']['eligible'], ['cataloguer', 'builder'])
        self.assertEqual(sorted(out['persona']['choice']['probabilities']), ['builder', 'cataloguer'])
        self.assertEqual(out['persona']['persona'], 'builder')
        self.assertEqual(out['persona']['adequacy'], 0.9)
        self.assertFalse(out['persona']['below_line'])
        self.check_records(out)
        # Eleven requests: eight Nouls, the act Choice, the persona Choice and the adequacy Noul.
        self.assertEqual(len(out['jev_calls']), 11)
        records = self.records()
        self.assertEqual(len(self.jev.seen), 11)
        ids = [call['call_id'] for call in out['jev_calls']]
        for call_id in ids:
            pair = [r for r in records if r.get('call_id') == call_id]
            self.assertEqual(len(pair), 2, call_id)
        text = (self.ledger / ('%s.jsonl' % SESSION)).read_text(encoding='utf-8')
        self.assertNotIn('export script', text)
        data = self.pending()
        self.assertEqual(data['kind']['value'], 'build')
        self.assertEqual(data['triage_persona']['value'], 'builder')
        self.assertEqual(data['chosen_by']['value'], 'the planning skill')
        self.assertNotIn('below_line', data)
        self.assertEqual(len(data['decision_records']['value']), 2)
        for value in data.values():
            self.assertRegex(value['stamped_at'], r'^\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d')
        self.check_schema(data)

    def test_an_empty_roster_gives_none_adequate_never_a_pick(self):
        code, out = self.run_decide('roster-empty.yaml')
        self.assertEqual(code, 0, out)
        self.assertEqual(out['act']['kind'], 'build')
        self.assertEqual(out['persona']['eligible'], [])
        self.assertIsNone(out['persona']['persona'])
        self.assertTrue(out['persona']['answer'].startswith('none adequate'))
        self.assertEqual(len(out['jev_calls']), 9)
        record = out['decision_records'][1]
        self.assertEqual(record['lane'], 'reasoned')
        self.check_records(out)
        data = self.pending()
        self.assertNotIn('triage_persona', data)
        self.check_schema(data)

    def test_a_likeness_gives_below_line(self):
        code, out = self.run_decide('roster-likeness.yaml')
        self.assertEqual(code, 0, out)
        self.assertEqual(out['persona']['eligible'], ['cataloguer'])
        excluded = out['persona']['excluded']
        self.assertEqual(sorted(excluded), ['drafter', 'ghost', 'the-user'])
        self.assertEqual(out['persona']['persona'], 'cataloguer')
        self.assertEqual(out['persona']['adequacy'], 0.1)
        self.assertTrue(out['persona']['below_line'])
        record = out['decision_records'][1]
        self.assertEqual(record['lane'], 'reasoned')
        self.assertIn('below the line', record['answer'])
        self.check_records(out)
        data = self.pending()
        self.assertEqual(data['below_line']['value'], {'probability': 0.1, 'line': 0.5, 'line_version': 0})
        self.check_schema(data)

    def test_a_failed_request_is_recorded_and_the_pending_file_still_written(self):
        self.jev.fail.add('choice')
        code, out = self.run_decide('roster-two.yaml', member='m2')
        self.assertEqual(code, 3, out)
        self.assertTrue(out['act']['answer'].startswith('unrecorded ('))
        self.assertIsNone(out['act']['kind'])
        self.assertIsNone(out['persona'])
        failed = [r for r in self.records() if r.get('outcome') == 'failed']
        self.assertEqual(len(failed), 4)  # the first try and three retries on HTTP 500
        data = self.pending(member='m2')
        self.assertIn('triage_failure', data)
        self.assertNotIn('kind', data)
        self.check_schema(data)

    def test_the_user_and_unknown_files_are_never_eligible(self):
        code, out = self.run_decide('roster-likeness.yaml', member='m3')
        self.assertNotIn('the-user', out['persona']['eligible'])
        self.assertNotIn('ghost', out['persona']['eligible'])


if __name__ == '__main__':
    unittest.main()
