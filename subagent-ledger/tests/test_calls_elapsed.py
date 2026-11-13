"""Tests for the call reader's derived `elapsed_s`, `skill/scripts/calls.py`'s `row_of`.

A call's elapsed time is derived from the ledger, never written by a model: `returned_at` less
`dispatched_at`, both through the reader's own `parse_time`, to three places. Where either does not
parse, the row names the absence, `unrecorded (<field> reads <its text>)`, never a zero.

The records are one dispatch and one return of the shape the captures write, cut to the fields the
frame reads. The times are session f68da5cf's Callimachus call, 63.4 s by the ledger.

Each test was first run against the reader without the field, and failed.

Run from the skill's folder:  python3 -m unittest tests.test_calls_elapsed
"""

import importlib.util
import sys
import unittest
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parent.parent / 'skill' / 'scripts'

SESSION = 'f68da5cf-0000-4000-8000-000000000000'
CALL = 'toolu_elapsed'
AGENT = 'a242ae5203d216689'
DISPATCHED = '2026-11-05T06:31:12.659Z'
RETURNED = '2026-11-05T06:32:16.076Z'
NO_DISPATCH = 'unrecorded (no dispatch record)'


def load():
    if str(SCRIPTS) not in sys.path:
        sys.path.insert(0, str(SCRIPTS))
    spec = importlib.util.spec_from_file_location('calls_elapsed_under_test', SCRIPTS / 'calls.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def dispatch():
    return {'record': 'dispatch', 'call_id': CALL, 'session': SESSION, 'agent_id': AGENT,
            'dispatched_at': DISPATCHED, 'returned_at': 'unrecorded (not returned yet)', 'outcome': 'pending'}


def back(dispatched_at=DISPATCHED):
    return {'record': 'return', 'call_id': CALL, 'session': SESSION, 'agent_id': AGENT,
            'dispatched_at': dispatched_at, 'returned_at': RETURNED, 'outcome': 'returned'}


class TestElapsed(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.calls = load()

    def test_row_derives_elapsed_s(self):
        row = self.calls.row_of(dispatch(), back())
        self.assertEqual(row.get('elapsed_s'), 63.417)
        self.assertEqual(list(row).index('elapsed_s'), list(row).index('returned_at') + 1)

    def test_row_names_an_absence(self):
        row = self.calls.row_of(None, back(NO_DISPATCH))
        self.assertEqual(row.get('elapsed_s'), 'unrecorded (dispatched_at reads %s)' % NO_DISPATCH)
        self.assertNotIn(row.get('elapsed_s'), (0, 0.0, None))


if __name__ == '__main__':
    unittest.main()
