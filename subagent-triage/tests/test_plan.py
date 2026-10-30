"""Tests for plan.py: the plan file, written before the first dispatch (R-7, K-4); a re-dispatch listed against its
member with its attempt; the next plan of a pattern leaving out a hop the last closed plan of that pattern marked not
cited (R-8, K-4; TC-14's second half); and the planner's own pending file (R-3; TC-6).

The planner's pending file is read back by the ledger skill's own capture, on a PreToolUse payload whose brief names
the plan request, so the test shows the dispatch is recorded as the planner's. Every ledger folder is a temporary
folder, proved so before anything runs.

Run from the skill's folder:  python3 -m unittest discover -s tests
"""

import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
SCRIPT = HERE.parent / 'skill' / 'scripts' / 'plan.py'
FIXTURES = HERE / 'fixtures'
HISTORY = FIXTURES / 'plan' / 'history'
LEDGER_SCRIPTS = HERE.parent.parent / 'subagent-ledger' / 'skill' / 'scripts'
CAPTURE = LEDGER_SCRIPTS / 'capture_claude_code.py'
SESSION = '0e0e0e0e-1111-4222-8333-555555555555'
PATTERN = ['build', 'deliberation', 'verdict-or-review']


def clean_env():
    env = dict(os.environ)
    for name in ('SUBAGENT_LEDGER_DIR', 'SUBAGENT_LEDGER_SCRIPTS'):
        env.pop(name, None)
    return env


class PlanTests(unittest.TestCase):

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.ledger = self.tmp / 'ledger'
        self.ledger.mkdir()
        (self.ledger / 'config.json').write_text('{"fields": "all"}', encoding='utf-8')
        self.folder = self.tmp / 'team'
        self.folder.mkdir()
        for path in (self.ledger, self.folder):
            # Where every write lands, proved before anything runs: inside this test's own temporary folder.
            self.assertTrue(str(path.resolve()).startswith(str(Path(tempfile.gettempdir()).resolve())))
        self.briefs = {}
        for member in ('m1', 'm2', 'm3'):
            brief = self.folder / ('%s-1.md' % member)
            brief.write_text('---\nmember: %s\nattempt: 1\n---\n\nA brief.\n' % member, encoding='utf-8')
            self.briefs[member] = str(brief)

    def tearDown(self):
        shutil.rmtree(str(self.tmp), ignore_errors=True)

    def run_plan(self, *arguments):
        done = subprocess.run([sys.executable, str(SCRIPT)] + [str(a) for a in arguments], capture_output=True,
                              text=True, env=clean_env(), timeout=60)
        try:
            out = json.loads(done.stdout)
        except ValueError:
            self.fail('no JSON on stdout (exit %s): %s %s' % (done.returncode, done.stdout, done.stderr))
        return done.returncode, out

    def member(self, member, kind, persona, write_set='none', repository='none', **extra):
        entry = {'member': member, 'part': 'Part %s.' % member, 'act_kind': kind, 'persona': persona,
                 'brief': self.briefs[member], 'repository': repository, 'write_set': write_set}
        entry.update(extra)
        return entry

    def team(self, **changes):
        proposal = {'task': '2026-01-15-report',
                    'members': [self.member('m1', 'build', 'builder', ['tables/'], 'report'),
                                self.member('m2', 'verdict-or-review', 'reviewer'),
                                self.member('m3', 'deliberation', 'synthesiser')],
                    'parallel': [['m1', 'm2'], ['m3']], 'synthesiser': 'm3'}
        proposal.update(changes)
        return proposal

    def write(self, proposal, out=None, history=None, extra=()):
        path = self.tmp / ('proposal-%d.json' % len(list(self.tmp.glob('proposal-*.json'))))
        path.write_text(json.dumps(proposal), encoding='utf-8')
        out = out or self.folder / 'plan.json'
        arguments = ['write', '--proposal', path, '--out', out]
        for folder in history or []:
            arguments += ['--history', folder]
        code, result = self.run_plan(*(arguments + list(extra)))
        return code, result, Path(out)

    # -- The plan file ------------------------------------------------------------------------------------------------

    def test_a_plan_is_written_with_its_fields_and_pattern(self):
        code, out, path = self.write(self.team())
        self.assertEqual(code, 0, out)
        plan = json.loads(path.read_text(encoding='utf-8'))
        self.assertEqual(set(plan), {'plan_request', 'task', 'written_at', 'pattern', 'members', 'parallel',
                                     'synthesiser', 'hops', 'changes'})
        self.assertEqual(plan['pattern'], PATTERN)
        self.assertRegex(plan['written_at'], r'^\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d')
        self.assertEqual([m['attempt'] for m in plan['members']], [1, 1, 1])
        self.assertEqual(plan['hops'], [
            {'from': 'm1', 'to': 'parent', 'kind': 'return', 'cited': None},
            {'from': 'm2', 'to': 'parent', 'kind': 'return', 'cited': None},
            {'from': 'm3', 'to': 'parent', 'kind': 'synthesis', 'cited': None}])
        self.assertNotIn('closed_at', plan)
        self.assertEqual(out['plan_file'], str(path))

    def test_tc6_empty_a_delegation_of_one_part_has_one_member_and_no_planner(self):
        proposal = {'task': '2026-01-15-report', 'members': [self.member('m1', 'build', 'builder', ['tables/'],
                                                                         'report')],
                    'parallel': [['m1']], 'synthesiser': 'parent'}
        code, out, path = self.write(proposal)
        self.assertEqual(code, 0, out)
        plan = json.loads(path.read_text(encoding='utf-8'))
        self.assertEqual(len(plan['members']), 1)
        self.assertEqual(plan['hops'], [{'from': 'm1', 'to': 'parent', 'kind': 'return', 'cited': None}])
        self.assertEqual(list(self.ledger.rglob('planner-*.json')), [])

    def test_the_plan_holds_no_value_that_belongs_on_a_record(self):
        for where in ('top', 'member'):
            proposal = self.team()
            if where == 'top':
                proposal['effort'] = 'high'
            else:
                proposal['members'][0]['effort'] = 'high'
            code, out, path = self.write(proposal, out=self.folder / ('plan-%s.json' % where))
            self.assertEqual(code, 1, out)
            self.assertIn('effort', out['error'])
            self.assertFalse(path.exists())

    def test_a_brief_that_does_not_resolve_is_refused(self):
        proposal = self.team()
        proposal['members'][1]['brief'] = str(self.folder / 'missing.md')
        code, out, path = self.write(proposal)
        self.assertEqual(code, 1, out)
        self.assertIn('missing.md', out['error'])

    def test_a_member_left_out_of_the_parallel_order_is_refused(self):
        code, out, path = self.write(self.team(parallel=[['m1', 'm2']]))
        self.assertEqual(code, 1, out)
        self.assertIn('m3', out['error'])

    def test_an_unknown_kind_and_a_write_set_without_its_repository_are_refused(self):
        proposal = self.team()
        proposal['members'][0]['act_kind'] = 'poetry'
        code, out, _ = self.write(proposal)
        self.assertEqual(code, 1, out)
        self.assertIn('poetry', out['error'])
        proposal = self.team()
        proposal['members'][0]['repository'] = 'none'
        code, out, _ = self.write(proposal)
        self.assertEqual(code, 1, out)
        self.assertIn('repository', out['error'])

    def test_an_existing_plan_file_is_never_overwritten(self):
        code, out, path = self.write(self.team())
        self.assertEqual(code, 0, out)
        before = path.read_text(encoding='utf-8')
        code, out, _ = self.write(self.team(), out=path)
        self.assertEqual(code, 1, out)
        self.assertEqual(path.read_text(encoding='utf-8'), before)

    # -- A re-dispatch ------------------------------------------------------------------------------------------------

    def test_a_re_dispatch_is_a_new_entry_under_its_member_with_the_next_attempt(self):
        code, out, path = self.write(self.team())
        self.assertEqual(code, 0, out)
        brief = self.folder / 'm1-2.md'
        brief.write_text('A second brief.\n', encoding='utf-8')
        code, out = self.run_plan('redispatch', '--plan', path, '--member', 'm1', '--brief', brief,
                                  '--reason', 'the first attempt wrote outside its set')
        self.assertEqual(code, 0, out)
        plan = json.loads(path.read_text(encoding='utf-8'))
        entries = [m for m in plan['members'] if m['member'] == 'm1']
        self.assertEqual([m['attempt'] for m in entries], [1, 2])
        self.assertEqual(entries[0]['brief'], self.briefs['m1'])
        self.assertEqual(entries[1]['brief'], str(brief))
        self.assertEqual(entries[1]['redispatch_reason'], 'the first attempt wrote outside its set')
        self.assertEqual(entries[1]['write_set'], ['tables/'])
        self.assertEqual(out['entry'], entries[1])

    def test_a_re_dispatch_with_no_reason_or_of_an_unknown_member_is_refused(self):
        code, out, path = self.write(self.team())
        self.assertEqual(code, 0, out)
        brief = self.folder / 'm1-2.md'
        brief.write_text('A second brief.\n', encoding='utf-8')
        code, out = self.run_plan('redispatch', '--plan', path, '--member', 'm1', '--brief', brief, '--reason', ' ')
        self.assertEqual(code, 1, out)
        code, out = self.run_plan('redispatch', '--plan', path, '--member', 'm9', '--brief', brief, '--reason', 'r')
        self.assertEqual(code, 1, out)
        self.assertEqual(len(json.loads(path.read_text(encoding='utf-8'))['members']), 3)

    # -- TC-14: the next plan of the same pattern leaves out a hop not cited -----------------------------------------

    def test_tc14_a_hop_the_last_closed_plan_of_the_pattern_marked_not_cited_is_left_out(self):
        code, out, path = self.write(self.team(), history=[HISTORY])
        self.assertEqual(code, 0, out)
        plan = json.loads(path.read_text(encoding='utf-8'))
        self.assertEqual([(h['from'], h['kind']) for h in plan['hops']], [('m1', 'return'), ('m2', 'return')])
        self.assertEqual(out['left_out'], [{'from': 'm3', 'to': 'parent', 'kind': 'synthesis'}])
        self.assertEqual(out['history_plan'], str(HISTORY / 'newer' / 'plan-2.json'))
        change = plan['changes'][-1]
        self.assertEqual(change['part'], 'm3')
        self.assertEqual(change['chosen'], 'left out')
        self.assertIn('plan-2', change['reason'])

    def test_a_left_out_hop_the_parent_restores_is_kept_and_recorded_as_a_change(self):
        restore = [{'from': 'm3', 'to': 'parent', 'kind': 'synthesis', 'reason': 'this report needs one voice'}]
        code, out, path = self.write(self.team(restore=restore), history=[HISTORY])
        self.assertEqual(code, 0, out)
        plan = json.loads(path.read_text(encoding='utf-8'))
        self.assertIn({'from': 'm3', 'to': 'parent', 'kind': 'synthesis', 'cited': None}, plan['hops'])
        self.assertEqual(out['left_out'], [])
        self.assertEqual(plan['changes'][-1]['reason'], 'this report needs one voice')
        self.assertEqual(plan['changes'][-1]['chosen'], 'restored')

    def test_another_pattern_and_a_cited_hop_leave_nothing_out(self):
        proposal = {'task': '2026-01-15-report', 'members': [self.member('m1', 'build', 'builder', ['tables/'],
                                                                         'report'),
                                                             self.member('m3', 'deliberation', 'synthesiser')],
                    'parallel': [['m1'], ['m3']], 'synthesiser': 'm3'}
        code, out, path = self.write(proposal, history=[HISTORY])
        self.assertEqual(code, 0, out)
        self.assertEqual(out['left_out'], [])
        self.assertIsNone(out['history_plan'])
        self.assertEqual(len(json.loads(path.read_text(encoding='utf-8'))['hops']), 2)

    # -- R-3: the planner's own pending file --------------------------------------------------------------------------

    def test_the_planner_s_pending_file_is_found_by_the_capture_and_removed(self):
        code, out = self.run_plan('planner', '--ledger', self.ledger, '--session', SESSION)
        self.assertEqual(code, 0, out)
        request = out['plan_request']
        pending = Path(out['pending_file'])
        self.assertEqual(pending, self.ledger / '.pending' / SESSION / ('planner-%s.json' % request))
        self.assertTrue(pending.is_file())
        brief = self.folder / 'planner-brief.md'
        brief.write_text('Plan the team for plan request %s.\n' % request, encoding='utf-8')
        payload = {'session_id': SESSION, 'hook_event_name': 'PreToolUse', 'tool_name': 'Agent',
                   'tool_use_id': 'toolu_planner_1', 'cwd': str(self.folder),
                   'tool_input': {'prompt': 'Read %s and propose the team.' % brief, 'description': 'the planner'}}
        done = subprocess.run([sys.executable, str(CAPTURE), 'PreToolUse', '--ledger', str(self.ledger)],
                              input=json.dumps(payload), capture_output=True, text=True, env=clean_env(), timeout=60)
        self.assertEqual(done.returncode, 0, done.stderr)
        rows = [json.loads(line) for line in (self.ledger / ('%s.jsonl' % SESSION)).read_text(
            encoding='utf-8').splitlines() if line.strip()]
        dispatch = [row for row in rows if row.get('record') == 'dispatch'][0]
        self.assertIn('planner\'s own dispatch, plan request %s' % request, dispatch.get('member', ''))
        self.assertFalse(pending.exists())

    def test_the_plan_takes_the_planner_s_request_id(self):
        code, out = self.run_plan('planner', '--ledger', self.ledger, '--session', SESSION)
        self.assertEqual(code, 0, out)
        code, result, path = self.write(self.team(), extra=['--plan-request', out['plan_request']])
        self.assertEqual(code, 0, result)
        self.assertEqual(json.loads(path.read_text(encoding='utf-8'))['plan_request'], out['plan_request'])


if __name__ == '__main__':
    unittest.main()
