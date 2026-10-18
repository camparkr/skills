"""Tests for the subagent ledger's writer, `skill/scripts/ledger.py`, and its record schema.

Controls K-3 to K-9 each run twice: once on the writer as built, where the check must pass, and once
with one part of the writer switched off by the test, where the same check must fail. A control that
cannot fail proves nothing. The switches live here, as patches on the writer's private functions,
and never in the writer's interface.

No test writes to a real ledger: every write goes to a folder under the system's temporary folder,
and SUBAGENT_LEDGER_DIR is set to it for the run.

Run from the skill's folder:  python3 -m unittest discover -s tests
"""

import contextlib
import copy
import importlib.util
import io
import json
import os
import re
import stat
import subprocess
import sys
import tempfile
import textwrap
import unittest
from pathlib import Path
from unittest import mock

HERE = Path(__file__).resolve().parent
SCRIPTS = HERE.parent / 'skill' / 'scripts'
FIXTURES = HERE / 'fixtures'
LEDGER_PY = SCRIPTS / 'ledger.py'
SCHEMA_PATH = SCRIPTS / 'record.schema.json'


def load_writer():
    spec = importlib.util.spec_from_file_location('subagent_ledger_writer_under_test', LEDGER_PY)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


ledger = load_writer()

UNRECORDED = re.compile(r'^unrecorded \(.+\)$')
PLANTED = 'planted-value-1234567890'


def lines_of(path):
    path = Path(path)
    if not path.is_file():
        return []
    return [json.loads(line) for line in path.read_text(encoding='utf-8').splitlines() if line.strip()]


def fixture(name):
    return json.loads((FIXTURES / name).read_text(encoding='utf-8'))


class Folder(unittest.TestCase):
    """Each test gets its own ledger folder, and SUBAGENT_LEDGER_DIR names it."""

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix='subagent-ledger-test-'))
        self.folder = self.tmp / 'ledger'
        self.folder.mkdir()
        patcher = mock.patch.dict(os.environ, {'SUBAGENT_LEDGER_DIR': str(self.folder)})
        patcher.start()
        self.addCleanup(patcher.stop)
        self.addCleanup(self._every_line_validates)
        self.addCleanup(self._remove)

    def _remove(self):
        for path in self.tmp.rglob('*'):
            try:
                path.chmod(0o700 if path.is_dir() else 0o600)
            except OSError:
                pass
        import shutil
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _every_line_validates(self):
        """Every line any test leaves in a ledger file validates against the real schema."""
        if getattr(self, 'skip_line_check', False):
            return
        schema = ledger.load_schema()
        for path in self.tmp.rglob('*.jsonl'):
            for n, record in enumerate(lines_of(path)):
                problems = ledger.validate(record, schema)
                self.assertEqual(problems, [], '%s line %d does not validate: %s' % (path, n + 1, problems))

    def config(self, fields):
        (self.folder / 'config.json').write_text(json.dumps({'fields': fields}), encoding='utf-8')

    def session_lines(self, session='s-0001'):
        return lines_of(self.folder / ('%s.jsonl' % session))

    def errors(self):
        return lines_of(self.folder / 'capture-errors.jsonl')

    def a_dispatch(self, **extra):
        fields = dict(call_id='call-0001', session='s-0001', harness='fixture-harness',
                      route='script', model_requested='a-model', brief='a bounded question')
        fields.update(extra)
        return ledger.dispatch(**fields)


# ---------------------------------------------------------------------------
# K-3: a record that does not validate is not written; an error line says why
# ---------------------------------------------------------------------------

class K3Validation(Folder):

    def plant(self):
        bad_outcome = self.a_dispatch(outcome='ok')
        no_call_id = ledger.dispatch(session='s-0001', harness='fixture-harness', route='script',
                                     brief='a bounded question')
        return bad_outcome, no_call_id

    def test_k3_both_rejected_at_validate(self):
        bad_outcome, no_call_id = self.plant()
        self.assertFalse(bad_outcome.ok)
        self.assertFalse(no_call_id.ok)
        self.assertEqual(self.session_lines(), [], 'a rejected record reached the ledger')
        errors = self.errors()
        self.assertEqual([e['stage'] for e in errors], ['validate', 'validate'], errors)
        self.assertEqual(errors[0]['call_id'], 'call-0001')
        self.assertEqual(errors[0]['session'], 's-0001')
        self.assertIn('outcome', errors[0]['reason'])
        self.assertRegex(errors[1]['call_id'], UNRECORDED)
        self.assertIn('no call_id', errors[1]['reason'])

    def test_k3_control_validation_switched_off_writes_both(self):
        self.skip_line_check = True
        with mock.patch.object(ledger, '_validate_record', lambda record, kind: []):
            bad_outcome, no_call_id = self.plant()
        written = self.session_lines()
        self.assertEqual(len(written), 2, 'with validation off both planted records should land')
        self.assertEqual(written[0]['outcome'], 'ok')
        self.assertNotIn('call_id', written[1])


# ---------------------------------------------------------------------------
# K-4: a credential in the environment never reaches the ledger folder
# ---------------------------------------------------------------------------

class K4Scrub(Folder):

    def plant(self):
        with mock.patch.dict(os.environ, {'FAKE_API_KEY': PLANTED}):
            return self.a_dispatch(brief='Use the key %s to call the service.' % PLANTED)

    def grep(self):
        done = subprocess.run(['grep', '-r', 'planted-value', str(self.folder)],
                              capture_output=True, text=True)
        return done.stdout

    def test_k4_the_value_is_nowhere_and_counted(self):
        result = self.plant()
        self.assertTrue(result.ok, result.error)
        self.assertEqual(self.grep(), '')
        record = self.session_lines()[0]
        self.assertEqual(record['withheld'], 1)

    def test_k4_control_scrub_switched_off_shows_the_value(self):
        with mock.patch.object(ledger, '_scrub', lambda value, secrets, shapes: (value, 0)):
            result = self.plant()
        self.assertTrue(result.ok, result.error)
        self.assertIn(PLANTED, self.grep())

    def test_credential_shape_is_withheld(self):
        shaped = 'sk-ant-' + 'A' * 30
        result = self.a_dispatch(model_requested='m', harness_payload={'note': 'header %s' % shaped})
        self.assertTrue(result.ok, result.error)
        self.assertEqual(self.grep(), '')
        text = (self.folder / 's-0001.jsonl').read_text(encoding='utf-8')
        self.assertNotIn(shaped, text)


# ---------------------------------------------------------------------------
# K-5: the field-list rule
# ---------------------------------------------------------------------------

def without_field_rules(schema):
    out = copy.deepcopy(schema)
    out['$defs']['callRecord'].pop('allOf')
    return out


class K5FieldLists(unittest.TestCase):

    def test_k5_a_field_off_and_unlisted_is_rejected(self):
        record = fixture('invalid-field-off-unlisted.json')
        problems = ledger.validate(record, ledger.load_schema())
        self.assertTrue(problems)
        self.assertTrue(any('route' in p for p in problems), problems)

    def test_k5_control_without_the_rule_it_is_accepted(self):
        record = fixture('invalid-field-off-unlisted.json')
        self.assertEqual(ledger.validate(record, without_field_rules(ledger.load_schema())), [])

    def test_a_field_on_and_absent_is_rejected(self):
        record = fixture('invalid-field-on-absent.json')
        self.assertTrue(ledger.validate(record, ledger.load_schema()))

    def test_a_field_carried_and_named_not_chosen_is_rejected(self):
        record = fixture('valid-dispatch.json')
        record['route'] = 'script'
        self.assertTrue(ledger.validate(record, ledger.load_schema()))


# ---------------------------------------------------------------------------
# K-6: two processes writing to one session file
# ---------------------------------------------------------------------------

WORKER = textwrap.dedent('''
    import contextlib, importlib.util, sys
    spec = importlib.util.spec_from_file_location('w', sys.argv[1])
    ledger = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(ledger)
    if sys.argv[4] == 'unlocked':
        ledger._lock = lambda handle: contextlib.nullcontext()
    payload = 'x' * 6000
    for n in range(int(sys.argv[3])):
        result = ledger.witness(event='Worker-%s-%s' % (sys.argv[2], payload), session='s-0001',
                                agent_id='agent-%s-%d' % (sys.argv[2], n),
                                call_id='call-%s-%d' % (sys.argv[2], n))
        if not result.ok:
            print(result.error, file=sys.stderr)
            sys.exit(1)
''')


class K6Lock(Folder):

    def race(self, mode):
        worker = self.tmp / 'worker.py'
        worker.write_text(WORKER, encoding='utf-8')
        env = dict(os.environ, SUBAGENT_LEDGER_DIR=str(self.folder), PYTHONDONTWRITEBYTECODE='1')
        procs = [subprocess.Popen([sys.executable, str(worker), str(LEDGER_PY), tag, '1000', mode],
                                  env=env, stderr=subprocess.PIPE, text=True)
                 for tag in ('a', 'b')]
        for proc in procs:
            _out, err = proc.communicate(timeout=600)
            self.assertEqual(proc.returncode, 0, err)
        raw = (self.folder / 's-0001.jsonl').read_text(encoding='utf-8').split('\n')
        raw = [line for line in raw if line]
        parsed = 0
        for line in raw:
            try:
                json.loads(line)
                parsed += 1
            except ValueError:
                pass
        return len(raw), parsed

    def test_k6_two_thousand_lines_each_parsing(self):
        count, parsed = self.race('locked')
        self.assertEqual((count, parsed), (2000, 2000))

    def test_k6_control_without_the_lock_reported(self):
        """Interleaving is not certain to show without the lock, so the result is printed, not asserted."""
        self.skip_line_check = True
        count, parsed = self.race('unlocked')
        print('\nK6-UNLOCKED lines=%d parsing=%d' % (count, parsed), file=sys.stderr)


# ---------------------------------------------------------------------------
# K-7: a write that fails is an error line, never an exception
# ---------------------------------------------------------------------------

class K7WriteFails(Folder):

    def test_k7_read_only_ledger_file(self):
        first = self.a_dispatch()
        self.assertTrue(first.ok, first.error)
        target = self.folder / 's-0001.jsonl'
        target.chmod(stat.S_IRUSR)
        try:
            result = self.a_dispatch(call_id='call-0002')
        finally:
            target.chmod(0o600)
        self.assertFalse(result.ok)
        self.assertEqual(len(self.session_lines()), 1)
        error = self.errors()[-1]
        self.assertEqual(error['stage'], 'write')
        self.assertEqual(error['session'], 's-0001')
        self.assertEqual(error['call_id'], 'call-0002')
        self.assertIn('ermission', error['reason'])

    def test_k7_control_the_writers_guard_removed_lets_the_exception_through(self):
        """The writer's own guard, removed in a scratch copy of ledger.py: the exception reaches the caller."""
        import shutil
        scratch = self.tmp / 'scratch-scripts'
        shutil.copytree(SCRIPTS, scratch, ignore=shutil.ignore_patterns('__pycache__'))
        source = (scratch / 'ledger.py').read_text(encoding='utf-8')
        guard = ("    except Exception as exc:\n"
                 "        return _error_line(folder, stage, '%s: %s' % (type(exc).__name__, exc), held, keys)\n")
        self.assertEqual(source.count(guard), 1, 'the writer\'s guard was not found to remove')
        (scratch / 'ledger.py').write_text(source.replace(guard, "    except Exception:\n        raise\n"),
                                           encoding='utf-8')
        spec = importlib.util.spec_from_file_location('unguarded_writer', scratch / 'ledger.py')
        unguarded = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(unguarded)
        first = unguarded.dispatch(call_id='call-0001', session='s-0001', route='script', brief='b')
        self.assertTrue(first.ok, first.error)
        target = self.folder / 's-0001.jsonl'
        target.chmod(stat.S_IRUSR)
        try:
            with self.assertRaises(PermissionError):
                unguarded.dispatch(call_id='call-0002', session='s-0001', route='script', brief='b')
        finally:
            target.chmod(0o600)

    def test_an_error_line_that_cannot_be_written_goes_to_stderr(self):
        self.skip_line_check = True
        self.folder.chmod(stat.S_IRUSR | stat.S_IXUSR)
        err = io.StringIO()
        try:
            with contextlib.redirect_stderr(err):
                result = self.a_dispatch(outcome='ok')
        finally:
            self.folder.chmod(0o700)
        self.assertFalse(result.ok)
        self.assertIn('subagent-ledger-error/1', err.getvalue())

    def test_error_lines_carry_key_names_never_values(self):
        with mock.patch.dict(os.environ, {'FAKE_API_KEY': PLANTED}):
            self.a_dispatch(outcome='ok', model_requested='visible-value-xyz', brief='brief %s' % PLANTED)
        error = self.errors()[-1]
        text = json.dumps(error)
        self.assertNotIn('visible-value-xyz', text)
        self.assertNotIn(PLANTED, text)
        self.assertIn('model_requested', error['payload_keys'])


# ---------------------------------------------------------------------------
# K-8: a record whose session cannot be read
# ---------------------------------------------------------------------------

class K8Unattributed(Folder):

    def plant(self):
        return ledger.dispatch(call_id='call-0001', harness='fixture-harness', route='script',
                               brief='a bounded question with no session')

    def test_k8_lands_in_unattributed(self):
        result = self.plant()
        self.assertTrue(result.ok, result.error)
        records = lines_of(self.folder / 'unattributed.jsonl')
        self.assertEqual(len(records), 1)
        self.assertRegex(records[0]['session'], UNRECORDED)
        briefs = list((self.folder / 'unattributed').glob('*.md'))
        self.assertEqual(len(briefs), 1)
        others = [p.name for p in self.folder.glob('*.jsonl') if p.name != 'unattributed.jsonl']
        self.assertEqual(others, [], 'a file was named for an unrecorded session')

    def test_k8_control_routing_switched_off_names_a_file_from_the_session(self):
        self.skip_line_check = True
        naive_file = lambda folder, session: Path(folder) / ('%s.jsonl' % session)
        naive_dir = lambda folder, session: Path(folder) / session
        with mock.patch.object(ledger, '_session_file', naive_file), \
                mock.patch.object(ledger, '_copy_dir', naive_dir):
            self.plant()
        named = [p.name for p in self.folder.glob('unrecorded*.jsonl')]
        self.assertEqual(len(named), 1, list(self.folder.iterdir()))


# ---------------------------------------------------------------------------
# K-9: the validator refuses a keyword it does not implement
# ---------------------------------------------------------------------------

def keywords_used(schema):
    """Every keyword a schema uses, walking only into places that hold subschemas."""
    found = set()

    def walk(node):
        if not isinstance(node, dict):
            return
        for key, value in node.items():
            found.add(key)
            if key in ('properties', '$defs'):
                for sub in value.values():
                    walk(sub)
            elif key in ('allOf', 'anyOf', 'oneOf'):
                for sub in value:
                    walk(sub)
            elif key in ('items', 'contains', 'not', 'if', 'then', 'else', 'additionalProperties'):
                walk(value)
    walk(schema)
    return found


class K9Validator(unittest.TestCase):

    def planted(self):
        schema = copy.deepcopy(ledger.load_schema())
        schema['$defs']['callRecord']['dependentRequired'] = {'model': ['tokens']}
        return schema

    def test_every_keyword_the_schema_uses_is_implemented(self):
        used = keywords_used(ledger.load_schema())
        known = set(ledger.IMPLEMENTED_KEYWORDS) | set(ledger.ANNOTATION_KEYWORDS)
        self.assertEqual(sorted(used - known), [])
        print('\nK9-KEYWORDS ' + json.dumps(sorted(used)), file=sys.stderr)

    def test_k9_the_planted_keyword_is_refused_loudly(self):
        self.assertIn('dependentRequired', keywords_used(self.planted()))
        with self.assertRaises(ledger.UnknownKeyword) as caught:
            ledger.validate(fixture('valid-dispatch.json'), self.planted())
        self.assertIn('dependentRequired', str(caught.exception))

    def test_k9_control_a_validator_ignoring_unknown_keywords_passes_it(self):
        with mock.patch.object(ledger, '_check_keywords', lambda schema: None):
            self.assertEqual(ledger.validate(fixture('valid-dispatch.json'), self.planted()), [])


# ---------------------------------------------------------------------------
# A pattern's `$` keeps its JSON Schema meaning: the end of the text, never before a final newline
# ---------------------------------------------------------------------------

# Each pattern in the record schema, by where it sits, with a value it accepts.
SCHEMA_PATTERNS = [
    ('#/$defs/unrecorded', 'unrecorded (x)'),
    ('#/$defs/time', '2026-10-18T04:00:00Z'),
    ('#/$defs/session/anyOf/0', 'b5label-0000-4000-8000-000000000001'),
    ('#/$defs/fingerprint/properties/sha256', 'a' * 64),
    ('#/$defs/witness/properties/fingerprints/items/properties/sha256', '0' * 64),
]


class PatternEnd(unittest.TestCase):
    """JSON Schema patterns follow ECMA-262, where `$` without the multiline flag matches only at
    the end of the text. Python's `$` also matches just before a final newline, so a value ending
    in a newline passed every pattern in the schema before the validator translated them."""

    def problems(self, pattern, value):
        return ledger.validate(value, {'type': 'string', 'pattern': pattern})

    def test_every_schema_pattern_is_covered(self):
        schema = ledger.load_schema()
        found = []

        def walk(node, at):
            if isinstance(node, dict):
                for key, sub in node.items():
                    if key == 'pattern':
                        found.append(at)
                    walk(sub, at + '/' + key)
            elif isinstance(node, list):
                for n, sub in enumerate(node):
                    walk(sub, '%s/%d' % (at, n))
        walk(schema, '#')
        self.assertEqual(sorted(found), sorted(ref for ref, _ in SCHEMA_PATTERNS))

    def test_each_schema_pattern_accepts_its_value_and_refuses_it_with_a_newline(self):
        for ref, value in SCHEMA_PATTERNS:
            node = ledger.load_schema()
            for part in ref[2:].split('/'):
                node = node[int(part)] if isinstance(node, list) else node[part]
            with self.subTest(ref=ref):
                self.assertEqual(ledger.validate(value, node), [])
                self.assertTrue(ledger.validate(value + '\n', node))

    def test_an_escaped_dollar_stays_a_literal_dollar(self):
        self.assertEqual(self.problems(r'^cost \$$', 'cost $'), [])
        self.assertTrue(self.problems(r'^cost \$$', 'cost $\n'))
        self.assertTrue(self.problems(r'^cost \$$', 'cost '))

    def test_a_dollar_inside_a_class_stays_a_literal_dollar(self):
        self.assertEqual(self.problems(r'^[$x]+$', '$x$'), [])
        self.assertTrue(self.problems(r'^[$x]+$', '$x$\n'))
        self.assertEqual(self.problems(r'^[\]$]$', '$'), [])
        self.assertEqual(self.problems(r'^[\]$]$', ']'), [])
        self.assertTrue(self.problems(r'^[\]$]$', ']\n'))

    def test_an_escaped_backslash_before_a_dollar_leaves_the_dollar_an_end(self):
        self.assertEqual(self.problems(r'^a\\$', 'a\\'), [])
        self.assertTrue(self.problems(r'^a\\$', 'a\\\n'))


# ---------------------------------------------------------------------------
# The schema against the fixtures, by the writer's validator and, where present, by jsonschema
# ---------------------------------------------------------------------------

VALID = ['valid-dispatch.json', 'valid-return.json', 'valid-return-failed.json',
         'valid-witness.json', 'valid-error.json']
INVALID = ['invalid-outcome-ok.json', 'invalid-no-call-id.json', 'invalid-field-off-unlisted.json',
           'invalid-return-no-outcome.json', 'invalid-field-on-absent.json']


class SchemaAgainstFixtures(unittest.TestCase):

    def test_valid_fixtures_validate(self):
        for name in VALID:
            with self.subTest(name=name):
                self.assertEqual(ledger.validate(fixture(name), ledger.load_schema()), [])

    def test_invalid_fixtures_are_rejected(self):
        for name in INVALID:
            with self.subTest(name=name):
                self.assertTrue(ledger.validate(fixture(name), ledger.load_schema()))

    def test_the_selectable_fields_match_the_writer(self):
        names = ledger.load_schema()['$defs']['selectableName']['enum']
        self.assertEqual(list(ledger.SELECTABLE), names)
        self.assertEqual(len(names), 29)  # 0.2.7 adds answer_source
        self.assertEqual(list(ledger.DEFAULT_FIELDS),
                         ['model_requested', 'model', 'tokens', 'cost', 'outcome_reason'])

    def test_with_jsonschema_where_it_is_installed(self):
        try:
            import jsonschema
        except ImportError:
            self.skipTest('the jsonschema package is not installed here, so the fixtures are checked '
                          'by the writer\'s own validator only')
        schema = ledger.load_schema()
        jsonschema.Draft202012Validator.check_schema(schema)
        validator = jsonschema.Draft202012Validator(schema)
        for name in VALID:
            self.assertEqual(list(validator.iter_errors(fixture(name))), [], name)
        for name in INVALID:
            self.assertTrue(list(validator.iter_errors(fixture(name))), name)


# ---------------------------------------------------------------------------
# The setting: which fields a record carries (SI-7)
# ---------------------------------------------------------------------------

FRAME = ['call_id', 'agent_id', 'session', 'dispatched_at', 'returned_at', 'outcome']
STRUCTURAL = ['schema', 'record', 'fields_on', 'fields_not_chosen', 'withheld']


class Setting(Folder):

    def one_call(self):
        sent = self.a_dispatch()
        self.assertTrue(sent.ok, sent.error)
        back = ledger.ret('call-0001', session='s-0001', outcome='served', model='a-model',
                          answer='the answer', harness='fixture-harness', route='script')
        self.assertTrue(back.ok, back.error)
        return self.session_lines()

    def test_frame(self):
        self.config('frame')
        for record in self.one_call():
            with self.subTest(record=record['record']):
                # 0.2.7: the fingerprint of the record's copied text is written whatever the setting.
                fingerprint = ['brief_fingerprint' if record['record'] == 'dispatch' else 'answer_fingerprint']
                self.assertEqual(sorted(record), sorted(FRAME + STRUCTURAL + fingerprint))
                self.assertEqual(record['fields_on'], [])
                self.assertEqual(record['fields_not_chosen'], list(ledger.SELECTABLE))

    def test_all(self):
        self.config('all')
        for record in self.one_call():
            with self.subTest(record=record['record']):
                for name in ledger.SELECTABLE:
                    self.assertIn(name, record)
                    value = record[name]
                    self.assertTrue(value not in (None, '', 0, [], {}), (name, value))
                self.assertEqual(record['fields_not_chosen'], [])
                self.assertEqual(record['fields_on'], list(ledger.SELECTABLE))

    def test_default_when_no_config(self):
        self.assertFalse((self.folder / 'config.json').exists())
        for record in self.one_call():
            with self.subTest(record=record['record']):
                self.assertEqual(record['fields_on'], list(ledger.DEFAULT_FIELDS))
                carried = [name for name in ledger.SELECTABLE if name in record]
                self.assertEqual(carried, list(ledger.DEFAULT_FIELDS))

    def test_default_by_name(self):
        self.config('default')
        for record in self.one_call():
            self.assertEqual(record['fields_on'], list(ledger.DEFAULT_FIELDS))

    def test_a_list(self):
        self.config(['route', 'harness'])
        for record in self.one_call():
            self.assertEqual(record['fields_on'], ['route', 'harness'])
            self.assertEqual(record['route'], 'script')

    def test_an_unknown_name_writes_an_error_and_no_record(self):
        self.config(['route', 'no_such_field'])
        result = self.a_dispatch()
        self.assertFalse(result.ok)
        self.assertEqual(self.session_lines(), [])
        error = self.errors()[-1]
        self.assertEqual(error['stage'], 'setting')
        self.assertIn('no_such_field', error['reason'])

    def test_return_copies_dispatched_at_and_keeps_the_answer_out(self):
        self.config('all')
        dispatch, back = self.one_call()
        self.assertEqual(back['dispatched_at'], dispatch['dispatched_at'])
        self.assertNotIn('the answer', json.dumps(back))
        answer = Path(back['answer_path'])
        if not answer.is_absolute():
            answer = self.folder.parent / answer
        self.assertTrue(answer.is_file() or (self.folder / 's-0001').is_dir())
        stored = list((self.folder / 's-0001').glob('*.md'))
        self.assertEqual(sorted(p.read_text(encoding='utf-8') for p in stored),
                         sorted(['a bounded question', 'the answer']))

    def test_brief_named_by_content_hash(self):
        import hashlib
        self.a_dispatch()
        name = hashlib.sha256('a bounded question'.encode('utf-8')).hexdigest()[:16] + '.md'
        self.assertTrue((self.folder / 's-0001' / name).is_file())


# ---------------------------------------------------------------------------
# Witness lines, error lines, the folder order and the command
# ---------------------------------------------------------------------------

class Lines(Folder):

    def test_witness_line(self):
        result = ledger.witness(event='SubagentStart', session='s-0001', agent_id='a-1')
        self.assertTrue(result.ok, result.error)
        line = self.session_lines()[0]
        self.assertEqual(line['record'], 'witness')
        self.assertRegex(line['call_id'], UNRECORDED)
        self.assertNotIn('fields_on', line)

    def test_error_line_by_hand(self):
        result = ledger.error(stage='payload', reason='x' * 1000, session='s-0001',
                              event='PreToolUse', payload_keys=['a', 'b'])
        self.assertTrue(result.ok, result.error)
        line = self.errors()[-1]
        self.assertEqual(len(line['reason']), 400)
        self.assertEqual(line['record'], 'unknown')

    def test_folder_order(self):
        explicit = self.tmp / 'explicit'
        ledger.witness(event='E', session='s-0001', agent_id='a', ledger=str(explicit))
        self.assertEqual(len(lines_of(explicit / 's-0001.jsonl')), 1)
        ledger.witness(event='E', session='s-0001', agent_id='a')
        self.assertEqual(len(self.session_lines()), 1)
        repo = self.tmp / 'repo'
        (repo / '.git').mkdir(parents=True)
        (repo / 'sub').mkdir()
        with mock.patch.dict(os.environ, {}, clear=False):
            os.environ.pop('SUBAGENT_LEDGER_DIR', None)
            with mock.patch.object(ledger.os, 'getcwd', lambda: str(repo / 'sub')):
                self.assertEqual(Path(ledger.ledger_folder()), repo / '.subagent-ledger')

    def test_the_writer_never_raises(self):
        result = ledger.dispatch(call_id='c', session='s-0001', harness_payload={'x': object()})
        self.assertFalse(result.ok)
        self.assertEqual(self.errors()[-1]['stage'], 'payload')

    def test_the_rework_classes_exist(self):
        """caller_time_limit and empty_answer are classes of reasons.json and the schema."""
        classes = json.loads((SCRIPTS / 'reasons.json').read_text(encoding='utf-8'))['classes']
        schema_classes = ledger.load_schema()['$defs']['reasonClass']['enum']
        for name in ('caller_time_limit', 'empty_answer'):
            self.assertIn(name, classes)
            self.assertIn(name, schema_classes)
        record = fixture('valid-return.json')
        record.update(outcome='empty', outcome_reason={'class': 'empty_answer', 'text': 'the answer was empty'})
        self.assertEqual(ledger.validate(record, ledger.load_schema()), [])

    def test_reason_classes(self):
        cases = [('Not logged in · Please run /login', 'not_signed_in'),
                 ('Perplexity returned 429. Too Many Requests', 'rate_limited'),
                 ("You've hit your usage limit", 'usage_limit'),
                 ('ANTHROPIC_API_KEY is not set.', 'missing_key'),
                 ('something unforeseen', 'other')]
        for text, expected in cases:
            with self.subTest(text=text):
                reason = ledger.reason_for('claude-research', text)
                self.assertEqual(reason['class'], expected)
                self.assertEqual(reason['text'], text)
        self.assertEqual(ledger.reason_for('codex', 'nothing', fallback='truncated')['class'], 'truncated')

    def test_command_reads_stdin_and_prints_nothing(self):
        payload = json.dumps({'call_id': 'cmd-1', 'session': 's-0001', 'route': 'subagent',
                              'brief': 'from the command'})
        done = subprocess.run([sys.executable, str(LEDGER_PY), 'dispatch', '--ledger', str(self.folder)],
                              input=payload, capture_output=True, text=True,
                              env=dict(os.environ, PYTHONDONTWRITEBYTECODE='1'))
        self.assertEqual(done.returncode, 0, done.stderr)
        self.assertEqual(done.stdout, '')
        self.assertEqual(self.session_lines()[0]['call_id'], 'cmd-1')
        bad = subprocess.run([sys.executable, str(LEDGER_PY), 'dispatch', '--ledger', str(self.folder)],
                             input='not json', capture_output=True, text=True,
                             env=dict(os.environ, PYTHONDONTWRITEBYTECODE='1'))
        self.assertEqual(bad.returncode, 0)
        self.assertEqual(self.errors()[-1]['stage'], 'payload')


if __name__ == '__main__':
    unittest.main()
