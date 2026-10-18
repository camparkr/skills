"""Two fixes: a brief that opens with front matter reaches the harness as the prompt, and a command-line model call
followed by another part of the same shell command is not given that command's exit status.

  * call.py passes the brief so no harness reads it as an option: Cursor's after `--`, which ends its options, and
    Gemini CLI's as `--prompt=<brief>`, one word its parser binds to the option whatever the text begins with. The
    stand-ins here parse their arguments as the real programs do for this one rule: Cursor refuses an unknown word
    beginning with `-` before `--`, and Gemini CLI refuses `-p` or `--prompt` followed by a word beginning with `-`.
  * The shell reports one exit status for a whole command. Where the model call is the command's last part, or only
    `&&` joins the parts after it (each runs only if the call succeeded), the status is read as the call's. Where any
    part follows it otherwise (`;`, `||`, `|`, `&`, a new line), the status says nothing of the call: the return's
    outcome reads unrecorded, saying why, unless the command printed the call's own result envelope.

Run from the skill's folder:  python3 -m unittest discover -s tests
"""

import json
import sys
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

import test_call as call_tests  # noqa: E402
import test_capture_claude_code as base  # noqa: E402

FRONT_MATTER = '---\nact_kind: inquiry\n---\nReply with the word ok.\n'


def refused_as_an_option(harness, argv):
    """Why the harness's own parser would refuse these arguments, or None."""
    if harness == 'cursor':
        before = argv[:argv.index('--')] if '--' in argv else argv
        known = {'-p', '--output-format', 'json', '--trust', '--model'}
        for word in before:
            if word.startswith('-') and word not in known:
                return "error: unknown option '%s'" % word
        return None
    for at, word in enumerate(argv[:-1]):
        if word in ('-p', '--prompt') and argv[at + 1].startswith('-'):
            return 'Not enough arguments following: p'
    return None


class FrontMatterBrief(call_tests.World):

    def run_with_front_matter(self, harness, name):
        self.brief.write_text(FRONT_MATTER, encoding='utf-8')
        done = self.run_call(harness)
        logged = [json.loads(line) for line in self.log.read_text(encoding='utf-8').splitlines()]
        argv = [entry for entry in logged if entry['harness'] == name][-1]['argv']
        return done, argv

    def test_cursor_takes_the_brief_after_the_end_of_its_options(self):
        done, argv = self.run_with_front_matter('cursor', 'cursor')
        self.assertEqual(done.returncode, 0, done.stderr)
        self.assertIsNone(refused_as_an_option('cursor', argv))
        self.assertEqual(argv[argv.index('--') + 1:], [FRONT_MATTER])

    def test_gemini_takes_the_brief_bound_to_its_prompt_option(self):
        done, argv = self.run_with_front_matter('gemini-cli', 'gemini')
        self.assertEqual(done.returncode, 0, done.stderr)
        self.assertIsNone(refused_as_an_option('gemini', argv))
        self.assertIn('--prompt=' + FRONT_MATTER, argv)


class CompoundExit(base.World):

    fields = 'all'

    def shell(self, command, event, response=None, error=None):
        rows = self.events('bash-cli-events.jsonl')
        pre, post = json.loads(json.dumps(rows[0])), json.loads(json.dumps(rows[-1]))
        for row in (pre, post):
            row['payload']['tool_input']['command'] = command
        post['event'] = event
        post['payload']['hook_event_name'] = event
        if event == 'PostToolUse':
            post['payload']['tool_response'] = response or {'stdout': 'Error: no credentials\ndone\n', 'stderr': '',
                                                             'interrupted': False}
        else:
            post['payload'].pop('tool_response', None)
            post['payload']['error'] = error or 'Exit code 1\nError: no credentials'
        self.feed([pre, post])
        back = [r for r in self.records() if r['record'] == 'return']
        self.assertEqual(len(back), 1, self.errors())
        return back[0]

    def test_a_call_followed_by_another_part_has_no_outcome_from_the_exit_status(self):
        back = self.shell('claude -p "say ok"; echo done', 'PostToolUse')
        self.assertTrue(back['outcome'].startswith('unrecorded ('), back['outcome'])
        self.assertIn('exit status', back['outcome'])

    def test_a_call_followed_by_or_has_no_outcome_from_the_exit_status(self):
        back = self.shell('claude -p "say ok" || echo failed', 'PostToolUse')
        self.assertTrue(back['outcome'].startswith('unrecorded ('), back['outcome'])

    def test_a_call_alone_still_reads_its_own_status(self):
        self.assertEqual(self.shell('claude -p "say ok"', 'PostToolUseFailure')['outcome'], 'failed')

    def test_a_call_followed_by_and_still_reads_the_status(self):
        self.assertEqual(self.shell('claude -p "say ok" && echo done', 'PostToolUse')['outcome'], 'served')

    def test_a_call_after_other_parts_still_reads_the_status(self):
        self.assertEqual(self.shell('cd /tmp; claude -p "say ok"', 'PostToolUseFailure')['outcome'], 'failed')


if __name__ == '__main__':
    unittest.main()
