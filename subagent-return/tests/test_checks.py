"""Controls for the four checks, each run as the ledger's wrapper runs it, at a member's hand-back and stop.

TC-8 to TC-12 and TC-21 of the specification, and the misread rows of the dry run that asked why a check cannot run
(rows 5, 6, 8, 9, 10 and 13). Each criterion has its paired cases: an empty one (zero of the thing, which must give a
stated reason, never a silent pass) and a likeness (the right shape with the wrong substance, which must be told
apart). They were committed before the checks existed, and each failed then.

Each test builds its own world (world.py): a git repository, members with briefs and transcripts, a worktree per
writer, and a ledger of its own. The front-matter validator is a stand-in. No test calls a live service.

Run from the skill's folder:  python3 -m unittest discover -s tests
"""

import calendar
import json
import os
import shutil
import sys
import tempfile
import time
import unittest
from pathlib import Path

import world
from world import BAD_FRONT, GOOD_FRONT, report


class Base(unittest.TestCase):

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix='return-check-'))
        self.addCleanup(shutil.rmtree, str(self.tmp), True)
        self.w = world.World(self.tmp)
        self.w.start()

    def at_handback(self, member, message):
        """Hand back `message` and return its witness line's results, {check: result}."""
        decision = self.w.handback(member, message)
        self.assertIsNone(self.w.denied(decision), 'the check refuses no hand-back')
        line = self.w.witnesses(member, 'PreToolUse')[-1]
        return self.w.results(line)

    def assertResult(self, found, check, value, reason=None):
        self.assertEqual(found[check]['result'], value, found[check])
        if reason is not None:
            self.assertIn(reason, found[check].get('reason') or '', found[check])
        if value == 'fail':
            self.assertTrue(found[check].get('repair'), 'a fail carries a recommended repair: %s' % found[check])


class Authorship(Base):
    """TC-8: check 1 reads the report's output section and judges each claim."""

    def test_tc8_empty_none_and_no_markdown_gives_checks_1_and_2_not_applicable_and_3_and_4_still_run(self):
        m = self.w.member('reader', None)
        self.w.dispatch(m)
        found = self.at_handback(m, report())
        self.assertResult(found, 1, 'not_applicable')
        self.assertResult(found, 2, 'not_applicable')
        self.assertResult(found, 3, 'pass')
        self.assertResult(found, 4, 'pass')

    def test_tc8_likeness_a_claimed_existing_file_the_member_did_not_write_fails(self):
        m = self.w.member('claimer', ['docs/'])
        self.w.dispatch(m)
        found = self.at_handback(m, report('docs/existing.md'))
        self.assertResult(found, 1, 'fail', 'docs/existing.md')
        self.assertEqual(found[1]['paths'], ['docs/existing.md'])

    def test_tc8_a_claimed_file_that_does_not_exist_fails_naming_it(self):
        m = self.w.member('ghost', ['docs/'])
        self.w.dispatch(m)
        found = self.at_handback(m, report('docs/missing.md'))
        self.assertResult(found, 1, 'fail', 'does not exist: docs/missing.md')

    def test_tc8_empty_a_report_with_no_output_section_fails_with_its_reason(self):
        m = self.w.member('silent', ['docs/'])
        self.w.dispatch(m)
        found = self.at_handback(m, 'I wrote docs/new.md.')
        self.assertResult(found, 1, 'fail', 'no output section')

    def test_tc8_empty_an_empty_output_section_fails_as_malformed(self):
        m = self.w.member('blank', ['docs/'])
        self.w.dispatch(m)
        found = self.at_handback(m, 'Done.\n\n## Output\n\n')
        self.assertResult(found, 1, 'fail', 'output section malformed')

    def test_tc8_likeness_the_planners_own_dispatch_with_no_section_is_not_applicable(self):
        m = self.w.member('planner', None, brief=False)
        self.w.dispatch(m)
        found = self.at_handback(m, 'Here is the plan, with no section.')
        self.assertResult(found, 1, 'not_applicable', 'no member brief')

    def test_tc8_a_correct_file_written_by_a_command_in_a_writers_worktree_passes_checks_1_and_4(self):
        m = self.w.member('scripter', ['src/'])
        self.w.dispatch(m)
        m.shell("printf 'x = 1\\n' > src/new.py")
        found = self.at_handback(m, report('src/new.py'))
        self.assertResult(found, 1, 'pass')
        self.assertResult(found, 2, 'not_applicable')
        self.assertResult(found, 4, 'pass')

    def test_tc8_a_correct_python_file_written_by_write_passes_checks_1_and_4_with_check_2_not_applicable(self):
        m = self.w.member('coder', ['src/'])
        self.w.dispatch(m)
        m.write('src/good.py', 'print(2)\n')
        found = self.at_handback(m, report('src/good.py'))
        self.assertEqual([found[n]['result'] for n in (1, 2, 3, 4)], ['pass', 'not_applicable', 'pass', 'pass'])

    def test_tc8_likeness_a_read_only_reviewer_citing_inputs_in_prose_with_section_none_is_not_applicable(self):
        m = self.w.member('reviewer', None)
        self.w.dispatch(m)
        found = self.at_handback(m, report(prose='I read `docs/existing.md` and `src/app.py`; they agree.'))
        self.assertResult(found, 1, 'not_applicable')

    def test_tc8_a_read_only_members_write_fails_check_4_and_its_claim_fails_check_1(self):
        m = self.w.member('meddler', None)
        self.w.dispatch(m)
        m.write('docs/meddled.md', GOOD_FRONT)
        found = self.at_handback(m, report('docs/meddled.md'))
        self.assertResult(found, 1, 'fail', 'read-only member claims output')
        self.assertResult(found, 4, 'fail', 'docs/meddled.md')

    def test_tc8_a_hand_back_claiming_a_missing_file_fails_from_its_message_not_the_closing_text(self):
        m = self.w.member('closer', ['docs/'])
        self.w.dispatch(m)
        found = self.at_handback(m, report('missing.md'))
        self.assertResult(found, 1, 'fail', 'missing.md')
        line = self.w.witnesses(m, 'PreToolUse')[-1]
        self.assertEqual(self.w.runs(line)[0]['report'], 'hand-back message')
        self.w.stop(m, closing='Closing words.\n\n## Output\nnone\n')
        stop = self.w.witnesses(m, 'SubagentStop')[-1]
        self.assertResult(self.w.results(stop), 1, 'fail', 'missing.md')
        self.assertEqual(self.w.runs(stop)[0]['report'], 'hand-back message')

    def test_tc8_likeness_a_good_hand_back_whose_closing_text_has_no_section_passes(self):
        m = self.w.member('tidy', ['docs/'])
        self.w.dispatch(m)
        m.write('docs/tidy.md', GOOD_FRONT)
        self.assertResult(self.at_handback(m, report('docs/tidy.md')), 1, 'pass')
        self.w.stop(m, closing='All done, no section here.')
        stop = self.w.witnesses(m, 'SubagentStop')[-1]
        self.assertResult(self.w.results(stop), 1, 'pass')


class Frontmatter(Base):
    """TC-8 and dry run 10, rows 6 and 7: check 2 reads what the member wrote, and the validator's text."""

    def test_tc8_bad_front_matter_with_section_none_fails_check_2_naming_the_file(self):
        m = self.w.member('scribe', ['docs/'])
        self.w.dispatch(m)
        m.write('docs/bad.md', BAD_FRONT)
        found = self.at_handback(m, report())
        self.assertResult(found, 1, 'not_applicable')
        self.assertResult(found, 2, 'fail', "Missing required field: 'type'")
        self.assertTrue(found[2]['paths'][0].endswith('docs/bad.md'), found[2])

    def test_tc8_likeness_good_front_matter_passes_check_2(self):
        m = self.w.member('scribe-ok', ['docs/'])
        self.w.dispatch(m)
        m.write('docs/good.md', GOOD_FRONT)
        self.assertResult(self.at_handback(m, report('docs/good.md')), 2, 'pass')

    def test_row6_an_excluded_path_reads_not_checkable_from_the_validators_text(self):
        m = self.w.member('excluder', ['docs/'])
        self.w.dispatch(m)
        m.write('docs/excluded/page.md', GOOD_FRONT)
        self.assertResult(self.at_handback(m, report()), 2, 'not_checkable', '0 files examined')

    def test_row6_control_read_by_its_exit_code_alone_the_excluded_path_misreads_as_fail(self):
        self.w.configure(settings={'validator_not_checkable': []})
        m = self.w.member('excluder-code', ['docs/'])
        self.w.dispatch(m)
        m.write('docs/excluded/page.md', GOOD_FRONT)
        self.assertResult(self.at_handback(m, report()), 2, 'fail')

    def test_row6_a_missing_path_reads_not_checkable(self):
        m = self.w.member('deleter', ['docs/'])
        self.w.dispatch(m)
        m.write('docs/gone.md', GOOD_FRONT)
        (m.root / 'docs' / 'gone.md').unlink()
        self.assertResult(self.at_handback(m, report()), 2, 'not_checkable', 'path not found')

    def test_row6_a_validator_that_cannot_read_its_own_inputs_reads_not_checkable(self):
        self.w.configure(settings={'validator': 'env STAND_IN_VALIDATOR_BROKEN=1 "%s" "%s"' % (
            sys.executable, world.VALIDATOR)})
        m = self.w.member('broken', ['docs/'])
        self.w.dispatch(m)
        m.write('docs/fine.md', GOOD_FRONT)
        self.assertResult(self.at_handback(m, report()), 2, 'not_checkable', 'VISIBLE ERROR')

    def test_check2_empty_no_validator_set_is_not_checkable(self):
        self.w.configure(settings={'validator': ''})
        m = self.w.member('unset', ['docs/'])
        self.w.dispatch(m)
        m.write('docs/any.md', GOOD_FRONT)
        self.assertResult(self.at_handback(m, report()), 2, 'not_checkable', 'no front-matter validator')


class Ledger(Base):
    """TC-9 and dry run 10, row 13: check 3 tells a missing record from a missing ledger and a killed hook."""

    def test_tc9_empty_with_the_capture_stopped_every_member_reads_ledger_absent_and_no_parent_call_is_refused(self):
        tmp = Path(tempfile.mkdtemp(prefix='return-check-off-'))
        self.addCleanup(shutil.rmtree, str(tmp), True)
        w = world.World(tmp)
        members = [w.member('one', None), w.member('two', None)]
        for m in members:
            w.dispatch(m)
            # The capture was off: no session-start line, and none of the dispatch records it would have written.
            (w.ledger / ('%s.jsonl' % world.SESSION)).unlink()
            w.handback(m, report())
            self.assertEqual(w.results(w.witnesses(m, 'PreToolUse')[-1])[3]['result'], 'ledger_absent')
        _code, decision, _err = w.parent('Write', {'file_path': str(w.repo / 'x.md'), 'content': 'x'})
        self.assertIsNone(w.denied(decision), 'ledger_absent stops nothing')

    def test_tc9_likeness_with_the_capture_running_and_the_dispatch_record_deleted_check_3_fails(self):
        m = self.w.member('lost', None)
        self.w.dispatch(m)
        path = self.w.ledger / ('%s.jsonl' % world.SESSION)
        kept = [r for r in world.lines(path) if r.get('record') != 'dispatch']
        path.write_text(''.join(json.dumps(r) + '\n' for r in kept), encoding='utf-8')
        found = self.at_handback(m, report())
        self.assertResult(found, 3, 'fail', 'member lost attempt 1')

    def test_row13_a_dispatch_whose_hook_was_cancelled_reads_not_checkable_not_fail(self):
        m = self.w.member('killed', None)
        # The harness killed the dispatch's wrapper at its time limit: no dispatch record, and its note in the
        # parent's transcript (dry run 2).
        self.w.parent_rows.append({'type': 'attachment', 'attachment': {
            'type': 'hook_cancelled', 'hookName': 'PreToolUse:Agent', 'toolUseID': m.call_id,
            'hookEvent': 'PreToolUse', 'durationMs': 3011, 'timedOut': True, 'timeoutMs': 3000}})
        self.w.flush_parent()
        found = self.at_handback(m, report())
        self.assertResult(found, 3, 'not_checkable', "dispatch's hook was cancelled")

    def test_row13_control_the_same_missing_record_with_no_cancelled_hook_fails(self):
        m = self.w.member('unrecorded', None)
        found = self.at_handback(m, report())
        self.assertResult(found, 3, 'fail')


class WriteSet(Base):
    """TC-8, TC-11 and TC-21: check 4 reads the worktree's changes and the transcript's writes."""

    def test_tc8_a_write_to_the_scratch_folder_never_fails_check_4(self):
        for name, write_set in (('scratch-reader', None), ('scratch-writer', ['docs/'])):
            with self.subTest(member=name):
                m = self.w.member(name, write_set)
                self.w.dispatch(m)
                m.write(None, 'notes', path=self.w.scratchpad / ('%s.txt' % name))
                self.assertResult(self.at_handback(m, report()), 4, 'pass')

    def test_tc8_a_writers_write_by_absolute_path_outside_the_repository_fails_from_the_transcript(self):
        m = self.w.member('stray', ['docs/'])
        self.w.dispatch(m)
        target = self.w.outside / 'stray.txt'
        m.write(None, 'x', path=target)
        found = self.at_handback(m, report())
        self.assertResult(found, 4, 'fail', os.path.realpath(str(target)))

    def test_tc8_likeness_a_write_through_another_spelling_of_the_worktree_is_not_failed(self):
        m = self.w.member('spelled', ['docs/'])
        self.w.dispatch(m)
        link = self.tmp / 'link'
        link.symlink_to(m.root)
        m.write(None, GOOD_FRONT, path=link / 'docs' / 'spelled.md')
        self.assertResult(self.at_handback(m, report('docs/spelled.md')), 4, 'pass')

    def test_tc8_a_tool_call_listed_twice_under_one_id_is_counted_once(self):
        m = self.w.member('echo', ['docs/'])
        self.w.dispatch(m)
        m.write(None, 'x', path=self.w.outside / 'twice.txt', twice=True)
        found = self.at_handback(m, report())
        self.assertResult(found, 4, 'fail')
        self.assertEqual(len(found[4]['paths']), 1, found[4])

    def test_tc8_si5_out_of_scope_by_a_write_call_inside_the_worktree_outside_its_set_fails(self):
        m = self.w.member('scope-write', ['docs/'])
        self.w.dispatch(m)
        m.write('src/other.py', 'print(3)\n')
        self.assertResult(self.at_handback(m, report()), 4, 'fail', 'src/other.py')

    def test_tc8_tc21_si5_out_of_scope_by_a_shell_command_inside_the_worktree_fails_from_the_diff(self):
        m = self.w.member('scope-shell', ['docs/'])
        self.w.dispatch(m)
        m.shell("printf 'y\\n' > src/shelled.py")
        self.assertResult(self.at_handback(m, report()), 4, 'fail', 'src/shelled.py')

    def test_tc21_a_notebook_edit_outside_the_set_fails_naming_its_notebook_path(self):
        m = self.w.member('notebook', ['docs/'])
        self.w.dispatch(m)
        target = self.w.outside / 'lab.ipynb'
        m.write(None, '{}', tool='NotebookEdit', path=target)
        self.assertResult(self.at_handback(m, report()), 4, 'fail', os.path.realpath(str(target)))

    def test_tc21_empty_a_member_that_called_no_shell_is_not_shell_using(self):
        m = self.w.member('quiet', None)
        self.w.dispatch(m)
        found = self.at_handback(m, report())
        self.assertResult(found, 4, 'pass')
        self.assertNotIn('residue', found[4])

    def test_row10_a_read_only_member_that_used_a_shell_reads_not_checkable(self):
        m = self.w.member('grepper', None)
        self.w.dispatch(m)
        m.shell('true')
        self.assertResult(self.at_handback(m, report()), 4, 'not_checkable', 'shell writes not checkable')

    def test_row10_likeness_a_shell_using_writer_with_no_fail_passes_with_the_residue_stated(self):
        m = self.w.member('builder', ['src/'])
        self.w.dispatch(m)
        m.shell("printf 'z\\n' > src/built.py")
        found = self.at_handback(m, report('src/built.py'))
        self.assertResult(found, 4, 'pass')
        self.assertIn('shell writes outside the worktree', found[4]['residue'])

    def test_tc11_empty_a_check_4_fail_leaves_the_worktree_in_place(self):
        m = self.w.member('kept', ['docs/'])
        self.w.dispatch(m)
        m.write('src/outside.py', 'x\n')
        self.assertResult(self.at_handback(m, report()), 4, 'fail')
        self.w.stop(m)
        self.assertTrue((m.root / 'src' / 'outside.py').is_file(), 'the check removes and reverts nothing')
        self.assertIn(os.path.realpath(str(m.root)), world.git(self.w.repo, 'worktree', 'list'))

    def test_tc11_likeness_a_change_outside_the_set_in_the_worktree_is_named_in_the_result(self):
        m = self.w.member('named', ['docs/'])
        self.w.dispatch(m)
        m.write('src/named.py', 'x\n')
        self.assertEqual(self.at_handback(m, report())[4]['paths'], ['src/named.py'])


class Baseline(Base):
    """TC-12, the rows the return check owns: checks read against the recorded baseline."""

    def test_tc12_a_member_that_commits_its_output_in_its_worktree_passes_check_1(self):
        m = self.w.member('committer', ['docs/'])
        self.w.dispatch(m)
        m.write('docs/committed.md', GOOD_FRONT)
        world.git(m.root, 'add', 'docs/committed.md')
        world.git(m.root, '-c', 'user.email=t@example.invalid', '-c', 'user.name=T', 'commit', '-q', '-m', 'out')
        found = self.at_handback(m, report('docs/committed.md'))
        self.assertResult(found, 1, 'pass')
        self.assertResult(found, 4, 'pass')

    def test_tc12_likeness_an_uncommitted_file_placed_at_dispatch_is_not_counted_as_the_members_change(self):
        m = self.w.member('placed', ['docs/'])
        self.w.dispatch(m)
        placed = m.root / 'docs' / 'placed.md'
        placed.write_text(GOOD_FRONT, encoding='utf-8')
        sent = [r for r in self.w.records() if r.get('record') == 'dispatch' and r.get('call_id') == m.call_id][0]
        stamp = calendar.timegm(time.strptime(sent['dispatched_at'][:19], '%Y-%m-%dT%H:%M:%S')) - 5
        os.utime(placed, (stamp, stamp))
        self.assertResult(self.at_handback(m, report('docs/placed.md')), 1, 'fail', 'not changed since the dispatch')

    def test_tc12_a_commit_in_the_main_checkout_after_dispatch_does_not_change_the_members_reading(self):
        m = self.w.member('steady', ['docs/'])
        self.w.dispatch(m)
        (self.w.repo / 'src' / 'later.py').write_text('x\n', encoding='utf-8')
        world.git(self.w.repo, 'add', 'src/later.py')
        world.git(self.w.repo, 'commit', '-q', '-m', 'a peer commits')
        m.write('docs/steady.md', GOOD_FRONT)
        found = self.at_handback(m, report('docs/steady.md'))
        self.assertResult(found, 1, 'pass')
        self.assertResult(found, 4, 'pass')

    def test_row5_a_writer_with_no_dispatch_record_reads_not_checkable_on_checks_1_and_4(self):
        m = self.w.member('unsent', ['docs/'])
        m.write('docs/unsent.md', GOOD_FRONT)
        found = self.at_handback(m, report('docs/unsent.md'))
        self.assertResult(found, 1, 'not_checkable', 'no dispatch record')
        self.assertResult(found, 4, 'not_checkable', 'no dispatch record')


class Transcript(Base):
    """Dry run 10, rows 8 and 9: a transcript whose writes cannot be read in full."""

    def test_row8_a_write_call_with_no_result_yet_reads_not_checkable_on_checks_2_and_4(self):
        m = self.w.member('pending', ['docs/'])
        self.w.dispatch(m)
        m.write('docs/later.md', GOOD_FRONT, result=None)
        found = self.at_handback(m, report())
        self.assertResult(found, 2, 'not_checkable', 'no result yet')
        self.assertResult(found, 4, 'not_checkable', 'no result yet')

    def test_row9_a_write_result_that_cannot_be_read_as_an_error_or_not_reads_not_checkable(self):
        m = self.w.member('unclear', ['docs/'])
        self.w.dispatch(m)
        m.write('docs/unclear.md', GOOD_FRONT, result='perhaps')
        found = self.at_handback(m, report())
        self.assertResult(found, 4, 'not_checkable', 'cannot be read as an error or not')

    def test_row8_likeness_a_write_whose_result_is_an_error_is_not_counted(self):
        m = self.w.member('refusedwrite', None)
        self.w.dispatch(m)
        m.write(None, 'x', path=self.w.outside / 'denied.txt', result=False)
        self.assertResult(self.at_handback(m, report()), 4, 'pass')


class Results(Base):
    """R-12 and R-18: one closed set, an id unique in the call, a repair on every fail, nothing refused."""

    def test_every_result_is_in_the_closed_set_and_carries_an_id_unique_in_its_call(self):
        m = self.w.member('ids', ['docs/'])
        self.w.dispatch(m)
        self.at_handback(m, report('docs/nothing.md'))
        self.at_handback(m, report())
        self.w.stop(m)
        back = self.w.returns(m)[0]
        ids = [c['id'] for run in self.w.runs(back) for c in run['checks']]
        self.assertEqual(len(ids), len(set(ids)), ids)
        self.assertEqual(len(ids), 12)
        self.assertTrue(all(c['result'] in ('pass', 'fail', 'not_applicable', 'not_checkable', 'ledger_absent')
                            for run in self.w.runs(back) for c in run['checks']))

    def test_a_failing_stop_is_not_refused(self):
        m = self.w.member('nostop', ['docs/'], mode='default')
        self.w.dispatch(m)
        decision = self.w.stop(m, closing='No section.')
        self.assertIsNone(decision, 'the check refuses no stop')
        self.assertResult(self.w.results(self.w.returns(m)[0]), 1, 'fail', 'no output section')


if __name__ == '__main__':
    unittest.main()
