"""Controls for the label line: the writer's `label`, its schema, and the reader's join.

The labeller writes one `record: label` line per labelled return into the session's own ledger file, and never
rewrites a record. The reader joins each label line to its call's row by `call_id`, shows the newest and counts the
older ones, and names a label line whose call has no row as the absence `label for no call`. This file holds the
public skill's half of the controls, the reader's join among them, and a fix to how the reader merges a call's two
records. The labeller's half is with the labeller, which this skill does not ship.

Each control has a half that runs on the code as built and must pass, and a half that switches one part off, by a
patch in this file, and shows the fault. Before the code existed every test here failed, for the reason each names.

No test writes to a real ledger: SUBAGENT_LEDGER_DIR names a temporary folder.

Run from the skill's folder:  python3 -m unittest discover -s tests
"""

import contextlib
import importlib.util
import io
import json
import os
import re
import shutil
import stat
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

HERE = Path(__file__).resolve().parent
SCRIPTS = HERE.parent / 'skill' / 'scripts'
LEDGER_PY = SCRIPTS / 'ledger.py'
CALLS_PY = SCRIPTS / 'calls.py'
CAPTURES = ('capture_claude_code.py', 'capture_codex.py', 'capture_opencode.py', 'call.py')

SESSION = 'b5label-0000-4000-8000-000000000001'
UNSET = 'unrecorded (cut-off not yet set)'
ON_LABEL_LINE = 'unrecorded (labelled on the label line)'
# The wordings a record carried before label lines: an unbuilt labeller, or none having read it.
OLD_WORDINGS = re.compile(r'not built|no labeller has read this record')
# The label line's keys, in their documented order.
LABEL_KEYS = ['schema', 'record', 'call_id', 'session', 'labelled_at', 'labelled_because', 'failure_modes',
              'likelihoods', 'cutoff', 'roster_revision', 'question_revision', 'labeller_model', 'labeller_call_ids',
              'withheld']
ROW_LABEL_KEYS = {'labelled_because', 'failure_modes', 'likelihoods', 'cutoff', 'roster_revision', 'question_revision',
                  'labeller_model', 'labeller_call_ids', 'labelled_at', 'earlier'}
REVISION = '178097501b17147731b194d3a88211bbc53d03aa'
QUESTION_REVISION = 'f' * 40
LOW = {'0': 0.7, '1': 0.2, '2': 0.06, '3': 0.04}
HIGH = {'0': 0.05, '1': 0.1, '2': 0.25, '3': 0.6}


def load(path, name):
    """The module at `path`, loaded fresh."""
    if str(SCRIPTS) not in sys.path:
        sys.path.insert(0, str(SCRIPTS))
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def writer():
    return load(LEDGER_PY, 'ledger_for_label_test_%d' % id(object()))


def lines_of(path):
    path = Path(path)
    if not path.is_file():
        return []
    return [json.loads(line) for line in path.read_text(encoding='utf-8').splitlines() if line.strip()]


def score(levels):
    return {'score': round(sum(int(k) * v for k, v in levels.items()), 2), 'probabilities': dict(levels),
            'confidence': 0.3}


def likelihoods(high=None):
    out = dict(('mode_%02d' % n, score(LOW)) for n in range(18))
    if high:
        out[high] = score(HIGH)
    return out


def marks(high=None):
    return [{'mode': high, 'level': 3, 'p': 0.6}] if high else []


class LabelWorld(unittest.TestCase):
    """A ledger folder with every field on, and a session holding two calls of two records each."""

    fields = 'all'

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix='label-line-test-'))
        self.addCleanup(self._cleanup)
        self.folder = self.tmp / 'ledger'
        self.folder.mkdir()
        patcher = mock.patch.dict(os.environ, {'SUBAGENT_LEDGER_DIR': str(self.folder)})
        patcher.start()
        self.addCleanup(patcher.stop)
        (self.folder / 'config.json').write_text(json.dumps({'fields': self.fields}), encoding='utf-8')
        self.ledger = writer()

    def _cleanup(self):
        for path in self.tmp.rglob('*'):
            with contextlib.suppress(OSError):
                os.chmod(path, stat.S_IRWXU)
        shutil.rmtree(self.tmp, True)

    def a_call(self, call_id, route_back='subagent', at='2026-10-09T01:00:00.000Z'):
        sent = self.ledger.dispatch(call_id=call_id, session=SESSION, route='subagent', harness='fixture-harness',
                                    caller='parent', dispatched_at=at, brief='a bounded question')
        self.assertTrue(sent.ok, sent.error)
        fields = dict(call_id=call_id, session=SESSION, agent_id='agent-%s' % call_id, outcome='served',
                      outcome_reason='none (served)', harness='fixture-harness', caller='parent', answer='an answer')
        if route_back is not None:
            fields['route'] = route_back
        back = self.ledger.ret(**fields)
        self.assertTrue(back.ok, back.error)

    def a_label(self, call_id, labelled_at, high=None, labeller_call_id='label-call-1'):
        if not hasattr(self.ledger, 'label'):
            raise AssertionError('ledger.py has no label(): the label line\'s writer is not built')
        return self.ledger.label(call_id=call_id, session=SESSION, labelled_at=labelled_at,
                                 labelled_because=['always: verdict-or-review'], failure_modes=marks(high),
                                 likelihoods=likelihoods(high), cutoff=2, roster_revision=REVISION,
                                 question_revision=QUESTION_REVISION, labeller_model='labeller-1.0.0',
                                 labeller_call_ids=[labeller_call_id, 'label-call-b', 'label-call-c'])

    def session_lines(self):
        return lines_of(self.folder / ('%s.jsonl' % SESSION))

    def errors(self):
        return lines_of(self.folder / 'capture-errors.jsonl')

    def read(self, module=None):
        module = module or load(CALLS_PY, 'calls_for_label_test_%d' % id(object()))
        out = io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(io.StringIO()):
            code = module.main(['--session', SESSION, '--json'])
        return code, json.loads(out.getvalue())

    def row(self, data, call_id):
        return [row for row in data['calls'] if row['call_id'] == call_id][0]


# ---------------------------------------------------------------------------
# The line itself: its documented shape, validated, no field setting
# ---------------------------------------------------------------------------

class TheLine(LabelWorld):

    fields = 'frame'

    def test_the_line_has_sevens_shape_and_validates(self):
        self.a_call('call-1')
        written = self.a_label('call-1', '2026-10-09T02:00:00.000Z', high='mode_03')
        self.assertTrue(written.ok, written.error)
        line = [r for r in self.session_lines() if r['record'] == 'label'][0]
        self.assertEqual(list(line), LABEL_KEYS, 'the label line\'s keys, in their documented order')
        self.assertEqual(line['schema'], 'subagent-ledger/1')
        self.assertEqual(line['failure_modes'], [{'mode': 'mode_03', 'level': 3, 'p': 0.6}])
        self.assertEqual(line['cutoff'], 2)
        self.assertEqual(line['likelihoods']['mode_03'], score(HIGH))
        self.assertEqual(line['withheld'], 0)
        self.assertNotIn('fields_on', line, 'a label line takes no field setting, even under "frame"')
        self.assertEqual(self.ledger.validate(line, self.ledger.load_schema(), ref='#/$defs/label'), [])
        self.assertEqual(self.ledger.validate(line, self.ledger.load_schema()), [])
        self.assertEqual(self.errors(), [])

    def test_a_set_cut_off_and_its_marks_validate(self):
        self.a_call('call-1')
        if not hasattr(self.ledger, 'label'):
            raise AssertionError('ledger.py has no label(): the label line\'s writer is not built')
        written = self.ledger.label(call_id='call-1', session=SESSION, labelled_at='2026-10-09T02:00:00.000Z',
                                    labelled_because=['outcome: failed'],
                                    failure_modes=[{'mode': 'mode_03', 'level': 2, 'p': 0.4}],
                                    likelihoods=likelihoods('mode_03'), cutoff=2, roster_revision=REVISION,
                                    question_revision=QUESTION_REVISION, labeller_model='labeller-1.0.0',
                                    labeller_call_ids=['label-call-1', 'label-call-2', 'label-call-3'])
        self.assertTrue(written.ok, written.error)

    def test_switched_off_a_line_with_a_field_setting_or_no_likelihoods_is_rejected(self):
        schema = self.ledger.load_schema()
        good = {'schema': 'subagent-ledger/1', 'record': 'label', 'call_id': 'c', 'session': SESSION,
                'labelled_at': '2026-10-09T02:00:00Z', 'labelled_because': ['always: verdict-or-review'],
                'failure_modes': [], 'likelihoods': likelihoods(), 'cutoff': 2, 'roster_revision': REVISION,
                'question_revision': QUESTION_REVISION, 'labeller_model': 'labeller-1.0.0',
                'labeller_call_ids': ['label-call-1', 'label-call-2', 'label-call-3'], 'withheld': 0}
        self.assertEqual(self.ledger.validate(good, schema), [])
        with_setting = dict(good, fields_on=[], fields_not_chosen=[])
        self.assertTrue(self.ledger.validate(with_setting, schema))
        no_likelihoods = dict(good)
        del no_likelihoods['likelihoods']
        self.assertTrue(self.ledger.validate(no_likelihoods, schema))
        old_name = dict(no_likelihoods, all=likelihoods())
        self.assertTrue(self.ledger.validate(old_name, schema), '`all` was the earlier name of `likelihoods`')


# ---------------------------------------------------------------------------
# The newest label shown, the older counted
# ---------------------------------------------------------------------------

class CL1Join(LabelWorld):

    def two_calls_labelled(self):
        self.a_call('call-1', at='2026-10-09T01:00:00.000Z')
        self.a_call('call-2', at='2026-10-09T01:00:01.000Z')
        self.assertTrue(self.a_label('call-1', '2026-10-09T02:00:00.000Z', high='mode_01').ok)
        self.assertTrue(self.a_label('call-2', '2026-10-09T02:00:00.000Z', high='mode_02').ok)
        self.assertTrue(self.a_label('call-1', '2026-10-09T03:00:00.000Z', high='mode_09',
                                     labeller_call_id='label-call-3').ok)

    def test_c_l_1_the_newest_label_and_one_earlier(self):
        self.two_calls_labelled()
        code, data = self.read()
        self.assertEqual(code, 0)
        first, second = self.row(data, 'call-1'), self.row(data, 'call-2')
        self.assertEqual(set(first['labels']), ROW_LABEL_KEYS)
        self.assertEqual(first['labels']['labelled_at'], '2026-10-09T03:00:00.000Z')
        self.assertEqual(first['labels']['likelihoods']['mode_09'], score(HIGH))
        self.assertEqual(first['labels']['earlier'], 1)
        self.assertEqual(first['labels']['failure_modes'], [{'mode': 'mode_09', 'level': 3, 'p': 0.6}])
        self.assertEqual(first['labels']['cutoff'], 2)
        self.assertEqual(first['labels']['question_revision'], QUESTION_REVISION)
        self.assertEqual(first['labels']['labeller_call_ids'], ['label-call-3', 'label-call-b', 'label-call-c'])
        self.assertEqual(first['labels']['roster_revision'], REVISION)
        self.assertEqual(first['labels']['labeller_model'], 'labeller-1.0.0')
        self.assertEqual(second['labels']['earlier'], 0)
        self.assertEqual(second['labels']['likelihoods']['mode_02'], score(HIGH))
        self.assertEqual(data['absences'], [])

    def test_c_l_1_a_call_with_no_label_line_says_so(self):
        self.a_call('call-1')
        _, data = self.read()
        self.assertEqual(self.row(data, 'call-1')['labels'], 'unrecorded (no label line for this call)')

    def test_c_l_1_switched_off_the_first_label_line_shown_is_the_older(self):
        self.two_calls_labelled()
        module = load(CALLS_PY, 'calls_first_label')
        module.newest_label = lambda lines: lines[0]
        _, data = self.read(module)
        self.assertEqual(self.row(data, 'call-1')['labels']['labelled_at'], '2026-10-09T02:00:00.000Z')


# ---------------------------------------------------------------------------
# A label line whose call has no row
# ---------------------------------------------------------------------------

class CL3NoCall(LabelWorld):

    def test_c_l_3_label_for_no_call(self):
        self.a_call('call-1')
        self.assertTrue(self.a_label('call-missing', '2026-10-09T02:00:00.000Z').ok)
        _, data = self.read()
        self.assertEqual([row['call_id'] for row in data['calls']], ['call-1'])
        self.assertEqual(data['absences'], [{'call_id': 'call-missing', 'reason': 'label for no call',
                                             'witnesses': []}])

    def test_c_l_3_switched_off_the_label_drops_out(self):
        self.a_call('call-1')
        self.assertTrue(self.a_label('call-missing', '2026-10-09T02:00:00.000Z').ok)
        module = load(CALLS_PY, 'calls_no_label_absence')
        module.labels_for_no_call = lambda labels, row_ids: []
        _, data = self.read(module)
        self.assertEqual(data['absences'], [])


# ---------------------------------------------------------------------------
# The return record's own three fields
# ---------------------------------------------------------------------------

class CL4ReturnFields(LabelWorld):

    def test_c_l_4_a_new_return_reads_labelled_on_the_label_line(self):
        self.a_call('call-1')
        back = [r for r in self.session_lines() if r['record'] == 'return'][0]
        for name in ('failure_modes', 'roster_revision', 'labeller_model'):
            self.assertEqual(back[name], ON_LABEL_LINE, name)

    def test_c_l_4_no_writer_or_capture_carries_an_old_wording(self):
        for name in ('ledger.py',) + CAPTURES:
            text = (SCRIPTS / name).read_text(encoding='utf-8')
            self.assertIsNone(OLD_WORDINGS.search(text), '%s still reads an old wording' % name)

    def test_c_l_4_switched_off_the_old_default_is_seen(self):
        self.ledger.NOT_GIVEN = dict(self.ledger.NOT_GIVEN, failure_modes='unrecorded (labeller not built)')
        self.a_call('call-1')
        back = [r for r in self.session_lines() if r['record'] == 'return'][0]
        self.assertEqual(back['failure_modes'], 'unrecorded (labeller not built)')
        self.assertNotEqual(back['failure_modes'], ON_LABEL_LINE)


# ---------------------------------------------------------------------------
# A label line that cannot be written
# ---------------------------------------------------------------------------

class CL6WriteFails(LabelWorld):

    def lock_and_label(self):
        self.a_call('call-1')
        target = self.folder / ('%s.jsonl' % SESSION)
        target.chmod(stat.S_IRUSR)
        try:
            return self.a_label('call-1', '2026-10-09T02:00:00.000Z')
        finally:
            target.chmod(0o600)

    def test_c_l_6_an_error_line_at_write_and_the_reader_says_write_failed(self):
        result = self.lock_and_label()
        self.assertFalse(result.ok)
        self.assertEqual([r for r in self.session_lines() if r['record'] == 'label'], [])
        error = self.errors()[-1]
        self.assertEqual(error['stage'], 'write')
        self.assertEqual(error['record'], 'label')
        self.assertEqual(error['call_id'], 'call-1')
        self.assertEqual(error['session'], SESSION)
        self.assertEqual(self.ledger.validate(error, self.ledger.load_schema()), [])
        _, data = self.read()
        reasons = [a['reason'] for a in data['absences'] if a['call_id'] == 'call-1']
        self.assertEqual(len(reasons), 1)
        self.assertTrue(reasons[0].startswith('write failed: PermissionError'), reasons)
        self.assertEqual(self.row(data, 'call-1')['labels'], 'unrecorded (no label line for this call)')

    def test_c_l_6_switched_off_without_error_lines_the_reader_is_silent(self):
        self.lock_and_label()
        module = load(CALLS_PY, 'calls_no_errors')
        module.error_lines = lambda folder: []
        _, data = self.read(module)
        self.assertEqual(data['absences'], [])


# ---------------------------------------------------------------------------
# The reader shows a filled value over an unrecorded one
# ---------------------------------------------------------------------------

class FilledOverUnrecorded(LabelWorld):

    def test_a_return_without_route_shows_the_dispatchs_route(self):
        self.a_call('call-1', route_back=None)
        back = [r for r in self.session_lines() if r['record'] == 'return'][0]
        self.assertTrue(re.match(r'^unrecorded \(.+\)$', back['route']), back['route'])
        _, data = self.read()
        row = self.row(data, 'call-1')
        self.assertEqual(row['route'], 'subagent')
        self.assertEqual(row['harness'], 'fixture-harness')

    def test_both_filled_the_return_still_wins(self):
        self.a_call('call-1', route_back='cli')
        _, data = self.read()
        self.assertEqual(self.row(data, 'call-1')['route'], 'cli')

    def test_switched_off_the_returns_unrecorded_value_is_shown(self):
        self.a_call('call-1', route_back=None)
        module = load(CALLS_PY, 'calls_return_always')
        module.shared_value = lambda sent, back, name: module.field_value(back if back is not None else sent, name)
        _, data = self.read(module)
        self.assertTrue(self.row(data, 'call-1')['route'].startswith('unrecorded ('))


if __name__ == '__main__':
    unittest.main()
