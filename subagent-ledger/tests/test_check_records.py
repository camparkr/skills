"""Controls for what the ledger records of a check's results and of the parent's decisions on them.

  * The witness line at each checked hand-back and each stop carries that point's result (R-19, R-21).
  * A hand-back member's stop with no delivered hand-back before it writes no return (R-19, R-23).
  * The wrapper's gate step at the parent's PreToolUse, and its context step after the capture (R-33, R-36).
  * The disposition line: its writer, its schema, and the capture's turning of a pending file into one (R-36).
  * The count check's rules for results and dispositions (TC-16).

Each criterion has its paired cases: an empty one (zero of the thing, which must give an error or a stated reason,
never a silent pass) and a likeness (the right shape with the wrong substance, which must be told apart). They were
committed before the code they test, and each failed then.

The checks here are stand-ins written by this file, and the check results are planted in the shape a check leaves
them, so the ledger skill's tests need no other skill. No test calls a live service. Each test has its own ledger
folder; SUBAGENT_LEDGER_DIR is removed from the environment, and HOME and CLAUDE_CONFIG_DIR name temporary folders.

Run from the skill's folder:  python3 -m unittest discover -s tests
"""

import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
SCRIPTS = HERE.parent / 'skill' / 'scripts'
CAPTURE = SCRIPTS / 'capture_claude_code.py'
WRAPPER = SCRIPTS / 'wrapper.py'
CALLS = SCRIPTS / 'calls.py'
SESSION = '0d0d0d0d-4444-4555-8666-777777777777'
CLOSING = 'All finished here.'
REPORT = 'The work is done.\n\n## Output\nnone\n'
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))


def lines(path):
    path = Path(path)
    if not path.is_file():
        return []
    return [json.loads(line) for line in path.read_text(encoding='utf-8').splitlines() if line.strip()]


def sha(text):
    return hashlib.sha256(text.encode('utf-8')).hexdigest()


def usage(output=3):
    return {'input_tokens': 10, 'cache_creation_input_tokens': 0, 'cache_read_input_tokens': 0,
            'output_tokens': output}


def run(call_id, agent, results, run_id='r1', text=REPORT, **extra):
    """A check run as a check leaves it: its key, the text it read, and one result per check."""
    found = {'key': {'agent_id': agent, 'call_id': call_id, 'member': 'm', 'attempt': 1},
             'report': 'hand-back message', 'sha256': sha(text),
             'checks': [dict({'id': '%s-%d' % (run_id, n), 'check': n, 'result': value},
                             **({'repair': 'Do this.'} if value == 'fail' else {}))
                        for n, value in enumerate(results, 1)]}
    found.update(extra)
    return found


# A stand-in check that prints a run with one fail, and one whose result is a clean run.
CHECK_FAIL = ("import json, sys; p = json.load(sys.stdin); print(json.dumps({'refuse': False, 'reason': '', "
              "'key': {'agent_id': p.get('agent_id'), 'call_id': 'toolu_k_1'}, 'report': 'final message', "
              "'checks': [{'id': 'x1-1', 'check': 1, 'result': 'fail', 'repair': 'Fix it.'}]}))")
CHECK_PASS = ("import json, sys; p = json.load(sys.stdin); print(json.dumps({'refuse': False, 'reason': '', "
              "'key': {'agent_id': p.get('agent_id')}, 'checks': [{'id': 'x2-1', 'check': 1, 'result': 'pass'}]}))")
GATE_REFUSE = "import json, sys; sys.stdin.read(); print(json.dumps({'refuse': True, 'reason': 'held by the gate'}))"
GATE_RAISE = "import sys; sys.stdin.read(); raise SystemExit('the gate broke')"
CONTEXT = ("import json, sys; p = json.load(sys.stdin); print(json.dumps({'refuse': False, 'reason': '', "
           "'context': 'results for ' + p.get('hook_event_name', '')}))")


class World(unittest.TestCase):

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix='check-records-'))
        self.addCleanup(shutil.rmtree, str(self.tmp), True)
        self.ledger = self.tmp / 'ledger'
        self.ledger.mkdir()
        self.work = self.tmp / 'work'
        self.work.mkdir()
        self.config_dir = self.tmp / 'config'
        self.project = self.config_dir / 'projects' / 'p'
        self.project.mkdir(parents=True)
        self.set_config()

    def script(self, name, code):
        path = self.tmp / ('%s.py' % name)
        path.write_text(code + '\n', encoding='utf-8')
        return '"%s" "%s"' % (sys.executable, path)

    def set_config(self, **checks):
        config = {'fields': 'all', 'background_wait_seconds': 3, 'check_seconds': 10}
        if checks:
            config['checks'] = checks
        (self.ledger / 'config.json').write_text(json.dumps(config), encoding='utf-8')

    def hook(self, script, event, payload):
        env = dict(os.environ, HOME=str(self.tmp / 'home'), CLAUDE_CONFIG_DIR=str(self.config_dir))
        env.pop('SUBAGENT_LEDGER_DIR', None)
        done = subprocess.run([sys.executable, str(script), event, '--ledger', str(self.ledger)],
                              input=json.dumps(payload), capture_output=True, text=True, env=env,
                              cwd=str(self.work), timeout=60)
        self.assertEqual(done.returncode, 0, done.stderr)
        text = done.stdout.strip()
        return json.loads(text) if text else None

    def records(self):
        return lines(self.ledger / ('%s.jsonl' % SESSION))

    def write(self, writer, **fields):
        import ledger
        found = getattr(ledger, writer)(ledger=str(self.ledger), session=SESSION, **fields)
        self.assertTrue(getattr(found, 'ok', False), lines(self.ledger / 'capture-errors.jsonl'))
        return found

    def transcript(self, agent, rows):
        path = self.project / SESSION / 'subagents' / ('agent-%s.jsonl' % agent)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(''.join(json.dumps(r) + '\n' for r in rows), encoding='utf-8')
        return path

    def parent(self, tool, given, call_id='toolu_p_1', event='PreToolUse', **more):
        payload = {'session_id': SESSION, 'cwd': str(self.work), 'hook_event_name': event, 'tool_name': tool,
                   'tool_input': given, 'tool_use_id': call_id, 'transcript_path': str(self.tmp / 'none.jsonl'),
                   'effort': {'level': 'high'}}
        payload.update(more)
        return self.hook(WRAPPER, event, payload)

    def denied(self, decision):
        found = (decision or {}).get('hookSpecificOutput') or {}
        return found.get('permissionDecisionReason') if found.get('permissionDecision') == 'deny' else None

    def count_check(self, call_ids=()):
        parent = self.project / ('%s.jsonl' % SESSION)
        parent.write_text(''.join(json.dumps({'type': 'assistant', 'uuid': 'p-%s' % c, 'message': {
            'id': 'p-%s' % c, 'role': 'assistant', 'model': 'test-model', 'stop_reason': 'tool_use',
            'content': [{'type': 'tool_use', 'id': c, 'name': 'Agent', 'input': {'prompt': 'x'}}],
            'usage': usage(1)}}) + '\n' for c in call_ids), encoding='utf-8')
        env = dict(os.environ, HOME=str(self.tmp / 'home'), CLAUDE_CONFIG_DIR=str(self.config_dir))
        env.pop('SUBAGENT_LEDGER_DIR', None)
        done = subprocess.run([sys.executable, str(CALLS), '--session', SESSION, '--ledger', str(self.ledger),
                               '--json', '--count-check', '--harness', 'claude-code', '--transcript', str(parent)],
                              capture_output=True, text=True, env=env, timeout=60)
        return done.returncode, json.loads(done.stdout)


# ---------------------------------------------------------------------------
# R-19 and R-21: the witness line carries the result at a hand-back and at a stop
# ---------------------------------------------------------------------------

class Witness(World):

    def handback(self, agent, call='toolu_hb_1', event='PreToolUse'):
        payload = {'session_id': SESSION, 'cwd': str(self.work), 'hook_event_name': event, 'agent_id': agent,
                   'tool_name': 'SubagentHandback', 'tool_use_id': call, 'tool_input': {'message': REPORT},
                   'permission_mode': 'auto'}
        return self.hook(WRAPPER, event, payload)

    def test_r19_a_passing_hand_back_writes_a_witness_line_carrying_its_result(self):
        self.set_config(handback=self.script('pass', CHECK_PASS))
        self.assertIsNone(self.handback('a7000000000000001'))
        rows = self.records()
        self.assertEqual([(r['record'], r['event'], r['call_id']) for r in rows],
                         [('witness', 'PreToolUse', 'toolu_hb_1')])
        self.assertEqual(rows[0]['check_results'][0]['checks'][0]['id'], 'x2-1')

    def test_r19_likeness_a_failing_hand_back_is_not_refused_and_its_fail_is_on_the_line(self):
        self.set_config(handback=self.script('fail', CHECK_FAIL))
        self.assertIsNone(self.handback('a7000000000000002'))
        self.assertEqual(self.records()[0]['check_results'][0]['checks'][0]['result'], 'fail')

    def test_r19_empty_a_hand_back_with_no_check_on_writes_no_line(self):
        self.handback('a7000000000000003')
        self.assertEqual(self.records(), [])

    def test_r19_a_stops_witness_line_carries_its_result(self):
        self.set_config(stop=self.script('fail', CHECK_FAIL))
        agent = 'a7000000000000004'
        path = self.transcript(agent, [])
        self.hook(WRAPPER, 'SubagentStop', {'session_id': SESSION, 'cwd': str(self.work), 'agent_id': agent,
                                           'hook_event_name': 'SubagentStop', 'agent_transcript_path': str(path),
                                           'last_assistant_message': CLOSING, 'stop_hook_active': False})
        stops = [r for r in self.records() if r.get('event') == 'SubagentStop']
        self.assertEqual(stops[0]['check_results'][0]['checks'][0]['result'], 'fail')

    def test_r19_empty_a_stop_with_no_check_on_carries_no_result(self):
        agent = 'a7000000000000005'
        path = self.transcript(agent, [])
        self.hook(WRAPPER, 'SubagentStop', {'session_id': SESSION, 'cwd': str(self.work), 'agent_id': agent,
                                           'hook_event_name': 'SubagentStop', 'agent_transcript_path': str(path),
                                           'last_assistant_message': CLOSING, 'stop_hook_active': False})
        self.assertNotIn('check_results', self.records()[0])


# ---------------------------------------------------------------------------
# R-19 and R-23: a hand-back member's stop before its delivered hand-back writes no return
# ---------------------------------------------------------------------------

class HandbackMember(World):

    def background(self, call_id, agent, mode, rows):
        self.hook(CAPTURE, 'PreToolUse', {
            'session_id': SESSION, 'cwd': str(self.work), 'hook_event_name': 'PreToolUse', 'tool_name': 'Agent',
            'tool_use_id': call_id, 'transcript_path': str(self.tmp / 'none.jsonl'),
            'tool_input': {'prompt': 'Do the thing.', 'run_in_background': True}})
        self.hook(CAPTURE, 'PostToolUse', {
            'session_id': SESSION, 'cwd': str(self.work), 'hook_event_name': 'PostToolUse', 'tool_name': 'Agent',
            'tool_use_id': call_id, 'tool_input': {'prompt': 'Do the thing.', 'run_in_background': True},
            'tool_response': {'status': 'async_launched', 'agentId': agent, 'isAsync': True}})
        path = self.transcript(agent, rows)
        self.hook(CAPTURE, 'SubagentStop', {
            'session_id': SESSION, 'cwd': str(self.work), 'hook_event_name': 'SubagentStop', 'agent_id': agent,
            'agent_transcript_path': str(path), 'last_assistant_message': CLOSING, 'stop_hook_active': False,
            'permission_mode': mode, 'background_tasks': [{'id': agent, 'type': 'subagent'}]})

    def closing(self):
        return [{'type': 'assistant', 'uuid': 'c-u', 'message': {
            'id': 'mc', 'model': 'test-model', 'role': 'assistant', 'stop_reason': 'end_turn',
            'content': [{'type': 'text', 'text': CLOSING}], 'usage': usage()}}]

    def handback_rows(self):
        return [{'type': 'assistant', 'uuid': 'h-u', 'message': {
            'id': 'mh', 'model': 'test-model', 'role': 'assistant', 'stop_reason': 'tool_use',
            'content': [{'type': 'tool_use', 'id': 'h1', 'name': 'SubagentHandback', 'input': {'message': REPORT}}],
            'usage': usage()}},
            {'type': 'user', 'uuid': 'h-r', 'message': {'role': 'user', 'content': [
                {'type': 'tool_result', 'tool_use_id': 'h1', 'content': 'delivered'}]}}]

    def test_r19_a_hand_back_members_stop_with_no_delivered_hand_back_writes_no_return(self):
        self.background('toolu_hm_1', 'a8000000000000001', 'auto', self.closing())
        self.assertEqual([r for r in self.records() if r.get('record') == 'return'], [])
        self.assertEqual(len([r for r in self.records() if r.get('event') == 'SubagentStop']), 1)

    def test_r19_likeness_after_a_delivered_hand_back_the_stop_writes_the_return(self):
        self.background('toolu_hm_2', 'a8000000000000002', 'auto', self.handback_rows() + self.closing())
        back = [r for r in self.records() if r.get('record') == 'return']
        self.assertEqual(len(back), 1)
        self.assertEqual(back[0]['harness_payload']['answer_from'], 'hand-back message')

    def test_r19_likeness_a_member_without_the_hand_back_tool_has_its_return_at_its_stop(self):
        self.background('toolu_hm_3', 'a8000000000000003', 'default', self.closing())
        self.assertEqual(len([r for r in self.records() if r.get('record') == 'return']), 1)


# ---------------------------------------------------------------------------
# R-33 and R-36: the wrapper's gate and context steps
# ---------------------------------------------------------------------------

class Gate(World):

    def test_r36_a_gate_refusal_at_the_parent_denies_the_call_and_writes_no_record_for_it(self):
        self.set_config(gate=self.script('gate', GATE_REFUSE))
        reason = self.denied(self.parent('Bash', {'command': 'claude -p "hello"'}))
        self.assertEqual(reason, 'held by the gate')
        self.assertEqual(self.records(), [], 'the call never runs, so nothing is dispatched')

    def test_r36_a_gate_refused_agent_call_has_one_dispatch_record_and_one_failed_return(self):
        self.set_config(gate=self.script('gate', GATE_REFUSE))
        self.assertTrue(self.denied(self.parent('Agent', {'prompt': 'Do a part.'}, call_id='toolu_g_1')))
        rows = [r for r in self.records() if r.get('call_id') == 'toolu_g_1']
        self.assertEqual([r['record'] for r in rows], ['dispatch', 'return'])
        self.assertEqual(rows[1]['outcome_reason']['class'], 'refused_by_check')
        self.assertFalse(list((self.ledger / '.pending' / SESSION).glob('*.json')), 'no pending file is left')

    def test_r36_likeness_the_gate_never_decides_at_a_member(self):
        self.set_config(gate=self.script('gate', GATE_REFUSE))
        self.assertIsNone(self.denied(self.parent('Write', {'file_path': 'x'}, agent_id='a9000000000000001')))

    def test_r36_empty_with_no_gate_named_nothing_is_refused(self):
        self.assertIsNone(self.denied(self.parent('Write', {'file_path': 'x'})))

    def test_r36_a_gate_that_raises_refuses_nothing_and_a_witness_line_says_not_checkable(self):
        self.set_config(gate=self.script('gate', GATE_RAISE))
        self.assertIsNone(self.denied(self.parent('Write', {'file_path': 'x'})))
        lines_ = [r for r in self.records() if r.get('record') == 'witness']
        self.assertEqual(len(lines_), 1)
        self.assertEqual(lines_[0]['check_results'][0]['check'], 'gate')
        self.assertTrue(lines_[0]['check_results'][0]['result'].startswith('not_checkable (check error'))


class Context(World):

    def test_r36_the_context_step_hands_its_text_to_the_parent_after_a_foreground_call(self):
        self.set_config(context=self.script('context', CONTEXT))
        decision = self.parent('Agent', {'prompt': 'Do a part.'}, event='PostToolUse',
                               tool_response={'status': 'completed', 'agentId': 'a9000000000000002',
                                              'content': [{'type': 'text', 'text': 'note'}]})
        self.assertEqual(decision['hookSpecificOutput'],
                         {'hookEventName': 'PostToolUse', 'additionalContext': 'results for PostToolUse'})

    def test_r36_the_context_step_hands_its_text_at_the_parents_user_prompt_submit(self):
        self.set_config(context=self.script('context', CONTEXT))
        decision = self.hook(WRAPPER, 'UserPromptSubmit', {'session_id': SESSION, 'cwd': str(self.work),
                                                           'hook_event_name': 'UserPromptSubmit',
                                                           'prompt': '<agent-message from="a1">READY</agent-message>'})
        self.assertEqual(decision['hookSpecificOutput']['additionalContext'], 'results for UserPromptSubmit')

    def test_r36_empty_with_no_context_step_named_nothing_is_printed(self):
        self.assertIsNone(self.hook(WRAPPER, 'UserPromptSubmit', {'session_id': SESSION, 'cwd': str(self.work),
                                                                  'hook_event_name': 'UserPromptSubmit',
                                                                  'prompt': 'hello'}))

    def test_r33_the_hook_entries_match_every_tool_for_the_gate_and_add_user_prompt_submit_for_context(self):
        self.set_config(gate=self.script('gate', GATE_REFUSE), context=self.script('context', CONTEXT))
        done = subprocess.run([sys.executable, str(WRAPPER), '--hook-entries', '--ledger', str(self.ledger)],
                              capture_output=True, text=True, timeout=60)
        hooks = json.loads(done.stdout)['hooks']
        self.assertNotIn('matcher', hooks['PreToolUse'][0])
        self.assertIn('UserPromptSubmit', hooks)

    def test_r33_likeness_with_neither_named_the_entries_are_as_before(self):
        done = subprocess.run([sys.executable, str(WRAPPER), '--hook-entries', '--ledger', str(self.ledger)],
                              capture_output=True, text=True, timeout=60)
        hooks = json.loads(done.stdout)['hooks']
        self.assertIn('matcher', hooks['PreToolUse'][0])
        self.assertNotIn('UserPromptSubmit', hooks)


# ---------------------------------------------------------------------------
# R-36: the disposition line
# ---------------------------------------------------------------------------

class DispositionLine(World):

    def fields(self, **more):
        found = {'call_id': 'toolu_d_1', 'agent_id': 'a1', 'member': 'm', 'attempt': 1, 'result_ids': ['r1-1'],
                 'kind': 'accepted', 'reason': 'read and kept', 'decided_by': 'parent',
                 'decided_at': '2026-10-29T01:00:00.000Z', 'recorded_at_call': 'toolu_bash_1'}
        found.update(more)
        return found

    def test_r36_a_disposition_line_is_written_with_its_fields_in_order(self):
        self.write('disposition', **self.fields())
        row = self.records()[0]
        self.assertEqual(list(row)[:4], ['schema', 'record', 'session', 'call_id'])
        self.assertEqual((row['record'], row['kind']), ('disposition', 'accepted'))

    def test_r36_likeness_a_kind_or_decider_outside_the_closed_sets_is_rejected(self):
        import ledger
        for more in ({'kind': 'ignored'}, {'decided_by': 'someone'}, {'result_ids': []}):
            with self.subTest(more=more):
                found = ledger.disposition(ledger=str(self.ledger), session=SESSION, **self.fields(**more))
                self.assertFalse(found.ok)
        self.assertEqual(self.records(), [])

    def test_r36_the_capture_writes_a_pending_disposition_file_as_a_line_at_the_parents_shell_post_tool_use(self):
        pending = self.ledger / '.pending' / SESSION
        pending.mkdir(parents=True)
        data = self.fields()
        data.pop('recorded_at_call')
        (pending / 'disposition-toolu_d_1.json').write_text(json.dumps(data), encoding='utf-8')
        self.hook(CAPTURE, 'PostToolUse', {'session_id': SESSION, 'cwd': str(self.work), 'tool_name': 'Bash',
                                           'hook_event_name': 'PostToolUse', 'tool_use_id': 'toolu_bash_7',
                                           'tool_input': {'command': 'python3 disposition.py'},
                                           'tool_response': {'stdout': '', 'stderr': ''}})
        row = [r for r in self.records() if r.get('record') == 'disposition'][0]
        self.assertEqual(row['recorded_at_call'], 'toolu_bash_7')
        self.assertFalse(list(pending.glob('disposition-*.json')))

    def test_r36_the_listing_shows_each_calls_dispositions(self):
        self.write('dispatch', call_id='toolu_d_1', harness='claude-code', route='subagent', caller='parent',
                   project='p', brief='b')
        self.write('disposition', **self.fields())
        out = json.loads(subprocess.run([sys.executable, str(CALLS), '--session', SESSION, '--ledger',
                                         str(self.ledger), '--json'], capture_output=True, text=True,
                                        timeout=60).stdout)
        self.assertEqual([d['kind'] for d in out['calls'][0]['dispositions']], ['accepted'])


# ---------------------------------------------------------------------------
# TC-16: the count check's rules for results and dispositions
# ---------------------------------------------------------------------------

class DecisionFaults(World):

    def call(self, call_id, agent, runs_on_return, witness_runs=(), returned=True, wait=False):
        self.write('dispatch', call_id=call_id, harness='claude-code', route='subagent', caller='parent',
                   project='p', brief='b', dispatched_at='2026-10-29T01:00:00.000Z')
        for at, found in witness_runs:
            self.write('witness', event='PreToolUse', agent_id=agent, call_id='h-%s' % call_id, at=at,
                       check_results=[found])
        if returned:
            self.write('ret', call_id=call_id, harness='claude-code', route='subagent', caller='parent',
                       project='p', agent_id=agent, outcome='served', outcome_reason='none (served)',
                       returned_at='2026-10-29T01:05:00.000Z', check_results=runs_on_return)

    def faults(self, call_ids):
        code, out = self.count_check(call_ids)
        return code, out['count_check']['faults']

    def test_tc16_empty_a_session_whose_results_all_pass_has_no_decision_fault(self):
        found = run('toolu_f_1', 'a1', ['pass', 'pass', 'pass', 'pass'])
        self.call('toolu_f_1', 'a1', [found], [('2026-10-29T01:01:00.000Z', found)])
        code, faults = self.faults(['toolu_f_1'])
        self.assertEqual((code, faults), (0, {}))

    def test_tc16_a_fail_no_disposition_settles_is_a_fault_at_the_runs_end(self):
        found = run('toolu_f_2', 'a2', ['fail', 'pass', 'pass', 'pass'])
        self.call('toolu_f_2', 'a2', [found])
        code, faults = self.faults(['toolu_f_2'])
        self.assertEqual(faults.get('a fail no disposition settles'), 1, faults)
        self.assertEqual(code, 4)

    def test_tc16_likeness_a_fail_a_disposition_settles_is_no_fault(self):
        found = run('toolu_f_3', 'a3', ['fail', 'pass', 'pass', 'pass'], run_id='s3')
        self.call('toolu_f_3', 'a3', [found])
        self.write('disposition', call_id='toolu_f_3', agent_id='a3', member='m', attempt=1, result_ids=['s3-1'],
                   kind='accepted', reason='kept', decided_by='parent', decided_at='2026-10-29T01:06:00.000Z',
                   recorded_at_call='toolu_bash_1')
        self.assertEqual(self.faults(['toolu_f_3']), (0, {}))

    def test_tc16_a_disposition_naming_a_result_its_call_does_not_carry_is_a_fault(self):
        found = run('toolu_f_4', 'a4', ['fail', 'pass', 'pass', 'pass'], run_id='s4')
        self.call('toolu_f_4', 'a4', [found])
        self.write('disposition', call_id='toolu_f_4', agent_id='a4', member='m', attempt=1,
                   result_ids=['s4-1', 'zz-9'], kind='accepted', reason='kept', decided_by='parent',
                   decided_at='2026-10-29T01:06:00.000Z', recorded_at_call='toolu_bash_1')
        _code, faults = self.faults(['toolu_f_4'])
        self.assertEqual(faults.get('a disposition names a result its call does not carry'), 1, faults)

    def test_tc16_a_repaired_disposition_with_no_later_commit_changing_its_paths_is_a_fault(self):
        repo = self.tmp / 'repo'
        repo.mkdir()
        subprocess.run(['git', 'init', '-q', str(repo)], check=True)
        found = run('toolu_f_5', 'a5', ['fail', 'pass', 'pass', 'pass'], run_id='s5')
        self.call('toolu_f_5', 'a5', [found])
        self.write('disposition', call_id='toolu_f_5', agent_id='a5', member='m', attempt=1, result_ids=['s5-1'],
                   kind='repaired', reason='I fix it', decided_by='parent', paths=['fixed.md'],
                   repository=str(repo), decided_at='2026-10-29T01:06:00.000Z', recorded_at_call='toolu_bash_1')
        _code, faults = self.faults(['toolu_f_5'])
        self.assertEqual(faults.get('a repaired disposition with no later commit changing its paths'), 1, faults)
        (repo / 'fixed.md').write_text('fixed\n', encoding='utf-8')
        env = dict(os.environ, GIT_AUTHOR_NAME='T', GIT_AUTHOR_EMAIL='t@example.invalid', GIT_COMMITTER_NAME='T',
                   GIT_COMMITTER_EMAIL='t@example.invalid')
        subprocess.run(['git', '-C', str(repo), 'add', 'fixed.md'], check=True, env=env)
        subprocess.run(['git', '-C', str(repo), 'commit', '-q', '-m', 'fix'], check=True, env=env)
        _code, faults = self.faults(['toolu_f_5'])
        self.assertNotIn('a repaired disposition with no later commit changing its paths', faults)

    def test_tc16_a_witness_line_whose_run_differs_from_the_returns_is_a_fault(self):
        on_line = run('toolu_f_6', 'a6', ['fail', 'pass', 'pass', 'pass'], run_id='s6')
        on_return = run('toolu_f_6', 'a6', ['pass', 'pass', 'pass', 'pass'], run_id='s6')
        self.call('toolu_f_6', 'a6', [on_return], [('2026-10-29T01:01:00.000Z', on_line)])
        _code, faults = self.faults(['toolu_f_6'])
        self.assertEqual(faults.get("a witness line's check run differs from its call's return"), 1, faults)

    def test_tc16_likeness_a_witness_run_missing_from_the_return_is_a_fault(self):
        on_line = run('toolu_f_7', 'a7', ['pass', 'pass', 'pass', 'pass'], run_id='s7')
        other = run('toolu_f_7', 'a7', ['pass', 'pass', 'pass', 'pass'], run_id='t7')
        self.call('toolu_f_7', 'a7', [other], [('2026-10-29T01:01:00.000Z', on_line)])
        _code, faults = self.faults(['toolu_f_7'])
        self.assertEqual(faults.get("a witness line's check run differs from its call's return"), 1, faults)

    def test_tc16_a_witness_line_written_after_its_calls_return_is_a_fault(self):
        found = run('toolu_f_8', 'a8', ['pass', 'pass', 'pass', 'pass'], run_id='s8')
        self.call('toolu_f_8', 'a8', [found], [('2026-10-29T01:09:00.000Z', found)])
        _code, faults = self.faults(['toolu_f_8'])
        self.assertEqual(faults.get("a witness line carries a result written after its call's return"), 1, faults)

    def test_tc16_a_call_ended_with_no_hand_back_is_a_fault(self):
        found = run('toolu_f_9', 'a9', ['not_applicable', 'pass', 'pass', 'pass'], run_id='s9',
                    report='final message', report_reached_parent=False)
        self.call('toolu_f_9', 'a9', [], returned=False)
        self.write('witness', event='SubagentStop', agent_id='a9', at='2026-10-29T01:02:00.000Z',
                   check_results=[found])
        _code, faults = self.faults(['toolu_f_9'])
        self.assertEqual(faults.get('a call ended with no hand-back'), 1, faults)

    def test_tc16_likeness_a_call_whose_last_stop_reached_the_parent_is_not_ended_with_no_hand_back(self):
        found = run('toolu_f_10', 'a10', ['pass', 'pass', 'pass', 'pass'], run_id='s10')
        self.call('toolu_f_10', 'a10', [], returned=False)
        self.write('witness', event='SubagentStop', agent_id='a10', at='2026-10-29T01:02:00.000Z',
                   check_results=[found])
        _code, faults = self.faults(['toolu_f_10'])
        self.assertNotIn('a call ended with no hand-back', faults)


if __name__ == '__main__':
    unittest.main()
