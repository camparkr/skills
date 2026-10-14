"""Fix note FN-16: a subagent resumed by `SendMessage` whose turns end with a hand-back call.

Turn read once. A lane that ends each turn by calling `SubagentHandback` (the `handback` tool in
subagent-tools.json) stops no request for a reason other than tool_use: in a real transcript every request's
`stop_reason` is null. Before the fix, `turn_begun` found no end of a turn before a delivered message, returned 0,
and each resume's return read the transcript from its first row: every earlier turn's counters and every earlier
turn's outside commands. A request that calls a hand-back tool now ends a turn too.

Every test on HandbackLane, here and in test_isolation_cut.py, checks at cleanup that no line its ledger holds is
over 64 KB (65,536 bytes as one JSON line).

The fixtures are small and synthetic: background-events.jsonl's payloads, and a transcript written turn by turn as
the lane would write it, each turn a delivered message, one `Bash` call and one `SubagentHandback` call, every
request's `stop_reason` null.

Run from the skill's folder:  python3 -m unittest tests/test_handback_turns.py
"""

import json
import sys
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

import test_capture_claude_code as base  # noqa: E402

AGENT = base.BACKGROUND_AGENT
RECORD_LIMIT = 65536
DELIVERED = 'The coordinator sent a message while you were working:\n%s'
MESSAGES = {2: 'Please also read the second notes file.', 3: 'Now read the third notes file, please.'}
MESSAGE_IDS = {2: 'toolu_fn16_message_0002', 3: 'toolu_fn16_message_0003'}


def usage(turn, request):
    """Counters that differ by turn and request, so a sum over the wrong rows shows."""
    base_value = turn * 1000 + request * 100
    return {'input_tokens': base_value + 1, 'cache_creation_input_tokens': base_value + 2,
            'cache_read_input_tokens': base_value + 3, 'output_tokens': base_value + 4}


def tokens_of(turn):
    """The four counters of one turn's two requests."""
    first, second = usage(turn, 1), usage(turn, 2)
    return {'input': first['input_tokens'] + second['input_tokens'],
            'cache_write': first['cache_creation_input_tokens'] + second['cache_creation_input_tokens'],
            'cache_read': first['cache_read_input_tokens'] + second['cache_read_input_tokens'],
            'output': first['output_tokens'] + second['output_tokens']}


class HandbackLane(base.World):
    """A background lane dispatched once and resumed twice by SendMessage, each turn ended by SubagentHandback."""

    fields = 'all'

    def setUp(self):
        super().setUp()
        self.addCleanup(self.check_record_size)

    def check_record_size(self):
        for path in sorted(self.ledger.glob('*.jsonl')):
            for number, line in enumerate(path.read_text(encoding='utf-8').splitlines(), 1):
                size = len(line.encode('utf-8'))
                self.assertLessEqual(size, RECORD_LIMIT, '%s line %d is %d bytes' % (path.name, number, size))

    # -- the transcript, written turn by turn ------------------------------------------------------

    def answer_of(self, turn):
        return 'Answer of turn %d.' % turn

    def commands_of(self, turn):
        return ['cat /elsewhere/turn-%d.md' % turn]

    def turn_rows(self, turn, opening):
        cwd = str(self.work)
        rows = [{'type': 'user', 'cwd': cwd, 'message': {'role': 'user', 'content': opening}}]
        commands = self.commands_of(turn)
        rows.append({'type': 'assistant', 'cwd': cwd, 'message': {
            'id': 'msg_fn16_turn%d_bash' % turn, 'role': 'assistant', 'model': 'claude-haiku-5-5',
            'stop_reason': None,
            'content': [{'type': 'tool_use', 'id': 'toolu_fn16_bash_%d_%d' % (turn, at), 'name': 'Bash',
                         'input': {'command': command}} for at, command in enumerate(commands)],
            'usage': usage(turn, 1)}})
        rows.append({'type': 'user', 'cwd': cwd, 'message': {'role': 'user', 'content': [
            {'type': 'tool_result', 'tool_use_id': 'toolu_fn16_bash_%d_%d' % (turn, at), 'content': 'read'}
            for at in range(len(commands))]}})
        rows.append({'type': 'assistant', 'cwd': cwd, 'message': {
            'id': 'msg_fn16_turn%d_handback' % turn, 'role': 'assistant', 'model': 'claude-haiku-5-5',
            'stop_reason': None,
            'content': [{'type': 'tool_use', 'id': 'toolu_fn16_handback_%d' % turn, 'name': 'SubagentHandback',
                         'input': {'message': self.answer_of(turn)}}],
            'usage': usage(turn, 2)}})
        rows.append({'type': 'user', 'cwd': cwd, 'message': {'role': 'user', 'content': [
            {'type': 'tool_result', 'tool_use_id': 'toolu_fn16_handback_%d' % turn,
             'content': [{'type': 'text', 'text': '{"success":true,"message":"Report delivered."}'}]}]}})
        return rows

    def append_turn(self, turn, opening):
        with open(self.path, 'a', encoding='utf-8') as handle:
            for row in self.turn_rows(turn, opening):
                handle.write(json.dumps(row) + '\n')

    # -- the hook events ---------------------------------------------------------------------------

    def message_rows(self, turn):
        pre, post = json.loads(json.dumps(self.rows[0])), json.loads(json.dumps(self.rows[2]))
        for row in (pre, post):
            row['payload'].update(tool_name='SendMessage', tool_use_id=MESSAGE_IDS[turn],
                                  tool_input={'to': AGENT, 'message': MESSAGES[turn]})
        post['payload']['tool_response'] = {'success': True, 'message': 'Resuming agent %s' % AGENT}
        return [pre, post]

    def stop_rows(self, turn):
        start = json.loads(json.dumps(self.rows[1]))
        stop = json.loads(json.dumps(self.rows[3]))
        stop['payload']['last_assistant_message'] = self.answer_of(turn)
        return [start, stop]

    def run_lane(self):
        """Dispatch, then two resumes; each turn is in the transcript before its stop is fed."""
        self.rows = self.events('background-events.jsonl')
        self.path = Path(self.rows[3]['payload']['agent_transcript_path'])
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text('', encoding='utf-8')
        self.append_turn(1, self.rows[0]['payload']['tool_input']['prompt'])
        self.feed(self.rows)
        for turn in (2, 3):
            self.feed(self.message_rows(turn))
            self.append_turn(turn, DELIVERED % MESSAGES[turn])
            self.feed(self.stop_rows(turn))

    def returns(self):
        return dict((line['call_id'], line) for line in self.records() if line['record'] == 'return')

    def own_tokens(self, record):
        return dict((key, record['tokens'][key]) for key in ('input', 'cache_write', 'cache_read', 'output'))


class TurnReadOnce(HandbackLane):

    def test_fn16_the_second_resume_reads_its_own_turn_only(self):
        self.run_lane()
        self.assertEqual(self.errors(), [])
        back = self.returns()[MESSAGE_IDS[3]]
        self.assertEqual(self.own_tokens(back), tokens_of(3))
        self.assertEqual([entry['command'] for entry in back['isolation']['outside']], self.commands_of(3))

    def test_fn16_the_first_resume_reads_its_own_turn_only(self):
        self.run_lane()
        back = self.returns()[MESSAGE_IDS[2]]
        self.assertEqual(self.own_tokens(back), tokens_of(2))
        self.assertEqual([entry['command'] for entry in back['isolation']['outside']], self.commands_of(2))

    def test_fn16_the_dispatch_keeps_its_own_turn(self):
        self.run_lane()
        back = self.returns()[self.rows[0]['payload']['tool_use_id']]
        self.assertEqual(self.own_tokens(back), tokens_of(1))
        self.assertEqual([entry['command'] for entry in back['isolation']['outside']], self.commands_of(1))

    def test_fn16_control_without_the_hand_back_boundary_the_resume_reads_from_the_start(self):
        begun = self.capture.turn_begun
        with base.mock.patch.object(self.capture, 'turn_begun',
                                    lambda rows, position, handbacks=None: begun(rows, position, {})):
            self.run_lane()
        back = self.returns().get(MESSAGE_IDS[3])
        self.assertIsNotNone(back)
        self.assertEqual(self.own_tokens(back)['output'], sum(tokens_of(turn)['output'] for turn in (1, 2, 3)))


class TurnsSumOnce(HandbackLane):
    """Each distinct turn's tokens, added up once across a lane's returns, equal the transcript's own turn-by-turn
    totals. The third turn answers two messages with one hand-back: the first delivered as the user row that opens
    the turn, the second queued and delivered mid-turn as a `queued_command` attachment, as in session bc2f0e03's
    lane adec2091345ee7106 (rows 697, 776 and 892). Their two returns carry identical figures, and the sum counts
    them once. A record carries no span, so a turn is told by what its returns share: the agent, the answer file
    and the four counters."""

    QUEUED = 'And count the lines of the third notes file too.'
    QUEUED_ID = 'toolu_fn16_message_0004'

    def turn_rows(self, turn, opening):
        rows = super().turn_rows(turn, opening)
        if turn == 3:
            rows.insert(3, {'type': 'attachment', 'isSidechain': True, 'cwd': str(self.work),
                            'attachment': {'type': 'queued_command', 'prompt': self.QUEUED, 'isMeta': True,
                                           'origin': {'kind': 'coordinator'}}})
        return rows

    def queued_rows(self):
        pre, post = self.message_rows(3)
        for row in (pre, post):
            row['payload'].update(tool_use_id=self.QUEUED_ID,
                                  tool_input={'to': AGENT, 'message': self.QUEUED})
        post['payload']['tool_response'] = {'success': True,
                                            'message': 'Message queued for delivery to %s.' % AGENT}
        return [pre, post]

    def run_lane(self):
        """Dispatch; a resume; then two messages sent before the third turn's stop, both answered by that turn."""
        self.rows = self.events('background-events.jsonl')
        self.path = Path(self.rows[3]['payload']['agent_transcript_path'])
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text('', encoding='utf-8')
        self.append_turn(1, self.rows[0]['payload']['tool_input']['prompt'])
        self.feed(self.rows)
        self.feed(self.message_rows(2))
        self.append_turn(2, DELIVERED % MESSAGES[2])
        self.feed(self.stop_rows(2))
        self.feed(self.message_rows(3) + self.queued_rows())
        self.append_turn(3, DELIVERED % MESSAGES[3])
        self.feed(self.stop_rows(3))

    def transcript_turn_totals(self):
        """The four counters of each turn, read straight from the transcript: a turn ends at a hand-back call."""
        totals, current = [], dict.fromkeys(('input', 'cache_write', 'cache_read', 'output'), 0)
        names = (('input', 'input_tokens'), ('cache_write', 'cache_creation_input_tokens'),
                 ('cache_read', 'cache_read_input_tokens'), ('output', 'output_tokens'))
        for line in self.path.read_text(encoding='utf-8').splitlines():
            message = json.loads(line).get('message') or {}
            if not isinstance(message.get('usage'), dict):
                continue
            for label, native in names:
                current[label] += message['usage'][native]
            if any(part.get('name') == 'SubagentHandback' for part in message.get('content') or []
                   if isinstance(part, dict)):
                totals.append(current)
                current = dict.fromkeys(current, 0)
        return totals

    def test_fn16_each_turn_summed_once_equals_the_transcripts_turns(self):
        self.run_lane()
        self.assertEqual(self.errors(), [])
        returns = self.returns()
        self.assertEqual(len(returns), 4, sorted(returns))
        both = returns[MESSAGE_IDS[3]], returns[self.QUEUED_ID]
        self.assertEqual(self.own_tokens(both[0]), self.own_tokens(both[1]), 'one turn answered both messages')
        self.assertEqual(both[0]['answer_path'], both[1]['answer_path'])
        turns = {}
        for record in returns.values():
            own = self.own_tokens(record)
            turns[(record['agent_id'], record['answer_path'], tuple(sorted(own.items())))] = own
        self.assertEqual(len(turns), 3, 'three distinct turns')
        summed = dict((key, sum(own[key] for own in turns.values())) for key in ('input', 'cache_write',
                                                                                   'cache_read', 'output'))
        per_turn = self.transcript_turn_totals()
        self.assertEqual(len(per_turn), 3)
        self.assertEqual(summed, dict((key, sum(turn[key] for turn in per_turn)) for key in summed))


if __name__ == '__main__':
    unittest.main()
