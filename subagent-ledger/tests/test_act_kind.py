"""Controls for the kind of act on a dispatch record, the user's answer, and the label line's new shape.

The public skill's controls:

  * each capture writes `act_kind` on the dispatch record. It reads the brief's kind at the
    frontmatter key `config.json` names, translates it through the `kind_names` file, and writes one
    of the plain names in kinds.json, or `unrecorded (<reason>)` saying why.
    A value that maps to no kind is unrecorded, logged as an error line at stage `setting`, and the
    record is still written.
  * a dispatch of the kind `user-decision` carries `user_answer`, read from the caller's
    transcript: an answered question call between the caller's previous dispatch and this one gives
    `answered_first: yes`; none gives `not found`. The brief's own statement goes in `agent_record`
    only. The call goes out unchanged in every case.
  * the label line's shape, and the reader's `labels`.

The kind values used here are this file's own; no workspace's values appear in a public file.

Each control has a half that runs on the code as built and must pass, and a half that switches one part
off, by a patch in this file, and shows the fault. Before the code existed every test here failed.

Run from the skill's folder:  python3 -m unittest discover -s tests
"""

import contextlib
import importlib.util
import io
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
FIXTURES = HERE / 'fixtures'
KINDS_FILE = SCRIPTS / 'kinds.json'

KIND_NAMES = ['verdict-or-review', 'deliberation', 'build', 'inquiry', 'archiving', 'transfer', 'conversion',
              'user-decision']
# This file's own values for each kind, standing in for whatever a workspace's briefs carry.
VALUES = dict((name, 'value-for-%s' % name) for name in KIND_NAMES)
NO_KIND = 'unrecorded (the brief names no kind; no triage ran)'
NO_KIND_CLI = 'unrecorded (the command names no kind; no triage ran)'
NO_AGENT = 'unrecorded (no agent: script call)'
NOT_DECISION = 'none (not a user decision)'
SESSION = '6449f88e-c7fa-40ca-8065-7558230a320d'


def load(path, name):
    if not Path(path).is_file():
        raise AssertionError('%s does not exist yet: the code this control tests is not built' % Path(path).name)
    if str(SCRIPTS) not in sys.path:
        sys.path.insert(0, str(SCRIPTS))
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def lines_of(path):
    path = Path(path)
    if not path.is_file():
        return []
    return [json.loads(line) for line in path.read_text(encoding='utf-8').splitlines() if line.strip()]


def brief_text(kind=None, statement=None):
    meta = ['---', 'type: brief', 'meta:']
    if kind is not None:
        meta.append('  kind: %s' % kind)
    if statement is not None:
        meta.append('  answer: "%s"' % statement)
    meta.append('  task: 2026-01-01-example-task')
    return '\n'.join(meta + ['---', '', 'Reply with the word received and nothing else.', ''])


class KindWorld(unittest.TestCase):
    """A ledger folder with every field on, the frontmatter map, and a kind map with this file's values."""

    mapped = True

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix='act-kind-test-'))
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.ledger = self.tmp / 'ledger'
        self.config = self.tmp / 'config'
        self.work = self.tmp / 'work'
        self.tasks = self.tmp / 'tasks'
        self.home = self.tmp / 'codex-home'
        for folder in (self.ledger, self.config, self.work, self.tasks, self.home):
            folder.mkdir()
        env = {'SUBAGENT_LEDGER_DIR': str(self.ledger), 'CLAUDE_CONFIG_DIR': str(self.config),
               'CODEX_HOME': str(self.home), 'OPENAI_API_KEY': '', 'XDG_DATA_HOME': str(self.tmp / 'data')}
        for name in ('ANTHROPIC_API_KEY', 'CLAUDE_CODE_OAUTH_TOKEN', 'ANTHROPIC_AUTH_TOKEN',
                     'CLAUDE_CODE_USE_BEDROCK', 'CLAUDE_CODE_USE_VERTEX'):
            env[name] = ''
        patcher = mock.patch.dict(os.environ, env)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.write_config(self.mapped)
        self.capture = load(SCRIPTS / 'capture_claude_code.py', 'capture_claude_code_kind_%d' % id(self))

    def write_config(self, mapped):
        config = {'fields': 'all', 'frontmatter': {'act_kind': 'meta.kind', 'user_answer': 'meta.answer',
                                                   'task': 'meta.task'}}
        if mapped:
            (self.ledger / 'kind-map.json').write_text(json.dumps({'kinds': dict(
                (name, {'value': value}) for name, value in VALUES.items())}), encoding='utf-8')
            config['kind_names'] = 'kind-map.json'
        (self.ledger / 'config.json').write_text(json.dumps(config), encoding='utf-8')

    def fill(self, text):
        return (text.replace('${CONFIG}', str(self.config)).replace('${WORK}', str(self.work))
                .replace('${TASKROOT}', str(self.tasks)).replace('${CODEX_HOME}', str(self.home)))

    def events(self, folder, name):
        return [json.loads(self.fill(line)) for line in
                (FIXTURES / folder / name).read_text(encoding='utf-8').splitlines() if line.strip()]

    def records(self):
        found = []
        for path in sorted(self.ledger.glob('*.jsonl')):
            if path.name != 'capture-errors.jsonl':
                found.extend(lines_of(path))
        return found

    def dispatches(self):
        return [r for r in self.records() if r['record'] == 'dispatch']

    def errors(self):
        return lines_of(self.ledger / 'capture-errors.jsonl')

    def pre_agent(self, brief, tool_use_id='toolu_kind_0001', transcript=None):
        """One Claude Code PreToolUse on Agent naming brief.md, from the foreground fixture's first payload."""
        (self.work / 'brief.md').write_text(brief, encoding='utf-8')
        payload = dict(self.events('claude-code', 'foreground-events.jsonl')[0]['payload'])
        payload['tool_use_id'] = tool_use_id
        if transcript is not None:
            payload['transcript_path'] = str(transcript)
        return payload

    def dispatch_kind(self, brief):
        self.capture.handle('PreToolUse', json.dumps(self.pre_agent(brief)), None)
        return self.dispatches()[-1]


# ---------------------------------------------------------------------------
# kinds.json and the schema
# ---------------------------------------------------------------------------

class TheKinds(unittest.TestCase):

    def test_kinds_json_holds_the_eight_names_each_with_a_test(self):
        if not KINDS_FILE.is_file():
            raise AssertionError('kinds.json does not exist yet: the code this control tests is not built')
        data = json.loads(KINDS_FILE.read_text(encoding='utf-8'))
        self.assertEqual([k['name'] for k in data['kinds']], KIND_NAMES)
        for kind in data['kinds']:
            self.assertEqual(set(kind), {'name', 'test'})
            self.assertTrue(kind['test'].startswith('Does the call ') and kind['test'].endswith('?'), kind)

    def test_the_schema_takes_exactly_the_kinds_json_names(self):
        writer = load(SCRIPTS / 'ledger.py', 'ledger_kinds_%d' % id(self))
        schema = writer.load_schema()
        prop = schema['$defs']['callRecord']['properties'].get('act_kind')
        if prop is None:
            raise AssertionError('the schema has no act_kind field yet')
        data = json.loads(KINDS_FILE.read_text(encoding='utf-8'))
        names = [k['name'] for k in data['kinds']]
        enum = [form['enum'] for form in schema['$defs'][prop['$ref'].split('/')[-1]]['anyOf'] if 'enum' in form]
        self.assertEqual(enum, [names])
        self.assertNotIn('characteristic', schema['$defs']['selectableName']['enum'])
        on = writer.SELECTABLE
        self.assertEqual(on.index('user_answer'), on.index('act_kind') + 1)

    def test_switched_off_a_value_outside_the_kinds_is_rejected(self):
        writer = load(SCRIPTS / 'ledger.py', 'ledger_kinds_off_%d' % id(self))
        if 'act_kind' not in writer.SELECTABLE:
            raise AssertionError('ledger.py has no act_kind field yet')
        schema = writer.load_schema()
        record = json.loads((FIXTURES / 'valid-dispatch.json').read_text(encoding='utf-8'))
        for name in ('act_kind', 'user_answer'):
            if name in record['fields_not_chosen']:
                record['fields_not_chosen'].remove(name)
                record['fields_on'].append(name)
        record['fields_on'] = [n for n in writer.SELECTABLE if n in record['fields_on']]
        record['act_kind'] = 'build'
        record['user_answer'] = NOT_DECISION
        self.assertEqual(writer.validate(record, schema, ref='#/$defs/dispatch'), [])
        record['act_kind'] = 'craft'
        self.assertTrue(writer.validate(record, schema, ref='#/$defs/dispatch'))


# ---------------------------------------------------------------------------
# The kind on the record
# ---------------------------------------------------------------------------

class CR7Kind(KindWorld):

    def test_c_r_7_a_mapped_value_gives_its_plain_name(self):
        self.assertEqual(self.dispatch_kind(brief_text(VALUES['verdict-or-review']))['act_kind'], 'verdict-or-review')
        self.assertEqual(self.errors(), [])

    def test_c_r_7_the_decision_value_gives_user_decision(self):
        self.assertEqual(self.dispatch_kind(brief_text(VALUES['user-decision']))['act_kind'], 'user-decision')

    def test_c_r_7_a_plain_name_is_itself(self):
        self.assertEqual(self.dispatch_kind(brief_text('build'))['act_kind'], 'build')

    def test_c_r_7_a_value_no_kind_maps_to_is_unrecorded_and_logged_and_the_record_written(self):
        sent = self.dispatch_kind(brief_text('no-such-value'))
        self.assertEqual(sent['act_kind'], 'unrecorded (no-such-value is not a kind)')
        errors = self.errors()
        self.assertEqual(len(errors), 1, errors)
        self.assertEqual((errors[0]['stage'], errors[0]['record'], errors[0]['call_id']),
                         ('setting', 'dispatch', 'toolu_kind_0001'))
        self.assertEqual(len(self.dispatches()), 1)

    def test_c_r_7_a_brief_with_no_kind(self):
        self.assertEqual(self.dispatch_kind(brief_text(None))['act_kind'], NO_KIND)
        self.assertEqual(self.errors(), [])

    def test_c_r_7_a_command_line_call(self):
        self.capture.handle('PreToolUse', json.dumps(self.events('claude-code', 'bash-cli-events.jsonl')[0]['payload']),
                            None)
        sent = self.dispatches()[-1]
        self.assertEqual(sent['route'], 'cli')
        self.assertEqual(sent['act_kind'], NO_KIND_CLI)
        self.assertEqual(sent['user_answer'], NOT_DECISION)

    def test_c_r_7_switched_off_without_the_translation_the_brief_value_reaches_the_record(self):
        if not hasattr(self.capture, 'kind_of'):
            raise AssertionError('capture_claude_code.py has no kind_of() yet')
        with mock.patch.object(self.capture, 'kind_of', lambda folder, value, held=None: value):
            self.capture.handle('PreToolUse', json.dumps(self.pre_agent(brief_text(VALUES['verdict-or-review']))),
                                None)
        self.assertEqual(self.dispatches(), [], 'the untranslated value is refused, so no record is written')
        errors = self.errors()
        self.assertEqual([e['stage'] for e in errors], ['validate'])
        self.assertIn('act_kind', errors[0]['reason'])


class CR7NoMap(KindWorld):

    mapped = False

    def test_c_r_7_with_kind_names_absent_a_mapped_value_is_not_a_kind(self):
        value = VALUES['verdict-or-review']
        sent = self.dispatch_kind(brief_text(value))
        self.assertEqual(sent['act_kind'], 'unrecorded (%s is not a kind)' % value)
        self.assertEqual([e['stage'] for e in self.errors()], ['setting'])

    def test_c_r_7_with_kind_names_absent_a_plain_name_is_read_directly(self):
        self.assertEqual(self.dispatch_kind(brief_text('inquiry'))['act_kind'], 'inquiry')


class CR7OtherCaptures(KindWorld):

    def test_c_r_7_codex_reads_the_kind_and_has_no_question_tool(self):
        codex = load(SCRIPTS / 'capture_codex.py', 'capture_codex_kind_%d' % id(self))
        (self.work / 'brief.md').write_text(brief_text(VALUES['user-decision']), encoding='utf-8')
        first = self.events('codex', 'dr3-events.jsonl')[0]
        codex.handle(first['event'], json.dumps(first['payload']), None)
        sent = self.dispatches()[-1]
        self.assertEqual(sent['act_kind'], 'user-decision')
        self.assertEqual(sent['user_answer'], 'unrecorded (no question tool for codex)')

    def test_c_r_7_opencode_reads_the_kind(self):
        opencode = load(SCRIPTS / 'capture_opencode.py', 'capture_opencode_kind_%d' % id(self))
        (self.work / 'brief.md').write_text(brief_text(VALUES['inquiry']), encoding='utf-8')
        first = self.events('opencode', 'dr3-events.jsonl')[0]
        opencode.handle(first['event'], json.dumps({'input': first['input'], 'output': first['output']}), None)
        sent = self.dispatches()[-1]
        self.assertEqual(sent['act_kind'], 'inquiry')
        self.assertEqual(sent['user_answer'], NOT_DECISION)

    def test_c_r_7_the_call_script_reads_the_kind(self):
        call = load(SCRIPTS / 'call.py', 'call_kind_%d' % id(self))
        brief = self.work / 'brief.md'
        brief.write_text(brief_text(VALUES['build']), encoding='utf-8')
        with mock.patch.dict(os.environ, {'PATH': str(self.tmp / 'empty-path')}), \
                contextlib.redirect_stdout(io.StringIO()):
            call.main(['--harness', 'gemini-cli', '--brief', str(brief), '--session', SESSION])
        sent = self.dispatches()[-1]
        self.assertEqual(sent['act_kind'], 'build')
        self.assertEqual(sent['user_answer'], NOT_DECISION)

    def test_c_r_7_the_call_script_with_no_kind(self):
        call = load(SCRIPTS / 'call.py', 'call_nokind_%d' % id(self))
        brief = self.work / 'brief.md'
        brief.write_text('Reply with ok.\n', encoding='utf-8')
        with mock.patch.dict(os.environ, {'PATH': str(self.tmp / 'empty-path')}), \
                contextlib.redirect_stdout(io.StringIO()):
            call.main(['--harness', 'cursor', '--brief', str(brief), '--session', SESSION])
        self.assertEqual(self.dispatches()[-1]['act_kind'], NO_KIND)

    def test_c_r_7_a_writer_caller_that_names_a_script_call(self):
        writer = load(SCRIPTS / 'ledger.py', 'ledger_script_kind_%d' % id(self))
        writer.dispatch(call_id='script-1', session=SESSION, agent_id=NO_AGENT, route='script', brief='a request',
                        act_kind=NO_AGENT)
        sent = self.dispatches()[-1]
        self.assertEqual(sent['act_kind'], NO_AGENT)
        self.assertEqual(sent['user_answer'], NOT_DECISION)


# ---------------------------------------------------------------------------
# The user's answer
# ---------------------------------------------------------------------------

QUESTION_ID = 'toolu_question_0001'


def transcript_rows(asked_at, answered_at, with_question=True, answered=True):
    rows = [{'type': 'user', 'timestamp': '2026-10-10T00:00:00.000Z', 'sessionId': SESSION,
             'message': {'role': 'user', 'content': 'Start the work.'}}]
    if with_question:
        rows.append({'type': 'assistant', 'timestamp': asked_at, 'sessionId': SESSION,
                     'message': {'role': 'assistant', 'model': 'fixture-model', 'id': 'msg_q',
                                 'content': [{'type': 'tool_use', 'id': QUESTION_ID, 'name': 'AskUserQuestion',
                                              'input': {'questions': [{'question': 'Go ahead?'}]}}]}})
        if answered:
            rows.append({'type': 'user', 'timestamp': answered_at, 'sessionId': SESSION,
                         'message': {'role': 'user', 'content': [{'type': 'tool_result', 'tool_use_id': QUESTION_ID,
                                                                  'content': 'Yes, go ahead.'}]}})
    rows.append({'type': 'assistant', 'timestamp': '2026-10-10T00:50:00.000Z', 'sessionId': SESSION,
                 'message': {'role': 'assistant', 'model': 'fixture-model', 'id': 'msg_a',
                             'content': [{'type': 'text', 'text': 'Dispatching now.'}]}})
    return rows


class CR11UserAnswer(KindWorld):

    def transcript(self, rows):
        path = self.config / 'projects' / '-fixture-work' / ('%s.jsonl' % SESSION)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(''.join(json.dumps(r) + '\n' for r in rows), encoding='utf-8')
        return path

    def previous_dispatch(self, at):
        writer = load(SCRIPTS / 'ledger.py', 'ledger_prev_%d' % id(self))
        sent = writer.dispatch(call_id='toolu_previous', session=SESSION, route='subagent', caller='parent',
                               dispatched_at=at, brief='an earlier brief', harness='claude-code')
        self.assertTrue(sent.ok, sent.error)

    def run_hook(self, payload):
        """The capture run as the harness runs it: what it prints, and its exit code."""
        done = subprocess.run([sys.executable, str(SCRIPTS / 'capture_claude_code.py'), 'PreToolUse'],
                              input=json.dumps(payload), capture_output=True, text=True, env=dict(os.environ))
        return done

    def answer_of(self, rows, kind='user-decision', statement=None, previous=None):
        path = self.transcript(rows)
        if previous:
            self.previous_dispatch(previous)
        payload = self.pre_agent(brief_text(VALUES[kind], statement), transcript=path)
        done = self.run_hook(payload)
        self.assertEqual((done.returncode, done.stdout, done.stderr), (0, '', ''),
                         'the call goes out unchanged: the capture prints nothing and exits 0')
        sent = [r for r in self.dispatches() if r['call_id'] == 'toolu_kind_0001'][0]
        return sent['user_answer'], sent

    def test_c_r_11_an_answered_question_in_the_window(self):
        answer, sent = self.answer_of(transcript_rows('2026-10-10T00:10:00.000Z', '2026-10-10T00:11:00.000Z'),
                                      statement='The user said yes in chat.')
        self.assertEqual(sent['act_kind'], 'user-decision')
        self.assertEqual(answer, {'answered_first': 'yes', 'question_call': QUESTION_ID,
                                  'asked_at': '2026-10-10T00:10:00.000Z', 'answered_at': '2026-10-10T00:11:00.000Z',
                                  'agent_record': 'The user said yes in chat.'})

    def test_c_r_11_the_question_removed_reads_not_found(self):
        answer, _ = self.answer_of(transcript_rows(None, None, with_question=False),
                                   statement='The user said yes in chat.')
        self.assertEqual(answer, {'answered_first': 'not found', 'question_call': None, 'asked_at': None,
                                  'answered_at': None, 'agent_record': 'The user said yes in chat.'})

    def test_c_r_11_a_question_left_unanswered_reads_not_found(self):
        answer, _ = self.answer_of(transcript_rows('2026-10-10T00:10:00.000Z', None, answered=False))
        self.assertEqual(answer['answered_first'], 'not found')
        self.assertEqual(answer['agent_record'], 'none')

    def test_c_r_11_a_question_before_the_callers_previous_dispatch_reads_not_found(self):
        answer, _ = self.answer_of(transcript_rows('2026-10-10T00:10:00.000Z', '2026-10-10T00:11:00.000Z'),
                                   previous='2026-10-10T00:30:00.000Z')
        self.assertEqual(answer['answered_first'], 'not found')

    def test_c_r_11_another_kind_reads_none(self):
        answer, _ = self.answer_of(transcript_rows('2026-10-10T00:10:00.000Z', '2026-10-10T00:11:00.000Z'),
                                   kind='build')
        self.assertEqual(answer, NOT_DECISION)

    def test_c_r_11_an_unreadable_transcript_is_unrecorded(self):
        payload = self.pre_agent(brief_text(VALUES['user-decision']), transcript=self.tmp / 'no-such.jsonl')
        done = self.run_hook(payload)
        self.assertEqual((done.returncode, done.stdout), (0, ''))
        answer = self.dispatches()[-1]['user_answer']
        self.assertTrue(answer.startswith('unrecorded ('), answer)

    def test_c_r_11_the_statement_never_counts_as_the_evidence(self):
        answer, _ = self.answer_of(transcript_rows(None, None, with_question=False), statement='yes')
        self.assertEqual(answer['answered_first'], 'not found')
        self.assertEqual(answer['agent_record'], 'yes')

    def test_c_r_11_switched_off_without_the_window_an_old_question_reads_yes(self):
        if not hasattr(self.capture, 'previous_dispatch_at'):
            raise AssertionError('capture_claude_code.py has no previous_dispatch_at() yet')
        self.transcript(transcript_rows('2026-10-10T00:10:00.000Z', '2026-10-10T00:11:00.000Z'))
        self.previous_dispatch('2026-10-10T00:30:00.000Z')
        path = self.config / 'projects' / '-fixture-work' / ('%s.jsonl' % SESSION)
        with mock.patch.object(self.capture, 'previous_dispatch_at', lambda *args, **kwargs: None):
            self.capture.handle('PreToolUse', json.dumps(self.pre_agent(brief_text(VALUES['user-decision']),
                                                                        transcript=path)), None)
        sent = [r for r in self.dispatches() if r['call_id'] == 'toolu_kind_0001'][0]
        self.assertEqual(sent['user_answer']['answered_first'], 'yes', 'the check sees the window switched off')


class FN8ServedRequests(KindWorld):
    """Fix note FN-8, from the first live session: the triage's own request, written as a dispatch record
    naming the Agent call it serves in `harness_payload.serves_call_id`, hid the answered question.

    The fixtures are the replay: the ledger as the hook saw it (four SubagentStop witness lines and the
    triage's record, verbatim but for its model, key name and endpoint, which name a workspace's service) and the
    caller's transcript cut at the dispatch, its question and answer text replaced. The IDs and times are the
    live ones.
    """

    LIVE_SESSION = 'bc2f0e03-97ba-4464-82a4-90d6a18ffbbc'
    LIVE_QUESTION = 'toolu_01Ha7kPt5zZiGfnwXVExtind'

    def setUp(self):
        super().setUp()
        self.path = self.ledger / ('%s.jsonl' % self.LIVE_SESSION)
        shutil.copy(FIXTURES / 'claude-code' / 'fn8-ledger-at-hook.jsonl', self.path)
        self.transcript = FIXTURES / 'claude-code' / 'fn8-transcript-at-hook.jsonl'

    def answer(self):
        return self.capture.user_answer_of(str(self.ledger), 'claude-code', self.LIVE_SESSION, 'parent',
                                           str(self.transcript), 'user-decision', '')

    def test_fn_8_the_triages_own_request_does_not_open_the_window(self):
        answer = self.answer()
        self.assertEqual(answer['answered_first'], 'yes')
        self.assertEqual(answer['question_call'], self.LIVE_QUESTION)
        self.assertEqual((answer['asked_at'], answer['answered_at']),
                         ('2026-10-12T02:28:41.338Z', '2026-10-12T02:28:46.208Z'))

    def test_fn_8_switched_off_the_triages_request_hides_the_question(self):
        if not hasattr(self.capture, 'serves_another_call'):
            raise AssertionError('capture_claude_code.py has no serves_another_call() yet')
        with mock.patch.object(self.capture, 'serves_another_call', lambda row: False):
            answer = self.answer()
        self.assertEqual(answer['answered_first'], 'not found', 'the check sees the live fault come back')

    def test_fn_8_a_real_earlier_dispatch_by_the_caller_still_narrows_the_window(self):
        writer = load(SCRIPTS / 'ledger.py', 'ledger_fn8_%d' % id(self))
        sent = writer.dispatch(call_id='toolu_fn8_earlier', session=self.LIVE_SESSION, route='subagent',
                               caller='parent', dispatched_at='2026-10-12T02:28:50.000Z', brief='an earlier brief',
                               harness='claude-code')
        self.assertTrue(sent.ok, sent.error)
        self.assertEqual(self.answer()['answered_first'], 'not found')


# ---------------------------------------------------------------------------
# The label line's shape, and the reader
# ---------------------------------------------------------------------------

REVISION = '178097501b17147731b194d3a88211bbc53d03aa'
QUESTION_REVISION = 'f' * 40


def score(levels):
    return {'score': round(sum(int(k) * v for k, v in levels.items()), 2), 'probabilities': levels,
            'confidence': 0.25}


def new_line(**changes):
    line = {'schema': 'subagent-ledger/1', 'record': 'label', 'call_id': 'call-1', 'session': SESSION,
            'labelled_at': '2026-10-10T02:00:00.000Z', 'labelled_because': ['always: verdict-or-review'],
            'failure_modes': [{'mode': 'mode_a', 'level': 3, 'p': 0.35}],
            'likelihoods': {'mode_a': score({'0': 0.15, '1': 0.32, '2': 0.18, '3': 0.35}),
                            'mode_b': score({'0': 0.8, '1': 0.1, '2': 0.05, '3': 0.05})},
            'cutoff': 2, 'roster_revision': REVISION, 'question_revision': QUESTION_REVISION,
            'labeller_model': 'labeller-1.0.0', 'labeller_call_ids': ['j-1', 'j-2', 'j-3'], 'withheld': 0}
    line.update(changes)
    return line


class CR8Line(unittest.TestCase):

    def setUp(self):
        self.writer = load(SCRIPTS / 'ledger.py', 'ledger_line_%d' % id(self))
        self.schema = self.writer.load_schema()

    def test_c_r_8_sevens_shape_validates(self):
        self.assertEqual(self.writer.validate(new_line(), self.schema, ref='#/$defs/label'), [])
        self.assertEqual(self.writer.validate(new_line(failure_modes=[]), self.schema, ref='#/$defs/label'), [])

    def test_c_r_8_the_old_name_a_number_or_no_question_revision_is_rejected(self):
        old = new_line(labeller_call_id='j-1')
        del old['labeller_call_ids']
        numeric = new_line(likelihoods={'mode_a': 0.35})
        unrevised = new_line()
        del unrevised['question_revision']
        for name, line in (('labeller_call_id', old), ('numeric', numeric), ('no question_revision', unrevised)):
            with self.subTest(name):
                self.assertTrue(self.writer.validate(line, self.schema, ref='#/$defs/label'), name)

    def test_c_r_8_a_level_below_two_or_an_empty_reason_list_is_rejected(self):
        self.assertTrue(self.writer.validate(new_line(failure_modes=[{'mode': 'mode_a', 'level': 1, 'p': 0.4}]),
                                             self.schema, ref='#/$defs/label'))
        self.assertTrue(self.writer.validate(new_line(labelled_because=[]), self.schema, ref='#/$defs/label'))

    def test_c_r_8_the_writer_keeps_sevens_order(self):
        folder = Path(tempfile.mkdtemp(prefix='act-kind-line-'))
        self.addCleanup(shutil.rmtree, folder, True)
        line = new_line()
        given = dict((k, v) for k, v in line.items() if k not in ('schema', 'record', 'withheld'))
        written = self.writer.label(ledger=str(folder), **dict(reversed(list(given.items()))))
        self.assertTrue(written.ok, written.error)
        stored = lines_of(folder / ('%s.jsonl' % SESSION))[0]
        self.assertEqual(list(stored), list(line))


class CR8Reader(unittest.TestCase):

    def setUp(self):
        self.folder = Path(tempfile.mkdtemp(prefix='act-kind-reader-'))
        self.addCleanup(shutil.rmtree, self.folder, True)
        patcher = mock.patch.dict(os.environ, {'SUBAGENT_LEDGER_DIR': str(self.folder)})
        patcher.start()
        self.addCleanup(patcher.stop)
        (self.folder / 'config.json').write_text(json.dumps({'fields': 'all'}), encoding='utf-8')
        self.writer = load(SCRIPTS / 'ledger.py', 'ledger_reader_%d' % id(self))
        self.writer.dispatch(call_id='call-1', session=SESSION, route='subagent', caller='parent', brief='b',
                             act_kind='verdict-or-review')
        self.writer.ret(call_id='call-1', session=SESSION, agent_id='a-1', outcome='served',
                        outcome_reason='none (served)', answer='an answer')

    def read(self, module=None):
        module = module or load(SCRIPTS / 'calls.py', 'calls_line_%d' % id(object()))
        out = io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(io.StringIO()):
            module.main(['--session', SESSION, '--json'])
        return json.loads(out.getvalue())

    def test_c_r_8_the_reader_shows_the_new_and_renamed_keys(self):
        line = new_line()
        given = dict((k, v) for k, v in line.items() if k not in ('schema', 'record', 'withheld'))
        self.assertTrue(self.writer.label(**given).ok)
        row = self.read()['calls'][0]
        self.assertEqual(row['act_kind'], 'verdict-or-review')
        labels = row['labels']
        for name in ('labelled_because', 'question_revision', 'likelihoods', 'labeller_call_ids', 'cutoff',
                     'failure_modes', 'roster_revision', 'labeller_model', 'labelled_at'):
            self.assertEqual(labels[name], line[name], name)
        self.assertNotIn('labeller_call_id', labels)

    def test_c_r_8_switched_off_the_old_label_fields_hide_the_new_keys(self):
        line = new_line()
        given = dict((k, v) for k, v in line.items() if k not in ('schema', 'record', 'withheld'))
        self.assertTrue(self.writer.label(**given).ok)
        module = load(SCRIPTS / 'calls.py', 'calls_old_fields_%d' % id(self))
        module.LABEL_FIELDS = ('failure_modes', 'likelihoods', 'cutoff', 'roster_revision', 'labeller_model',
                               'labelled_at')
        labels = self.read(module)['calls'][0]['labels']
        self.assertNotIn('labelled_because', labels)


if __name__ == '__main__':
    unittest.main()
