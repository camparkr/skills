"""Controls C-11-1 to C-11-4: the shell route reads through wrappers, compound commands, here-documents and runner
scripts, with no model and no network.

Each command below is fed to Claude Code's capture as a `Bash` PreToolUse payload (the first payload of
fixtures/claude-code/b2-matcher-events.jsonl, its command and call id replaced). A command that makes a model call
writes one dispatch record, route `cli`, whose `harness_payload.matched` lists each site found. Each control has a
half that switches its rule off, by emptying it from `commands.RULES`, and shows the command then writes nothing,
as under the rule before (the program after leading assignments and `env` only, and the parts the old split gave).

Run from the skill's folder:  python3 -m unittest discover -s tests
"""

import json
import os
import shutil
import sys
import unittest
from pathlib import Path
from unittest import mock

HERE = Path(__file__).resolve().parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

import test_commands as base  # noqa: E402

WRAPPED = {
    'toolu_w1': 'CODEX_HOME=x timeout 600 codex exec "Reply with one word."',
    'toolu_w2': '/usr/bin/time -p env A=b timeout 200 codex exec --skip-git-repo-check "Reply."',
    'toolu_w3': 'printf "a\\nb\\n" | xargs -n1 claude -p',
}
# Compound commands, each written in a form the old split did not open: a loop's body in a double-quoted
# substitution, a loop's condition, a subshell holding a quoted substitution, and a quoted substitution.
COMPOUND = {
    'toolu_c1': 'for q in a b; do out="$(codex exec "$q")"; echo "$out"; done',
    'toolu_c2': 'while ! gemini -p "Is it ready?"; do sleep 5; done',
    'toolu_c3': '( cd /tmp && echo "$(claude -p hi)" )',
    'toolu_c4': 'echo "answer: $(opencode run "hi")"',
}
# The bare forms the delegation names: the old split already opened them, so they match with the rule off too.
BARE = {
    'toolu_b1': 'for q in a b; do codex exec "$q"; done',
    'toolu_b2': '( codex exec "x" )',
    'toolu_b3': 'x=$(codex exec "x")',
}
HEREDOCS_MATCH = {
    'toolu_h1': 'bash <<EOF\ngemini -p "Reply with one word."\nEOF',
    'toolu_h2': ("python3 - <<'EOF'\nimport urllib.request\n"
                 "urllib.request.urlopen('https://api.anthropic.com/v1/messages', data=b'{}')\nEOF"),
}
HEREDOCS_NOT = {
    'toolu_h3': 'cat > notes.txt <<EOF\ngemini -p "Reply."\nEOF',
    'toolu_h4': 'bash <<EOF\necho hello\nEOF',
    'toolu_h5': "python3 - <<'EOF'\nprint('https://example.org/')\nEOF",
}


class Matching(base.World):
    """A working folder for scripts, and the dispatch records with their matched sites."""

    def setUp(self):
        base.World.setUp(self)
        (self.ledger / 'config.json').write_text(json.dumps({'fields': 'all'}), encoding='utf-8')
        self.work = self.tmp / 'work'
        self.work.mkdir()

    def feed_commands(self, commands, cwd=None):
        rows = []
        for call_id, command in commands.items():
            row = self.with_command(command, call_id)
            row['payload']['cwd'] = str(cwd or self.work)
            rows.append(row)
        self.feed(rows)

    def dispatch_records(self):
        found = {}
        for path in self.ledger.glob('*.jsonl'):
            if path.name == 'capture-errors.jsonl':
                continue
            for line in path.read_text(encoding='utf-8').splitlines():
                row = json.loads(line)
                if row['record'] == 'dispatch':
                    self.assertNotIn(row['call_id'], found, 'one record per tool call')
                    found[row['call_id']] = row
        return found

    def matched(self, record):
        return record['harness_payload']['matched']

    def rules_off(self, *names):
        return mock.patch.object(self.capture.commands, 'RULES', set(self.capture.commands.RULES) - set(names))

    def write(self, name, text, mode=0o755):
        path = self.work / name
        path.write_text(text, encoding='utf-8')
        path.chmod(mode)
        return path


class C11_1Wrappers(Matching):

    def test_c_11_1_each_wrapped_command_matches(self):
        self.feed_commands(WRAPPED)
        found = self.dispatch_records()
        self.assertEqual(sorted(found), sorted(WRAPPED))
        programs = dict((call_id, [site['program'] for site in self.matched(found[call_id])]) for call_id in found)
        self.assertEqual(programs, {'toolu_w1': ['codex'], 'toolu_w2': ['codex'], 'toolu_w3': ['claude']})
        for call_id in found:
            self.assertEqual([site['how'] for site in self.matched(found[call_id])], ['wrapper'], call_id)
            self.assertEqual(found[call_id]['route'], 'cli')

    def test_c_11_1_the_wrappers_are_data(self):
        patterns = json.loads((base.SCRIPTS / 'cli-patterns.json').read_text(encoding='utf-8'))
        names = [entry['name'] for entry in patterns['wrappers']]
        for name in ('timeout', 'time', 'nice', 'nohup', 'command', 'exec', 'xargs'):
            self.assertIn(name, names)

    def test_c_11_1_switched_off_the_old_rule_matches_none(self):
        with mock.patch.object(self.capture.commands, 'RULES', set()):
            self.feed_commands(WRAPPED)
        self.assertEqual(self.dispatch_records(), {})


class C11_2Compound(Matching):

    def test_c_11_2_each_compound_command_matches_once(self):
        self.feed_commands(COMPOUND)
        found = self.dispatch_records()
        self.assertEqual(sorted(found), sorted(COMPOUND))
        for call_id, record in found.items():
            self.assertEqual(len(self.matched(record)), 1, (call_id, self.matched(record)))
            self.assertEqual(self.matched(record)[0]['how'], 'loop', call_id)

    def test_c_11_2_the_bare_forms_match_once(self):
        self.feed_commands(BARE)
        found = self.dispatch_records()
        self.assertEqual(sorted(found), sorted(BARE))
        for record in found.values():
            self.assertEqual(len(self.matched(record)), 1)

    def test_c_11_2_switched_off_none_matches(self):
        with self.rules_off('compound'):
            self.feed_commands(COMPOUND)
        self.assertEqual(self.dispatch_records(), {})


class C11_3HereDocuments(Matching):

    def test_c_11_3_a_shell_body_and_a_python_body_naming_a_model_host_match(self):
        self.feed_commands(HEREDOCS_MATCH)
        found = self.dispatch_records()
        self.assertEqual(sorted(found), sorted(HEREDOCS_MATCH))
        self.assertEqual([(s['how'], s['program']) for s in self.matched(found['toolu_h1'])], [('heredoc', 'gemini')])
        self.assertEqual([(s['how'], s['host']) for s in self.matched(found['toolu_h2'])],
                         [('host', 'api.anthropic.com')])

    def test_c_11_3_a_body_with_neither_does_not(self):
        self.feed_commands(HEREDOCS_NOT)
        self.assertEqual(self.dispatch_records(), {})

    def test_c_11_3_switched_off_neither_matches(self):
        with self.rules_off('heredoc'):
            self.feed_commands(HEREDOCS_MATCH)
        self.assertEqual(self.dispatch_records(), {})


class C11_4RunnerScripts(Matching):

    def scripts(self):
        self.write('run.sh', '#!/bin/bash\nset -e\ntimeout 60 codex exec "$1"\n')
        self.write('run.py', 'import subprocess\n\nsubprocess.run(["claude", "-p", "Reply."], check=True)\n')
        self.write('outer.sh', '#!/bin/bash\nbash inner.sh "$@"\n')
        self.write('inner.sh', '#!/bin/bash\ngemini -p "$1"\n')
        self.write('one.sh', '#!/bin/bash\nbash two.sh\n')
        self.write('two.sh', '#!/bin/bash\nbash three.sh\n')
        self.write('three.sh', '#!/bin/bash\ncodex exec "deep"\n')

    def test_c_11_4_a_shell_script_and_a_python_script_match_at_pre_tool_use(self):
        self.scripts()
        self.feed_commands({'toolu_s1': 'bash run.sh "q"', 'toolu_s2': './run.sh "q"', 'toolu_s3': 'python3 run.py'})
        found = self.dispatch_records()
        self.assertEqual(sorted(found), ['toolu_s1', 'toolu_s2', 'toolu_s3'])
        for call_id, program in (('toolu_s1', 'codex'), ('toolu_s2', 'codex'), ('toolu_s3', 'claude')):
            sites = self.matched(found[call_id])
            self.assertEqual([(s['how'], s['program']) for s in sites], [('script', program)], call_id)
            self.assertTrue(sites[0]['where'].endswith('run.sh' if program == 'codex' else 'run.py'), sites)

    def test_c_11_4_depth_two_is_read_and_depth_three_is_not(self):
        self.scripts()
        self.feed_commands({'toolu_d2': 'bash outer.sh "q"', 'toolu_d3': 'bash one.sh'})
        found = self.dispatch_records()
        self.assertEqual(sorted(found), ['toolu_d2'])
        self.assertTrue(self.matched(found['toolu_d2'])[0]['where'].endswith('inner.sh'))

    def test_c_11_4_a_deleted_script_is_noted_and_is_no_match(self):
        self.feed_commands({'toolu_g1': 'bash gone.sh', 'toolu_g2': 'bash gone.sh; claude -p "x"'})
        found = self.dispatch_records()
        self.assertEqual(sorted(found), ['toolu_g2'])
        self.assertEqual([s['how'] for s in self.matched(found['toolu_g2'])], ['direct'])
        notes = found['toolu_g2']['harness_payload']['notes']
        self.assertTrue(any(note.startswith('script unread: ') and 'gone.sh' in note for note in notes), notes)

    def test_c_11_4_a_script_that_writes_its_own_records_is_not_matched(self):
        self.write('own.py', 'import os, subprocess\nos.environ.get("SUBAGENT_LEDGER_SCRIPTS")\n'
                             'subprocess.run(["codex", "exec", "x"])\n')
        self.feed_commands({'toolu_o1': 'python3 own.py --query x'})
        self.assertEqual(self.dispatch_records(), {})

    def test_c_11_4_the_script_is_resolved_against_the_hook_cwd(self):
        self.scripts()
        elsewhere = self.tmp / 'elsewhere'
        elsewhere.mkdir()
        self.feed_commands({'toolu_r1': 'bash run.sh q'}, cwd=elsewhere)
        self.assertEqual(self.dispatch_records(), {})

    def test_c_11_4_switched_off_none_matches(self):
        self.scripts()
        with self.rules_off('script'):
            self.feed_commands({'toolu_s1': 'bash run.sh "q"', 'toolu_s2': './run.sh "q"',
                                'toolu_s3': 'python3 run.py', 'toolu_d2': 'bash outer.sh "q"'})
        self.assertEqual(self.dispatch_records(), {})


class WrappedReturn(Matching):
    """A wrapped call's return names no single model unless one JSON envelope names it."""

    def test_the_return_of_a_wrapped_call_says_why_it_names_no_model(self):
        row = self.with_command(WRAPPED['toolu_w1'], 'toolu_w1')
        row['payload']['cwd'] = str(self.work)
        self.feed([row])
        post = json.loads(json.dumps(row))
        post['event'] = 'PostToolUse'
        post['payload']['hook_event_name'] = 'PostToolUse'
        post['payload']['tool_response'] = {'stdout': 'word', 'stderr': '', 'interrupted': False}
        self.feed([post])
        back = [json.loads(line) for path in self.ledger.glob('*.jsonl') if path.name != 'capture-errors.jsonl'
                for line in path.read_text(encoding='utf-8').splitlines() if json.loads(line)['record'] == 'return']
        self.assertEqual(len(back), 1)
        self.assertEqual(back[0]['model'], "unrecorded (a wrapped command's output names no single model)")
        self.assertEqual(back[0]['outcome'], 'served')


if __name__ == '__main__':
    unittest.main()
