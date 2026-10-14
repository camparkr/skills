"""Tests for the reader's window: --since and --until bound the count check and the received messages.

A session's ledger may start after its transcript does, when the capture was installed mid-session. The count check
then compares only the transcript tool uses and the ledger records inside the window, so the calls made before the
install are not reported as missing. A row of the transcript is in the window by its own `timestamp`; a ledger record
by its dispatch time, or its return time where it has no dispatch. A received message is in it by its row's time.

Run from the skill's folder:  python3 -m unittest discover -s tests
"""

import json
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
SCRIPTS = HERE.parent / 'skill' / 'scripts'
SESSION = 'window00-0000-4000-8000-000000000001'


class Window(unittest.TestCase):

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix='window-test-'))
        self.addCleanup(shutil.rmtree, str(self.tmp), True)
        self.ledger = self.tmp / 'ledger'
        self.ledger.mkdir()
        (self.ledger / 'config.json').write_text(json.dumps({'fields': 'all'}), encoding='utf-8')
        sys.path.insert(0, str(SCRIPTS))
        import ledger
        common = {'session': SESSION, 'harness': 'claude-code', 'route': 'subagent', 'caller': 'parent',
                  'project': 'fixture', 'agent_id': 'a-after'}
        ledger.dispatch(ledger=str(self.ledger), brief='b', call_id='toolu_after', dispatched_at='2026-10-12T05:00:00.000Z',
                        **common)
        ledger.ret('toolu_after', ledger=str(self.ledger), answer='a', returned_at='2026-10-12T05:01:00.000Z',
                   outcome='served', outcome_reason='none (served)', **common)
        rows = []
        for at, call_id, name in (('2026-10-12T03:00:00.000Z', 'toolu_before', 'Agent'),
                                  ('2026-10-12T05:00:00.000Z', 'toolu_after', 'Agent'),
                                  ('2026-10-12T03:30:00.000Z', 'toolu_fetch_before', 'WebFetch')):
            rows.append({'type': 'assistant', 'sessionId': SESSION, 'timestamp': at,
                         'message': {'id': 'm-' + call_id, 'content': [{'type': 'tool_use', 'id': call_id, 'name': name,
                                                                         'input': {}}]}})
        for at in ('2026-10-12T03:10:00.000Z', '2026-10-12T05:10:00.000Z'):
            rows.append({'type': 'queue-operation', 'operation': 'enqueue', 'sessionId': SESSION, 'timestamp': at,
                         'content': '<cross-session-message from="uds:/x" from-session="local_x" from-name="Other">'
                                    'hello</cross-session-message>'})
        self.transcript = self.tmp / ('%s.jsonl' % SESSION)
        self.transcript.write_text(''.join(json.dumps(r) + '\n' for r in rows), encoding='utf-8')

    def check(self, *window):
        done = subprocess.run([sys.executable, str(SCRIPTS / 'calls.py'), '--session', SESSION, '--ledger',
                               str(self.ledger), '--json', '--count-check', '--harness', 'claude-code', '--transcript',
                               str(self.transcript)] + list(window), capture_output=True, text=True)
        return done.returncode, json.loads(done.stdout)

    def test_without_a_window_the_calls_before_the_install_are_missing(self):
        code, out = self.check()
        self.assertEqual((code, out['count_check']['difference']), (4, 2))

    def test_with_since_they_are_not_counted(self):
        code, out = self.check('--since', '2026-10-12T04:00:00Z')
        self.assertEqual((code, out['count_check']['difference']), (0, 0))
        self.assertEqual(out['count_check']['by_caller'], [{'caller': 'parent', 'transcript_count': 1,
                                                            'ledger_count': 1}])
        self.assertEqual([m['at'] for m in out['received_messages']], ['2026-10-12T05:10:00.000Z'])

    def test_until_bounds_the_other_end(self):
        code, out = self.check('--until', '2026-10-12T04:00:00Z')
        self.assertEqual(out['count_check']['by_caller'], [{'caller': 'parent', 'transcript_count': 1,
                                                            'ledger_count': 0}])
        self.assertEqual([m['at'] for m in out['received_messages']], ['2026-10-12T03:10:00.000Z'])


if __name__ == '__main__':
    unittest.main()
