"""Tests for the fingerprints on each record and for `calls.py --prune`, which removes a session's copies.

Each record carries the fingerprint (`sha256`, `bytes`, `lines`) of every text the ledger copies, whatever `fields`
says; a return names the file its answer can be read from (`answer_source`). With `keep_copies` `until-close` in the
ledger folder's config.json, `calls.py --session <id> --prune` writes one witness line, `event` `prune`, and then
removes the session's copies; it refuses, deleting nothing, where a copy's fingerprint could be lost. The reader shows
each copy `kept`, `removed` or `missing`.

Ledgers written before fingerprints existed are built here by hand, as the writer wrote them then. No test writes to a
real ledger: every ledger folder is a temporary one.

Run from the skill's folder:  python3 -m unittest discover -s tests
"""

import datetime
import hashlib
import importlib.util
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

HERE = Path(__file__).resolve().parent
SCRIPTS = HERE.parent / 'skill' / 'scripts'
SESSION = 'prune000-0000-4000-8000-000000000001'
NO_BRIEF = 'unrecorded (no brief was passed)'
NO_ANSWER = 'unrecorded (no answer came back)'

for folder in (SCRIPTS, HERE):
    if str(folder) not in sys.path:
        sys.path.insert(0, str(folder))
import test_capture_claude_code as base  # noqa: E402


def load(name):
    spec = importlib.util.spec_from_file_location('%s_fp_%d' % (name, id(object())), SCRIPTS / ('%s.py' % name))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def fingerprint(data):
    """What the record should hold for these bytes."""
    lines = data.count(b'\n') + (1 if data and not data.endswith(b'\n') else 0)
    return {'sha256': hashlib.sha256(data).hexdigest(), 'bytes': len(data), 'lines': lines}


def rows_of(path):
    return [json.loads(line) for line in Path(path).read_text(encoding='utf-8').splitlines() if line.strip()]


class Ledger(unittest.TestCase):
    """A scratch ledger folder."""

    keep = 'until-close'
    fields = 'all'

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix='fingerprints-'))
        self.addCleanup(shutil.rmtree, str(self.tmp), True)
        self.ledger = self.tmp / 'ledger'
        self.ledger.mkdir()
        self.config({'fields': self.fields, 'keep_copies': self.keep})
        self.writer = load('ledger')

    def config(self, data):
        (self.ledger / 'config.json').write_text(json.dumps(data), encoding='utf-8')

    @property
    def jsonl(self):
        return self.ledger / ('%s.jsonl' % SESSION)

    @property
    def folder(self):
        return self.ledger / SESSION

    def common(self, call_id):
        return {'session': SESSION, 'harness': 'claude-code', 'route': 'subagent', 'caller': 'parent',
                'project': 'fixture', 'call_id': call_id}

    def write_call(self, call_id, brief='The brief.\nTwo lines.\n', answer='The answer, one line', prompt=None,
                   at='2026-10-18T01:00:00.000Z'):
        self.writer.dispatch(ledger=str(self.ledger), brief=brief, prompt=prompt, agent_id='unrecorded (not yet returned)',
                             dispatched_at=at, **self.common(call_id))
        self.writer.ret(ledger=str(self.ledger), answer=answer, agent_id='a-%s' % call_id, outcome='served',
                        outcome_reason='none (served)', returned_at=at.replace(':00.000Z', ':30.000Z'),
                        **self.common(call_id))

    def records(self):
        return [r for r in rows_of(self.jsonl) if r.get('record') in ('dispatch', 'return')]

    def prune(self, *extra):
        done = subprocess.run([sys.executable, str(SCRIPTS / 'calls.py'), '--session', SESSION, '--ledger',
                               str(self.ledger), '--prune'] + list(extra), capture_output=True, text=True)
        try:
            out = json.loads(done.stdout)
        except ValueError:
            out = None
        return done.returncode, out, done

    def read(self):
        done = subprocess.run([sys.executable, str(SCRIPTS / 'calls.py'), '--session', SESSION, '--ledger',
                               str(self.ledger), '--json'], capture_output=True, text=True)
        return json.loads(done.stdout)

    def copies(self):
        return sorted(p.name for p in self.folder.iterdir()) if self.folder.is_dir() else []

    def old_record(self, kind, call_id, field, path, at):
        """A record as the writer wrote it before fingerprints: it names its copy and carries no fingerprint."""
        record = {'schema': 'subagent-ledger/1', 'record': kind, 'call_id': call_id, 'session': SESSION,
                  'agent_id': 'unrecorded (not yet returned)', 'dispatched_at': at,
                  'returned_at': 'unrecorded (not yet returned)' if kind == 'dispatch' else at,
                  'outcome': 'unrecorded (not yet returned)' if kind == 'dispatch' else 'served',
                  'fields_on': [field], 'fields_not_chosen': [], 'withheld': 0, field: str(path)}
        with open(self.jsonl, 'a', encoding='utf-8') as handle:
            handle.write(json.dumps(record) + '\n')

    def old_copy(self, text, raw=None):
        """A copy named, as the writer names one, by the first 16 hex characters of its text's hash."""
        self.folder.mkdir(exist_ok=True)
        data = text.encode('utf-8')
        path = self.folder / ('%s.md' % hashlib.sha256(data).hexdigest()[:16])
        path.write_bytes(raw if raw is not None else data)
        return path


# ---------------------------------------------------------------------------
# B13-1, B13-2: the fingerprints
# ---------------------------------------------------------------------------

class Fingerprints(Ledger):

    def test_b13_1_each_fingerprint_matches_its_copy(self):
        brief_file = self.tmp / 'named-brief.md'
        brief_file.write_text('A named brief.\n', encoding='utf-8')
        self.write_call('c-named', brief='A named brief.\n', prompt='Follow named-brief.md please.')
        self.write_call('c-inline', brief='An inline brief with no end of line')
        for record in self.records():
            for name in (('brief', 'prompt') if record['record'] == 'dispatch' else ('answer',)):
                found = record.get('%s_fingerprint' % name)
                if name == 'prompt' and record['call_id'] != 'c-named':
                    self.assertNotIn('prompt_fingerprint', record)
                    continue
                self.assertIsInstance(found, dict, '%s %s' % (record['record'], name))
                copy = self.folder / ('%s.md' % found['sha256'][:16])
                self.assertTrue(copy.is_file(), copy.name)
                self.assertEqual(found, fingerprint(copy.read_bytes()))
            self.assertEqual(self.writer.validate(record, ref='#/$defs/%s' % record['record']), [])
            for key in ('brief_fingerprint', 'prompt_fingerprint', 'answer_fingerprint'):
                self.assertNotIn(key, record['fields_on'] + record['fields_not_chosen'])

    def test_b13_1_with_the_default_fields_the_fingerprints_are_still_written(self):
        self.config({'fields': 'default'})
        self.write_call('c-default')
        sent, back = self.records()
        self.assertIsInstance(sent['brief_fingerprint'], dict)
        self.assertIsInstance(back['answer_fingerprint'], dict)

    def test_b13_1_a_copy_holds_exactly_the_hashed_bytes(self):
        self.write_call('c-lines', brief='one\ntwo\n')
        sent = self.records()[0]
        copy = self.folder / ('%s.md' % sent['brief_fingerprint']['sha256'][:16])
        self.assertEqual(copy.read_bytes(), b'one\ntwo\n')
        self.assertEqual(sent['brief_fingerprint']['lines'], 2)

    def test_b13_2_no_brief_and_no_answer_say_so(self):
        self.writer.dispatch(ledger=str(self.ledger), agent_id='unrecorded (not yet returned)',
                             dispatched_at='2026-10-18T01:00:00.000Z', **self.common('c-none'))
        self.writer.ret(ledger=str(self.ledger), agent_id='a', outcome='failed',
                        outcome_reason={'class': 'other', 'text': 'x'}, returned_at='2026-10-18T01:00:01.000Z',
                        **self.common('c-none'))
        sent, back = self.records()
        self.assertEqual(sent['brief_fingerprint'], NO_BRIEF)
        self.assertEqual(back['answer_fingerprint'], NO_ANSWER)


# ---------------------------------------------------------------------------
# B13-3 and BS-1: answer_source, and an inline brief's source
# ---------------------------------------------------------------------------

class Sources(base.World):

    fields = 'all'

    def test_b13_3_a_subagent_return_names_its_transcript(self):
        rows = self.foreground()
        self.feed(rows)
        back = [r for r in self.records() if r['record'] == 'return'][0]
        stop = [r for r in rows if r['event'] == 'SubagentStop'][0]
        self.assertEqual(back['answer_source'], stop['payload']['agent_transcript_path'])

    def test_b13_3_a_cli_return_names_the_callers_transcript(self):
        rows = self.events('bash-cli-events.jsonl')
        self.feed(rows)
        back = [r for r in self.records() if r['record'] == 'return'][0]
        self.assertEqual(back['answer_source'], rows[0]['payload']['transcript_path'])

    def test_b13_3_a_call_script_return_says_no_file_keeps_its_answer(self):
        call = load('call')
        base_fields = {'call_id': 'call-fp-1', 'session': 'fp-session', 'route': 'script', 'harness': 'gemini-cli',
                       'caller': 'parent', 'project': 'fixture', 'dispatched_at': '2026-10-18T01:00:00.000Z'}
        with mock.patch.object(sys, 'stdout'):
            call.finish(str(self.ledger), base_fields, 'served', 'none (served)', payload={}, answer='x')
        back = [r for r in self.records() if r['record'] == 'return'][0]
        self.assertEqual(back['answer_source'],
                         'unrecorded (the answer came from the program\'s standard output, which no file keeps)')

    def test_bs_1_an_inline_brief_names_the_callers_transcript(self):
        rows = self.events('foreground-events.jsonl')
        pre = json.loads(json.dumps(rows[0]))
        pre['payload']['tool_input']['prompt'] = 'Reply with one word. No file is named here.'
        self.feed([pre])
        sent = [r for r in self.records() if r['record'] == 'dispatch'][0]
        self.assertEqual(sent['brief_source'], 'inline in %s' % pre['payload']['transcript_path'])


# ---------------------------------------------------------------------------
# B13-4 to B13-8, B13-10 to B13-12: the prune
# ---------------------------------------------------------------------------

class Prune(Ledger):

    def fingerprinted_session(self):
        self.write_call('c-1')
        self.write_call('c-2', brief='Another brief.\n', answer='Another answer.\n', at='2026-10-18T01:05:00.000Z')
        return self.jsonl.read_bytes(), self.copies()

    def test_b13_4_a_record_naming_a_lost_copy_with_no_fingerprint_refuses(self):
        before_bytes, _ = self.fingerprinted_session()
        lost = self.old_copy('A brief whose copy is lost.\n')
        self.old_record('dispatch', 'c-old', 'brief_path', lost, '2026-10-18T00:59:00.000Z')
        lost.unlink()
        before_bytes, before = self.jsonl.read_bytes(), self.copies()
        code, out, done = self.prune()
        self.assertEqual(code, 5, done.stdout + done.stderr)
        self.assertEqual(self.copies(), before)
        self.assertEqual(self.jsonl.read_bytes(), before_bytes)
        self.assertIn(lost.name, json.dumps(out))

    def test_b13_5_the_ledger_file_only_gains_one_line(self):
        before, copies = self.fingerprinted_session()
        code, out, done = self.prune()
        self.assertEqual(code, 0, done.stdout + done.stderr)
        after = self.jsonl.read_bytes()
        self.assertTrue(after.startswith(before))
        self.assertEqual(after[len(before):].count(b'\n'), 1)
        self.assertEqual(out['removed'], len(copies))

    def test_b13_6_the_witness_line(self):
        _, copies = self.fingerprinted_session()
        started = datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(seconds=1)
        code, out, done = self.prune()
        ended = datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(seconds=1)
        line = rows_of(self.jsonl)[-1]
        self.assertEqual(self.writer.validate(line, ref='#/$defs/witness'), [])
        self.assertEqual((line['record'], line['event'], line['copies']), ('witness', 'prune', len(copies)))
        at = datetime.datetime.fromisoformat(line['at'].replace('Z', '+00:00'))
        self.assertTrue(started <= at <= ended, line['at'])
        self.assertNotIn('fingerprints', line, 'every copy here has its fingerprint on a record')
        self.assertFalse(self.folder.exists(), 'the copy folder is gone')

    def test_b13_7_always_and_absent_delete_nothing(self):
        before, copies = self.fingerprinted_session()
        for setting in ({'fields': 'all', 'keep_copies': 'always'}, {'fields': 'all'}):
            self.config(setting)
            code, out, done = self.prune()
            self.assertEqual((code, out['removed'], out['keep_copies']), (0, 0, 'always'), done.stderr)
            self.assertEqual(self.copies(), copies)
            self.assertEqual(self.jsonl.read_bytes(), before)

    def test_b13_7_an_unknown_setting_is_refused(self):
        self.fingerprinted_session()
        self.config({'fields': 'all', 'keep_copies': 'sometimes'})
        self.assertEqual(self.prune()[0], 1)

    def test_b13_8_an_old_ledger_is_fingerprinted_from_its_copies(self):
        brief = self.old_copy('An old brief.\n')
        answer = self.old_copy('An old answer.')
        orphan = self.old_copy('A copy no record names.\n')
        self.old_record('dispatch', 'c-old', 'brief_path', brief, '2026-10-18T01:00:00.000Z')
        self.old_record('return', 'c-old', 'answer_path', answer, '2026-10-18T01:00:30.000Z')
        expected = dict((p.name, fingerprint(p.read_bytes())) for p in (brief, answer, orphan))
        code, out, done = self.prune()
        self.assertEqual(code, 0, done.stdout + done.stderr)
        self.assertEqual(out['fingerprinted_from_copies'], 3)
        line = rows_of(self.jsonl)[-1]
        named = dict((Path(f['path']).name, f) for f in line['fingerprints'])
        self.assertEqual(sorted(named), sorted(expected))
        for name, found in named.items():
            self.assertEqual({k: found[k] for k in ('sha256', 'bytes', 'lines')}, expected[name])
        self.assertEqual(named[orphan.name]['named_by'], 'no record')
        self.assertEqual(named[brief.name]['named_by'], 'a record without a fingerprint')
        row = self.read()['calls'][0]
        self.assertEqual(row['copies']['brief']['state'], 'removed')
        self.assertEqual(row['copies']['brief']['sha256'], expected[brief.name]['sha256'])
        self.assertEqual(row['copies']['answer']['state'], 'removed')

    def test_b13_10_paired_fixtures_are_both_rejected(self):
        # The empty fixture: a session file of zero lines beside a folder of one copy.
        self.jsonl.write_bytes(b'')
        self.old_copy('A copy with no ledger lines.\n')
        code, out, done = self.prune()
        self.assertEqual(code, 3, done.stdout + done.stderr)
        self.assertEqual(len(self.copies()), 1)
        print('negative_fixture_empty: calls.py --prune on a zero-line ledger -> exit %d = expected rejection '
              'observed' % code, file=sys.stderr)
        # The likeness: records shaped right whose brief fingerprint is one character off its copy's hash.
        self.jsonl.unlink()
        shutil.rmtree(str(self.folder))
        self.write_call('c-likeness')
        rows = rows_of(self.jsonl)
        sha = rows[0]['brief_fingerprint']['sha256']
        rows[0]['brief_fingerprint']['sha256'] = sha[:-1] + ('0' if sha[-1] != '0' else '1')
        self.jsonl.write_text(''.join(json.dumps(r) + '\n' for r in rows), encoding='utf-8')
        before, copies = self.jsonl.read_bytes(), self.copies()
        code, out, done = self.prune()
        self.assertEqual(code, 5, done.stdout + done.stderr)
        self.assertEqual((self.copies(), self.jsonl.read_bytes()), (copies, before))
        print('negative_fixture_likeness: calls.py --prune with a fingerprint one character off -> exit %d = '
              'expected rejection observed' % code, file=sys.stderr)

    def test_b13_11_a_stray_file_is_refused_by_name(self):
        self.fingerprinted_session()
        (self.folder / 'notes.txt').write_text('mine', encoding='utf-8')
        before = self.copies()
        code, out, done = self.prune()
        self.assertEqual(code, 5)
        self.assertIn('notes.txt', json.dumps(out))
        self.assertEqual(self.copies(), before)

    def test_b13_12_an_old_windows_copy_is_fingerprinted_by_its_text(self):
        text = 'Line one\nLine two\n'
        copy = self.old_copy(text, raw=text.replace('\n', '\r\n').encode('utf-8'))
        self.old_record('dispatch', 'c-win', 'brief_path', copy, '2026-10-18T01:00:00.000Z')
        code, out, done = self.prune()
        self.assertEqual(code, 0, done.stdout + done.stderr)
        line = rows_of(self.jsonl)[-1]
        self.assertEqual(line['fingerprints'][0]['sha256'], hashlib.sha256(text.encode('utf-8')).hexdigest())

    def test_the_prune_takes_no_window_or_count_check(self):
        self.fingerprinted_session()
        self.assertEqual(self.prune('--since', '2026-10-18T00:00:00Z')[0], 1)


class StrayNames(Ledger):
    """The stray-name rule on its own: entries the hash check would let through."""

    def test_b13_11_a_sub_folder_is_refused_by_name(self):
        self.write_call('c-1')
        (self.folder / 'sub').mkdir()
        before = self.copies()
        code, out, done = self.prune()
        self.assertEqual(code, 5, done.stdout + done.stderr)
        self.assertIn('sub', out['refused']['paths'])
        self.assertEqual(self.copies(), before)

    def test_b13_11_a_file_hashing_to_its_name_but_not_named_as_a_copy_is_refused(self):
        self.write_call('c-1')
        data = b'not the writer\'s\n'
        stray = self.folder / ('%s.txt' % hashlib.sha256(data).hexdigest()[:16])
        stray.write_bytes(data)
        before = self.copies()
        code, out, done = self.prune()
        self.assertEqual(code, 5, done.stdout + done.stderr)
        self.assertIn(stray.name, out['refused']['paths'])
        self.assertEqual(self.copies(), before)


class OldPrompt(Ledger):
    """A record written before fingerprints that names its prompt's copy only by `moved to` under harness_payload."""

    def test_the_reader_shows_an_old_records_prompt_copy(self):
        brief = self.old_copy('An old named brief.\n')
        prompt = self.old_copy('Follow the brief file.')
        self.old_record('dispatch', 'c-old', 'brief_path', brief, '2026-10-18T01:00:00.000Z')
        rows = rows_of(self.jsonl)
        rows[-1]['harness_payload'] = {'tool_input': {'prompt': 'moved to %s' % prompt}}
        self.jsonl.write_text(''.join(json.dumps(r) + '\n' for r in rows), encoding='utf-8')
        row = self.read()['calls'][0]
        self.assertEqual(sorted(row['copies']), ['brief', 'prompt'])
        self.assertEqual(row['copies']['prompt']['state'], 'kept')
        self.assertEqual(self.prune()[0], 0)
        row = self.read()['calls'][0]
        self.assertEqual(row['copies']['prompt']['state'], 'removed')
        self.assertEqual(row['copies']['prompt']['sha256'], fingerprint(b'Follow the brief file.')['sha256'])


class OlderRecords(unittest.TestCase):
    """A record written before 0.2.7 lists neither answer_source nor the fields added since it was written, and
    still validates; a 0.2.7 record, which carries a fingerprint, must list answer_source as on or not chosen."""

    def test_a_record_from_before_fingerprints_validates(self):
        writer = load('ledger')
        record = json.loads((HERE / 'fixtures' / 'valid-dispatch-0.2.6.json').read_text(encoding='utf-8'))
        self.assertNotIn('answer_source', record['fields_on'] + record['fields_not_chosen'])
        self.assertEqual(writer.validate(record, ref='#/$defs/dispatch'), [])

    def test_a_fingerprinted_record_lacking_answer_source_fails(self):
        writer = load('ledger')
        record = json.loads((HERE / 'fixtures' / 'valid-dispatch-0.2.6.json').read_text(encoding='utf-8'))
        record['brief_fingerprint'] = 'unrecorded (no brief was passed)'
        self.assertNotEqual(writer.validate(record, ref='#/$defs/dispatch'), [])


# ---------------------------------------------------------------------------
# B13-9: the reader's copies
# ---------------------------------------------------------------------------

class Reader(Ledger):

    def test_b13_9_kept_removed_and_missing(self):
        self.write_call('c-removed', brief='Removed brief.\n', answer='Removed answer.\n', at='2026-10-18T01:00:00.000Z')
        self.assertEqual(self.prune()[0], 0)
        prune_at = rows_of(self.jsonl)[-1]['at']
        later = datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(minutes=5)
        stamp = later.strftime('%Y-%m-%dT%H:%M:%S.000Z')
        self.write_call('c-kept', brief='Kept brief.\n', answer='Kept answer.\n', at=stamp)
        self.write_call('c-missing', brief='Missing brief.\n', answer='Missing answer.\n', at=stamp)
        missing = [r for r in self.records() if r['call_id'] == 'c-missing' and r['record'] == 'dispatch'][0]
        (self.folder / ('%s.md' % missing['brief_fingerprint']['sha256'][:16])).unlink()
        rows = dict((row['call_id'], row) for row in self.read()['calls'])
        self.assertEqual(rows['c-removed']['copies']['brief']['state'], 'removed')
        self.assertEqual(rows['c-removed']['copies']['brief']['removed_at'], prune_at)
        self.assertEqual(rows['c-kept']['copies']['brief']['state'], 'kept')
        self.assertEqual(rows['c-missing']['copies']['brief']['state'], 'missing')
        self.assertNotIn('removed_at', rows['c-missing']['copies']['brief'])

    def test_b13_9_the_prune_line_is_not_in_the_span(self):
        self.write_call('c-1', at='2026-10-18T01:00:00.000Z')
        with open(self.jsonl, 'a', encoding='utf-8') as handle:
            handle.write(json.dumps({'schema': 'subagent-ledger/1', 'record': 'witness', 'event': 'prune',
                                     'session': SESSION, 'agent_id': 'unrecorded (no agent: the prune)',
                                     'call_id': 'unrecorded (not carried by prune)', 'at': '2026-10-18T03:00:00.000Z',
                                     'withheld': 0, 'copies': 0}) + '\n')
        with open(self.ledger / 'capture-errors.jsonl', 'a', encoding='utf-8') as handle:
            handle.write(json.dumps({'schema': 'subagent-ledger-error/1', 'at': '2026-10-18T02:00:00.000Z',
                                     'session': 'unrecorded (none)', 'call_id': 'unrecorded (none)',
                                     'agent_id': 'unrecorded (none)', 'record': 'dispatch', 'harness': 'x',
                                     'event': 'x', 'stage': 'payload', 'reason': 'x', 'payload_keys': []}) + '\n')
        reasons = [a['reason'] for a in self.read()['absences']]
        self.assertNotIn('unattributed capture error', reasons)


if __name__ == '__main__':
    unittest.main()
