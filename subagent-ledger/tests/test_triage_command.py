"""Tests for the ledger folder's `triage_command` and for `effort_assigned`.

Where `config.json` names a `triage_command`, a capture runs it at each subagent dispatch, with the brief on
standard input, and records its reading as `triage_kind` beside `act_kind`. The brief's own kind governs; the
triage's is used where the brief names none. A failing triage leaves the dispatch written and the call unchanged.
`effort_assigned` is the effort the dispatching agent set for the call, never the session's own.

The triage here is a stand-in written by this file: it answers from a mark in the brief.

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
FIXTURES = HERE / 'fixtures'
SESSION = '0e0e0e0e-1111-4222-8333-444444444444'

STAND_IN = r'''
import json, os, re, sys
brief = sys.stdin.read()
with open(sys.argv[1], 'a') as seen:
    seen.write(json.dumps({'call_id': os.environ.get('SUBAGENT_LEDGER_CALL_ID')}) + '\n')
found = re.search(r'MARK\[([a-z-]+)\]', brief)
mark = found.group(1) if found else 'none'
if mark == 'fail':
    print(json.dumps({'kind': None, 'reason': 'told to fail'}))
    sys.exit(1)
print(json.dumps({'kind': mark, 'reason': 'read a mark'}))
'''


def fixture_lines(path):
    return [json.loads(line) for line in Path(path).read_text(encoding='utf-8').splitlines() if line.strip()]


class TriageCommand(unittest.TestCase):

    with_triage = True

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix='triage-command-'))
        self.addCleanup(shutil.rmtree, str(self.tmp), True)
        self.ledger = self.tmp / 'ledger'
        self.ledger.mkdir()
        self.work = self.tmp / 'work'
        self.work.mkdir()
        self.seen = self.tmp / 'seen.jsonl'
        stand_in = self.tmp / 'stand_in.py'
        stand_in.write_text(STAND_IN, encoding='utf-8')
        config = {'fields': 'all'}
        if self.with_triage:
            config['triage_command'] = '"%s" "%s" "%s"' % (sys.executable, stand_in, self.seen)
        (self.ledger / 'config.json').write_text(json.dumps(config), encoding='utf-8')

    def dispatch(self, brief, call_id, effort=None):
        row = [r for r in fixture_lines(FIXTURES / 'claude-code' / 'effort-events.jsonl')
               if r['event'] == 'PreToolUse'][0]
        payload = json.loads(json.dumps(row['payload']))
        payload.update(session_id=SESSION, tool_use_id=call_id, cwd=str(self.work),
                       transcript_path=str(self.tmp / 'none.jsonl'))
        payload['tool_input']['prompt'] = brief
        if effort is not None:
            payload['tool_input']['effort'] = effort
        env = dict(os.environ, HOME=str(self.tmp / 'home'), CLAUDE_CONFIG_DIR=str(self.tmp / 'config'))
        env.pop('SUBAGENT_LEDGER_DIR', None)
        done = subprocess.run([sys.executable, str(SCRIPTS / 'capture_claude_code.py'), 'PreToolUse', '--ledger',
                               str(self.ledger)], input=json.dumps(payload), capture_output=True, text=True,
                              env=env, cwd=str(self.work), timeout=60)
        self.assertEqual((done.returncode, done.stdout), (0, ''))
        path = self.ledger / ('%s.jsonl' % SESSION)
        found = [r for r in fixture_lines(path) if r.get('call_id') == call_id and r.get('record') == 'dispatch']
        self.assertEqual(len(found), 1, 'the dispatch record is written')
        return found[0]


class WithTriage(TriageCommand):

    def test_the_brief_kind_governs_and_both_are_kept(self):
        sent = self.dispatch('---\nact_kind: build\n---\nMake it. MARK[inquiry]', 'toolu_triage_0001')
        self.assertEqual((sent['act_kind'], sent['triage_kind']), ('build', 'inquiry'))
        self.assertIsInstance(sent['harness_payload']['triage_seconds'], (int, float))

    def test_a_brief_naming_no_kind_takes_the_triage_reading(self):
        sent = self.dispatch('Look it up. MARK[inquiry]', 'toolu_triage_0002')
        self.assertEqual((sent['act_kind'], sent['triage_kind']), ('inquiry', 'inquiry'))
        self.assertEqual(fixture_lines(self.seen), [{'call_id': 'toolu_triage_0002'}])

    def test_a_reading_of_none(self):
        sent = self.dispatch('Say hello.', 'toolu_triage_0003')
        self.assertEqual(sent['triage_kind'], 'unrecorded (the triage read none)')
        self.assertEqual(sent['act_kind'], 'unrecorded (the brief names no kind; the triage read none)')

    def test_a_failing_triage_leaves_the_dispatch_written(self):
        sent = self.dispatch('Do it. MARK[fail]', 'toolu_triage_0004')
        self.assertEqual(sent['triage_kind'], 'unrecorded (the triage failed: it exited 1: told to fail)')
        self.assertEqual(sent['act_kind'], 'unrecorded (the brief names no kind; the triage failed)')
        self.assertFalse((self.ledger / 'capture-errors.jsonl').exists())

    def test_a_name_not_in_kinds_json_is_a_failure(self):
        sent = self.dispatch('Do it. MARK[crafting]', 'toolu_triage_0005')
        self.assertEqual(sent['triage_kind'], 'unrecorded (the triage failed: crafting is not a kind)')


class WithoutTriage(TriageCommand):

    with_triage = False

    def test_no_command_named_gives_no_triage_ran(self):
        sent = self.dispatch('Look it up. MARK[inquiry]', 'toolu_triage_0006')
        self.assertEqual(sent['triage_kind'], 'unrecorded (no triage ran)')
        self.assertNotIn('triage_seconds', sent['harness_payload'])


class RelativePath(TriageCommand):
    """A relative path at the start of the command's script argument is resolved against the ledger folder, so
    the triage is found whatever folder the session runs in."""

    def relative(self, command):
        config = json.loads((self.ledger / 'config.json').read_text(encoding='utf-8'))
        config['triage_command'] = command
        (self.ledger / 'config.json').write_text(json.dumps(config), encoding='utf-8')

    def setUp(self):
        super().setUp()
        tools = self.tmp / 'tools'
        tools.mkdir()
        shutil.copy(str(self.tmp / 'stand_in.py'), str(tools / 'stand_in.py'))

    def test_a_script_named_relative_to_the_ledger_folder(self):
        self.relative('"%s" ../tools/stand_in.py "%s"' % (sys.executable, self.seen))
        sent = self.dispatch('Look it up. MARK[inquiry]', 'toolu_triage_0010')
        self.assertEqual(sent['triage_kind'], 'inquiry')

    def test_a_script_run_as_the_command_itself(self):
        script = self.tmp / 'tools' / 'run.sh'
        script.write_text('#!/bin/sh\nexec "%s" "%s" "$@"\n' % (sys.executable, self.tmp / 'tools' / 'stand_in.py'),
                          encoding='utf-8')
        script.chmod(0o755)
        self.relative('../tools/run.sh "%s"' % self.seen)
        sent = self.dispatch('Look it up. MARK[inquiry]', 'toolu_triage_0011')
        self.assertEqual(sent['triage_kind'], 'inquiry')

    def test_a_working_folder_elsewhere_does_not_matter(self):
        self.relative('"%s" ../tools/stand_in.py "%s"' % (sys.executable, self.seen))
        shutil.rmtree(str(self.tmp / 'work'))
        (self.tmp / 'deeper' / 'work').mkdir(parents=True)
        self.work = self.tmp / 'deeper' / 'work'
        sent = self.dispatch('Look it up. MARK[inquiry]', 'toolu_triage_0012')
        self.assertEqual(sent['triage_kind'], 'inquiry', 'the working folder does not matter')

    def test_what_is_left_as_written(self):
        resolve = load_capture().triage_command_resolved
        config = self.ledger / 'config.json'
        for command in ('python3 /abs/check.py', 'python3 -m triage', 'python3 "$HOME/check.py"',
                        'python3 ~/check.py', 'uv run triage --fast', '/usr/bin/python3 /abs/check.py'):
            self.assertEqual(resolve(command, config), command)
        self.assertEqual(resolve('/usr/bin/python3 ../tools/t.py x', config),
                         '/usr/bin/python3 %s x' % (self.tmp / 'tools' / 't.py'))


def load_capture():
    import importlib.util
    spec = importlib.util.spec_from_file_location('capture_for_triage_path', str(SCRIPTS / 'capture_claude_code.py'))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class EffortAssigned(TriageCommand):

    with_triage = False

    def test_the_agents_own_setting_for_the_call(self):
        self.assertEqual(self.dispatch('Go.', 'toolu_effort_0001', effort='high')['effort_assigned'], 'high')

    def test_none_set_never_reads_the_sessions_level(self):
        sent = self.dispatch('Go.', 'toolu_effort_0002')
        self.assertEqual(sent['effort_assigned'], 'unrecorded (the agent set no effort for this call)')
        self.assertEqual(sent['harness_payload']['effort'], {'level': 'low'}, 'the session ran at low')


if __name__ == '__main__':
    unittest.main()
