"""Controls for the wrapper: one hook entry per event that runs a configured check, then the capture, in one process.

Each criterion has its paired cases: an empty one (zero of the thing, which must give an error or a stated reason,
never a silent pass) and a likeness (the right shape with the wrong substance, which must be told apart). They were
committed before the wrapper existed, and each failed then.

The checks here are stand-ins written by this file: one passes, one refuses, one sleeps past its bound, one exits with
an error. No test calls a live service. Each test has its own ledger folder; SUBAGENT_LEDGER_DIR is removed from the
environment, and HOME and CLAUDE_CONFIG_DIR name temporary folders.

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
SCRIPTS = HERE.parent / 'skill' / 'scripts'
CAPTURE = SCRIPTS / 'capture_claude_code.py'
WRAPPER = SCRIPTS / 'wrapper.py'
SESSION = '0f0f0f0f-3333-4444-8555-666666666666'
CLOSING = 'All finished here.'

CHECKS = {
    'pass': "import json, sys; sys.stdin.read(); print(json.dumps({'refuse': False, 'reason': 'clean'}))",
    'refuse': "import json, sys; sys.stdin.read(); print(json.dumps({'refuse': True, 'reason': 'held: no output section'}))",
    'sleep': "import sys, time; sys.stdin.read(); time.sleep(30)",
    'error': "import sys; sys.stdin.read(); sys.stderr.write('the check broke'); sys.exit(3)",
}


def lines(path):
    path = Path(path)
    if not path.is_file():
        return []
    return [json.loads(line) for line in path.read_text(encoding='utf-8').splitlines() if line.strip()]


def closing_rows():
    return [{'type': 'assistant', 'uuid': 'm9-u', 'message': {
        'id': 'm9', 'model': 'test-model', 'role': 'assistant', 'stop_reason': 'end_turn',
        'content': [{'type': 'text', 'text': CLOSING}],
        'usage': {'input_tokens': 10, 'cache_creation_input_tokens': 0, 'cache_read_input_tokens': 0,
                  'output_tokens': 3}}}]


class World(unittest.TestCase):

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix='wrapper-'))
        self.addCleanup(shutil.rmtree, str(self.tmp), True)
        self.work = self.tmp / 'work'
        self.work.mkdir()
        self.config_dir = self.tmp / 'config'
        for name, code in CHECKS.items():
            (self.tmp / ('check_%s.py' % name)).write_text(code + '\n', encoding='utf-8')

    def ledger(self, name='ledger', checks=None, **more):
        folder = self.tmp / name
        folder.mkdir(exist_ok=True)
        config = {'fields': 'all'}
        if checks:
            config['checks'] = dict((where, '"%s" "%s"' % (sys.executable, self.tmp / ('check_%s.py' % which)))
                                    for where, which in checks.items())
            config['check_seconds'] = 2
        config.update(more)
        (folder / 'config.json').write_text(json.dumps(config), encoding='utf-8')
        return folder

    def hook(self, script, event, payload, folder):
        env = dict(os.environ, HOME=str(self.tmp / 'home'), CLAUDE_CONFIG_DIR=str(self.config_dir))
        env.pop('SUBAGENT_LEDGER_DIR', None)
        return subprocess.run([sys.executable, str(script), event, '--ledger', str(folder)], input=json.dumps(payload),
                              capture_output=True, text=True, env=env, cwd=str(self.work), timeout=60)

    def wrapped(self, event, payload, folder):
        done = self.hook(WRAPPER, event, payload, folder)
        self.assertEqual(done.returncode, 0, done.stderr)
        return done

    def records(self, folder):
        return lines(folder / ('%s.jsonl' % SESSION))

    def transcript(self, agent):
        path = self.config_dir / 'projects' / 'p' / SESSION / 'subagents' / ('agent-%s.jsonl' % agent)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(''.join(json.dumps(r) + '\n' for r in closing_rows()), encoding='utf-8')
        return path

    def dispatch_payload(self, call_id):
        return {'session_id': SESSION, 'transcript_path': str(self.tmp / 'none.jsonl'), 'cwd': str(self.work),
                'hook_event_name': 'PreToolUse', 'tool_name': 'Agent', 'tool_use_id': call_id,
                'effort': {'level': 'high'}, 'tool_input': {'prompt': 'Do the thing.'}}

    def stop_payload(self, agent, path):
        return {'session_id': SESSION, 'cwd': str(self.work), 'hook_event_name': 'SubagentStop', 'agent_id': agent,
                'agent_type': 'general-purpose', 'agent_transcript_path': str(path), 'last_assistant_message': CLOSING,
                'stop_hook_active': False, 'effort': {'level': 'low'}}

    def post_payload(self, call_id, agent):
        return {'session_id': SESSION, 'cwd': str(self.work), 'hook_event_name': 'PostToolUse', 'tool_name': 'Agent',
                'tool_use_id': call_id, 'tool_input': {'prompt': 'Do the thing.'},
                'tool_response': {'status': 'completed', 'agentId': agent, 'resolvedModel': 'test-model',
                                  'content': [{'type': 'text', 'text': CLOSING}]}}

    def handback_payload(self, event, agent, call_id='toolu_hb_0001'):
        payload = {'session_id': SESSION, 'cwd': str(self.work), 'hook_event_name': event,
                   'tool_name': 'SubagentHandback', 'tool_use_id': call_id, 'agent_id': agent,
                   'tool_input': {'message': 'The report.\n\n## Output\nnone\n'}}
        if event == 'PostToolUse':
            payload['tool_response'] = {'delivered': True}
        return payload

    def foreground_call(self, run, folder, call_id, agent):
        path = self.transcript(agent)
        run('PreToolUse', self.dispatch_payload(call_id), folder)
        out = run('SubagentStop', self.stop_payload(agent, path), folder)
        run('PostToolUse', self.post_payload(call_id, agent), folder)
        return out

    def deny(self, done):
        text = done.stdout.strip()
        return json.loads(text) if text else None


VARYING = ('dispatched_at', 'returned_at', 'at', 'brief_path', 'answer_path', 'read_at', 'read_after_seconds',
           'withheld')


def steady(record):
    """The record less the values that differ between two runs of the same events: times and copy paths."""
    if isinstance(record, dict):
        return dict((k, steady(v)) for k, v in record.items() if k not in VARYING)
    if isinstance(record, list):
        return [steady(v) for v in record]
    if isinstance(record, str):
        return record.replace('/ledger-alone/', '/L/').replace('/ledger-wrapped/', '/L/')
    return record


# ---------------------------------------------------------------------------
# TC-19 and SC-09: with no check on, the wrapper writes what the capture writes
# ---------------------------------------------------------------------------

class NoCheckOn(World):

    def test_tc19_empty_with_no_check_on_the_records_match_the_capture_alone_field_by_field(self):
        alone, wrapped = self.ledger('ledger-alone'), self.ledger('ledger-wrapped')
        capture = lambda event, payload, folder: self.hook(CAPTURE, event, payload, folder)
        self.foreground_call(capture, alone, 'toolu_t_0001', 'a5000000000000001')
        self.foreground_call(self.wrapped, wrapped, 'toolu_t_0001', 'a5000000000000001')
        first, second = self.records(alone), self.records(wrapped)
        self.assertEqual(len(first), 3)  # dispatch, the stop's witness line, return
        self.assertEqual([steady(r) for r in first], [steady(r) for r in second])

    def test_sc09_with_no_check_on_nothing_is_refused_and_nothing_printed(self):
        folder = self.ledger()
        done = self.foreground_call(self.wrapped, folder, 'toolu_t_0002', 'a5000000000000002')
        self.assertEqual(done.stdout, '')


# ---------------------------------------------------------------------------
# TC-19's likenesses: a check that overruns or errors refuses nothing; a failing capture refuses nothing
# ---------------------------------------------------------------------------

class CheckFailures(World):

    def stop_result(self, folder, call_id):
        back = [r for r in self.records(folder) if r.get('record') == 'return' and r.get('call_id') == call_id]
        self.assertEqual(len(back), 1, 'the capture still writes the return')
        return back[0]['check_results']

    def test_tc19_a_check_past_its_bound_refuses_nothing_and_reads_timed_out(self):
        folder = self.ledger(checks={'stop': 'sleep'})
        done = self.foreground_call(self.wrapped, folder, 'toolu_t_0101', 'a5000000000000101')
        self.assertIsNone(self.deny(done))
        results = self.stop_result(folder, 'toolu_t_0101')
        self.assertEqual(results[0]['result'], 'not_checkable (check timed out)')
        self.assertIs(results[0]['refused'], False)

    def test_tc19_a_check_that_errors_refuses_nothing_and_reads_check_error(self):
        folder = self.ledger(checks={'stop': 'error'})
        done = self.foreground_call(self.wrapped, folder, 'toolu_t_0102', 'a5000000000000102')
        self.assertIsNone(self.deny(done))
        results = self.stop_result(folder, 'toolu_t_0102')
        self.assertTrue(results[0]['result'].startswith('not_checkable (check error: '), results)

    def test_tc19_a_failing_capture_refuses_nothing(self):
        # A field setting the writer refuses: the capture writes an error line and no record.
        folder = self.ledger(checks={'dispatch': 'refuse'}, fields=7)
        done = self.wrapped('PreToolUse', self.dispatch_payload('toolu_t_0103'), folder)
        self.assertEqual(self.records(folder), [])
        self.assertTrue(lines(folder / 'capture-errors.jsonl'))
        # The check refused, so the call is refused for the check's reason; never for the capture's failure.
        self.assertEqual(self.deny(done)['hookSpecificOutput']['permissionDecisionReason'], 'held: no output section')
        folder = self.ledger('ledger-two', checks={'dispatch': 'pass'}, fields=7)
        self.assertIsNone(self.deny(self.wrapped('PreToolUse', self.dispatch_payload('toolu_t_0104'), folder)))

    def test_sc09_each_parts_time_is_recorded(self):
        folder = self.ledger(checks={'stop': 'pass'})
        self.foreground_call(self.wrapped, folder, 'toolu_t_0105', 'a5000000000000105')
        results = self.stop_result(folder, 'toolu_t_0105')
        self.assertIsInstance(results[0]['check_seconds'], (int, float))


# ---------------------------------------------------------------------------
# SC-09: the check runs before the capture; a refused stop leaves a witness line and no return
# ---------------------------------------------------------------------------

class StopCheck(World):

    def test_sc09_a_refused_stop_is_refused_and_the_capture_writes_only_its_witness_line(self):
        folder = self.ledger(checks={'stop': 'refuse'})
        agent = 'a5000000000000201'
        path = self.transcript(agent)
        self.wrapped('PreToolUse', self.dispatch_payload('toolu_t_0201'), folder)
        done = self.wrapped('SubagentStop', self.stop_payload(agent, path), folder)
        self.assertEqual(self.deny(done), {'decision': 'block', 'reason': 'held: no output section'})
        self.assertFalse([r for r in self.records(folder) if r.get('record') == 'return'])
        self.assertEqual(len([r for r in self.records(folder) if r.get('event') == 'SubagentStop']), 1)

    def test_sc09_likeness_a_passing_stop_is_not_refused_and_its_result_reaches_the_return(self):
        folder = self.ledger(checks={'stop': 'pass'})
        done = self.foreground_call(self.wrapped, folder, 'toolu_t_0202', 'a5000000000000202')
        self.assertIsNone(self.deny(done))
        back = [r for r in self.records(folder) if r.get('record') == 'return']
        self.assertEqual([r['refused'] for r in back[0]['check_results']], [False])


# ---------------------------------------------------------------------------
# R-33: the hand-back: matched at PreToolUse and PostToolUse, no record written there
# ---------------------------------------------------------------------------

class HandbackCheck(World):

    def test_r33_a_refused_hand_back_is_denied_with_a_witness_line_and_no_call_record(self):
        folder = self.ledger(checks={'handback': 'refuse'})
        done = self.wrapped('PreToolUse', self.handback_payload('PreToolUse', 'a5000000000000301'), folder)
        decision = self.deny(done)['hookSpecificOutput']
        self.assertEqual((decision['permissionDecision'], decision['permissionDecisionReason']),
                         ('deny', 'held: no output section'))
        rows = self.records(folder)
        self.assertEqual([(r['record'], r['event'], r['call_id']) for r in rows],
                         [('witness', 'PreToolUse', 'toolu_hb_0001')])

    def test_r33_empty_a_passing_hand_back_writes_its_witness_line_and_its_delivery_is_marked(self):
        # Since the rework of 28 October 2026 (R-19), every checked hand-back writes a witness line carrying its
        # result, before its report can reach the parent; it writes no call record.
        folder = self.ledger(checks={'handback': 'pass'})
        agent = 'a5000000000000302'
        self.assertIsNone(self.deny(self.wrapped('PreToolUse', self.handback_payload('PreToolUse', agent), folder)))
        self.wrapped('PostToolUse', self.handback_payload('PostToolUse', agent), folder)
        rows = self.records(folder)
        self.assertEqual([(r['record'], r['event'], r['call_id']) for r in rows],
                         [('witness', 'PreToolUse', 'toolu_hb_0001')])
        self.assertEqual(rows[0]['check_results'][0]['reason'], 'clean')
        kept = [json.loads(p.read_text(encoding='utf-8'))
                for p in (folder / '.pending' / SESSION).glob('check-*.json')]
        self.assertEqual(len(kept), 1)
        self.assertIs(kept[0]['delivered'], True)

    def test_r33_likeness_a_hand_back_with_no_check_on_writes_nothing(self):
        folder = self.ledger()
        self.wrapped('PreToolUse', self.handback_payload('PreToolUse', 'a5000000000000303'), folder)
        self.wrapped('PostToolUse', self.handback_payload('PostToolUse', 'a5000000000000303'), folder)
        self.assertEqual(self.records(folder), [])
        self.assertFalse(list((folder / '.pending').glob('*/check-*.json')))


# ---------------------------------------------------------------------------
# SC-10: the refused dispatch
# ---------------------------------------------------------------------------

class RefusedDispatch(World):

    def test_sc10_a_refused_dispatch_has_one_dispatch_and_one_failed_return_at_pre_tool_use(self):
        folder = self.ledger(checks={'dispatch': 'refuse'})
        done = self.wrapped('PreToolUse', self.dispatch_payload('toolu_t_0401'), folder)
        decision = self.deny(done)['hookSpecificOutput']
        self.assertEqual(decision['permissionDecision'], 'deny')
        rows = [r for r in self.records(folder) if r.get('call_id') == 'toolu_t_0401']
        self.assertEqual([r['record'] for r in rows], ['dispatch', 'return'])
        back = rows[1]
        self.assertEqual(back['outcome'], 'failed')
        self.assertEqual(back['outcome_reason']['class'], 'refused_by_check')
        self.assertIn('held: no output section', back['outcome_reason']['text'])
        self.assertEqual(back['harness_payload']['hook_event_name'], 'PreToolUse')
        self.assertFalse(list((folder / '.pending' / SESSION).glob('*.json')), 'no pending file is left')

    def test_sc10_empty_a_passing_dispatch_check_writes_the_dispatch_alone(self):
        folder = self.ledger(checks={'dispatch': 'pass'})
        done = self.wrapped('PreToolUse', self.dispatch_payload('toolu_t_0402'), folder)
        self.assertIsNone(self.deny(done))
        self.assertEqual([r['record'] for r in self.records(folder)], ['dispatch'])
        sent = self.records(folder)[0]
        self.assertIsInstance(sent['harness_payload']['wrapper']['check_seconds'], (int, float))

    def test_sc10_likeness_a_dispatch_check_that_errors_refuses_nothing_and_says_so(self):
        folder = self.ledger(checks={'dispatch': 'error'})
        done = self.wrapped('PreToolUse', self.dispatch_payload('toolu_t_0403'), folder)
        self.assertIsNone(self.deny(done))
        sent = self.records(folder)
        self.assertEqual([r['record'] for r in sent], ['dispatch'])
        self.assertTrue(sent[0]['harness_payload']['wrapper']['result'].startswith('not_checkable (check error: '))

    def test_sc10_the_reason_class_is_in_reasons_json(self):
        classes = json.loads((SCRIPTS / 'reasons.json').read_text(encoding='utf-8'))['classes']
        self.assertIn('refused_by_check', classes)



# ---------------------------------------------------------------------------
# R-33: the hook's time limit, set explicitly above the capture's longest wait (written after wrapper.py)
# ---------------------------------------------------------------------------

class HookEntries(World):

    def entries(self, folder):
        return subprocess.run([sys.executable, str(WRAPPER), '--hook-entries', '--ledger', str(folder)],
                              capture_output=True, text=True, timeout=60)

    def test_r33_each_entry_carries_a_limit_above_the_bounded_wait(self):
        folder = self.ledger(checks={'stop': 'pass'}, background_wait_seconds=50)
        done = self.entries(folder)
        self.assertEqual(done.returncode, 0, done.stderr)
        hooks = json.loads(done.stdout)['hooks']
        limits = [entry['hooks'][0]['timeout'] for entries in hooks.values() for entry in entries]
        self.assertEqual(sorted(hooks), ['PostToolUse', 'PostToolUseFailure', 'PreToolUse', 'SessionStart',
                                         'SubagentStart', 'SubagentStop'])
        self.assertEqual(set(limits), {50 + 2 + 30})

    def test_r33_empty_an_unbounded_wait_has_no_limit_to_sit_above_and_is_refused(self):
        done = self.entries(self.ledger())
        self.assertEqual(done.returncode, 2)
        self.assertIn('background_wait_seconds', done.stderr)

if __name__ == '__main__':
    unittest.main()
