"""Tests for run_triggers.py's detector, which decides from a session's output whether the harness chose
persona-judge, on recorded Claude Code transcripts.

Each transcript in tests/evals/transcripts/ is a `claude -p --output-format stream-json` session recorded on
4 October 2026, kept to its assistant, user and result events, with thinking blocks dropped and the scratch folder's
full path shortened to /tmp/scratch. The recording machine's command sandbox failed to start, so its details were
removed too: each tool result holding the sandbox's start-up error now reads 'Error: (removed: ...)', and each
assistant reply or final result that quoted that error, named the recording machine's scratch folders or listed the
recording account's connectors now reads '(The model's reply is removed: ...)'. The detector reads only the
assistant's tool calls, and the trimming leaves every tool call as recorded.

The kinds: a request the model answered with a Skill tool call; a '/persona-judge' request, which loads the skill's
text with no Skill call, after which the model read a file in the skill's folder with Read, or named one in a Bash
command. The controls load no skill: an arithmetic question, and a near-miss request about a CLAUDE.md.
"""

import json
import sys
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import run_triggers  # noqa: E402

TRANSCRIPTS = HERE / "evals" / "transcripts"


def transcript(name):
    return (TRANSCRIPTS / name).read_text(encoding="utf-8")


def tool_calls(text):
    """The names of the assistant's tool calls, in order."""
    out = []
    for ev in run_triggers.events(text):
        if ev.get("type") == "assistant":
            out += [d.get("name") for d in run_triggers.walk(ev.get("message", {})) if d.get("type") == "tool_use"]
    return out


class TestClaudeDetector(unittest.TestCase):
    def test_skill_tool_call(self):
        text = transcript("claude-skill-call.jsonl")
        self.assertIn("Skill", tool_calls(text))
        self.assertTrue(run_triggers.chosen("claude", text))

    def test_slash_command_then_read(self):
        """'/persona-judge review the CLAUDE.md in this folder': no Skill call; the model read the skill's
        reviewer.md."""
        text = transcript("claude-slash-command-read.jsonl")
        self.assertNotIn("Skill", tool_calls(text))
        self.assertIn("Read", tool_calls(text))
        self.assertTrue(run_triggers.chosen("claude", text))

    def test_slash_command_then_bash(self):
        """'/persona-judge .gemini/agents/triage.md': no Skill call and no Read; a Bash command names the skill's
        reviewer.md."""
        text = transcript("claude-slash-command-bash.jsonl")
        self.assertEqual(set(tool_calls(text)), {"Bash"})
        self.assertTrue(run_triggers.chosen("claude", text))

    def test_control_no_skill(self):
        text = transcript("claude-control-no-skill.jsonl")
        self.assertEqual(tool_calls(text), [])
        self.assertFalse(run_triggers.chosen("claude", text))

    def test_control_near_miss(self):
        """A request about a CLAUDE.md, which the model answered with tool calls that never name the skill."""
        text = transcript("claude-control-near-miss.jsonl")
        self.assertTrue(tool_calls(text))
        self.assertFalse(run_triggers.chosen("claude", text))

    def test_prompt_words_never_count(self):
        """A tool call's text that only mentions the skill's name, with no file in its folder, does not count."""
        event = {"type": "assistant", "message": {"content": [
            {"type": "tool_use", "name": "Grep", "input": {"pattern": "persona-judge", "path": "."}},
            {"type": "tool_use", "name": "Bash", "input": {"command": "echo persona-judge-notes/x.md"}},
        ]}}
        self.assertFalse(run_triggers.chosen("claude", json.dumps(event)))


if __name__ == "__main__":
    unittest.main()
