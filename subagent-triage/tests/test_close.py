"""Tests for close.py: closing a plan. It marks each hop cited or not cited by the citation rule (R-8; TC-14), and
reports the parts dispatched below the persona decision's line (R-29), the dispatches the plan does not list and the
planner's and members' own dispatches apart (TC-6), the override rates by probability band and by parent (TC-3), the
effort passed against the effort decision's (TC-22), and every pending triage file whose dispatch never happened,
removing none (T-7).

Each test writes its dispatch and return records through the ledger skill's own writer, ledger.py, into a temporary
ledger folder proved so before anything runs, and a parent transcript of assistant rows in Claude Code's form.

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
SCRIPTS = HERE.parent / 'skill' / 'scripts'
SCRIPT = SCRIPTS / 'close.py'
PLAN_SCRIPT = SCRIPTS / 'plan.py'
LEDGER_SCRIPTS = HERE.parent.parent / 'subagent-ledger' / 'skill' / 'scripts'
SESSION = '0e0e0e0e-1111-4222-8333-555555555555'
WRITTEN = '2026-01-15T00:00:00.000000Z'
NO_PENDING = 'unrecorded (no pending triage file for this call)'
SYNTHESIS = ('The two reports agree that the export flag should print every file it would write, name each '
             'target folder, and leave the store untouched until the parent confirms the run by hand.')
PLANNER_MEMBER = "unrecorded (the planner's own dispatch, plan request plan-1: its brief carries no member)"

sys.path.insert(0, str(LEDGER_SCRIPTS))
import ledger  # noqa: E402


def at(minute, second=0):
    return '2026-01-15T00:%02d:%02d.000Z' % (minute, second)


def stamped(value, when):
    return {'value': value, 'stamped_at': when}


def clean_env():
    env = dict(os.environ)
    for name in ('SUBAGENT_LEDGER_DIR', 'SUBAGENT_LEDGER_SCRIPTS'):
        env.pop(name, None)
    return env


class CloseTests(unittest.TestCase):

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.ledger = self.tmp / 'ledger'
        self.ledger.mkdir()
        (self.ledger / 'config.json').write_text('{"fields": "all"}', encoding='utf-8')
        self.team = self.tmp / 'team'
        self.team.mkdir()
        for path in (self.ledger, self.team):
            # Where every write lands, proved before anything runs: inside this test's own temporary folder.
            self.assertTrue(str(path.resolve()).startswith(str(Path(tempfile.gettempdir()).resolve())))
        self.transcript = self.team / 'parent.jsonl'
        self.rows = []

    def tearDown(self):
        shutil.rmtree(str(self.tmp), ignore_errors=True)

    # -- Builders -----------------------------------------------------------------------------------------------------

    def plan(self, members, parallel, synthesiser='parent', hops=None, pattern=None):
        entries = []
        for member, kind in members:
            entries.append({'member': member, 'attempt': 1, 'part': 'Part %s.' % member, 'act_kind': kind,
                            'persona': 'builder', 'brief': str(self.team / ('%s-1.md' % member)),
                            'repository': 'none', 'write_set': 'none'})
        if hops is None:
            hops = [{'from': m, 'to': 'parent', 'kind': 'synthesis' if m == synthesiser else 'return', 'cited': None}
                    for m, _ in members]
        plan = {'plan_request': 'plan-1', 'task': '2026-01-15-report', 'written_at': WRITTEN,
                'pattern': pattern or sorted(set(kind for _, kind in members)), 'members': entries,
                'parallel': parallel, 'synthesiser': synthesiser, 'hops': hops, 'changes': []}
        path = self.team / 'plan.json'
        path.write_text(json.dumps(plan, indent=1), encoding='utf-8')
        return path

    def dispatch(self, call, member, attempt=1, when=None, caller='parent', persona='builder', effort='medium',
                 unaided=('medium', at(0, 10)), records=None, records_at=at(0, 20), overrides=None, below=None,
                 extra=None):
        fields = {'session': SESSION, 'call_id': call, 'agent_id': 'unrecorded (not yet returned)',
                  'dispatched_at': when or at(1), 'route': 'subagent', 'harness': 'claude-code', 'caller': caller,
                  'member': member, 'attempt': attempt, 'effort_assigned': effort,
                  'continues_call_id': 'unrecorded (not a resumption)',
                  'harness_payload': {'transcript_path': str(self.transcript)}}
        fields['persona-name'] = persona
        if unaided is not None:
            fields['effort_unaided'] = stamped(unaided[0], unaided[1])
            fields['decision_records'] = stamped(records if records is not None else [
                {'question': 'd3-figure', 'answer': persona, 'uncertainty_basis': {'adequacy': 0.9, 'line': 0.5}},
                {'question': 'd4-effort', 'answer': 'medium'}], records_at)
        for name, value in (('overrides', overrides), ('below_line', below)):
            if value is not None:
                fields[name] = stamped(value, at(0, 30))
        fields.update(extra or {})
        written = ledger.dispatch(ledger=str(self.ledger), brief='A brief for %s.' % member, **fields)
        self.assertTrue(written.ok, written)

    def returned(self, call, answer, when, agent='agent-x'):
        written = ledger.ret(call, ledger=str(self.ledger), answer=answer, session=SESSION, agent_id=agent,
                             returned_at=when, outcome='served', outcome_reason='none (served)', route='subagent',
                             caller='parent')
        self.assertTrue(written.ok, written)

    def say(self, when, text=None, tool=None, given=None):
        block = {'type': 'text', 'text': text} if tool is None else {'type': 'tool_use', 'id': 'toolu_%d' % len(
            self.rows), 'name': tool, 'input': given or {}}
        self.rows.append({'type': 'assistant', 'timestamp': when, 'isSidechain': False,
                          'message': {'role': 'assistant', 'content': [block]}})
        self.transcript.write_text('\n'.join(json.dumps(row) for row in self.rows) + '\n', encoding='utf-8')

    def close(self, plan, *extra):
        done = subprocess.run([sys.executable, str(SCRIPT), '--plan', str(plan), '--session', SESSION,
                               '--ledger', str(self.ledger)] + list(extra), capture_output=True, text=True,
                              env=clean_env(), timeout=60)
        try:
            out = json.loads(done.stdout)
        except ValueError:
            self.fail('no JSON on stdout (exit %s): %s %s' % (done.returncode, done.stdout, done.stderr))
        return done.returncode, out

    def hop(self, out, member):
        found = [hop for hop in out['hops'] if hop['from'] == member]
        self.assertEqual(len(found), 1, out['hops'])
        return found[0]

    def team_of_three(self):
        plan = self.plan([('m1', 'build'), ('m2', 'verdict-or-review'), ('m3', 'deliberation')],
                         [['m1', 'm2'], ['m3']], synthesiser='m3')
        self.dispatch('toolu_m1', 'm1')
        self.returned('toolu_m1', 'Built.\n\n## Output\ntables/summary.md\n', at(3))
        self.dispatch('toolu_m2', 'm2')
        self.returned('toolu_m2', 'Reviewed.\n\n## Output\nnone\n', at(4))
        self.dispatch('toolu_m3', 'm3', when=at(5))
        self.returned('toolu_m3', SYNTHESIS + '\n\n## Output\nnone\n', at(7))
        return plan

    # -- TC-14: marking hops ------------------------------------------------------------------------------------------

    def test_tc14_empty_a_team_with_no_hop_marks_nothing(self):
        plan = self.plan([('m1', 'build')], [['m1']], hops=[])
        self.dispatch('toolu_m1', 'm1')
        self.returned('toolu_m1', 'Built.\n\n## Output\nnone\n', at(3))
        self.say(at(4), 'Done.')
        code, out = self.close(plan)
        self.assertEqual(code, 0, out)
        self.assertEqual(out['hops'], [])
        closed = json.loads(plan.read_text(encoding='utf-8'))
        self.assertEqual(closed['hops'], [])
        self.assertRegex(closed['closed_at'], r'^\d{4}-')

    def test_tc14_likeness_a_synthesis_the_parent_opens_and_ignores_is_not_cited(self):
        plan = self.team_of_three()
        self.say(at(8), tool='Read', given={'file_path': '/work/synthesis.md'})
        self.say(at(8, 30), 'I will now update the changelog for the release.')
        code, out = self.close(plan)
        hop = self.hop(out, 'm3')
        self.assertIs(hop['cited'], False)
        self.assertEqual(hop['output']['kind'], 'reply')
        self.assertIs(json.loads(plan.read_text(encoding='utf-8'))['hops'][2]['cited'], False)

    def test_tc14_likeness_an_inline_synthesis_quoted_twenty_words_is_cited(self):
        plan = self.team_of_three()
        words = SYNTHESIS.split()
        self.say(at(8), 'The synthesis says:\n\n> %s\n> %s\n\nSo I will go ahead.' % (
            ' '.join(words[2:12]), ' '.join(words[12:22])))
        code, out = self.close(plan)
        hop = self.hop(out, 'm3')
        self.assertIs(hop['cited'], True)
        self.assertIn('20 words', hop['citation'])
        marked = json.loads(plan.read_text(encoding='utf-8'))['hops'][2]
        self.assertIs(marked['cited'], True)
        self.assertEqual(marked['citation'], hop['citation'])

    def test_tc14_likeness_a_synthesis_acted_on_by_paraphrase_is_reported_not_cited(self):
        plan = self.team_of_three()
        words = SYNTHESIS.split()
        self.say(at(8), 'In short: %s, and then something else entirely.' % ' '.join(words[2:21]))
        code, out = self.close(plan)
        hop = self.hop(out, 'm3')
        self.assertIs(hop['cited'], False)
        self.assertIn(' '.join(words[2:6]), hop['output']['text'])

    def test_a_hop_whose_output_path_the_parent_names_is_cited(self):
        plan = self.team_of_three()
        self.say(at(5, 30), 'The summary is at `tables/summary.md`; the review passed.')
        self.say(at(8), 'All done.')
        code, out = self.close(plan)
        self.assertIs(self.hop(out, 'm1')['cited'], True)
        self.assertIn('tables/summary.md', self.hop(out, 'm1')['citation'])
        self.assertIs(self.hop(out, 'm3')['cited'], False)

    def test_a_hop_s_call_id_in_the_next_dispatch_prompt_or_a_written_file_is_cited(self):
        plan = self.team_of_three()
        self.say(at(4, 30), tool='Agent', given={'prompt': 'Weigh toolu_m1 and toolu_m2 into one report.'})
        self.say(at(8), tool='Write', given={'file_path': '/work/notes.md', 'content': 'From toolu_m3: agreed.'})
        code, out = self.close(plan)
        self.assertIs(self.hop(out, 'm1')['cited'], True)
        self.assertEqual(self.hop(out, 'm1')['output']['kind'], 'dispatch prompt')
        self.assertIs(self.hop(out, 'm3')['cited'], True)
        self.assertEqual(self.hop(out, 'm3')['output']['kind'], 'file')

    def test_a_parallel_group_is_read_after_its_last_return(self):
        plan = self.team_of_three()
        # m1 returned at 00:03 and m2 at 00:04; an output between the two is not the group's first output.
        self.say(at(3, 30), 'The summary is at tables/summary.md.')
        self.say(at(4, 30), 'Both are back.')
        code, out = self.close(plan)
        self.assertIs(self.hop(out, 'm1')['cited'], False)
        self.assertEqual(self.hop(out, 'm1')['output']['text'], 'Both are back.')

    def test_a_hop_with_no_return_is_not_cited(self):
        plan = self.plan([('m1', 'build')], [['m1']])
        self.dispatch('toolu_m1', 'm1')
        self.say(at(8), 'Still waiting.')
        code, out = self.close(plan, '--transcript', str(self.transcript))
        self.assertIs(self.hop(out, 'm1')['cited'], False)
        self.assertIn('no return', self.hop(out, 'm1')['reason'])

    def test_tc14_the_next_plan_of_the_pattern_leaves_out_the_hop_close_marked_not_cited(self):
        plan = self.team_of_three()
        self.say(at(8), 'I will now update the changelog for the release.')
        code, out = self.close(plan)
        self.assertIs(self.hop(out, 'm3')['cited'], False)
        for member in ('a', 'b', 'c'):
            (self.team / ('%s-1.md' % member)).write_text('A brief.\n', encoding='utf-8')
        proposal = {'task': '2026-01-16-report', 'synthesiser': 'c', 'parallel': [['a', 'b'], ['c']], 'members': [
            {'member': m, 'part': 'Part %s.' % m, 'act_kind': k, 'persona': 'builder',
             'brief': str(self.team / ('%s-1.md' % m)), 'repository': 'none', 'write_set': 'none'}
            for m, k in (('a', 'build'), ('b', 'verdict-or-review'), ('c', 'deliberation'))]}
        (self.tmp / 'proposal.json').write_text(json.dumps(proposal), encoding='utf-8')
        done = subprocess.run([sys.executable, str(PLAN_SCRIPT), 'write', '--proposal', str(self.tmp / 'proposal.json'),
                               '--out', str(self.team / 'plan-next.json')], capture_output=True, text=True,
                              env=clean_env(), timeout=60)
        self.assertEqual(done.returncode, 0, done.stdout + done.stderr)
        self.assertEqual(json.loads(done.stdout)['left_out'], [{'from': 'c', 'to': 'parent', 'kind': 'synthesis'}])

    def test_a_closed_plan_is_not_closed_again(self):
        plan = self.team_of_three()
        self.say(at(8), 'Done.')
        code, out = self.close(plan)
        before = plan.read_text(encoding='utf-8')
        code, out = self.close(plan)
        self.assertEqual(code, 1, out)
        self.assertIn('already closed', out['error'])
        self.assertEqual(plan.read_text(encoding='utf-8'), before)

    # -- TC-6: what was dispatched against what was planned -----------------------------------------------------------

    def test_tc6_likeness_a_dispatch_whose_member_the_plan_does_not_list_is_reported(self):
        plan = self.team_of_three()
        self.dispatch('toolu_m9', 'm9', when=at(6))
        self.say(at(8), 'Done.')
        code, out = self.close(plan)
        self.assertEqual(code, 3, out)
        self.assertEqual([d['call_id'] for d in out['dispatches']['not_in_plan']], ['toolu_m9'])
        self.assertTrue(any('toolu_m9' == fault['call_id'] for fault in out['faults']))

    def test_tc6_the_planner_s_own_and_a_member_s_own_dispatch_are_each_counted_apart(self):
        plan = self.team_of_three()
        self.dispatch('toolu_planner', PLANNER_MEMBER, attempt=PLANNER_MEMBER, when=at(0, 40), unaided=None)
        self.dispatch('toolu_inner', 'm1', when=at(2), caller='agent-member-1', unaided=None)
        self.say(at(8), 'Done.')
        code, out = self.close(plan)
        self.assertEqual(code, 0, out)
        counted = out['dispatches']
        self.assertEqual([d['call_id'] for d in counted['planner']], ['toolu_planner'])
        self.assertEqual([d['call_id'] for d in counted['members_own']], ['toolu_inner'])
        self.assertEqual(counted['not_in_plan'], [])
        self.assertEqual((counted['planned'], counted['dispatched']), (3, 3))

    def test_a_resumption_is_left_out_of_the_counts(self):
        plan = self.team_of_three()
        self.dispatch('toolu_resume', 'm1', when=at(6), unaided=None,
                      extra={'continues_call_id': 'toolu_m1'})
        self.say(at(8), 'Done.')
        code, out = self.close(plan)
        self.assertEqual(code, 0, out)
        self.assertEqual(out['dispatches']['resumptions_left_out'], 1)

    # -- R-29: below the line -----------------------------------------------------------------------------------------

    def test_the_parts_dispatched_below_the_line_are_counted_and_named(self):
        plan = self.plan([('m1', 'build'), ('m2', 'build')], [['m1', 'm2']])
        self.dispatch('toolu_m1', 'm1', below={'probability': 0.2, 'line': 0.5, 'line_version': 0})
        self.dispatch('toolu_m2', 'm2')
        self.say(at(8), 'Done.')
        code, out = self.close(plan)
        self.assertEqual(out['below_line']['count'], 1)
        part, = out['below_line']['parts']
        self.assertEqual((part['member'], part['probability'], part['line'], part['line_version']),
                         ('m1', 0.2, 0.5, 0))

    # -- T-7: pending files whose dispatch never happened -------------------------------------------------------------

    def test_pending_triage_files_never_dispatched_are_reported_and_none_removed(self):
        plan = self.team_of_three()
        folder = self.ledger / '.pending' / SESSION
        folder.mkdir(parents=True, exist_ok=True)
        left = [folder / 'triage-m4-1.json', folder / 'planner-plan-9.json']
        for path in left:
            path.write_text('{}', encoding='utf-8')
        self.say(at(8), 'Done.')
        code, out = self.close(plan)
        self.assertEqual(sorted(out['pending_never_dispatched']), ['planner-plan-9.json', 'triage-m4-1.json'])
        for path in left:
            self.assertTrue(path.is_file())

    # -- TC-3: override rates -----------------------------------------------------------------------------------------

    def test_tc3_empty_zero_overrides_over_zero_dispatches_is_zero_of_zero(self):
        plan = self.plan([('m1', 'build')], [['m1']])
        self.dispatch('toolu_m1', 'm1', unaided=None)
        self.say(at(8), 'Done.')
        code, out = self.close(plan)
        rates = out['overrides']['persona']
        self.assertEqual(rates['overall'], '0 of 0')
        self.assertTrue(all(value == '0 of 0' for value in rates['by_band'].values()))
        self.assertNotIn('%', json.dumps(out['overrides']))

    def test_tc3_override_rates_by_band_and_by_parent(self):
        plan = self.plan([('m1', 'build'), ('m2', 'build'), ('m3', 'build')], [['m1', 'm2', 'm3']])
        d3 = lambda p: [{'question': 'd3-figure', 'answer': 'builder', 'uncertainty_basis': {'adequacy': p}},
                        {'question': 'd4-effort', 'answer': 'medium'}]
        override = {'decision': 'd3-figure', 'decision_persona': 'builder', 'adequacy_probability': 0.85,
                    'parent_persona': 'lead', 'persona_chosen': 'cataloguer', 'reason': 'a catalogue part',
                    'at': at(0, 25)}
        self.dispatch('toolu_m1', 'm1', records=d3(0.9))
        self.dispatch('toolu_m2', 'm2', persona='cataloguer', records=d3(0.85), overrides=[override])
        self.dispatch('toolu_m3', 'm3', records=d3(0.3))
        self.say(at(8), 'Done.')
        code, out = self.close(plan, '--parent', 'lead')
        self.assertEqual(code, 0, out)
        rates = out['overrides']['persona']
        self.assertEqual(rates['overall'], '1 of 3')
        self.assertEqual(rates['by_band']['0.8 to 0.9'], '1 of 1')
        self.assertEqual(rates['by_band']['0.9 to 1.0'], '0 of 1')
        self.assertEqual(rates['by_band']['0.3 to 0.4'], '0 of 1')
        self.assertEqual(rates['by_parent'], {'lead': '1 of 3'})

    def test_tc3_likeness_an_override_lacking_its_reason_or_probability_is_a_fault(self):
        plan = self.plan([('m1', 'build')], [['m1']])
        override = {'decision': 'd3-figure', 'decision_persona': 'builder', 'parent_persona': 'lead',
                    'persona_chosen': 'cataloguer', 'at': at(0, 25)}
        self.dispatch('toolu_m1', 'm1', persona='cataloguer', overrides=[override])
        self.say(at(8), 'Done.')
        code, out = self.close(plan)
        self.assertEqual(code, 3, out)
        fault, = [f for f in out['faults'] if f['call_id'] == 'toolu_m1']
        self.assertIn('reason', fault['fault'])
        self.assertIn('adequacy_probability', fault['fault'])

    # -- TC-22: the effort passed -------------------------------------------------------------------------------------

    def test_tc22_likeness_a_passed_effort_differing_from_d4_s_with_no_override_is_a_fault(self):
        plan = self.plan([('m1', 'build')], [['m1']])
        self.dispatch('toolu_m1', 'm1', effort='high')
        self.say(at(8), 'Done.')
        code, out = self.close(plan)
        self.assertEqual(code, 3, out)
        fault, = out['faults']
        self.assertIn('high', fault['fault'])
        self.assertIn('medium', fault['fault'])

    def test_an_effort_override_on_the_record_makes_the_passed_effort_right(self):
        plan = self.plan([('m1', 'build')], [['m1']])
        override = {'decision': 'd4-effort', 'decision_level': 'medium', 'level_passed': 'high',
                    'reason': 'three schemas', 'at': at(0, 25)}
        self.dispatch('toolu_m1', 'm1', effort='high', overrides=[override])
        self.say(at(8), 'Done.')
        code, out = self.close(plan)
        self.assertEqual(code, 0, out)
        self.assertEqual(out['faults'], [])
        self.assertEqual(out['overrides']['effort']['overall'], '1 of 1')

    def test_tc22_empty_with_no_level_from_d4_the_unaided_level_is_the_one_passed(self):
        plan = self.plan([('m1', 'build'), ('m2', 'build')], [['m1', 'm2']])
        records = [{'question': 'd4-effort', 'answer': 'unrecorded (Jev failed: HTTP 500)'}]
        self.dispatch('toolu_m1', 'm1', effort='low', unaided=('low', at(0, 10)), records=records)
        self.dispatch('toolu_m2', 'm2', effort='medium', unaided=('low', at(0, 10)), records=records)
        self.say(at(8), 'Done.')
        code, out = self.close(plan)
        self.assertEqual(code, 3, out)
        self.assertEqual([f['call_id'] for f in out['faults']], ['toolu_m2'])
        self.assertIn('unaided', out['faults'][0]['fault'])

    def test_tc22_likeness_the_unaided_level_stamped_after_d4_s_is_a_fault(self):
        plan = self.plan([('m1', 'build')], [['m1']])
        self.dispatch('toolu_m1', 'm1', unaided=('medium', at(0, 40)), records_at=at(0, 20))
        self.say(at(8), 'Done.')
        code, out = self.close(plan)
        self.assertEqual(code, 3, out)
        self.assertIn('stamped after', out['faults'][0]['fault'])


if __name__ == '__main__':
    unittest.main()
