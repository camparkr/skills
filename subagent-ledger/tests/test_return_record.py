"""Controls for the return record: kept check results on the call's one return, the hand-back's message as the
answer, the background wait's bound, and the count check's new faults.

Each criterion has its paired cases: an empty one (zero of the thing, which must give an error or a stated reason,
never a silent pass) and a likeness (the right shape with the wrong substance, which must be told apart). They were
committed before the code they test, and each failed on the capture as it stood.

The capture is run as a hook runs it, in a new process. A check's kept result is planted in the session's pending
folder in the form pending.schema.json gives it, as the wrapper will leave it. Transcripts are built here, in the
Claude Code form the capture reads. No test reads or writes a real ledger: SUBAGENT_LEDGER_DIR is removed from the
environment, and HOME and CLAUDE_CONFIG_DIR name temporary folders.

Run from the skill's folder:  python3 -m unittest discover -s tests
"""

import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
SCRIPTS = HERE.parent / 'skill' / 'scripts'
CAPTURE = SCRIPTS / 'capture_claude_code.py'
CALLS = SCRIPTS / 'calls.py'
SESSION = '0e0e0e0e-2222-4333-8444-555555555555'
UNRECORDED_RESULT = 'unrecorded (no check result when the return was written)'
REPORT = 'The work is done.\n\n## Output\nnone\n'
CLOSING = 'All finished here.'
NOTE = 'The subagent handed its report back to the parent.'


def lines(path):
    path = Path(path)
    if not path.is_file():
        return []
    return [json.loads(line) for line in path.read_text(encoding='utf-8').splitlines() if line.strip()]


def sha(text):
    return hashlib.sha256(text.encode('utf-8')).hexdigest()


def usage(output):
    return {'input_tokens': 10, 'cache_creation_input_tokens': 0, 'cache_read_input_tokens': 0,
            'output_tokens': output}


def handback_rows(message, call='h1', delivered=True, request='m1', output=5):
    rows = [{'type': 'assistant', 'uuid': request + '-u', 'message': {
        'id': request, 'model': 'test-model', 'role': 'assistant', 'stop_reason': 'tool_use',
        'content': [{'type': 'tool_use', 'id': call, 'name': 'SubagentHandback', 'input': {'message': message}}],
        'usage': usage(output)}}]
    result = {'type': 'tool_result', 'tool_use_id': call, 'content': 'delivered' if delivered else 'refused'}
    if not delivered:
        result['is_error'] = True
    rows.append({'type': 'user', 'uuid': request + '-r', 'message': {'role': 'user', 'content': [result]}})
    return rows


def closing_rows(text=CLOSING, request='m9', output=3):
    return [{'type': 'assistant', 'uuid': request + '-u', 'message': {
        'id': request, 'model': 'test-model', 'role': 'assistant', 'stop_reason': 'end_turn',
        'content': [{'type': 'text', 'text': text}], 'usage': usage(output)}}]


def open_rows(request='m5'):
    """A transcript still running: its last request is a tool call with no result yet."""
    return [{'type': 'assistant', 'uuid': request + '-u', 'message': {
        'id': request, 'model': 'test-model', 'role': 'assistant', 'stop_reason': 'tool_use',
        'content': [{'type': 'tool_use', 'id': 't-open', 'name': 'Read', 'input': {'file_path': 'x'}}],
        'usage': usage(1)}}]


def kept_result(event, refused=False, report='final message', text=REPORT, n=1, **extra):
    data = {'event': event, 'at': '2026-10-29T02:00:0%dZ' % n, 'report': report, 'sha256': sha(text),
            'results': {'check': 'fail' if refused else 'pass'}, 'refused': refused}
    data.update(extra)
    return data


class World(unittest.TestCase):

    config = {'fields': 'all'}

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix='return-record-'))
        self.addCleanup(shutil.rmtree, str(self.tmp), True)
        self.ledger = self.tmp / 'ledger'
        self.ledger.mkdir()
        self.work = self.tmp / 'work'
        self.work.mkdir()
        self.config_dir = self.tmp / 'config'
        self.project = self.config_dir / 'projects' / 'p'
        self.project.mkdir(parents=True)
        self.set_config(dict(self.config))

    def set_config(self, config):
        (self.ledger / 'config.json').write_text(json.dumps(config), encoding='utf-8')

    def run_event(self, event, payload, timeout=60):
        env = dict(os.environ, HOME=str(self.tmp / 'home'), CLAUDE_CONFIG_DIR=str(self.config_dir))
        env.pop('SUBAGENT_LEDGER_DIR', None)
        done = subprocess.run([sys.executable, str(CAPTURE), event, '--ledger', str(self.ledger)],
                              input=json.dumps(payload), capture_output=True, text=True, env=env,
                              cwd=str(self.work), timeout=timeout)
        self.assertEqual((done.returncode, done.stdout), (0, ''), done.stderr)

    def records(self):
        return lines(self.ledger / ('%s.jsonl' % SESSION))

    def returns(self, call_id):
        return [r for r in self.records() if r.get('record') == 'return' and r.get('call_id') == call_id]

    def pending(self):
        return self.ledger / '.pending' / SESSION

    def transcript(self, agent, rows):
        path = self.project / SESSION / 'subagents' / ('agent-%s.jsonl' % agent)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(''.join(json.dumps(r) + '\n' for r in rows), encoding='utf-8')
        return path

    def parent_transcript(self, call_ids):
        path = self.project / ('%s.jsonl' % SESSION)
        rows = [{'type': 'assistant', 'uuid': 'p-%s' % c, 'message': {
            'id': 'p-%s' % c, 'role': 'assistant', 'model': 'test-model', 'stop_reason': 'tool_use',
            'content': [{'type': 'tool_use', 'id': c, 'name': 'Agent', 'input': {'prompt': 'x'}}],
            'usage': usage(1)}} for c in call_ids]
        path.write_text(''.join(json.dumps(r) + '\n' for r in rows), encoding='utf-8')
        return path

    def keep(self, agent, seq, data):
        self.pending().mkdir(parents=True, exist_ok=True)
        path = self.pending() / ('check-%s-%04d.json' % (agent, seq))
        path.write_text(json.dumps(data) if not isinstance(data, str) else data, encoding='utf-8')
        return path

    def dispatch(self, call_id, background):
        self.run_event('PreToolUse', {
            'session_id': SESSION, 'transcript_path': str(self.tmp / 'none.jsonl'), 'cwd': str(self.work),
            'hook_event_name': 'PreToolUse', 'tool_name': 'Agent', 'tool_use_id': call_id,
            'effort': {'level': 'high'},
            'tool_input': {'prompt': 'Do the thing.', 'run_in_background': background}})

    def launched(self, call_id, agent):
        self.run_event('PostToolUse', {
            'session_id': SESSION, 'cwd': str(self.work), 'hook_event_name': 'PostToolUse', 'tool_name': 'Agent',
            'tool_use_id': call_id, 'tool_input': {'prompt': 'Do the thing.', 'run_in_background': True},
            'tool_response': {'status': 'async_launched', 'agentId': agent, 'isAsync': True}})

    def stop(self, agent, path, background, last=CLOSING, timeout=60):
        payload = {'session_id': SESSION, 'cwd': str(self.work), 'hook_event_name': 'SubagentStop',
                   'agent_id': agent, 'agent_type': 'general-purpose', 'agent_transcript_path': str(path),
                   'last_assistant_message': last, 'stop_hook_active': False, 'effort': {'level': 'low'}}
        if background:
            payload['background_tasks'] = [{'id': agent, 'type': 'subagent'}]
        self.run_event('SubagentStop', payload, timeout=timeout)

    def foreground_return(self, call_id, agent, content=NOTE, handback_text=None):
        response = {'status': 'completed', 'agentId': agent, 'content': [{'type': 'text', 'text': content}],
                    'resolvedModel': 'test-model'}
        if handback_text is not None:
            response['handbackReport'] = {'text': handback_text}
        self.run_event('PostToolUse', {
            'session_id': SESSION, 'cwd': str(self.work), 'hook_event_name': 'PostToolUse', 'tool_name': 'Agent',
            'tool_use_id': call_id, 'tool_input': {'prompt': 'Do the thing.'}, 'tool_response': response})

    def answer_of(self, record):
        return Path(record['answer_path']).read_text(encoding='utf-8')


# ---------------------------------------------------------------------------
# SC-06 and SC-07: kept check results on the call's one return
# ---------------------------------------------------------------------------

class KeptResults(World):

    def test_sc06_sc07_a_background_member_refused_once_has_one_return_carrying_both_results(self):
        agent = 'a1000000000000001'
        self.dispatch('toolu_b_0001', True)
        self.launched('toolu_b_0001', agent)
        path = self.transcript(agent, closing_rows())
        self.keep(agent, 1, kept_result('SubagentStop', refused=True, n=1))
        self.stop(agent, path, True)
        self.assertEqual(self.returns('toolu_b_0001'), [], 'a refused stop writes no return')
        self.keep(agent, 2, kept_result('SubagentStop', refused=False, n=2))
        self.stop(agent, path, True)
        found = self.returns('toolu_b_0001')
        self.assertEqual(len(found), 1, 'one return per call')
        self.assertEqual([r['refused'] for r in found[0]['check_results']], [True, False])
        self.assertEqual(found[0]['harness_payload']['hook_event_name'], 'SubagentStop')
        stops = [r for r in self.records() if r.get('record') == 'witness' and r.get('event') == 'SubagentStop']
        self.assertEqual(len(stops), 2)
        self.assertFalse(list(self.pending().glob('check-*.json')), 'no kept result outlives its return')

    def test_sc06_a_foreground_member_refused_once_has_both_results_on_its_post_tool_use_return(self):
        agent = 'a1000000000000002'
        self.dispatch('toolu_f_0001', False)
        path = self.transcript(agent, closing_rows())
        self.keep(agent, 1, kept_result('SubagentStop', refused=True, n=1))
        self.stop(agent, path, False)
        self.keep(agent, 2, kept_result('SubagentStop', refused=False, n=2))
        self.stop(agent, path, False)
        self.foreground_return('toolu_f_0001', agent, content=CLOSING)
        found = self.returns('toolu_f_0001')
        self.assertEqual(len(found), 1)
        self.assertEqual([r['refused'] for r in found[0]['check_results']], [True, False])
        self.assertFalse(list(self.pending().glob('check-*.json')))

    def test_sc06_the_field_setting_cannot_drop_the_results(self):
        self.set_config({'fields': 'frame'})
        agent = 'a1000000000000003'
        self.dispatch('toolu_f_0002', False)
        path = self.transcript(agent, closing_rows())
        self.keep(agent, 1, kept_result('SubagentStop', n=1))
        self.stop(agent, path, False)
        self.foreground_return('toolu_f_0002', agent, content=CLOSING)
        self.assertEqual(len(self.returns('toolu_f_0002')[0]['check_results']), 1)

    def test_sc06_empty_with_no_check_on_and_none_kept_the_return_carries_no_results(self):
        agent = 'a1000000000000004'
        self.dispatch('toolu_f_0003', False)
        path = self.transcript(agent, closing_rows())
        self.stop(agent, path, False)
        self.foreground_return('toolu_f_0003', agent, content=CLOSING)
        self.assertNotIn('check_results', self.returns('toolu_f_0003')[0])

    def test_sc06_empty_with_a_stop_check_on_and_none_kept_the_return_says_unrecorded_never_pass(self):
        self.set_config({'fields': 'all', 'checks': {'stop': 'true'}})
        agent = 'a1000000000000005'
        self.dispatch('toolu_f_0004', False)
        path = self.transcript(agent, closing_rows())
        self.stop(agent, path, False)
        self.foreground_return('toolu_f_0004', agent, content=CLOSING)
        self.assertEqual(self.returns('toolu_f_0004')[0]['check_results'], [UNRECORDED_RESULT])

    def test_sc06_likeness_another_agents_result_is_not_copied_and_stays(self):
        agent, other = 'a1000000000000006', 'a1000000000000099'
        self.dispatch('toolu_f_0005', False)
        path = self.transcript(agent, closing_rows())
        planted = self.keep(other, 1, kept_result('SubagentStop', n=1))
        self.stop(agent, path, False)
        self.foreground_return('toolu_f_0005', agent, content=CLOSING)
        self.assertNotIn('check_results', self.returns('toolu_f_0005')[0])
        self.assertTrue(planted.exists())

    def test_sc06_likeness_a_malformed_kept_result_is_recorded_unrecorded_with_its_reason(self):
        agent = 'a1000000000000007'
        self.dispatch('toolu_f_0006', False)
        path = self.transcript(agent, closing_rows())
        self.keep(agent, 1, '{not json')
        self.stop(agent, path, False)
        self.foreground_return('toolu_f_0006', agent, content=CLOSING)
        results = self.returns('toolu_f_0006')[0]['check_results']
        self.assertEqual(len(results), 1)
        self.assertTrue(results[0].startswith('unrecorded (a kept check result could not be read'), results)
        self.assertFalse(list(self.pending().glob('check-*.json')))


# ---------------------------------------------------------------------------
# SC-08: the delivered hand-back's message is the answer
# ---------------------------------------------------------------------------

class HandbackAnswer(World):

    def test_sc08_foreground_the_answer_is_the_hand_back_message_not_the_harness_note(self):
        agent = 'a2000000000000001'
        self.dispatch('toolu_h_0001', False)
        path = self.transcript(agent, handback_rows(REPORT) + closing_rows())
        self.stop(agent, path, False)
        self.foreground_return('toolu_h_0001', agent, content=NOTE, handback_text=REPORT)
        sent = self.returns('toolu_h_0001')[0]
        self.assertEqual(self.answer_of(sent), REPORT)
        self.assertEqual(sent['harness_payload']['answer_from'], 'hand-back message')

    def test_sc08_background_the_answer_is_the_last_delivered_hand_back_not_the_closing_text(self):
        agent = 'a2000000000000002'
        self.dispatch('toolu_h_0002', True)
        self.launched('toolu_h_0002', agent)
        rows = handback_rows('first try', call='h1', request='m1') + handback_rows(REPORT, call='h2', request='m2')
        path = self.transcript(agent, rows + closing_rows())
        self.stop(agent, path, True)
        sent = self.returns('toolu_h_0002')[0]
        self.assertEqual(self.answer_of(sent), REPORT)
        self.assertEqual(sent['harness_payload']['answer_from'], 'hand-back message')

    def test_sc08_empty_with_no_hand_back_the_answer_is_the_final_message(self):
        agent = 'a2000000000000003'
        self.dispatch('toolu_h_0003', True)
        self.launched('toolu_h_0003', agent)
        path = self.transcript(agent, closing_rows())
        self.stop(agent, path, True)
        sent = self.returns('toolu_h_0003')[0]
        self.assertEqual(self.answer_of(sent), CLOSING)
        self.assertEqual(sent['harness_payload']['answer_from'], 'final message')

    def test_sc08_likeness_a_refused_hand_back_is_not_the_answer(self):
        agent = 'a2000000000000004'
        self.dispatch('toolu_h_0004', True)
        self.launched('toolu_h_0004', agent)
        path = self.transcript(agent, handback_rows('held back', delivered=False) + closing_rows())
        self.stop(agent, path, True)
        sent = self.returns('toolu_h_0004')[0]
        self.assertEqual(self.answer_of(sent), CLOSING)
        self.assertEqual(sent['harness_payload']['answer_from'], 'final message')


# ---------------------------------------------------------------------------
# R-33: the background wait's bound
# ---------------------------------------------------------------------------

class WaitBound(World):

    def test_r33_past_the_bound_the_return_says_the_wait_was_unfinished(self):
        self.set_config({'fields': 'all', 'background_wait_seconds': 1})
        agent = 'a3000000000000001'
        self.dispatch('toolu_w_0001', True)
        self.launched('toolu_w_0001', agent)
        path = self.transcript(agent, open_rows())
        began = time.monotonic()
        self.stop(agent, path, True, last='', timeout=30)
        self.assertLess(time.monotonic() - began, 20)
        sent = self.returns('toolu_w_0001')[0]
        self.assertTrue(sent['harness_payload']['wait'].startswith('unfinished after 1 seconds'),
                        sent['harness_payload'].get('wait'))

    def test_r33_empty_an_ended_transcript_carries_no_wait_mark(self):
        self.set_config({'fields': 'all', 'background_wait_seconds': 5})
        agent = 'a3000000000000002'
        self.dispatch('toolu_w_0002', True)
        self.launched('toolu_w_0002', agent)
        path = self.transcript(agent, closing_rows())
        self.stop(agent, path, True)
        self.assertNotIn('wait', self.returns('toolu_w_0002')[0]['harness_payload'])

    def test_r33_likeness_a_setting_that_is_no_number_is_an_error_line_and_the_wait_is_unbounded(self):
        self.set_config({'fields': 'all', 'background_wait_seconds': 'soon'})
        agent = 'a3000000000000003'
        self.dispatch('toolu_w_0003', True)
        self.launched('toolu_w_0003', agent)
        path = self.transcript(agent, closing_rows())
        self.stop(agent, path, True)
        self.assertEqual(len(self.returns('toolu_w_0003')), 1)
        errors = lines(self.ledger / 'capture-errors.jsonl')
        self.assertTrue([e for e in errors if 'background_wait_seconds' in e.get('reason', '')], errors)


# ---------------------------------------------------------------------------
# TC-16 and TC-10: the count check's faults
# ---------------------------------------------------------------------------

class CountCheckFaults(World):

    def check(self):
        parent = self.parent_transcript(sorted(set(
            r['call_id'] for r in self.records() if r.get('record') == 'dispatch')))
        env = dict(os.environ, HOME=str(self.tmp / 'home'), CLAUDE_CONFIG_DIR=str(self.config_dir))
        env.pop('SUBAGENT_LEDGER_DIR', None)
        done = subprocess.run([sys.executable, str(CALLS), '--session', SESSION, '--ledger', str(self.ledger),
                               '--json', '--count-check', '--harness', 'claude-code', '--transcript', str(parent)],
                              capture_output=True, text=True, env=env, timeout=60)
        return done.returncode, json.loads(done.stdout)

    def clean_call(self, call_id, agent, rows=None, kept=None):
        self.dispatch(call_id, True)
        self.launched(call_id, agent)
        path = self.transcript(agent, rows or closing_rows())
        for seq, data in enumerate(kept or [], 1):
            self.keep(agent, seq, data)
        self.stop(agent, path, True)

    def rewrite(self, change):
        path = self.ledger / ('%s.jsonl' % SESSION)
        rows = lines(path)
        rows = [change(r) or r for r in rows]
        path.write_text(''.join(json.dumps(r) + '\n' for r in rows), encoding='utf-8')

    def test_tc16_empty_a_clean_session_has_zero_faults_stated_and_exits_0(self):
        self.clean_call('toolu_c_0001', 'a4000000000000001')
        code, out = self.check()
        self.assertEqual(out['count_check']['faults'], {})
        self.assertEqual(code, 0, out)

    def test_tc10_an_unrecorded_check_result_is_a_fault(self):
        self.set_config({'fields': 'all', 'checks': {'stop': 'true'}})
        self.clean_call('toolu_c_0002', 'a4000000000000002')
        code, out = self.check()
        self.assertEqual(out['count_check']['faults'].get('a return carries an unrecorded check result'), 1, out)
        self.assertEqual(code, 4)

    def test_tc16_a_last_check_result_naming_another_text_is_a_fault(self):
        self.clean_call('toolu_c_0003', 'a4000000000000003',
                        kept=[kept_result('SubagentStop', text='some other text')])
        code, out = self.check()
        self.assertEqual(out['count_check']['faults'].get(
            "a return's last check result names a text whose SHA-256 differs from its answer's"), 1, out)
        self.assertEqual(code, 4)

    def test_tc16_likeness_a_last_check_result_naming_the_answer_is_not_a_fault(self):
        self.clean_call('toolu_c_0004', 'a4000000000000004', kept=[kept_result('SubagentStop', text=CLOSING)])
        code, out = self.check()
        self.assertEqual(out['count_check']['faults'], {}, out)
        self.assertEqual(code, 0)

    def test_tc16_a_return_naming_an_event_the_harness_never_sent_is_a_fault(self):
        self.clean_call('toolu_c_0005', 'a4000000000000005')
        path = self.ledger / ('%s.jsonl' % SESSION)
        kept = [r for r in lines(path) if not (r.get('record') == 'witness' and r.get('event') == 'SubagentStop')]
        path.write_text(''.join(json.dumps(r) + '\n' for r in kept), encoding='utf-8')
        code, out = self.check()
        self.assertEqual(out['count_check']['faults'].get('a return names an event the harness never sent'), 1, out)
        self.assertEqual(code, 4)

    def test_tc16_an_answer_that_is_not_the_delivered_hand_back_is_a_fault(self):
        agent = 'a4000000000000006'
        self.clean_call('toolu_c_0006', agent, rows=handback_rows(REPORT) + closing_rows())
        # Plant the old reading: the answer's fingerprint is the closing text's.
        def change(row):
            if row.get('record') == 'return':
                row['answer_fingerprint'] = dict(row['answer_fingerprint'], sha256=sha(CLOSING))
        self.rewrite(change)
        code, out = self.check()
        self.assertEqual(out['count_check']['faults'].get(
            'a return on a call with a delivered hand-back has another answer'), 1, out)
        self.assertEqual(code, 4)

    def test_tc16_a_members_tokens_short_of_its_transcript_are_a_fault(self):
        # Since the rework of 28 October 2026 (TC-16), any member's one return counts every turn, not only a
        # refused member's.
        agent = 'a4000000000000007'
        self.clean_call('toolu_c_0007', agent, kept=[kept_result('SubagentStop', refused=True, n=1)])
        self.keep(agent, 2, kept_result('SubagentStop', text=CLOSING, n=2))
        self.stop(agent, self.project / SESSION / 'subagents' / ('agent-%s.jsonl' % agent), True)
        def change(row):
            if row.get('record') == 'return' and isinstance(row.get('tokens'), dict):
                row['tokens'] = dict(row['tokens'], output=row['tokens']['output'] - 1)
        self.rewrite(change)
        code, out = self.check()
        self.assertEqual(out['count_check']['faults'].get(
            "a member's return counts tokens other than its transcript's"), 1, out)
        self.assertEqual(code, 4)


if __name__ == '__main__':
    unittest.main()
