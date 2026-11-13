"""Tests for decide.py: the act decision (D-1), the persona decision (D-3) and the effort decision (D-4) for one part,
asked of a stand-in for Jev, with every request recorded through the ledger's writer and the pending triage file
written; and its override mode.

The stand-in answers from marks in the fixtures, never from the live service:
- the act Choice reads `build` at 0.8 when the part carries MARK-BUILD, `setting-right` when it carries MARK-CANON,
  `verdict-or-review` when it carries MARK-REVIEW and `two-or-more` when it carries MARK-TWO;
- each act Noul gives 0.9 for the build test on a MARK-BUILD part and for the setting-right test on a MARK-CANON
  part, and 0.05 otherwise;
- the form Choice reads `code` at 0.9 for MARK-CODE, `model` at 0.9 for MARK-SKILL, `both` at 0.9 for MARK-HOOK,
  `model` at 0.4 (below the line) for MARK-UNSURE, and `none` at 0.9 otherwise;
- the persona Choice gives most weight to a persona whose goal carries MARK-ADEQUATE;
- the adequacy Noul gives 0.9 when the persona's goal carries MARK-ADEQUATE, and 0.1 otherwise;
- the harness and model Choices read the option whose text carries MARK-PICK, else the first; on a MARK-OFFLIST part
  they answer `rogue`, a label the question never offered;
- the effort Choice reads `medium` at 0.6 where it is offered, else the first level offered.

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
         'user-decision', 'setting-right']
RECORD_FIELDS = {'question', 'definition_version', 'subject', 'quote', 'answer', 'uncertainty_basis',
                 'decision_point_classification', 'exact_evidence', 'lane', 'delegated_authority', 'evidence_state',
                 'decided_by', 'final_disposition'}
LEVELS = ['low', 'medium', 'high', 'xhigh', 'max']
STAGE = 'unrecorded (no task id was given)'
STAGE_TREE = FIXTURES / 'stage'
KEYS = ['--rows-key', 'rows', '--name-key', 'name', '--group-key', 'group', '--file-key', 'file',
        '--goal-key', 'meta.declaration.goal', '--does-key', 'meta.declaration.does',
        '--ratified-key', 'meta.declaration-ratified', '--user', 'the-user']


class StandIn:
    """A stand-in for Jev on a local port. `fail` names question types answered with HTTP 500; `fail_effort` fails the
    effort Choice alone. Each request is kept in `seen` with the time it arrived in `arrived`."""

    def __init__(self):
        self.fail = set()
        self.fail_qids = set()
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
                effort = qid == 'effort'
                if question['type'] in owner.fail or qid in owner.fail_qids or (effort and owner.fail_effort):
                    self.send_response(500)
                    self.end_headers()
                    self.wfile.write(b'stand-in told to fail')
                    return
                state = body['state']
                part = state.get('part', '')
                criteria = question.get('criteria', {})

                def spread(best, weight):
                    rest = (1.0 - weight) / max(len(criteria) - 1, 1)
                    return dict((label, weight if label == best else rest) for label in criteria)

                if effort:
                    best = 'medium' if 'medium' in criteria else list(criteria)[0]
                    probs = spread(best, 0.6)
                    answer = {'type': 'choice', 'choice': best, 'confidence': 0.6, 'probabilities': probs}
                elif qid == 'kind':
                    best = 'none'
                    for mark, label in (('MARK-TWO', 'two-or-more'), ('MARK-CANON', 'setting-right'),
                                        ('MARK-REVIEW', 'verdict-or-review'), ('MARK-BUILD', 'build')):
                        if mark in part and label in criteria:
                            best = label
                            break
                    probs = spread(best, 0.8)
                    answer = {'type': 'choice', 'choice': best, 'confidence': 0.9, 'probabilities': probs}
                elif qid == 'form':
                    best, weight = 'none', 0.9
                    for mark, label, at in (('MARK-CODE', 'code', 0.9), ('MARK-SKILL', 'model', 0.9),
                                            ('MARK-HOOK', 'both', 0.9), ('MARK-UNSURE', 'model', 0.4)):
                        if mark in part:
                            best, weight = label, at
                            break
                    probs = spread(best, weight)
                    answer = {'type': 'choice', 'choice': best, 'confidence': weight, 'probabilities': probs}
                elif qid in ('harness', 'model'):
                    picked = [label for label, text in criteria.items() if 'MARK-PICK' in text]
                    best = picked[0] if picked else list(criteria)[0]
                    probs = spread(best, 0.7)
                    if 'MARK-OFFLIST' in part:
                        best = 'rogue'
                        probs = dict(probs, rogue=0.9)
                    answer = {'type': 'choice', 'choice': best, 'confidence': 0.7, 'probabilities': probs}
                elif question['type'] == 'choice':
                    weights = dict((label, 7.0 if 'MARK-ADEQUATE' in text else 1.0)
                                   for label, text in criteria.items())
                    total = sum(weights.values())
                    probs = dict((label, weight / total) for label, weight in weights.items())
                    answer = {'type': 'choice', 'choice': max(probs, key=probs.get), 'confidence': 0.9,
                              'probabilities': probs}
                elif 'goal' in state:
                    answer = {'type': 'noul', 'noul': 0.9 if 'MARK-ADEQUATE' in state['goal'] else 0.1}
                else:
                    test = question['criteria']['true']
                    build = 'change what a program' in test and 'MARK-BUILD' in part
                    canon = 'governing text' in test and 'MARK-CANON' in part
                    answer = {'type': 'noul', 'noul': 0.9 if build or canon else 0.05}
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
        found = [body['state'] for body in self.jev.seen if list(body['questions']) == ['effort']]
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
        self.assertEqual(sorted(out['act']['choice']['probabilities']), sorted(KINDS + ['none', 'two-or-more']))
        self.assertEqual(out['act']['kind'], 'build')
        self.assertEqual(out['persona']['eligible'], ['cataloguer', 'builder'])
        self.assertEqual(sorted(out['persona']['choice']['probabilities']), ['builder', 'cataloguer'])
        self.assertEqual(out['persona']['persona'], 'builder')
        self.assertEqual(out['persona']['adequacy'], 0.9)
        self.assertFalse(out['persona']['below_line'])
        self.check_records(out)
        # Fourteen requests: nine Nouls, the act Choice, the form Choice, the persona Choice, the adequacy Noul and
        # the effort Choice. With no reachable list, the harness and the model are the parent's, and Jev is not asked.
        self.assertEqual(len(out['jev_calls']), 14)
        records = self.records()
        self.assertEqual(len(self.jev.seen), 14)
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
        self.assertEqual([r['question'] for r in data['decision_records']['value']],
                         ['d1-act', 'd5-form', 'd3-figure', 'd6-harness', 'd7-model', 'd4-effort'])
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
        self.assertEqual(len(out['jev_calls']), 12)
        record, = [r for r in out['decision_records'] if r['question'] == 'd3-figure']
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
        record, = [r for r in out['decision_records'] if r['question'] == 'd3-figure']
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
        exact = dict(self.d4(out)['exact_evidence'])
        self.assertEqual(exact.pop('levels_offered'), LEVELS)
        self.assertEqual(exact, facts)

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
        self.assertEqual([r['question'] for r in out['decision_records']],
                         ['d1-act', 'd6-harness', 'd7-model', 'd4-effort'])

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


    # -- The custodian rule (d3-figure's third eligibility rule) -----------------------------------------------------

    CUSTODIAN_RULE = 'the part names a unit the register records against other personas only'

    def test_custodian_a_part_naming_a_unit_reaches_only_its_custodian(self):
        # The builder's goal carries MARK-ADEQUATE, so without the rule the Choice would give it the part.
        code, out = self.run_decide('roster-two.yaml', part='part-unit.md', member='m30',
                                    extra=['--register', str(FIXTURES / 'register.yaml')])
        self.assertEqual(code, 0, out)
        self.assertEqual(out['persona']['eligible'], ['cataloguer'])
        self.assertIn(self.CUSTODIAN_RULE, out['persona']['excluded']['builder'])
        self.assertIn('shelves/catalogue/entry.md', out['persona']['excluded']['builder'])
        self.assertEqual(out['persona']['persona'], 'cataloguer')
        self.assertEqual(out['persona']['units_named'], ['shelves/catalogue/entry.md'])
        record, = [r for r in out['decision_records'] if r['question'] == 'd3-figure']
        self.assertEqual(record['exact_evidence']['units_named'], ['shelves/catalogue/entry.md'])
        data = self.pending(member='m30')
        self.assertEqual(data['persona_facts']['value']['eligible'], ['cataloguer'])
        self.check_schema(data)

    def test_custodian_the_register_s_keys_are_named_as_the_roster_s_are(self):
        code, out = self.run_decide('roster-two.yaml', part='part-unit.md', member='m31',
                                    extra=['--register', str(FIXTURES / 'register-keys.json'),
                                           '--register-rows-key', 'custody.entries', '--unit-key', 'item',
                                           '--custodian-key', 'keeper'])
        self.assertEqual(code, 0, out)
        self.assertEqual(out['persona']['eligible'], ['cataloguer'])

    def test_custodian_likeness_a_path_like_the_unit_is_not_the_unit(self):
        # An absolute path ending in the unit, and the unit with a suffix: neither is matched, so nothing changes.
        code, out = self.run_decide('roster-two.yaml', part='part-unit-likeness.md', member='m32',
                                    extra=['--register', str(FIXTURES / 'register.yaml')])
        self.assertEqual(code, 0, out)
        self.assertEqual(out['persona']['eligible'], ['cataloguer', 'builder'])
        self.assertEqual(out['persona']['units_named'], [])
        self.assertEqual(out['persona']['persona'], 'builder')

    def test_custodian_a_part_naming_no_unit_changes_nothing(self):
        code, out = self.run_decide('roster-two.yaml', member='m33',
                                    extra=['--register', str(FIXTURES / 'register.yaml')])
        self.assertEqual(code, 0, out)
        self.assertEqual(out['persona']['eligible'], ['cataloguer', 'builder'])
        self.assertEqual(out['persona']['excluded'], {})
        self.assertEqual(out['persona']['persona'], 'builder')

    def test_custodian_two_units_need_a_persona_recorded_against_each(self):
        code, out = self.run_decide('roster-two.yaml', part='part-two-units.md', member='m34',
                                    extra=['--register', str(FIXTURES / 'register.yaml')])
        self.assertEqual(code, 0, out)
        self.assertEqual(out['persona']['eligible'], [])
        self.assertTrue(out['persona']['answer'].startswith('none adequate ('), out['persona']['answer'])
        self.assertIn(self.CUSTODIAN_RULE, out['persona']['answer'])
        self.assertEqual(sorted(out['persona']['units_named']),
                         ['shelves/catalogue/entry.md', 'shelves/workshop/bench.md'])

    def test_custodian_an_unreadable_register_cannot_run(self):
        code, out = self.run_decide('roster-two.yaml', part='part-unit.md', member='m35',
                                    extra=['--register', str(self.tmp / 'missing.yaml')])
        self.assertEqual(code, 2, out)
        self.assertIn('missing.yaml', out['error'])
        self.assertFalse(self.pending_path(member='m35').exists())

    # -- R-37: the figure rests on the work, never on the sender (TC-24, the HARD constraint; SI-1) ----------------

    def persona_request(self):
        found = [body for body in self.jev.seen if list(body['questions']) == ['persona']]
        self.assertEqual(len(found), 1)
        return found[0]

    def test_tc24_r37_the_same_part_from_two_senders_gets_the_same_choice_and_no_sender_fact(self):
        code, first = self.run_decide('roster-two.yaml', member='m40', extra=['--parent-persona', 'cataloguer'])
        self.assertEqual(code, 0, first)
        sent_first = self.persona_request()
        self.jev.seen.clear()
        code, second = self.run_decide('roster-two.yaml', member='m41', extra=['--parent-persona', 'builder'])
        self.assertEqual(code, 0, second)
        sent_second = self.persona_request()
        # The request to Jev is the same whoever sent the part, and so is the choice.
        self.assertEqual(sent_first, sent_second)
        self.assertEqual(first['persona']['persona'], second['persona']['persona'])
        self.assertEqual(sorted(sent_first['state']), ['kind', 'part', 'stage'])
        for out in (first, second):
            d3, = [r for r in out['decision_records'] if r['question'] == 'd3-figure']
            for key in ('dispatching_persona', 'dispatching_group', 'kind_paired_group', 'sender'):
                self.assertNotIn(key, d3['exact_evidence'])
        # The sender is recorded as who sent the work, and on nothing a decision reads.
        self.assertEqual(self.pending(member='m40')['sender']['value'], 'cataloguer')
        self.assertEqual(self.pending(member='m41')['sender']['value'], 'builder')
        for member in ('m40', 'm41'):
            data = self.pending(member=member)
            self.assertNotIn('kind_paired_grouping', data)
            for key in ('dispatching_persona', 'dispatching_group', 'kind_paired_group'):
                self.assertNotIn(key, data['persona_facts']['value'])
            self.check_schema(data)

    def test_tc24_r37_the_choice_weighs_declared_goal_and_acts_and_names_no_group(self):
        code, out = self.run_decide('roster-two.yaml', member='m42')
        self.assertEqual(code, 0, out)
        question = self.persona_request()['questions']['persona']
        for text in [question['instructions']] + list(question['criteria'].values()):
            for word in ('dispatching', 'kind_paired', 'weigh both', 'workshop', 'library'):
                self.assertNotIn(word, text)
        self.assertIn('Builds what a settled design specifies', question['criteria']['builder'])
        self.assertIn('Writes code and its tests to a settled design', question['criteria']['builder'])
        adequacy = [body for body in self.jev.seen if list(body['questions']) == ['adequate']]
        self.assertEqual(len(adequacy), 1)
        self.assertNotIn('group', adequacy[0]['state'])
        self.assertNotIn('--kind-groups', SCRIPT.read_text(encoding='utf-8'))

    def test_tc24_r37_a_part_sent_by_the_persona_that_best_fits_it_goes_to_that_persona(self):
        code, out = self.run_decide('roster-two.yaml', member='m43', extra=['--parent-persona', 'builder'])
        self.assertEqual(code, 0, out)
        self.assertIn('builder', out['persona']['eligible'])
        self.assertEqual(out['persona']['persona'], 'builder')

    def test_tc24_r37_the_definition_s_instructions_carry_no_sender_and_no_paired_group(self):
        d3 = json.loads((SCRIPT.parent.parent / 'decisions' / 'd3-figure.json').read_text(encoding='utf-8'))
        text = json.dumps(d3['composition'])
        for word in ('dispatching', 'kind_paired', 'weigh both', '{group}'):
            self.assertNotIn(word, text)
        facts = ' '.join(d3['exact_facts']['facts_for_the_choice'])
        self.assertNotIn('dispatching', facts)
        self.assertNotIn('paired', facts)

    def test_tc24_r37_empty_a_part_meeting_no_test_goes_back_as_a_finding_with_no_kind_or_persona(self):
        code, out = self.run_decide('roster-two.yaml', part='part-plain.md', member='m44')
        self.assertEqual(code, 0, out)
        self.assertIsNone(out['act']['kind'])
        self.assertIsNone(out['persona'])
        self.assertIsNone(out['pending_file'])
        self.assertFalse([body for body in self.jev.seen if list(body['questions']) == ['persona']])

    def test_tc24_r37_a_part_meeting_two_tests_is_split_with_no_persona_and_no_pending_file(self):
        code, out = self.run_decide('roster-two.yaml', part='part-two-kinds.md', member='m45')
        self.assertEqual(code, 0, out)
        self.assertTrue(out['act']['split'])
        self.assertIsNone(out['act']['kind'])
        self.assertTrue(out['act']['answer'].startswith('split ('), out['act']['answer'])
        self.assertIsNone(out['persona'])
        self.assertIsNone(out['pending_file'])
        self.assertIn('split', out['no_pending_file'])
        kind_choice, = [body for body in self.jev.seen if list(body['questions']) == ['kind']]
        self.assertIn('two-or-more', kind_choice['questions']['kind']['criteria'])
        d1, = [r for r in out['decision_records'] if r['question'] == 'd1-act']
        self.assertIn('split', d1['answer'])

    # -- R-37's calling-to-account rule: the work's own record, never the sender -----------------------------------

    def work_record(self, persona, call_id='toolu_work_1'):
        sys.path.insert(0, str(LEDGER_SCRIPTS))
        import ledger
        # The ledger writes persona-name only where its settings turn the field on.
        (self.ledger / 'config.json').write_text('{"fields": "all"}', encoding='utf-8')
        written = ledger.dispatch(ledger=str(self.ledger), brief='The work called to account.', session=SESSION,
                                  call_id=call_id, agent_id='unrecorded (not yet returned)',
                                  dispatched_at='2026-01-15T00:00:00.000Z', route='subagent',
                                  harness='claude-code', caller='parent', **{'persona-name': persona})
        self.assertTrue(written.ok, written)
        return call_id

    def test_tc24_r37_a_review_part_excludes_the_group_of_the_persona_that_did_the_work(self):
        call = self.work_record('builder')
        code, out = self.run_decide('roster-three.yaml', part='part-review.md', member='m46',
                                    extra=['--work-call', call, '--parent-persona', 'cataloguer'])
        self.assertEqual(code, 0, out)
        self.assertEqual(out['act']['kind'], 'verdict-or-review')
        self.assertEqual(sorted(out['persona']['eligible']), ['cataloguer', 'reviewer'])
        for name in ('builder', 'reasoner'):
            self.assertIn('performed the work called to account', out['persona']['excluded'][name])
        chosen = out['persona']['persona']
        self.jev.seen.clear()
        # The same part sent by a persona of the workshop: the same candidates and the same choice.
        code, again = self.run_decide('roster-three.yaml', part='part-review.md', member='m47',
                                      extra=['--work-call', call, '--parent-persona', 'reasoner'])
        self.assertEqual(code, 0, again)
        self.assertEqual(again['persona']['eligible'], out['persona']['eligible'])
        self.assertEqual(again['persona']['persona'], chosen)

    def test_tc24_r37_empty_a_review_part_whose_work_names_no_performer_goes_back_as_a_finding(self):
        code, out = self.run_decide('roster-three.yaml', part='part-review.md', member='m48',
                                    extra=['--parent-persona', 'builder'])
        self.assertEqual(code, 0, out)
        self.assertIsNone(out['persona']['persona'])
        self.assertIn('called to account', out['persona']['answer'])
        self.assertFalse([body for body in self.jev.seen if list(body['questions']) == ['persona']])
        code, out = self.run_decide('roster-three.yaml', part='part-review.md', member='m49',
                                    extra=['--work-call', 'toolu_no_such_call'])
        self.assertEqual(code, 0, out)
        self.assertIsNone(out['persona']['persona'])
        self.assertIn('toolu_no_such_call', out['persona']['answer'])

    # -- R-38: the form decides the builder of a part that makes a capability (TC-25; SI-1) ------------------------

    FORMS = ['--forms', str(FIXTURES / 'forms.json')]

    def d(self, out, question):
        found = [r for r in out['decision_records'] if r['question'] == question]
        self.assertEqual(len(found), 1, [r['question'] for r in out['decision_records']])
        return found[0]

    def test_tc25_r38_a_parser_is_code_and_goes_to_the_code_builder_the_map_names(self):
        code, out = self.run_decide('roster-three.yaml', part='part-parser.md', member='m50', extra=self.FORMS)
        self.assertEqual(code, 0, out)
        self.assertEqual(out['form']['form'], 'code')
        self.assertFalse(out['form']['below_line'])
        self.assertEqual(out['persona']['persona'], 'builder')
        self.assertEqual(self.d(out, 'd5-form')['answer'], 'code')
        # The map names the builder exactly: no persona Choice is asked.
        self.assertFalse([body for body in self.jev.seen if list(body['questions']) == ['persona']])
        data = self.pending(member='m50')
        self.assertEqual(data['triage_persona']['value'], 'builder')
        self.assertIn('d5-form', [r['question'] for r in data['decision_records']['value']])
        self.check_schema(data)

    def test_tc25_r38_a_skill_is_model_and_goes_to_the_model_builder(self):
        code, out = self.run_decide('roster-three.yaml', part='part-skill.md', member='m51', extra=self.FORMS)
        self.assertEqual(code, 0, out)
        self.assertEqual(out['form']['form'], 'model')
        self.assertEqual(out['persona']['persona'], 'reasoner')

    def test_tc25_r38_a_hook_and_its_prompt_make_both_and_the_part_is_split(self):
        code, out = self.run_decide('roster-three.yaml', part='part-hook.md', member='m52', extra=self.FORMS)
        self.assertEqual(code, 0, out)
        self.assertTrue(out['form']['split'])
        self.assertIsNone(out['persona'])
        self.assertIsNone(out['pending_file'])
        self.assertIn('split', out['no_pending_file'])

    def test_tc25_r38_below_its_line_the_form_goes_to_the_model_builder_marked(self):
        code, out = self.run_decide('roster-three.yaml', part='part-unsure.md', member='m53', extra=self.FORMS)
        self.assertEqual(code, 0, out)
        self.assertTrue(out['form']['below_line'])
        self.assertEqual(out['form']['form'], 'model')
        self.assertEqual(out['persona']['persona'], 'reasoner')
        record = self.d(out, 'd5-form')
        self.assertIn('below the line', record['answer'])
        self.assertEqual(record['uncertainty_basis']['probability'], 0.4)
        self.assertEqual(record['uncertainty_basis']['line'], 0.5)
        self.assertEqual(record['uncertainty_basis']['line_version'], 0)
        self.assertEqual(record['lane'], 'reasoned')

    def test_tc25_r38_empty_a_build_part_making_no_capability_takes_no_form(self):
        code, out = self.run_decide('roster-three.yaml', member='m54', extra=self.FORMS)
        self.assertEqual(code, 0, out)
        self.assertIsNone(out['form']['form'])
        self.assertTrue(self.d(out, 'd5-form')['answer'].startswith('none ('))
        # Its persona is chosen by the persona Choice over every eligible persona (R-37 alone).
        request = self.persona_request()
        self.assertEqual(sorted(request['questions']['persona']['criteria']),
                         ['builder', 'cataloguer', 'reasoner', 'reviewer'])

    def test_tc25_r38_likeness_a_map_with_no_builder_for_the_form_is_a_finding(self):
        for member, extra in (('m55', ['--forms', str(FIXTURES / 'forms-no-code.json')]), ('m56', [])):
            code, out = self.run_decide('roster-three.yaml', part='part-parser.md', member=member, extra=extra)
            self.assertEqual(code, 0, out)
            self.assertIsNone(out['persona']['persona'])
            self.assertTrue(out['persona']['answer'].startswith('none adequate ('), out['persona']['answer'])
            self.assertIn('code', out['persona']['answer'])

    def test_tc25_r38_a_part_that_is_not_making_takes_no_form_question(self):
        code, out = self.run_decide('roster-three.yaml', part='part-canon.md', member='m57', extra=self.FORMS)
        self.assertEqual(code, 0, out)
        self.assertIsNone(out['form'])
        self.assertFalse([body for body in self.jev.seen if list(body['questions']) == ['form']])

    # -- R-39: the model and the harness, from the reachable list (TC-26; SI-4) ------------------------------------

    def reachable(self, name):
        return ['--reachable', str(FIXTURES / name), '--parent-harness', 'harness-p', '--parent-model', 'model-p']

    def test_tc26_r39_empty_settings_listing_nothing_assign_the_parent_s_own_saying_why(self):
        code, out = self.run_decide('roster-two.yaml', member='m60',
                                    extra=['--parent-harness', 'harness-p', '--parent-model', 'model-p'])
        self.assertEqual(code, 0, out)
        self.assertEqual(out['harness']['pass'], 'harness-p')
        self.assertEqual(out['model']['pass'], 'model-p')
        for question in ('d6-harness', 'd7-model'):
            record = self.d(out, question)
            self.assertIn('the settings list', json.dumps(record['uncertainty_basis']))
        self.assertFalse([body for body in self.jev.seen if list(body['questions']) in (['harness'], ['model'])])
        data = self.pending(member='m60')
        self.assertEqual(data['harness_assigned']['value'], 'harness-p')
        self.check_schema(data)

    def test_tc26_r39_the_harness_then_its_model_are_chosen_from_the_list_and_d4_over_its_levels(self):
        code, out = self.run_decide('roster-two.yaml', member='m61', extra=self.reachable('reachable-two.json'))
        self.assertEqual(code, 0, out)
        harness_q, = [b for b in self.jev.seen if list(b['questions']) == ['harness']]
        self.assertEqual(sorted(harness_q['questions']['harness']['criteria']), ['harness-a', 'harness-b'])
        self.assertEqual(out['harness']['pass'], 'harness-b')
        model_q, = [b for b in self.jev.seen if list(b['questions']) == ['model']]
        self.assertEqual(sorted(model_q['questions']['model']['criteria']), ['model-b1', 'model-b2'])
        self.assertEqual(out['model']['pass'], 'model-b2')
        effort_q, = [b for b in self.jev.seen if list(b['questions']) == ['effort']]
        self.assertEqual(list(effort_q['questions']['effort']['criteria']), ['medium', 'max'])
        self.assertEqual(effort_q['state']['harness'], 'harness-b')
        self.assertEqual(effort_q['state']['model'], 'model-b2')
        # The order: the figure, then the harness and the model, then the effort.
        order = [list(b['questions'])[0] for b in self.jev.seen]
        self.assertLess(order.index('persona'), order.index('harness'))
        self.assertLess(order.index('harness'), order.index('model'))
        self.assertLess(order.index('model'), order.index('effort'))
        self.assertEqual(self.pending(member='m61')['harness_assigned']['value'], 'harness-b')
        self.assertEqual(self.d(out, 'd4-effort')['exact_evidence']['levels_offered'], ['medium', 'max'])

    def test_tc26_r39_one_listed_harness_and_model_are_assigned_without_asking(self):
        code, out = self.run_decide('roster-two.yaml', member='m62', extra=self.reachable('reachable-one.json'))
        self.assertEqual(code, 0, out)
        self.assertEqual((out['harness']['pass'], out['model']['pass']), ('harness-only', 'model-only'))
        self.assertFalse([body for body in self.jev.seen if list(body['questions']) in (['harness'], ['model'])])
        effort_q, = [b for b in self.jev.seen if list(b['questions']) == ['effort']]
        self.assertEqual(list(effort_q['questions']['effort']['criteria']), ['low', 'high'])

    def test_tc26_r39_likeness_an_answer_off_the_list_is_never_assigned(self):
        code, out = self.run_decide('roster-two.yaml', part='part-offlist.md', member='m63',
                                    extra=self.reachable('reachable-two.json'))
        self.assertEqual(code, 3, out)
        self.assertNotEqual(out['harness']['pass'], 'rogue')
        self.assertNotEqual(out['model']['pass'], 'rogue')
        self.assertEqual(out['harness']['pass'], 'harness-p')
        self.assertTrue(self.d(out, 'd6-harness')['answer'].startswith('unrecorded ('))
        self.assertEqual(self.pending(member='m63')['harness_assigned']['value'], 'harness-p')

    def test_tc26_r39_empty_a_failed_decision_passes_the_parent_s_own_saying_why(self):
        self.jev.fail_qids.update(('harness', 'model'))
        code, out = self.run_decide('roster-two.yaml', member='m64', extra=self.reachable('reachable-two.json'))
        self.assertEqual(code, 3, out)
        self.assertEqual(out['harness']['pass'], 'harness-p')
        self.assertEqual(out['model']['pass'], 'model-p')
        self.assertIn('the parent', out['harness']['route'])
        data = self.pending(member='m64')
        self.assertIn('harness decision', data['triage_failure']['value'])

    def override_value(self, member, decision, option, value, reason='the work needs a longer context'):
        return self.run_script(['override', '--pending', str(self.pending_path(member=member)), '--decision',
                                decision, option, value, '--reason', reason])

    def test_tc26_r39_an_override_records_both_values_its_reason_and_time(self):
        code, out = self.run_decide('roster-two.yaml', member='m65', extra=self.reachable('reachable-two.json'))
        self.assertEqual(code, 0, out)
        code, out = self.override_value('m65', 'd6-harness', '--harness', 'harness-a')
        self.assertEqual(code, 0, out)
        entry = out['override']
        self.assertEqual((entry['decision'], entry['decision_harness'], entry['harness_passed']),
                         ('d6-harness', 'harness-b', 'harness-a'))
        self.assertEqual(entry['reason'], 'the work needs a longer context')
        self.assertRegex(entry['at'], r'^\d{4}-\d\d-\d\dT')
        code, out = self.override_value('m65', 'd7-model', '--model', 'model-b1')
        self.assertEqual(code, 0, out)
        entry = out['override']
        self.assertEqual((entry['decision_model'], entry['model_passed']), ('model-b2', 'model-b1'))
        data = self.pending(member='m65')
        self.assertEqual(data['harness_assigned']['value'], 'harness-a')
        self.assertEqual([o['decision'] for o in data['overrides']['value']], ['d6-harness', 'd7-model'])
        self.check_schema(data)

    def test_tc26_r39_likeness_an_override_off_the_list_or_with_no_reason_is_refused(self):
        code, out = self.run_decide('roster-two.yaml', member='m66', extra=self.reachable('reachable-two.json'))
        self.assertEqual(code, 0, out)
        before = self.pending_path(member='m66').read_text(encoding='utf-8')
        for decision, option, value, reason in (('d6-harness', '--harness', 'harness-z', 'r'),
                                                ('d7-model', '--model', 'model-a1', 'r'),
                                                ('d6-harness', '--harness', 'harness-a', '  '),
                                                ('d4-effort', '--level', 'low', 'r')):
            code, out = self.override_value('m66', decision, option, value, reason=reason)
            self.assertEqual(code, 1, (decision, value, out))
        self.assertEqual(self.pending_path(member='m66').read_text(encoding='utf-8'), before)

    # -- R-40: the values assigned reach the pending file (TC-27; SI-8) --------------------------------------------

    def test_tc27_r40_the_pending_file_carries_the_harness_assigned_the_sender_and_every_decision_record(self):
        code, out = self.run_decide('roster-three.yaml', part='part-parser.md', member='m67',
                                    extra=self.FORMS + self.reachable('reachable-two.json')
                                    + ['--parent-persona', 'cataloguer'])
        self.assertEqual(code, 0, out)
        data = self.pending(member='m67')
        self.assertEqual(data['harness_assigned']['value'], out['harness']['pass'])
        self.assertEqual(data['sender']['value'], 'cataloguer')
        self.assertEqual([r['question'] for r in data['decision_records']['value']],
                         ['d1-act', 'd5-form', 'd3-figure', 'd6-harness', 'd7-model', 'd4-effort'])
        model = [r for r in data['decision_records']['value'] if r['question'] == 'd7-model'][0]
        self.assertEqual(model['answer'], out['model']['pass'])
        self.check_records(out)
        self.check_schema(data)

    def test_tc27_r40_with_no_sender_given_the_sender_reads_unrecorded_with_its_reason(self):
        code, out = self.run_decide('roster-two.yaml', member='m68')
        self.assertEqual(code, 0, out)
        self.assertRegex(self.pending(member='m68')['sender']['value'], r'^unrecorded \(.+\)$')

    # -- The ninth kind: setting a governing text right ------------------------------------------------------------

    def test_a_part_setting_a_governing_text_right_reads_as_the_ninth_kind(self):
        code, out = self.run_decide('roster-two.yaml', part='part-canon.md', member='m70')
        self.assertEqual(code, 0, out)
        self.assertIn('setting-right', out['act']['nouls'])
        self.assertEqual(out['act']['nouls']['setting-right'], 0.9)
        self.assertEqual(out['act']['kind'], 'setting-right')
        self.assertEqual(self.pending(member='m70')['kind']['value'], 'setting-right')
        self.check_schema(self.pending(member='m70'))

    def test_likeness_a_skill_s_prose_still_reads_as_build(self):
        code, out = self.run_decide('roster-three.yaml', part='part-skill.md', member='m71', extra=self.FORMS)
        self.assertEqual(code, 0, out)
        self.assertEqual(out['act']['kind'], 'build')
        self.assertLess(out['act']['nouls']['setting-right'], 0.5)

    def test_the_act_decision_names_nine_kinds_and_the_kinds_file_tests_each(self):
        d1 = json.loads((SCRIPT.parent.parent / 'decisions' / 'd1-act.json').read_text(encoding='utf-8'))
        self.assertEqual(d1['kinds']['names'], KINDS)
        self.assertEqual(sorted(d1['composition']['nouls']['lines']), sorted(KINDS))
        kinds = json.loads((LEDGER_SCRIPTS / 'kinds.json').read_text(encoding='utf-8'))['kinds']
        test, = [k['test'] for k in kinds if k['name'] == 'setting-right']
        for word in ('canon', 'thiasos', 'diorth', 'Mouseion', 'synodos'):
            self.assertNotIn(word, test)

    # -- Themis's F7: the act decision's definition says what decide.py does with the Nouls -------------------------

    def test_f7_d1_the_definition_says_the_nouls_are_asked_while_no_line_is_set_and_none_is_applied(self):
        code, out = self.run_decide('roster-two.yaml', member='m80')
        self.assertEqual(code, 0, out)
        nouls_asked = [b for b in self.jev.seen
                       if [q['type'] for q in b['questions'].values()] == ['noul'] and
                       list(b['questions'])[0].startswith('kind_')]
        self.assertEqual(len(nouls_asked), len(KINDS), 'decide.py asks one Noul per kind')
        d1 = json.loads((SCRIPT.parent.parent / 'decisions' / 'd1-act.json').read_text(encoding='utf-8'))
        nouls = d1['composition']['nouls']
        self.assertTrue(all(line is None for line in nouls['lines'].values()), 'no line is set yet')
        self.assertIs(nouls['ask_before_lines_set'], True, 'the definition says the Nouls are not asked')
        self.assertIs(out['act']['line_applied'], False)
        self.assertNotIn('not asked', d1['basis'])
        self.assertIn('calibration', d1['basis'])

    # -- Themis's F4: after a model override, an effort override is checked against the passed model's levels ------

    def test_f4_r39_the_model_record_gives_the_levels_each_listed_model_is_offered(self):
        code, out = self.run_decide('roster-two.yaml', member='m81', extra=self.reachable('reachable-two.json'))
        self.assertEqual(code, 0, out)
        self.assertEqual(self.d(out, 'd7-model')['exact_evidence']['levels_offered'],
                         {'model-b1': ['low', 'high'], 'model-b2': ['medium', 'max']})

    def test_f4_r39_after_a_model_override_the_effort_override_is_checked_against_the_model_passed(self):
        code, out = self.run_decide('roster-two.yaml', member='m82', extra=self.reachable('reachable-two.json'))
        self.assertEqual(code, 0, out)
        self.assertEqual(out['model']['pass'], 'model-b2')  # offered medium and max on harness-b
        code, out = self.override_value('m82', 'd7-model', '--model', 'model-b1')  # offered low and high there
        self.assertEqual(code, 0, out)
        before = self.pending_path(member='m82').read_text(encoding='utf-8')
        code, out = self.override_value('m82', 'd4-effort', '--level', 'max')
        self.assertEqual(code, 1, ('max is offered model-b2, not model-b1, the model passed', out))
        self.assertEqual(self.pending_path(member='m82').read_text(encoding='utf-8'), before)
        code, out = self.override_value('m82', 'd4-effort', '--level', 'low')
        self.assertEqual(code, 0, ('low is offered model-b1, the model passed', out))
        self.assertEqual((out['override']['decision_level'], out['override']['level_passed']), ('medium', 'low'))
        self.check_schema(self.pending(member='m82'))

    def test_f4_r39_empty_with_no_model_override_the_decision_s_own_model_s_levels_still_decide(self):
        code, out = self.run_decide('roster-two.yaml', member='m83', extra=self.reachable('reachable-two.json'))
        self.assertEqual(code, 0, out)
        code, out = self.override_value('m83', 'd4-effort', '--level', 'low')
        self.assertEqual(code, 1, ('low is not offered model-b2, the model assigned', out))
        code, out = self.override_value('m83', 'd4-effort', '--level', 'max')
        self.assertEqual(code, 0, out)


if __name__ == '__main__':
    unittest.main()
