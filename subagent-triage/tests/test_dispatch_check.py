"""Tests for dispatch_check.py: the check the ledger's wrapper runs at the parent's PreToolUse on Agent and Task. It
refuses a dispatch with no pending triage file and no planner's file, never one whose file records a failed triage,
and never a member's own dispatch (R-11, R-3, R-22; TC-17, and TC-5's untriaged reading).

Each test runs the ledger skill's own wrapper, with config.json's `checks.dispatch` naming this check, on a PreToolUse
payload, so the check runs before the capture in one process, as it will in a session. Every ledger folder is a
temporary folder, proved so before anything runs; no setting any other session loads is touched.

Run from the skill's folder:  python3 -m unittest discover -s tests
"""

import json
import os
import shlex
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
SCRIPT = HERE.parent / 'skill' / 'scripts' / 'dispatch_check.py'
LEDGER_SCRIPTS = HERE.parent.parent / 'subagent-ledger' / 'skill' / 'scripts'
WRAPPER = LEDGER_SCRIPTS / 'wrapper.py'
SESSION = '0e0e0e0e-1111-4222-8333-555555555555'
STAMP = '2026-01-15T00:00:00.000Z'
TRIAGE_VALUES = ('effort_unaided', 'decision_records', 'triage_persona', 'persona_facts', 'chosen_by',
                 'triage_failure')


def clean_env():
    env = dict(os.environ)
    for name in ('SUBAGENT_LEDGER_DIR', 'SUBAGENT_LEDGER_SCRIPTS', 'SUBAGENT_LEDGER_SESSION'):
        env.pop(name, None)
    return env


class DispatchCheckTests(unittest.TestCase):

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.ledger = self.tmp / 'ledger'
        self.ledger.mkdir()
        self.work = self.tmp / 'work'
        self.work.mkdir()
        for path in (self.ledger, self.work):
            # Where every write lands, proved before anything runs: inside this test's own temporary folder.
            self.assertTrue(str(path.resolve()).startswith(str(Path(tempfile.gettempdir()).resolve())))
        self.configure(check=True)
        self.pending = self.ledger / '.pending' / SESSION
        self.persona = self.work / 'builder.md'
        self.persona.write_text('---\ntitle: Builder\n---\n\nA persona file.\n', encoding='utf-8')

    def tearDown(self):
        shutil.rmtree(str(self.tmp), ignore_errors=True)

    def configure(self, check):
        config = {'fields': 'all'}
        if check:
            config['checks'] = {'dispatch': '%s %s' % (shlex.quote(sys.executable), shlex.quote(str(SCRIPT)))}
        (self.ledger / 'config.json').write_text(json.dumps(config), encoding='utf-8')

    def brief(self, name='m1-1.md', member='m1', attempt='1', text='The task.'):
        path = self.work / name
        front = '---\nmember: %s\nattempt: %s\n---\n\n' % (member, attempt) if member else ''
        path.write_text(front + text + '\n', encoding='utf-8')
        return path

    def triage_file(self, member='m1', attempt='1', failure=None, text=None):
        self.pending.mkdir(parents=True, exist_ok=True)
        path = self.pending / ('triage-%s-%s.json' % (member, attempt))
        data = {'effort_unaided': {'value': 'medium', 'stamped_at': STAMP},
                'kind': {'value': 'build', 'stamped_at': STAMP}}
        if failure:
            data['triage_failure'] = {'value': failure, 'stamped_at': STAMP}
        path.write_text(text if text is not None else json.dumps(data), encoding='utf-8')
        return path

    def dispatch(self, prompt, agent=None, call='toolu_dispatch_1'):
        payload = {'session_id': SESSION, 'hook_event_name': 'PreToolUse', 'tool_name': 'Agent',
                   'tool_use_id': call, 'cwd': str(self.work),
                   'tool_input': {'prompt': prompt, 'description': 'a member'}}
        if agent:
            payload['agent_id'] = agent
        done = subprocess.run([sys.executable, str(WRAPPER), 'PreToolUse', '--ledger', str(self.ledger)],
                              input=json.dumps(payload), capture_output=True, text=True, env=clean_env(), timeout=60)
        self.assertEqual(done.returncode, 0, done.stderr)
        said = json.loads(done.stdout) if done.stdout.strip() else None
        path = self.ledger / ('%s.jsonl' % SESSION)
        rows = [json.loads(line) for line in path.read_text(encoding='utf-8').splitlines() if line.strip()] \
            if path.is_file() else []
        return said, rows

    def records(self, rows, kind):
        return [row for row in rows if row.get('record') == kind]

    def left(self, prefixes=('triage-', 'planner-')):
        """The pending files left: by default the triage and planner's files. A call let through also leaves the
        capture's own pending file for its return, which the return removes."""
        names = sorted(p.name for p in self.pending.glob('*.json')) if self.pending.is_dir() else []
        return [name for name in names if prefixes is None or name.startswith(prefixes)]

    def assert_let_through(self, said, rows):
        self.assertIsNone(said)
        dispatch, = self.records(rows, 'dispatch')
        self.assertEqual(dispatch['harness_payload']['wrapper']['refused'], False)
        self.assertEqual(dispatch['harness_payload']['wrapper']['result'], 'checked')
        self.assertEqual(self.records(rows, 'return'), [])
        return dispatch

    # -- TC-17 --------------------------------------------------------------------------------------------------------

    def test_tc17_empty_with_the_check_off_a_dispatch_carries_no_triage_values(self):
        self.configure(check=False)
        said, rows = self.dispatch('Read %s and do it.' % self.brief())
        self.assertIsNone(said)
        dispatch, = self.records(rows, 'dispatch')
        for name in TRIAGE_VALUES:
            self.assertEqual(dispatch[name], 'unrecorded (no pending triage file for this call)', name)
        self.assertNotIn('wrapper', dispatch['harness_payload'])

    def test_tc17_likeness_an_untriaged_dispatch_is_refused_with_its_record_and_failed_return(self):
        said, rows = self.dispatch('Read %s and do it.' % self.brief())
        decision = said['hookSpecificOutput']
        self.assertEqual(decision['permissionDecision'], 'deny')
        self.assertIn('triage-m1-1.json', decision['permissionDecisionReason'])
        dispatch, = self.records(rows, 'dispatch')
        returned, = self.records(rows, 'return')
        self.assertEqual(returned['call_id'], dispatch['call_id'])
        self.assertEqual(returned['outcome'], 'failed')
        self.assertEqual(returned['outcome_reason']['class'], 'refused_by_check')
        self.assertIn('triage-m1-1.json', returned['outcome_reason']['text'])
        self.assertEqual(self.left(prefixes=None), [])

    def test_tc17_likeness_a_triaged_dispatch_is_let_through_its_file_read_before_the_capture_removes_it(self):
        self.triage_file()
        said, rows = self.dispatch('Read %s and do it.' % self.brief())
        dispatch = self.assert_let_through(said, rows)
        self.assertEqual(dispatch['effort_unaided']['value'], 'medium')
        self.assertEqual(self.left(), [])

    def test_tc17_likeness_a_dispatch_whose_triage_failed_is_let_through_and_the_failure_recorded(self):
        self.triage_file(failure='act decision: Jev is unreachable')
        said, rows = self.dispatch('Read %s and do it.' % self.brief())
        dispatch = self.assert_let_through(said, rows)
        self.assertEqual(dispatch['triage_failure']['value'], 'act decision: Jev is unreachable')

    def test_tc17_likeness_the_planner_s_own_dispatch_is_let_through(self):
        self.pending.mkdir(parents=True, exist_ok=True)
        (self.pending / 'planner-plan-7a7a.json').write_text('{}', encoding='utf-8')
        brief = self.brief(name='planner.md', member=None, text='Plan the team for plan request plan-7a7a.')
        said, rows = self.dispatch('Read %s and propose the team.' % brief)
        dispatch = self.assert_let_through(said, rows)
        self.assertIn('plan request plan-7a7a', dispatch['member'])
        self.assertEqual(self.left(), [])

    def test_tc17_likeness_a_member_s_own_dispatch_is_let_through_and_the_check_s_result_recorded(self):
        said, rows = self.dispatch('Read %s and do it.' % self.brief(), agent='agent-member-1')
        dispatch = self.assert_let_through(said, rows)
        self.assertEqual(dispatch['caller'], 'agent-member-1')

    # -- R-11's no-persona override (ruled 30 October 2026) ------------------------------------------------------------

    def override_no_persona(self, member='m1', attempt='1', reason='a read-only search: it takes no persona'):
        decide = SCRIPT.parent / 'decide.py'
        done = subprocess.run([sys.executable, str(decide), 'override', '--decision', 'no-persona', '--ledger',
                               str(self.ledger), '--session', SESSION, '--member', member, '--attempt', attempt,
                               '--reason', reason], capture_output=True, text=True, env=clean_env(), timeout=60)
        self.assertEqual(done.returncode, 0, done.stdout + done.stderr)
        return json.loads(done.stdout)

    def test_r11_a_dispatch_with_no_persona_recorded_as_an_override_is_let_through_with_its_reason(self):
        self.override_no_persona()
        said, rows = self.dispatch('Read %s and do it.' % self.brief())
        dispatch = self.assert_let_through(said, rows)
        reason = dispatch['harness_payload']['wrapper']['reason']
        self.assertIn('no persona', reason)
        self.assertIn('a read-only search: it takes no persona', reason)
        entry, = dispatch['overrides']['value']
        self.assertEqual(entry['decision'], 'no-persona')
        self.assertEqual(self.left(), [])

    def test_r11_empty_an_untriaged_dispatch_s_refusal_prints_the_no_persona_override_command(self):
        said, rows = self.dispatch('Read %s and do it.' % self.brief())
        reason = said['hookSpecificOutput']['permissionDecisionReason']
        self.assertIn('override --decision no-persona', reason)
        self.assertIn('--member m1 --attempt 1', reason)
        self.assertIn('--session %s' % SESSION, reason)

    def test_r11_likeness_another_member_s_no_persona_override_does_not_let_this_one_through(self):
        self.override_no_persona(member='m2')
        said, rows = self.dispatch('Read %s and do it.' % self.brief())
        self.assertEqual(said['hookSpecificOutput']['permissionDecision'], 'deny')

    def test_the_check_s_reason_for_a_triaged_dispatch_is_on_the_record(self):
        self.triage_file()
        said, rows = self.dispatch('Read %s and do it.' % self.brief())
        dispatch = self.assert_let_through(said, rows)
        self.assertIn('triage-m1-1.json exists', dispatch['harness_payload']['wrapper']['reason'])

    # -- TC-5 and R-22: a first file that is not a brief --------------------------------------------------------------

    def test_tc5_a_persona_file_named_before_the_brief_is_read_as_untriaged_and_refused(self):
        self.triage_file()
        said, rows = self.dispatch('Your persona file is %s. Read %s and do it.' % (self.persona, self.brief()))
        self.assertEqual(said['hookSpecificOutput']['permissionDecision'], 'deny')
        self.assertIn('not a brief', said['hookSpecificOutput']['permissionDecisionReason'])
        returned, = self.records(rows, 'return')
        self.assertEqual(returned['outcome_reason']['class'], 'refused_by_check')

    def test_tc5_a_prompt_naming_no_file_is_refused(self):
        said, rows = self.dispatch('Add a dry-run flag to the export script.')
        self.assertEqual(said['hookSpecificOutput']['permissionDecision'], 'deny')
        self.assertIn('names no file', said['hookSpecificOutput']['permissionDecisionReason'])

    # -- Edges --------------------------------------------------------------------------------------------------------

    def test_a_pending_file_that_cannot_be_read_still_lets_the_dispatch_through(self):
        self.triage_file(text='{not json')
        said, rows = self.dispatch('Read %s and do it.' % self.brief())
        self.assert_let_through(said, rows)

    def test_another_attempt_s_file_does_not_let_this_attempt_through(self):
        self.triage_file(attempt='1')
        said, rows = self.dispatch('Read %s and do it.' % self.brief(name='m1-2.md', attempt='2'))
        self.assertEqual(said['hookSpecificOutput']['permissionDecision'], 'deny')
        self.assertIn('triage-m1-2.json', said['hookSpecificOutput']['permissionDecisionReason'])

    def test_the_check_alone_prints_its_decision_and_errs_on_a_payload_it_cannot_read(self):
        env = dict(clean_env(), SUBAGENT_LEDGER_DIR=str(self.ledger), SUBAGENT_LEDGER_SESSION=SESSION,
                   SUBAGENT_LEDGER_SCRIPTS=str(LEDGER_SCRIPTS))
        payload = {'session_id': SESSION, 'tool_name': 'Agent', 'tool_use_id': 't1', 'cwd': str(self.work),
                   'tool_input': {'prompt': 'Read %s.' % self.brief()}}
        done = subprocess.run([sys.executable, str(SCRIPT)], input=json.dumps(payload), capture_output=True,
                              text=True, env=env, timeout=60)
        self.assertEqual(done.returncode, 0, done.stderr)
        said = json.loads(done.stdout)
        self.assertIs(said['refuse'], True)
        done = subprocess.run([sys.executable, str(SCRIPT)], input='not json', capture_output=True, text=True,
                              env=env, timeout=60)
        self.assertNotEqual(done.returncode, 0)


if __name__ == '__main__':
    unittest.main()
