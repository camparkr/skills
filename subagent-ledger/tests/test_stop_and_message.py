"""Two fixes to Claude Code's capture: a subagent its caller stops with `TaskStop`, and a `SendMessage` addressed to
another session.

TaskStop. A background subagent stopped while it runs a tool ends its transcript in that tool call, so the stop's
wait for the transcript's end has nothing to end it. With the fix, `PreToolUse` on `TaskStop` naming an agent with a
pending call writes a `stopped-<agent>` pending file; the wait also ends on it, and the call's return reads `failed`,
class `stopped_by_caller`. `PostToolUse` on `TaskStop` writes the same return where none was written. A `TaskStop`
naming no pending agent writes nothing. The switched-off half runs a copy of the scripts with `READ_STOPS` false:
the stop is then cut off and no return is written.

SendMessage. A message whose `to` is no agent id the ledger holds, and whose response carries no
`resumedAgentId`, is a message to another session: its return is written at its `PostToolUse`, `served` where the
response's `success` is true and `failed` otherwise, its answer the response's text. The switched-off half sets
`MESSAGES_OUTSIDE` false and shows no return is written.

The payloads are the background fixtures' (fixtures/claude-code/background-events.jsonl), the tool name, input and
response replaced; the stopped transcript is background-agent.jsonl's first row and a made-up final request that
calls `Bash`. The `TaskStop` shapes follow a recorded one: input `{task_id}`, response `{message, task_id,
task_type}`.

Run from the skill's folder:  python3 -m unittest discover -s tests
"""

import json
import os
import shutil
import subprocess
import sys
import time
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

import test_capture_claude_code as base  # noqa: E402

AGENT = base.BACKGROUND_AGENT
STOPPED_ANSWER = 'unrecorded (the caller stopped the subagent)'
TOOL_CALL_ROW = {'type': 'assistant', 'message': {
    'id': 'msg_stopped_mid_tool', 'role': 'assistant', 'model': 'claude-haiku-5-5', 'stop_reason': 'tool_use',
    'content': [{'type': 'tool_use', 'id': 'toolu_lane_bash_running', 'name': 'Bash', 'input': {'command': 'sleep 600'}}],
    'usage': {'input_tokens': 5, 'cache_creation_input_tokens': 0, 'cache_read_input_tokens': 9, 'output_tokens': 3}}}


class Stopped(base.World):

    fields = 'all'
    CUT_OFF = 8

    def session(self):
        rows = self.events('background-events.jsonl')
        path = self.place_transcript('background-agent.jsonl', rows)
        first = path.read_text(encoding='utf-8').splitlines()[0]
        path.write_text(first + '\n' + json.dumps(TOOL_CALL_ROW) + '\n', encoding='utf-8')
        rows[3]['payload']['last_assistant_message'] = ''
        return rows

    def task_stop(self, rows, event, task_id=AGENT, call_id='toolu_taskstop_0001'):
        payload = json.loads(json.dumps(rows[0]['payload']))
        payload.update(hook_event_name=event, tool_name='TaskStop', tool_input={'task_id': task_id},
                       tool_use_id=call_id)
        if event == 'PostToolUse':
            payload['tool_response'] = {'message': 'Successfully stopped task: %s (a lane)' % task_id,
                                        'task_id': task_id, 'task_type': 'local_agent'}
        return {'event': event, 'payload': payload}

    def stop_process(self, row, scripts=None):
        script = (scripts or base.SCRIPTS) / 'capture_claude_code.py'
        return subprocess.Popen([sys.executable, str(script), 'SubagentStop'], stdin=subprocess.PIPE,
                                stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, cwd=str(self.work))

    def run_stop(self, row, scripts=None, cut_off=None):
        """The SubagentStop hook in a process of its own, as a harness runs it. True if it finished in time."""
        process = self.stop_process(row, scripts)
        try:
            process.communicate(json.dumps(row['payload']), timeout=cut_off or self.CUT_OFF)
            return True
        except subprocess.TimeoutExpired:
            process.kill()
            process.communicate()
            return False

    def returns(self):
        return [line for line in self.records() if line['record'] == 'return']

    def assert_stopped_return(self):
        back = self.returns()
        self.assertEqual(len(back), 1, back)
        record = back[0]
        self.assertEqual(record['agent_id'], AGENT)
        self.assertEqual(record['outcome'], 'failed')
        self.assertEqual(record['outcome_reason']['class'], 'stopped_by_caller')
        self.assertEqual(record['answer_path'], STOPPED_ANSWER)
        self.assertEqual(record['tokens']['output'], 3, 'the counters are the transcript as it stands')
        return record

    def test_c_11_6_a_stop_after_task_stop_ends_at_once_and_writes_failed(self):
        rows = self.session()
        self.feed(rows[:3])
        self.feed([self.task_stop(rows, 'PreToolUse')])
        self.assertTrue(self.run_stop(rows[3]), 'the stop was cut off')
        self.assert_stopped_return()
        self.feed([self.task_stop(rows, 'PostToolUse')])
        self.assertEqual(len(self.returns()), 1, 'PostToolUse writes no second return')
        self.assertEqual(self.errors(), [])

    def test_c_11_6_a_stop_already_waiting_ends_when_task_stop_comes(self):
        rows = self.session()
        self.feed(rows[:3])
        process = self.stop_process(rows[3])
        process.stdin.write(json.dumps(rows[3]['payload']))
        process.stdin.close()
        time.sleep(1.5)
        self.assertIsNone(process.poll(), 'the stop should be waiting')
        self.feed([self.task_stop(rows, 'PreToolUse')])
        try:
            process.wait(timeout=self.CUT_OFF)
        except subprocess.TimeoutExpired:
            process.kill()
            self.fail('the waiting stop did not end on TaskStop')
        finally:
            process.stdout.close()
            process.stderr.close()
        self.assert_stopped_return()

    def test_c_11_6_with_no_stop_post_tool_use_writes_the_return(self):
        rows = self.session()
        self.feed(rows[:3])
        self.feed([self.task_stop(rows, 'PreToolUse'), self.task_stop(rows, 'PostToolUse')])
        self.assert_stopped_return()
        self.assertEqual(list(self.capture.pending_dir(self.ledger, rows[0]['payload']['session_id']).glob('*.json')),
                         [], 'no pending file is left')

    def test_c_11_6_a_task_stop_naming_no_pending_agent_writes_nothing(self):
        rows = self.session()
        self.feed([self.task_stop(rows, 'PreToolUse', task_id='b87qfevlw'),
                   self.task_stop(rows, 'PostToolUse', task_id='b87qfevlw')])
        self.assertEqual(self.records(), [])
        self.assertEqual(self.errors(), [])
        folder = self.capture.pending_dir(self.ledger, rows[0]['payload']['session_id'])
        self.assertEqual(list(folder.glob('stopped-*.json')) if folder.exists() else [], [])

    def test_c_11_6_switched_off_the_stop_is_cut_off_and_no_return_is_written(self):
        copy = self.tmp / 'scripts-off'
        shutil.copytree(str(base.SCRIPTS), str(copy), ignore=shutil.ignore_patterns('__pycache__'))
        source = (copy / 'capture_claude_code.py').read_text(encoding='utf-8')
        self.assertIn('READ_STOPS = True', source)
        (copy / 'capture_claude_code.py').write_text(source.replace('READ_STOPS = True', 'READ_STOPS = False'),
                                                     encoding='utf-8')
        rows = self.session()
        self.feed(rows[:3])
        self.capture.READ_STOPS = False
        self.feed([self.task_stop(rows, 'PreToolUse')])
        self.assertFalse(self.run_stop(rows[3], scripts=copy, cut_off=4), 'the stop ended with the fix switched off')
        self.feed([self.task_stop(rows, 'PostToolUse')])
        self.assertEqual(self.returns(), [])


class MessageOutside(base.World):

    fields = 'all'
    TO = 'Another session on this machine'

    def message(self, rows, to, response, call_id='toolu_message_outside_01'):
        pre, post = json.loads(json.dumps(rows[0])), json.loads(json.dumps(rows[2]))
        for row in (pre, post):
            row['payload'].update(tool_name='SendMessage', tool_use_id=call_id,
                                  tool_input={'to': to, 'message': 'A note for the other session.'})
        pre['payload']['hook_event_name'] = 'PreToolUse'
        post['payload']['tool_response'] = response
        return [pre, post]

    def returns(self):
        return dict((line['call_id'], line) for line in self.records() if line['record'] == 'return')

    def answer(self, record):
        named = record['answer_path']
        found = [p for p in self.ledger.rglob('*') if p.is_file() and str(p).endswith(named)]
        return found[0].read_text(encoding='utf-8') if found else None

    def test_c_11_7_a_message_to_another_session_returns_at_its_post_tool_use(self):
        rows = self.events('background-events.jsonl')
        sent = 'Delivered to the inbox of %s.' % self.TO
        self.feed(self.message(rows, self.TO, {'success': True, 'message': sent, 'display': 'sent'}))
        back = self.returns()['toolu_message_outside_01']
        self.assertEqual(back['outcome'], 'served')
        self.assertEqual(back['agent_id'], 'unrecorded (addressed outside this session: %s)' % self.TO)
        self.assertEqual(self.answer(back), sent)
        self.assertEqual(self.errors(), [])

    def test_c_11_7_one_not_delivered_is_failed(self):
        rows = self.events('background-events.jsonl')
        self.feed(self.message(rows, self.TO, {'success': False, 'message': 'No one by that name is reachable.'}))
        self.assertEqual(self.returns()['toolu_message_outside_01']['outcome'], 'failed')

    def test_c_11_7_a_message_to_a_subagent_is_unchanged(self):
        rows = self.events('background-events.jsonl')
        self.place_transcript('background-agent.jsonl', rows)
        self.feed(rows[:3])
        self.feed(self.message(rows, AGENT, {'success': True, 'message': 'Message queued for delivery.'}))
        self.assertNotIn('toolu_message_outside_01', self.returns(), 'its return waits for the agent\'s stop')
        self.feed(self.message(rows, 'a-name-the-ledger-lacks', {'success': True, 'message': 'resumed',
                                                                 'resumedAgentId': AGENT},
                               call_id='toolu_message_resume_01'))
        self.assertNotIn('toolu_message_resume_01', self.returns(), 'a response naming resumedAgentId is a subagent call')

    def test_c_11_7_switched_off_no_return_is_written(self):
        rows = self.events('background-events.jsonl')
        self.capture.MESSAGES_OUTSIDE = False
        self.feed(self.message(rows, self.TO, {'success': True, 'message': 'sent'}))
        self.assertEqual(self.returns(), {})


if __name__ == '__main__':
    unittest.main()
