"""Controls for the dispatch record's new values: the session-start witness, the brief read, the pending triage file,
the session's effort, a writer's baseline and the resumption join.

Each criterion has its paired cases: an empty one (zero of the thing, which must give an error or a stated reason,
never a silent pass) and a likeness (the right shape with the wrong substance, which must be told apart). They were
committed before the code they test, and each failed on the capture as it stood.

Every test runs the capture as a hook runs it, in a new process, against a ledger folder of its own under a
temporary folder. No test reads or writes a real ledger: SUBAGENT_LEDGER_DIR is removed from the environment, and
HOME and CLAUDE_CONFIG_DIR name temporary folders.

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
CAPTURE = SCRIPTS / 'capture_claude_code.py'
SESSION = '0d0d0d0d-1111-4222-8333-555555555555'
OTHER_SESSION = '0d0d0d0d-1111-4222-8333-666666666666'
STAMP = '2026-10-29T01:00:00Z'
LATER = '2026-10-29T01:00:05Z'

# A stand-in triage: it notes each run in a file and answers `inquiry`. No test calls a live service.
STAND_IN = r'''
import json, sys
sys.stdin.read()
with open(sys.argv[1], 'a') as seen:
    seen.write('ran\n')
print(json.dumps({'kind': 'inquiry', 'reason': 'the stand-in answers inquiry'}))
'''


def lines(path):
    path = Path(path)
    if not path.is_file():
        return []
    return [json.loads(line) for line in path.read_text(encoding='utf-8').splitlines() if line.strip()]


def stamped(value, at=STAMP):
    return {'value': value, 'stamped_at': at}


def full_triage_file(persona='reviewer'):
    """A pending triage file holding every value, each stamped; the unaided effort stamped before the others."""
    return {
        'effort_unaided': stamped('medium', STAMP),
        'decision_records': stamped([{'question': 'kind', 'answer': 'build'},
                                     {'question': 'persona', 'answer': persona},
                                     {'question': 'effort', 'answer': 'high'}], LATER),
        'triage_persona': stamped(persona, LATER),
        'persona_facts': stamped({'grouping': 'makers', 'goal': 'builds what it is asked'}, LATER),
        'kind_paired_grouping': stamped('makers', LATER),
        'chosen_by': stamped('planner', LATER),
        'overrides': stamped([], LATER),
        'below_line': stamped({'below': False}, LATER),
        'triage_failure': stamped('none (the triage did not fail)', LATER),
    }


PENDING_VALUES = ('effort_unaided', 'decision_records', 'triage_persona', 'persona_facts', 'kind_paired_grouping',
                  'chosen_by', 'overrides', 'below_line', 'triage_failure')


class Capture(unittest.TestCase):
    """A ledger folder, a working folder and a way to run the capture on one event."""

    config = {'fields': 'all'}

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix='dispatch-record-'))
        self.addCleanup(shutil.rmtree, str(self.tmp), True)
        self.ledger = self.tmp / 'ledger'
        self.ledger.mkdir()
        self.work = self.tmp / 'work'
        self.work.mkdir()
        self.seen = self.tmp / 'triage-runs.txt'
        config = dict(self.config)
        (self.ledger / 'config.json').write_text(json.dumps(config), encoding='utf-8')

    def with_stand_in(self):
        stand_in = self.tmp / 'stand_in.py'
        stand_in.write_text(STAND_IN, encoding='utf-8')
        config = json.loads((self.ledger / 'config.json').read_text(encoding='utf-8'))
        config['triage_command'] = '"%s" "%s" "%s"' % (sys.executable, stand_in, self.seen)
        (self.ledger / 'config.json').write_text(json.dumps(config), encoding='utf-8')

    def triage_runs(self):
        return len(self.seen.read_text(encoding='utf-8').splitlines()) if self.seen.is_file() else 0

    def run_event(self, event, payload):
        env = dict(os.environ, HOME=str(self.tmp / 'home'), CLAUDE_CONFIG_DIR=str(self.tmp / 'config'))
        env.pop('SUBAGENT_LEDGER_DIR', None)
        done = subprocess.run([sys.executable, str(CAPTURE), event, '--ledger', str(self.ledger)],
                              input=json.dumps(payload), capture_output=True, text=True, env=env,
                              cwd=str(self.work), timeout=60)
        self.assertEqual((done.returncode, done.stdout), (0, ''), done.stderr)
        return done

    def records(self, session=SESSION):
        return lines(self.ledger / ('%s.jsonl' % session))

    def errors(self):
        return lines(self.ledger / 'capture-errors.jsonl')

    def pending(self, session=SESSION):
        return self.ledger / '.pending' / session

    def brief(self, name, front, body='Do the work.\n'):
        """A brief file in the working folder: frontmatter from `front` (one level of nesting), then the body."""
        out = ['---']
        for key, value in front.items():
            if isinstance(value, dict):
                out.append('%s:' % key)
                out.extend('  %s: %s' % (k, v) for k, v in value.items())
            else:
                out.append('%s: %s' % (key, value))
        out.append('---')
        path = self.work / name
        path.write_text('\n'.join(out) + '\n' + body, encoding='utf-8')
        return path

    def agent_payload(self, call_id, prompt, effort_level='high', effort=None, cwd=None):
        payload = {'session_id': SESSION, 'transcript_path': str(self.tmp / 'none.jsonl'),
                   'cwd': str(cwd or self.work), 'permission_mode': 'default',
                   'hook_event_name': 'PreToolUse', 'tool_name': 'Agent', 'tool_use_id': call_id,
                   'tool_input': {'description': 'a test call', 'prompt': prompt,
                                  'subagent_type': 'general-purpose'}}
        if effort_level is not None:
            payload['effort'] = {'level': effort_level}
        if effort is not None:
            payload['tool_input']['effort'] = effort
        return payload

    def dispatch(self, call_id, prompt, **kwargs):
        self.run_event('PreToolUse', self.agent_payload(call_id, prompt, **kwargs))
        found = [r for r in self.records() if r.get('record') == 'dispatch' and r.get('call_id') == call_id]
        self.assertEqual(len(found), 1, 'one dispatch record is written for %s' % call_id)
        return found[0]

    def write_triage(self, member, attempt, data, raw=None):
        folder = self.pending()
        folder.mkdir(parents=True, exist_ok=True)
        path = folder / ('triage-%s-%s.json' % (member, attempt))
        path.write_text(raw if raw is not None else json.dumps(data), encoding='utf-8')
        return path


# ---------------------------------------------------------------------------
# SC-01: the session-start witness
# ---------------------------------------------------------------------------

class SessionStartWitness(Capture):

    def start_payload(self, session=SESSION, source='startup'):
        return {'session_id': session, 'transcript_path': str(self.tmp / 't.jsonl'), 'cwd': str(self.work),
                'hook_event_name': 'SessionStart', 'source': source}

    def test_sc01_a_session_start_writes_a_witness_line_before_the_first_call(self):
        self.run_event('SessionStart', self.start_payload())
        self.dispatch('toolu_sc01_0001', 'Say hello.')
        rows = self.records()
        self.assertEqual(rows[0]['record'], 'witness', 'the first line of the session file is the witness')
        self.assertEqual((rows[0]['event'], rows[0]['session']), ('SessionStart', SESSION))
        self.assertTrue(rows[0]['agent_id'].startswith('unrecorded ('))
        self.assertEqual(rows[1]['record'], 'dispatch')

    def test_sc01_empty_a_session_start_with_no_session_id_gives_an_error_line(self):
        payload = self.start_payload()
        del payload['session_id']
        self.run_event('SessionStart', payload)
        found = [e for e in self.errors() if 'session_id absent from SessionStart' in e.get('reason', '')]
        self.assertEqual(len(found), 1, 'an error line names the missing session id: %r' % self.errors())

    def test_sc01_likeness_a_witness_in_another_sessions_file_is_not_this_sessions(self):
        # Another session's file already holds a session-start witness; this session's start writes its own,
        # in its own file, and writes nothing into the other's.
        self.run_event('SessionStart', self.start_payload(session=OTHER_SESSION))
        before = self.records(OTHER_SESSION)
        self.run_event('SessionStart', self.start_payload(source='resume'))
        mine = [r for r in self.records() if r.get('record') == 'witness' and r.get('event') == 'SessionStart']
        self.assertEqual(len(mine), 1)
        self.assertEqual(mine[0]['session'], SESSION)
        self.assertEqual(self.records(OTHER_SESSION), before)

    def test_sc01_a_subagent_start_witness_is_not_a_session_start_witness(self):
        self.run_event('SubagentStart', {'session_id': SESSION, 'agent_id': 'a0000000000000001',
                                         'agent_type': 'general-purpose', 'hook_event_name': 'SubagentStart'})
        self.assertFalse([r for r in self.records() if r.get('event') == 'SessionStart'])
        self.run_event('SessionStart', self.start_payload())
        self.assertEqual(len([r for r in self.records() if r.get('event') == 'SessionStart']), 1)


# ---------------------------------------------------------------------------
# SC-02: the brief read, with member and attempt (TC-5)
# ---------------------------------------------------------------------------

class BriefRead(Capture):

    def test_sc02_a_brief_with_member_and_attempt_records_both(self):
        path = self.brief('brief.md', {'member': 'm-review', 'attempt': '2', 'act_kind': 'build'})
        sent = self.dispatch('toolu_sc02_0001', 'Read %s and do what it says.' % path)
        self.assertEqual((sent['member'], sent['attempt']), ('m-review', 2))

    def test_sc02_the_keys_are_read_where_the_frontmatter_map_names_them(self):
        config = {'fields': 'all', 'frontmatter': {'member': 'meta.member', 'attempt': 'meta.attempt'}}
        (self.ledger / 'config.json').write_text(json.dumps(config), encoding='utf-8')
        path = self.brief('brief.md', {'meta': {'member': 'm-two', 'attempt': '1'}})
        sent = self.dispatch('toolu_sc02_0002', 'Read %s first.' % path)
        self.assertEqual((sent['member'], sent['attempt']), ('m-two', 1))

    def test_sc02_empty_a_prompt_naming_no_file_records_member_unrecorded_with_its_reason(self):
        sent = self.dispatch('toolu_sc02_0003', 'Look around and report.')
        self.assertEqual(sent['member'], 'unrecorded (the prompt names no file)')
        self.assertEqual(sent['attempt'], 'unrecorded (the prompt names no file)')

    def test_sc02_likeness_a_prompt_naming_another_file_first_is_read_as_no_brief(self):
        other = self.brief('persona.md', {'act_kind': 'build', 'persona-name': 'someone'})
        brief = self.brief('brief.md', {'member': 'm-one', 'attempt': '1', 'act_kind': 'inquiry'})
        sent = self.dispatch('toolu_sc02_0004', 'Read %s, then %s.' % (other, brief))
        reason = 'unrecorded (the first file the prompt names is not a brief: %s)' % other
        self.assertEqual(sent['member'], reason)
        self.assertEqual(sent['attempt'], reason)
        self.assertEqual(sent['act_kind'], 'build', 'the kind is the one read from the first file')
        self.assertEqual(sent['harness_payload']['kinds_read_from'],
                         'the first file the prompt names is not a brief: %s' % other)

    def test_sc02_a_brief_with_member_and_no_attempt_says_so(self):
        path = self.brief('brief.md', {'member': 'm-one'})
        sent = self.dispatch('toolu_sc02_0005', 'Read %s.' % path)
        self.assertEqual(sent['member'], 'm-one')
        self.assertEqual(sent['attempt'], 'unrecorded (the brief names no attempt)')

    def test_sc02_an_attempt_that_is_not_a_whole_number_says_so(self):
        path = self.brief('brief.md', {'member': 'm-one', 'attempt': 'second'})
        sent = self.dispatch('toolu_sc02_0006', 'Read %s.' % path)
        self.assertEqual(sent['attempt'], 'unrecorded (the brief\'s attempt is not a whole number: second)')

    def test_sc02_a_brief_carries_no_kind_mark_when_it_is_a_brief(self):
        path = self.brief('brief.md', {'member': 'm-one', 'attempt': '1'})
        sent = self.dispatch('toolu_sc02_0007', 'Read %s.' % path)
        self.assertNotIn('kinds_read_from', sent['harness_payload'])


# ---------------------------------------------------------------------------
# SC-03 and SC-13: the pending triage file
# ---------------------------------------------------------------------------

class PendingTriageFile(Capture):

    def member_brief(self, member='m-one', attempt='1', persona='reviewer'):
        return self.brief('brief.md', {'member': member, 'attempt': attempt, 'persona-name': persona})

    def test_sc03_every_value_is_copied_with_its_stamp_and_the_file_removed(self):
        path = self.member_brief()
        planted = self.write_triage('m-one', 1, full_triage_file())
        sent = self.dispatch('toolu_sc03_0001', 'Read %s.' % path)
        for name in PENDING_VALUES:
            self.assertEqual(sent[name], full_triage_file()[name], name)
        self.assertLess(sent['effort_unaided']['stamped_at'], sent['decision_records']['stamped_at'])
        self.assertFalse(planted.exists(), 'no pending file outlives its record')
        self.assertEqual(self.errors(), [])

    def test_sc03_where_the_brief_and_the_file_name_different_personas_both_are_kept(self):
        path = self.member_brief(persona='reviewer')
        self.write_triage('m-one', 1, full_triage_file(persona='builder'))
        sent = self.dispatch('toolu_sc03_0002', 'Read %s.' % path)
        self.assertEqual(sent['persona-name'], 'reviewer')
        self.assertEqual(sent['triage_persona'], stamped('builder', LATER))

    def test_sc03_empty_a_zero_byte_file_gives_an_error_line_and_the_record_is_written(self):
        path = self.member_brief()
        planted = self.write_triage('m-one', 1, None, raw='')
        sent = self.dispatch('toolu_sc03_0003', 'Read %s.' % path)
        found = [e for e in self.errors() if e.get('stage') == 'pending']
        self.assertEqual(len(found), 1, self.errors())
        self.assertIn('triage-m-one-1.json', found[0]['reason'])
        self.assertTrue(sent['effort_unaided'].startswith('unrecorded (the pending triage file triage-m-one-1.json '
                                                          'could not be read'))
        self.assertFalse(planted.exists())

    def test_sc03_likeness_a_value_without_its_stamp_is_refused_and_nothing_is_copied(self):
        path = self.member_brief()
        data = full_triage_file()
        data['effort_unaided'] = 'medium'
        self.write_triage('m-one', 1, data)
        sent = self.dispatch('toolu_sc03_0004', 'Read %s.' % path)
        self.assertEqual(len([e for e in self.errors() if e.get('stage') == 'pending']), 1, self.errors())
        for name in PENDING_VALUES:
            self.assertTrue(isinstance(sent[name], str) and sent[name].startswith('unrecorded ('), name)

    def test_sc03_likeness_a_key_the_schema_does_not_list_is_refused(self):
        path = self.member_brief()
        data = full_triage_file()
        data['path'] = stamped('/etc/hosts')
        self.write_triage('m-one', 1, data)
        self.dispatch('toolu_sc03_0005', 'Read %s.' % path)
        self.assertEqual(len([e for e in self.errors() if e.get('stage') == 'pending']), 1, self.errors())

    def test_sc03_another_attempts_file_is_not_read_or_removed(self):
        path = self.member_brief(attempt='1')
        other = self.write_triage('m-one', 2, full_triage_file())
        sent = self.dispatch('toolu_sc03_0006', 'Read %s.' % path)
        self.assertNotIn('effort_unaided', sent)
        self.assertTrue(other.exists())

    def test_sc03_a_member_id_naming_a_path_deletes_nothing_outside_the_session_folder(self):
        outside = self.ledger / 'triage-x-1.json'
        outside.write_text(json.dumps(full_triage_file()), encoding='utf-8')
        path = self.brief('brief.md', {'member': '../../triage-x', 'attempt': '1'})
        self.dispatch('toolu_sc03_0007', 'Read %s.' % path)
        self.assertTrue(outside.exists(), 'a file outside <ledger>/.pending/<session>/ is never removed')

    def test_sc03_a_link_in_the_pending_folder_is_never_followed(self):
        outside = self.tmp / 'outside.json'
        outside.write_text(json.dumps(full_triage_file()), encoding='utf-8')
        path = self.member_brief()
        self.pending().mkdir(parents=True, exist_ok=True)
        link = self.pending() / 'triage-m-one-1.json'
        try:
            link.symlink_to(outside)
        except (OSError, NotImplementedError):
            self.skipTest('this file system makes no links')
        sent = self.dispatch('toolu_sc03_0008', 'Read %s.' % path)
        self.assertTrue(sent['effort_unaided'].startswith('unrecorded ('))
        self.assertEqual(json.loads(outside.read_text(encoding='utf-8')), full_triage_file())
        self.assertFalse(link.is_symlink() or link.exists(), 'the link itself is removed, not what it names')

    def test_sc03_the_pending_schemas_kinds_are_the_kinds_in_kinds_json(self):
        schema = json.loads((SCRIPTS / 'pending.schema.json').read_text(encoding='utf-8'))
        kinds = json.loads((SCRIPTS / 'kinds.json').read_text(encoding='utf-8'))['kinds']
        self.assertEqual(schema['$defs']['stampedKind']['properties']['value']['enum'], [k['name'] for k in kinds])

    def test_sc13_every_pending_file_malformed_still_exits_0_and_writes_each_record(self):
        for number, raw in enumerate(('', '{', '[]', '{"effort_unaided": 3}', 'null')):
            member = 'm-%d' % number
            path = self.brief('brief-%d.md' % number, {'member': member, 'attempt': '1'})
            self.write_triage(member, 1, None, raw=raw)
            self.dispatch('toolu_sc13_%04d' % number, 'Read %s.' % path)
        self.assertEqual(len([e for e in self.errors() if e.get('stage') == 'pending']), 5, self.errors())
        self.assertEqual(sorted(p.name for p in self.pending().glob('triage-*.json')), [])


# ---------------------------------------------------------------------------
# SC-04: no second triage where the file carries the kind
# ---------------------------------------------------------------------------

class PlannerOwnDispatch(Capture):
    """The planning skill's own dispatch: its pending file is planner-<plan-request-id>.json, and its brief names
    that id and carries no member. Its record says it is the planner's and names the plan request."""

    def planner_file(self, request_id):
        folder = self.pending()
        folder.mkdir(parents=True, exist_ok=True)
        path = folder / ('planner-%s.json' % request_id)
        path.write_text(json.dumps({'plan_request': request_id}), encoding='utf-8')
        return path

    def test_sc03_the_planners_file_is_removed_and_its_record_names_the_plan_request(self):
        planted = self.planner_file('req-0001')
        path = self.brief('plan.md', {'act_kind': 'deliberation'}, body='Plan request req-0001: divide the work.\n')
        sent = self.dispatch('toolu_sc03_0101', 'Read %s.' % path)
        mark = "unrecorded (the planner's own dispatch, plan request req-0001: its brief carries no member)"
        self.assertEqual((sent['member'], sent['attempt']), (mark, mark))
        self.assertNotIn('kinds_read_from', sent['harness_payload'])
        self.assertFalse(planted.exists(), 'no pending file outlives its record')

    def test_sc03_empty_a_brief_naming_no_plan_request_leaves_the_file_and_reads_as_no_brief(self):
        planted = self.planner_file('req-0002')
        path = self.brief('plan.md', {'act_kind': 'deliberation'}, body='Divide the work.\n')
        sent = self.dispatch('toolu_sc03_0102', 'Read %s.' % path)
        self.assertEqual(sent['member'], 'unrecorded (the first file the prompt names is not a brief: %s)' % path)
        self.assertTrue(planted.exists(), 'a file this dispatch does not name is not its to remove')

    def test_sc03_likeness_an_id_that_only_begins_with_the_plan_requests_is_not_it(self):
        planted = self.planner_file('req-0003')
        path = self.brief('plan.md', {'act_kind': 'deliberation'}, body='Plan request req-00031.\n')
        sent = self.dispatch('toolu_sc03_0103', 'Read %s.' % path)
        self.assertNotIn("planner's own dispatch", sent['member'])
        self.assertTrue(planted.exists())

    def test_sc03_likeness_a_member_brief_naming_the_id_is_the_members_not_the_planners(self):
        planted = self.planner_file('req-0004')
        path = self.brief('brief.md', {'member': 'm-one', 'attempt': '1'}, body='From plan request req-0004.\n')
        sent = self.dispatch('toolu_sc03_0104', 'Read %s.' % path)
        self.assertEqual((sent['member'], sent['attempt']), ('m-one', 1))
        self.assertTrue(planted.exists())


class NoSecondTriage(Capture):

    def setUp(self):
        super().setUp()
        self.with_stand_in()

    def test_sc04_the_files_kind_is_used_and_the_capture_runs_no_triage(self):
        path = self.brief('brief.md', {'member': 'm-one', 'attempt': '1'})
        data = full_triage_file()
        data['kind'] = stamped('build', LATER)
        self.write_triage('m-one', 1, data)
        sent = self.dispatch('toolu_sc04_0001', 'Read %s.' % path)
        self.assertEqual(self.triage_runs(), 0, 'no triage of its own')
        self.assertEqual((sent['triage_kind'], sent['act_kind']), ('build', 'build'))
        self.assertEqual(sent['harness_payload']['triage_source'], 'the pending triage file triage-m-one-1.json')
        self.assertNotIn('triage_seconds', sent['harness_payload'])

    def test_sc04_empty_a_file_with_no_kind_leaves_the_capture_to_run_its_triage_once(self):
        path = self.brief('brief.md', {'member': 'm-one', 'attempt': '1'})
        self.write_triage('m-one', 1, full_triage_file())
        sent = self.dispatch('toolu_sc04_0002', 'Read %s.' % path)
        self.assertEqual(self.triage_runs(), 1)
        self.assertEqual(sent['triage_kind'], 'inquiry')

    def test_sc04_likeness_a_kind_that_is_not_a_kind_is_refused_and_the_capture_triages(self):
        path = self.brief('brief.md', {'member': 'm-one', 'attempt': '1'})
        data = full_triage_file()
        data['kind'] = stamped('not-a-kind', LATER)
        self.write_triage('m-one', 1, data)
        sent = self.dispatch('toolu_sc04_0003', 'Read %s.' % path)
        self.assertEqual(len([e for e in self.errors() if e.get('stage') == 'pending']), 1, self.errors())
        self.assertEqual(self.triage_runs(), 1)
        self.assertEqual(sent['triage_kind'], 'inquiry')


# ---------------------------------------------------------------------------
# SC-05: the session's effort, a writer's baseline and the resumption join
# ---------------------------------------------------------------------------

class SessionEffort(Capture):

    def test_sc05_the_sessions_level_is_read_from_the_payload(self):
        sent = self.dispatch('toolu_sc05_0001', 'Say hello.', effort_level='high')
        self.assertEqual(sent['session_effort'], 'high')

    def test_sc05_empty_a_payload_with_no_level_says_so(self):
        sent = self.dispatch('toolu_sc05_0002', 'Say hello.', effort_level=None)
        self.assertEqual(sent['session_effort'], 'unrecorded (effort.level absent from PreToolUse)')

    def test_sc05_likeness_the_level_passed_for_the_member_is_not_the_sessions(self):
        sent = self.dispatch('toolu_sc05_0003', 'Say hello.', effort_level='high', effort='low')
        self.assertEqual((sent['session_effort'], sent['effort_assigned']), ('high', 'low'))


def git(cwd, *args):
    env = dict(os.environ, GIT_AUTHOR_NAME='t', GIT_AUTHOR_EMAIL='t@example.invalid', GIT_COMMITTER_NAME='t',
               GIT_COMMITTER_EMAIL='t@example.invalid', GIT_CONFIG_GLOBAL=os.devnull, GIT_CONFIG_NOSYSTEM='1')
    return subprocess.run(['git'] + list(args), cwd=str(cwd), capture_output=True, text=True, env=env,
                          check=True).stdout.strip()


class Baseline(Capture):

    def repository(self):
        repo = self.tmp / 'repo'
        repo.mkdir()
        git(repo, 'init', '-q')
        (repo / 'a.py').write_text('x = 1\n', encoding='utf-8')
        git(repo, 'add', 'a.py')
        git(repo, 'commit', '-q', '-m', 'first')
        return repo, git(repo, 'rev-parse', 'HEAD')

    def writer_brief(self, folder, write_set='src/a.py\nsrc/b.py'):
        path = folder / 'brief.md'
        path.write_text('---\nmember: m-w\nattempt: 1\n---\nRead the persona file.\n\n## Write set\n\n%s\n\n'
                        '## Output\n' % write_set, encoding='utf-8')
        return path

    def test_sc05_a_writers_record_carries_the_commit_its_worktree_branches_from(self):
        repo, head = self.repository()
        path = self.writer_brief(repo)
        sent = self.dispatch('toolu_sc05_0101', 'Read %s.' % path, cwd=repo)
        self.assertEqual(sent['baseline']['commit'], head)

    def test_sc05_a_read_only_members_record_carries_no_baseline(self):
        repo, _ = self.repository()
        path = self.writer_brief(repo, write_set='none')
        sent = self.dispatch('toolu_sc05_0102', 'Read %s.' % path, cwd=repo)
        self.assertNotIn('baseline', sent)

    def test_sc05_empty_a_writer_outside_any_repository_says_why_there_is_no_baseline(self):
        path = self.writer_brief(self.work)
        sent = self.dispatch('toolu_sc05_0103', 'Read %s.' % path)
        self.assertTrue(sent['baseline'].startswith('unrecorded (git could not read HEAD'), sent['baseline'])

    def test_sc05_likeness_a_path_in_the_prose_is_not_a_write_set(self):
        repo, _ = self.repository()
        path = repo / 'brief.md'
        path.write_text('---\nmember: m-r\nattempt: 1\n---\nReview src/a.py and report.\n\n## Write set\n\nnone\n',
                        encoding='utf-8')
        sent = self.dispatch('toolu_sc05_0104', 'Read %s.' % path, cwd=repo)
        self.assertNotIn('baseline', sent)


class ResumptionJoin(Capture):

    def message(self, call_id, to):
        return {'session_id': SESSION, 'transcript_path': str(self.tmp / 'none.jsonl'), 'cwd': str(self.work),
                'hook_event_name': 'PreToolUse', 'tool_name': 'SendMessage', 'tool_use_id': call_id,
                'effort': {'level': 'medium'}, 'tool_input': {'to': to, 'message': 'Carry on.'}}

    def background(self, call_id, agent):
        self.run_event('PostToolUse', {
            'session_id': SESSION, 'cwd': str(self.work), 'hook_event_name': 'PostToolUse', 'tool_name': 'Agent',
            'tool_use_id': call_id, 'tool_input': {'prompt': 'x', 'run_in_background': True},
            'tool_response': {'status': 'async_launched', 'agentId': agent, 'isAsync': True}})

    def resumed(self, call_id):
        found = [r for r in self.records() if r.get('record') == 'dispatch' and r.get('call_id') == call_id]
        self.assertEqual(len(found), 1)
        return found[0]

    def test_sc05_a_resumption_carries_the_call_member_and_attempt_it_continues(self):
        path = self.brief('brief.md', {'member': 'm-one', 'attempt': '3'})
        self.dispatch('toolu_sc05_0201', 'Read %s.' % path)
        self.background('toolu_sc05_0201', 'a00000000000000a1')
        self.run_event('PreToolUse', self.message('toolu_sc05_0202', 'a00000000000000a1'))
        sent = self.resumed('toolu_sc05_0202')
        self.assertEqual((sent['continues_call_id'], sent['member'], sent['attempt']),
                         ('toolu_sc05_0201', 'm-one', 3))
        self.assertEqual(sent['session_effort'], 'medium')

    def test_sc05_a_resumption_is_joined_through_the_return_record_once_the_join_file_is_gone(self):
        path = self.brief('brief.md', {'member': 'm-two', 'attempt': '1'})
        self.dispatch('toolu_sc05_0211', 'Read %s.' % path)
        self.run_event('PostToolUse', {
            'session_id': SESSION, 'cwd': str(self.work), 'hook_event_name': 'PostToolUse', 'tool_name': 'Agent',
            'tool_use_id': 'toolu_sc05_0211', 'tool_input': {'prompt': 'Read %s.' % path},
            'tool_response': {'status': 'completed', 'agentId': 'a00000000000000b1',
                              'content': [{'type': 'text', 'text': 'done'}]}})
        self.assertFalse(list(self.pending().glob('join-*.json')))
        self.run_event('PreToolUse', self.message('toolu_sc05_0212', 'a00000000000000b1'))
        sent = self.resumed('toolu_sc05_0212')
        self.assertEqual((sent['continues_call_id'], sent['member'], sent['attempt']),
                         ('toolu_sc05_0211', 'm-two', 1))

    def test_sc05_empty_an_agent_with_no_dispatch_joined_says_so(self):
        # The agent is known only from its start event: no call id is joined to it.
        self.run_event('SubagentStart', {'session_id': SESSION, 'agent_id': 'a00000000000000c1',
                                         'agent_type': 'general-purpose', 'hook_event_name': 'SubagentStart'})
        self.run_event('PreToolUse', self.message('toolu_sc05_0221', 'a00000000000000c1'))
        sent = self.resumed('toolu_sc05_0221')
        self.assertEqual(sent['continues_call_id'],
                         'unrecorded (no dispatch in this ledger is joined to agent a00000000000000c1)')

    def test_sc05_likeness_a_message_to_one_agent_is_not_joined_to_anothers_call(self):
        one = self.brief('one.md', {'member': 'm-a', 'attempt': '1'})
        two = self.brief('two.md', {'member': 'm-b', 'attempt': '2'})
        self.dispatch('toolu_sc05_0231', 'Read %s.' % one)
        self.background('toolu_sc05_0231', 'a00000000000000d1')
        self.dispatch('toolu_sc05_0232', 'Read %s.' % two)
        self.background('toolu_sc05_0232', 'a00000000000000d2')
        self.run_event('PreToolUse', self.message('toolu_sc05_0233', 'a00000000000000d2'))
        sent = self.resumed('toolu_sc05_0233')
        self.assertEqual((sent['continues_call_id'], sent['member'], sent['attempt']),
                         ('toolu_sc05_0232', 'm-b', 2))

    def test_sc05_a_message_to_another_session_carries_no_join(self):
        payload = self.message('toolu_sc05_0241', 'other-session-name')
        payload['tool_input']['recipient_kind'] = 'name'
        self.run_event('PreToolUse', payload)
        sent = self.resumed('toolu_sc05_0241')
        self.assertNotIn('continues_call_id', sent)



# ---------------------------------------------------------------------------
# H-14 item 4: the new fields are selectable like the rest
# ---------------------------------------------------------------------------

NEW_FIELDS = ('member', 'attempt', 'session_effort', 'continues_call_id', 'baseline') + PENDING_VALUES


class NewFieldsSelectable(Capture):

    def setting(self, fields):
        (self.ledger / 'config.json').write_text(json.dumps({'fields': fields}), encoding='utf-8')

    def test_selectable_the_writer_and_the_schema_list_every_new_field(self):
        schema = json.loads((SCRIPTS / 'record.schema.json').read_text(encoding='utf-8'))
        names = schema['$defs']['selectableName']['enum']
        for name in NEW_FIELDS:
            self.assertIn(name, names)

    def test_selectable_empty_the_frame_setting_writes_none_of_them(self):
        self.setting('frame')
        path = self.brief('brief.md', {'member': 'm-one', 'attempt': '1'})
        self.write_triage('m-one', 1, full_triage_file())
        sent = self.dispatch('toolu_sel_0001', 'Read %s.' % path)
        for name in NEW_FIELDS:
            self.assertNotIn(name, sent)
        self.assertEqual(sorted(set(NEW_FIELDS) & set(sent['fields_not_chosen'])), sorted(NEW_FIELDS))

    def test_selectable_likeness_a_list_naming_one_writes_that_one_only(self):
        self.setting(['member'])
        path = self.brief('brief.md', {'member': 'm-one', 'attempt': '1'})
        sent = self.dispatch('toolu_sel_0002', 'Read %s.' % path)
        self.assertEqual(sent['member'], 'm-one')
        for name in NEW_FIELDS[1:]:
            self.assertNotIn(name, sent)

    def test_selectable_a_field_on_with_no_value_says_why(self):
        sent = self.dispatch('toolu_sel_0003', 'Say hello.')
        self.assertEqual(sent['baseline'], "unrecorded (no writer's brief for this call)")
        self.assertEqual(sent['continues_call_id'], 'unrecorded (not a resumption)')
        self.assertEqual(sent['effort_unaided'], 'unrecorded (no pending triage file for this call)')

if __name__ == '__main__':
    unittest.main()
