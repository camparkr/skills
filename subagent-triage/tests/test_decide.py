"""Tests for decide.py: the act decision (D-1), the persona decision (D-3) and the effort decision (D-4) for one part,
asked of a stand-in for Jev, with every request recorded through the ledger's writer and the pending triage file
written; and its override mode.

The stand-in answers from marks in the fixtures, never from the live service:
- the act Choice reads `build` at 0.8 when the part carries MARK-BUILD;
- each act Noul gives 0.9 for the build test on a MARK-BUILD part, and 0.05 otherwise;
- the persona Choice gives most weight to a persona whose goal carries MARK-ADEQUATE;
- the adequacy Noul gives 0.9 when the persona's goal carries MARK-ADEQUATE, and 0.1 otherwise;
- the effort Choice reads `medium` at 0.6, each other level at 0.1.

The fixtures name no real persona, group or path. The pending file is checked against the ledger's
pending.schema.json where SUBAGENT_LEDGER_PENDING_SCHEMA names it or it sits beside ledger.py; otherwise that one check
is skipped.

Run from the skill's folder:  python3 -m unittest discover -s tests
"""

import datetime
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
LEVELS = ['low', 'medium', 'high', 'xhigh', 'max']
STAGE = 'unrecorded (no task id was given)'
STAGE_TREE = FIXTURES / 'stage'
KEYS = ['--rows-key', 'rows', '--name-key', 'name', '--group-key', 'group', '--file-key', 'file',
        '--goal-key', 'meta.declaration.goal', '--ratified-key', 'meta.declaration-ratified', '--user', 'the-user']


class StandIn:
    """A stand-in for Jev on a local port. `fail` names question types answered with HTTP 500; `fail_effort` fails the
    effort Choice alone. Each request is kept in `seen` with the time it arrived in `arrived`."""

    def __init__(self):
        self.fail = set()
        self.fail_effort = False
        self.seen = []
        self.arrived = []
        owner = self

        class Handler(http.server.BaseHTTPRequestHandler):
            def log_message(self, *args):
                pass

            def do_POST(self):
                body = json.loads(self.rfile.read(int(self.headers['Content-Length'])))
                owner.seen.append(body)
                owner.arrived.append(datetime.datetime.now(datetime.timezone.utc))
                (qid, question), = body['questions'].items()
                effort = question['type'] == 'choice' and sorted(question['criteria']) == sorted(LEVELS)
                if question['type'] in owner.fail or (effort and owner.fail_effort):
                    self.send_response(500)
                    self.end_headers()
                    self.wfile.write(b'stand-in told to fail')
                    return
                state = body['state']
                part = state.get('part', '')
                if effort:
                    probs = dict((level, 0.6 if level == 'medium' else 0.1) for level in LEVELS)
                    answer = {'type': 'choice', 'choice': 'medium', 'confidence': 0.6, 'probabilities': probs}
                elif question['type'] == 'choice':
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


def when(text):
    return datetime.datetime.strptime(text.replace('Z', '+0000'), '%Y-%m-%dT%H:%M:%S.%f%z')


class DecideTests(unittest.TestCase):

    def setUp(self):
        self.jev = StandIn()
        self.tmp = Path(tempfile.mkdtemp())
        self.ledger = self.tmp / 'ledger'
        self.ledger.mkdir()

    def tearDown(self):
        self.jev.stop()

    def run_script(self, arguments):
        env = dict(os.environ, JEV_API_KEY='stand-in-key', SUBAGENT_TRIAGE_JEV_URL=self.jev.url,
                   SUBAGENT_TRIAGE_RETRY_WAIT='0')
        env.pop('SUBAGENT_LEDGER_SCRIPTS', None)
        done = subprocess.run([sys.executable, str(SCRIPT)] + arguments, capture_output=True, text=True, env=env,
                              timeout=120)
        try:
            out = json.loads(done.stdout)
        except ValueError:
            self.fail('no JSON on stdout (exit %s): %s %s' % (done.returncode, done.stdout, done.stderr))
        return done.returncode, out

    def run_decide(self, roster, part='part-build.md', member='m1', attempt='1', unaided='medium', extra=()):
        delegation = part if os.path.isabs(str(part)) else FIXTURES / part
        return self.run_script(['--delegation', str(delegation), '--roster', str(FIXTURES / roster),
                                '--ledger', str(self.ledger), '--session', SESSION, '--member', member,
                                '--attempt', attempt, '--effort-unaided', unaided] + KEYS + list(extra))

    def pending_path(self, member='m1', attempt='1'):
        return self.ledger / '.pending' / SESSION / ('triage-%s-%s.json' % (member, attempt))

    def effort_state(self):
        found = [body['state'] for body in self.jev.seen
                 if sorted(list(body['questions'].values())[0]['criteria']) == sorted(LEVELS)]
        self.assertEqual(len(found), 1)
        return found[0]

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
        # Twelve requests: eight Nouls, the act Choice, the persona Choice, the adequacy Noul and the effort Choice.
        self.assertEqual(len(out['jev_calls']), 12)
        records = self.records()
        self.assertEqual(len(self.jev.seen), 12)
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
        self.assertEqual(len(data['decision_records']['value']), 3)
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
        self.assertEqual(len(out['jev_calls']), 10)
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
        # The act Choice and the effort Choice: each a first try and three retries on HTTP 500.
        self.assertEqual(len(failed), 8)
        data = self.pending(member='m2')
        self.assertIn('triage_failure', data)
        self.assertNotIn('kind', data)
        self.check_schema(data)

    def test_the_user_and_unknown_files_are_never_eligible(self):
        code, out = self.run_decide('roster-likeness.yaml', member='m3')
        self.assertNotIn('the-user', out['persona']['eligible'])
        self.assertNotIn('ghost', out['persona']['eligible'])

    # -- The effort decision (D-4) -----------------------------------------------------------------------------------

    def d4(self, out):
        found = [r for r in out['decision_records'] if r['question'] == 'd4-effort']
        self.assertEqual(len(found), 1)
        return found[0]

    def test_the_unaided_stamp_precedes_the_effort_record(self):
        code, out = self.run_decide('roster-two.yaml', unaided='high')
        self.assertEqual(code, 0, out)
        self.assertEqual(out['effort']['level'], 'medium')
        self.assertEqual(sorted(out['effort']['choice']['probabilities']), sorted(LEVELS))
        record = self.d4(out)
        self.assertEqual(record['answer'], 'medium')
        self.assertEqual(record['lane'], 'reasoned')
        self.check_records(out)
        data = self.pending()
        self.assertEqual(data['effort_unaided']['value'], 'high')
        unaided = when(data['effort_unaided']['stamped_at'])
        # Before the effort request reached Jev, before the ledger recorded its dispatch, and before the record.
        effort_call = [c for c in out['jev_calls'] if c['item'] == 'd4-effort choice']
        self.assertEqual(len(effort_call), 1)
        self.assertLess(unaided, self.jev.arrived[-1])
        dispatch = [r for r in self.records() if r.get('call_id') == effort_call[0]['call_id']
                    and r.get('dispatched_at')][0]
        self.assertLess(unaided, when(dispatch['dispatched_at']))
        self.assertLess(unaided, when(data['decision_records']['stamped_at']))
        self.assertEqual(data['decision_records']['value'][-1]['answer'], 'medium')
        self.check_schema(data)

    def test_a_failed_effort_request_gives_unrecorded_and_keeps_the_unaided_level(self):
        self.jev.fail_effort = True
        code, out = self.run_decide('roster-two.yaml', member='m4', unaided='low')
        self.assertEqual(code, 3, out)
        self.assertEqual(out['persona']['persona'], 'builder')
        self.assertIsNone(out['effort']['level'])
        self.assertRegex(out['effort']['answer'], r'^unrecorded \(.+\)$')
        self.assertEqual(out['effort']['pass'], 'low')
        self.assertIn('unaided level is passed', out['effort']['route'])
        self.assertEqual(self.d4(out)['answer'], out['effort']['answer'])
        data = self.pending(member='m4')
        self.assertEqual(data['effort_unaided']['value'], 'low')
        self.assertIn('effort decision', data['triage_failure']['value'])
        self.assertEqual(data['decision_records']['value'][-1]['answer'], out['effort']['answer'])
        self.check_schema(data)

    def test_the_effort_facts_count_named_inputs_and_the_write_set(self):
        text = (FIXTURES / 'part-inputs.md').read_text(encoding='utf-8').replace('@FIXTURES@', str(FIXTURES))
        delegation = self.tmp / 'part-inputs.md'
        delegation.write_text(text, encoding='utf-8')
        code, out = self.run_decide('roster-two.yaml', part=str(delegation), member='m5')
        self.assertEqual(code, 0, out)
        state = self.effort_state()
        self.assertEqual(state['kind'], 'build')
        self.assertEqual(state['persona'], 'builder')
        self.assertEqual(state['stage'], STAGE)
        self.assertEqual(state['words'], 19)
        self.assertEqual(state['input_files_resolving'], 1)
        self.assertEqual(state['input_bytes'], (FIXTURES / 'input-present.txt').stat().st_size)
        self.assertEqual(state['write_set_paths'], 2)
        self.assertIn('MARK-BUILD', state['part'])
        facts = dict((k, v) for k, v in state.items() if k != 'part')
        self.assertEqual(self.d4(out)['exact_evidence'], facts)

    def test_no_kind_and_no_persona_are_given_as_none(self):
        code, out = self.run_decide('roster-two.yaml', part='part-plain.md', member='m6')
        self.assertEqual(code, 0, out)
        self.assertIsNone(out['act']['kind'])
        state = self.effort_state()
        self.assertEqual(state['kind'], 'none')
        self.assertEqual(state['persona'], 'none')
        self.assertEqual(state['input_files_resolving'], 0)
        self.assertEqual(state['input_bytes'], 0)
        self.assertEqual(state['write_set_paths'], 'none')
        self.assertEqual(out['effort']['level'], 'medium')

    # U5 gap: a part the act decision reads as none is never dispatched, so a pending file for it was listed at the
    # ledger's close as never dispatched. No pending file is written for such a part, and the output says so. The
    # likeness is a part whose act request failed: its kind is also unset, but its pending file is still written,
    # holding the failure (test_a_failed_request_is_recorded_and_the_pending_file_still_written).

    def test_a_part_that_reads_as_none_writes_no_pending_file_and_the_output_says_so(self):
        code, out = self.run_decide('roster-two.yaml', part='part-plain.md', member='m6n')
        self.assertEqual(code, 0, out)
        self.assertTrue(out['act']['answer'].startswith('none ('), out['act']['answer'])
        self.assertFalse(self.pending_path(member='m6n').exists(), 'a part read as none leaves no pending file')
        self.assertFalse((self.ledger / '.pending' / SESSION).exists()
                         and list((self.ledger / '.pending' / SESSION).glob('triage-*.json')))
        self.assertIsNone(out['pending_file'])
        self.assertIn('none', out['no_pending_file'])
        self.assertEqual([r['question'] for r in out['decision_records']], ['d1-act', 'd4-effort'])

    def test_likeness_a_part_read_as_one_kind_still_writes_its_pending_file(self):
        code, out = self.run_decide('roster-two.yaml', member='m6k')
        self.assertEqual(code, 0, out)
        self.assertEqual(out['pending_file'], str(self.pending_path(member='m6k')))
        self.assertNotIn('no_pending_file', out)
        self.pending(member='m6k')

    # -- The stage read joins the facts -------------------------------------------------------------------------------

    def persona_state(self):
        found = [body['state'] for body in self.jev.seen
                 if list(body['questions'].values())[0]['type'] == 'choice'
                 and sorted(list(body['questions'].values())[0]['criteria']) == ['builder', 'cataloguer']]
        self.assertEqual(len(found), 1)
        return found[0]

    def test_the_stage_read_replaces_the_placeholder_in_the_effort_and_persona_facts(self):
        stage = ['--task', 'beta', '--build-root', str(STAGE_TREE / 'build-specs'),
                 '--ratified-root', str(STAGE_TREE / 'specs'), '--task-key', 'meta.task_id',
                 '--status-key', 'meta.status']
        code, out = self.run_decide('roster-two.yaml', member='m9', extra=stage)
        self.assertEqual(code, 0, out)
        self.assertEqual(out['stage']['stage'], 'ratified specification')
        self.assertEqual(self.effort_state()['stage'], 'ratified specification')
        self.assertEqual(self.d4(out)['exact_evidence']['stage'], 'ratified specification')
        self.assertEqual(self.persona_state()['stage'], 'ratified specification')
        d3 = [r for r in out['decision_records'] if r['question'] == 'd3-figure'][0]
        self.assertEqual(d3['exact_evidence']['stage'], 'ratified specification')
        data = self.pending(member='m9')
        self.assertEqual(data['persona_facts']['value']['stage'], 'ratified specification')
        self.check_schema(data)

    def test_a_task_with_no_specification_gives_the_stage_read_s_unrecorded_value(self):
        stage = ['--task', 'zeta', '--ratified-root', str(STAGE_TREE / 'specs'), '--task-key', 'meta.task_id',
                 '--status-key', 'meta.status']
        code, out = self.run_decide('roster-two.yaml', member='m10', extra=stage)
        self.assertEqual(code, 0, out)
        self.assertEqual(self.effort_state()['stage'], 'unrecorded (no specification found for zeta)')
        self.assertEqual(self.persona_state()['stage'], 'unrecorded (no specification found for zeta)')

    # -- The override ------------------------------------------------------------------------------------------------

    def override(self, path, level='high', reason='the part reconciles three schemas'):
        return self.run_script(['override', '--pending', str(path), '--decision', 'd4-effort', '--level', level,
                                '--reason', reason])

    def test_override_appends_one_entry(self):
        code, out = self.run_decide('roster-two.yaml', member='m7')
        self.assertEqual(code, 0, out)
        path = self.pending_path(member='m7')
        before = json.loads(path.read_text(encoding='utf-8'))
        self.assertNotIn('overrides', before)
        code, out = self.override(path)
        self.assertEqual(code, 0, out)
        data = json.loads(path.read_text(encoding='utf-8'))
        entries = data['overrides']['value']
        self.assertEqual(len(entries), 1)
        entry = entries[0]
        self.assertEqual(entry['decision'], 'd4-effort')
        self.assertEqual(entry['decision_level'], 'medium')
        self.assertEqual(entry['level_passed'], 'high')
        self.assertEqual(entry['reason'], 'the part reconciles three schemas')
        self.assertRegex(entry['at'], r'^\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d')
        self.assertEqual(out['override'], entry)
        for key in before:
            self.assertEqual(data[key], before[key], key)
        self.check_schema(data)
        code, out = self.override(path, level='low', reason='second thoughts')
        self.assertEqual(code, 0, out)
        data = json.loads(path.read_text(encoding='utf-8'))
        self.assertEqual([e['level_passed'] for e in data['overrides']['value']], ['high', 'low'])

    def test_override_refuses_a_file_with_no_effort_record_and_an_unknown_level(self):
        path = self.tmp / 'triage-no-d4.json'
        records = {'value': [{'question': 'd1-act', 'answer': 'build'}], 'stamped_at': '2026-10-29T00:00:00.000Z'}
        path.write_text(json.dumps({'decision_records': records}), encoding='utf-8')
        code, out = self.override(path)
        self.assertEqual(code, 1, out)
        self.assertIn('no d4-effort record', out['error'])
        self.assertNotIn('overrides', json.loads(path.read_text(encoding='utf-8')))
        code, out = self.run_decide('roster-two.yaml', member='m8')
        self.assertEqual(code, 0, out)
        good = self.pending_path(member='m8')
        code, out = self.override(good, level='extreme')
        self.assertEqual(code, 1, out)
        self.assertIn('unknown level', out['error'])
        self.assertNotIn('overrides', json.loads(good.read_text(encoding='utf-8')))


    # -- The no-persona override (R-11, ruled 30 October 2026) --------------------------------------------------------

    def override_no_persona(self, *where, reason='a search across the repository: it takes no persona'):
        return self.run_script(['override', '--decision', 'no-persona'] + list(where) + ['--reason', reason])

    def test_r11_a_dispatch_with_no_persona_and_no_triage_gets_a_pending_file_holding_its_override(self):
        path = self.pending_path(member='m21', attempt='2')
        self.assertFalse(path.exists())
        code, out = self.override_no_persona('--ledger', str(self.ledger), '--session', SESSION, '--member', 'm21',
                                             '--attempt', '2')
        self.assertEqual(code, 0, out)
        self.assertEqual(out['pending_file'], str(path))
        data = json.loads(path.read_text(encoding='utf-8'))
        entry, = data['overrides']['value']
        self.assertEqual(entry['decision'], 'no-persona')
        self.assertEqual(entry['reason'], 'a search across the repository: it takes no persona')
        self.assertRegex(entry['at'], r'^\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d')
        self.assertEqual(entry['decision_persona'], 'unrecorded (the pending file holds no d3-figure record)')
        self.assertEqual(out['override'], entry)
        self.assertEqual(data['chosen_by']['value'], 'the dispatching agent')
        self.assertNotIn('triage_persona', data)
        self.check_schema(data)

    def test_r11_a_no_persona_override_on_a_triaged_file_names_the_decision_s_persona_and_clears_it(self):
        code, out = self.run_decide('roster-two.yaml', member='m22')
        self.assertEqual(code, 0, out)
        path = self.pending_path(member='m22')
        before = json.loads(path.read_text(encoding='utf-8'))
        self.assertEqual(before['triage_persona']['value'], 'builder')
        code, out = self.override_no_persona('--pending', str(path))
        self.assertEqual(code, 0, out)
        data = json.loads(path.read_text(encoding='utf-8'))
        entry = data['overrides']['value'][-1]
        self.assertEqual(entry['decision'], 'no-persona')
        self.assertEqual(entry['decision_persona'], 'builder')
        # No persona goes out, so none is named; the decision's own record is left as it was.
        self.assertNotIn('triage_persona', data)
        self.assertEqual(data['chosen_by']['value'], 'the dispatching agent')
        for key in before:
            if key not in ('triage_persona', 'chosen_by'):
                self.assertEqual(data[key], before[key], key)
        self.check_schema(data)

    def test_r11_likeness_a_no_persona_override_with_no_reason_or_no_file_is_refused(self):
        code, out = self.override_no_persona('--ledger', str(self.ledger), '--session', SESSION, '--member', 'm23',
                                             reason='  ')
        self.assertEqual(code, 1, out)
        self.assertIn('reason', out['error'])
        self.assertFalse(self.pending_path(member='m23').exists())
        # A named pending file must exist: a wrong path is never created.
        missing = self.tmp / 'triage-m24-1.json'
        code, out = self.override_no_persona('--pending', str(missing))
        self.assertEqual(code, 1, out)
        self.assertFalse(missing.exists())
        # With neither the file nor the member's ledger, session and id, there is nowhere to write it.
        code, out = self.override_no_persona()
        self.assertEqual(code, 1, out)
        self.assertIn('--pending', out['error'])

    # -- The persona override (D-3) ----------------------------------------------------------------------------------

    def override_persona(self, path, persona='cataloguer', parent='lead', reason='the part is a catalogue entry'):
        return self.run_script(['override', '--pending', str(path), '--decision', 'd3-figure', '--persona', persona,
                                '--parent-persona', parent, '--reason', reason])

    def test_tc3_a_persona_override_records_its_six_values_from_the_file_s_own_record(self):
        code, out = self.run_decide('roster-two.yaml', member='m11')
        self.assertEqual(code, 0, out)
        path = self.pending_path(member='m11')
        before = json.loads(path.read_text(encoding='utf-8'))
        code, out = self.override_persona(path)
        self.assertEqual(code, 0, out)
        data = json.loads(path.read_text(encoding='utf-8'))
        entry = data['overrides']['value'][-1]
        self.assertEqual(entry['decision'], 'd3-figure')
        self.assertEqual(entry['decision_persona'], 'builder')
        self.assertEqual(entry['adequacy_probability'], 0.9)
        # R-4's "the parent's figure" is the parent's own persona (ruled 30 October 2026), not the persona it would
        # have chosen: it is recorded as given, need not be on the roster, and stands apart from the persona chosen.
        self.assertEqual(entry['parent_persona'], 'lead')
        d3, = [r for r in data['decision_records']['value'] if r['question'] == 'd3-figure']
        roster = d3['exact_evidence']['eligible'] + list(d3['exact_evidence']['excluded'])
        self.assertNotIn(entry['parent_persona'], roster)
        self.assertNotEqual(entry['parent_persona'], entry['persona_chosen'])
        self.assertEqual(entry['persona_chosen'], 'cataloguer')
        self.assertEqual(entry['reason'], 'the part is a catalogue entry')
        self.assertRegex(entry['at'], r'^\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d')
        self.assertEqual(out['override'], entry)
        # The persona chosen and who chose it change with the override; the decision's own record does not.
        self.assertEqual(data['triage_persona']['value'], 'cataloguer')
        self.assertEqual(data['chosen_by']['value'], 'the dispatching agent')
        for key in before:
            if key not in ('triage_persona', 'chosen_by'):
                self.assertEqual(data[key], before[key], key)
        self.check_schema(data)

    def test_tc3_a_below_line_persona_is_named_without_its_mark(self):
        code, out = self.run_decide('roster-likeness.yaml', member='m12')
        self.assertEqual(code, 0, out)
        code, out = self.override_persona(self.pending_path(member='m12'), persona='drafter')
        self.assertEqual(code, 0, out)
        self.assertEqual(out['override']['decision_persona'], 'cataloguer')
        self.assertEqual(out['override']['adequacy_probability'], 0.1)

    def test_tc3_likeness_an_override_with_no_reason_is_refused(self):
        code, out = self.run_decide('roster-two.yaml', member='m13')
        self.assertEqual(code, 0, out)
        path = self.pending_path(member='m13')
        before = path.read_text(encoding='utf-8')
        code, out = self.override_persona(path, reason='  ')
        self.assertEqual(code, 1, out)
        self.assertIn('reason', out['error'])
        self.assertEqual(path.read_text(encoding='utf-8'), before)

    def test_tc3_likeness_an_override_with_no_decision_probability_is_refused(self):
        path = self.tmp / 'triage-no-probability.json'
        record = {'question': 'd3-figure', 'answer': 'unrecorded (Jev failed: HTTP 500)',
                  'uncertainty_basis': {'choice': None, 'line': 0.5, 'line_version': 0},
                  'exact_evidence': {'eligible': ['cataloguer', 'builder'], 'excluded': {}}}
        path.write_text(json.dumps({'decision_records': {'value': [record], 'stamped_at': '2026-10-29T00:00:00.000Z'}}),
                        encoding='utf-8')
        code, out = self.override_persona(path)
        self.assertEqual(code, 1, out)
        self.assertIn('no adequacy probability', out['error'])
        self.assertNotIn('overrides', json.loads(path.read_text(encoding='utf-8')))

    def test_an_unknown_persona_is_refused_never_matched(self):
        code, out = self.run_decide('roster-two.yaml', member='m14')
        self.assertEqual(code, 0, out)
        path = self.pending_path(member='m14')
        code, out = self.override_persona(path, persona='catalog')
        self.assertEqual(code, 1, out)
        self.assertIn('unknown persona', out['error'])
        self.assertNotIn('overrides', json.loads(path.read_text(encoding='utf-8')))

    def test_the_decision_s_own_persona_is_no_override(self):
        code, out = self.run_decide('roster-two.yaml', member='m15')
        self.assertEqual(code, 0, out)
        code, out = self.override_persona(self.pending_path(member='m15'), persona='builder')
        self.assertEqual(code, 1, out)
        self.assertIn('the decision\'s own persona', out['error'])

    def test_a_persona_override_needs_the_parent_s_persona_and_a_persona_record(self):
        code, out = self.run_decide('roster-two.yaml', member='m16')
        self.assertEqual(code, 0, out)
        code, out = self.override_persona(self.pending_path(member='m16'), parent='')
        self.assertEqual(code, 1, out)
        path = self.tmp / 'triage-no-d3.json'
        records = {'value': [{'question': 'd1-act', 'answer': 'build'}], 'stamped_at': '2026-10-29T00:00:00.000Z'}
        path.write_text(json.dumps({'decision_records': records}), encoding='utf-8')
        code, out = self.override_persona(path)
        self.assertEqual(code, 1, out)
        self.assertIn('no d3-figure record', out['error'])

    def test_an_override_of_the_act_decision_is_refused(self):
        code, out = self.run_decide('roster-two.yaml', member='m17')
        self.assertEqual(code, 0, out)
        code, out = self.run_script(['override', '--pending', str(self.pending_path(member='m17')), '--decision',
                                     'd1-act', '--level', 'high', '--reason', 'r'])
        self.assertEqual(code, 1, out)
        self.assertIn('d3-figure', out['error'])
        self.assertIn('d1-act', out['error'])


    # -- The group the part's kind is paired with (R-10) -------------------------------------------------------------

    def test_r10_the_kind_s_paired_group_is_read_from_the_table_given(self):
        code, out = self.run_decide('roster-two.yaml', member='m20',
                                    extra=['--kind-groups', str(FIXTURES / 'kind-groups.json')])
        self.assertEqual(code, 0, out)
        self.assertEqual(out['kind_paired_grouping'], 'makers')
        data = self.pending(member='m20')
        self.assertEqual(data['kind_paired_grouping']['value'], 'makers')
        self.assertRegex(data['kind_paired_grouping']['stamped_at'], r'^\d{4}-\d\d-\d\dT')
        self.check_schema(data)

    def test_r10_a_named_key_finds_the_pairs(self):
        table = self.tmp / 'nested.json'
        table.write_text(json.dumps({'outer': {'groups': {'build': 'makers'}}}), encoding='utf-8')
        code, out = self.run_decide('roster-two.yaml', member='m21',
                                    extra=['--kind-groups', str(table), '--kind-groups-key', 'outer.groups'])
        self.assertEqual(code, 0, out)
        self.assertEqual(self.pending(member='m21')['kind_paired_grouping']['value'], 'makers')

    def test_r10_with_no_table_the_value_is_unrecorded_and_the_triage_goes_on(self):
        code, out = self.run_decide('roster-two.yaml', member='m22')
        self.assertEqual(code, 0, out)
        data = self.pending(member='m22')
        self.assertEqual(data['kind_paired_grouping']['value'], 'unrecorded (no kind-to-group table was given)')
        self.assertEqual(data['triage_persona']['value'], 'builder')
        self.check_schema(data)

    def test_r10_a_kind_the_table_lacks_is_unrecorded_never_guessed(self):
        code, out = self.run_decide('roster-two.yaml', member='m23',
                                    extra=['--kind-groups', str(FIXTURES / 'kind-groups-no-build.json')])
        self.assertEqual(code, 0, out)
        value = self.pending(member='m23')['kind_paired_grouping']['value']
        self.assertRegex(value, r'^unrecorded \(.+\)$')
        self.assertIn('pairs no group with build', value)
        self.assertNotIn('readers', value)
        self.assertEqual(out['persona']['persona'], 'builder')

    def test_r10_an_unreadable_table_is_unrecorded_and_the_triage_goes_on(self):
        code, out = self.run_decide('roster-two.yaml', member='m24',
                                    extra=['--kind-groups', str(self.tmp / 'missing.json')])
        self.assertEqual(code, 0, out)
        value = self.pending(member='m24')['kind_paired_grouping']['value']
        self.assertTrue(value.startswith('unrecorded (the kind-to-group table'), value)
        self.assertEqual(out['effort']['level'], 'medium')

    def test_r10_a_table_whose_key_holds_no_pairs_is_unrecorded(self):
        code, out = self.run_decide('roster-two.yaml', member='m25',
                                    extra=['--kind-groups', str(FIXTURES / 'kind-groups.json'),
                                           '--kind-groups-key', 'absent'])
        self.assertEqual(code, 0, out)
        value = self.pending(member='m25')['kind_paired_grouping']['value']
        self.assertIn('absent', value)
        self.assertTrue(value.startswith('unrecorded ('), value)

    def test_r10_with_no_kind_read_the_value_says_so(self):
        code, out = self.run_decide('roster-two.yaml', part='part-plain.md', member='m26',
                                    extra=['--kind-groups', str(FIXTURES / 'kind-groups.json')])
        self.assertEqual(code, 0, out)
        self.assertIsNone(out['act']['kind'])
        value = self.pending(member='m26')['kind_paired_grouping']['value']
        self.assertEqual(value, 'unrecorded (the act decision read no kind)')
        self.check_schema(self.pending(member='m26'))

if __name__ == '__main__':
    unittest.main()
