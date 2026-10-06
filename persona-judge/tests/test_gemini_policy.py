"""Tests for plugin/harness-agents/gemini/persona-judge.toml, the Gemini CLI policy that limits the reviewer agent's shell.

The policy's rules apply only to the agent tools/make_agents.py writes for Gemini CLI, persona-judge-reviewer. Its
allow rules let the shell run `python3 --version` and the skill's find.py, check.py and report.py, as guard.py does
for Claude Code, and one deny rule at a lower priority refuses every other shell command. setup.sh fills the
placeholder for the skill folder with the installed folder's paths.

Gemini CLI matches each pattern against the tool's arguments encoded as JSON, after '"command":"'. The tests encode a
command the same way and match it with Python's re, which reads these patterns as JavaScript does. They check:

- every rule names the agent make_agents.py writes, with a control that renames it;
- the rules have the shape Gemini CLI loads: a shell tool, a priority, a deny below every allow, and patterns its
  loader accepts, with a control that lifts the deny above an allow;
- every command the reviewer's steps give, filled with real paths, matches an allow rule, and so does the first line
  of each heredoc command, which Gemini CLI checks on its own; and
- commands guard.py refuses match no allow rule, as a control. A command that adds text after its heredoc closes is
  left out of this list: its pattern matches, and Gemini CLI refuses it by checking the added text on its own, which
  re cannot show.
"""

import json
import re
import tomllib
import unittest

from support import PLUGIN, SKILL, ScratchCase
# The module, not the class, so unittest does not run test_guard's tests a second time from here.
import test_guard  # noqa: E402

POLICY = PLUGIN / "harness-agents" / "gemini" / "persona-judge.toml"
GEMINI_AGENT = PLUGIN / "harness-agents" / "gemini" / "persona-judge-reviewer.md"
PLACEHOLDER = "@SKILL_DIRS@"
SHELL = "run_shell_command"
# Gemini CLI's loader refuses a pattern with a quantified group after a quantifier inside a group (a ReDoS guard),
# and one longer than this.
NESTED_QUANTIFIER = re.compile(r"\([^)]*[*+?{].*\)[*+?{]")
LONGEST_PATTERN = 2048


def agent_name(path=GEMINI_AGENT):
    """The name in the Gemini CLI agent's front matter."""
    for line in path.read_text(encoding="utf-8").split("---\n", 2)[1].splitlines():
        if line.startswith("name:"):
            return line.split(":", 1)[1].strip()
    raise AssertionError(f"{path} has no name")


def escape(path):
    """A path as a literal in a JavaScript regular expression, as setup.sh writes it."""
    return re.sub(r"([][\\.^$*+?(){}|])", r"\\\1", str(path))


def rules(text, skill_dirs=(SKILL,)):
    """The policy's rules, with the placeholder filled by a group of the given skill folders."""
    group = "(" + "|".join(escape(d) for d in skill_dirs) + ")"
    return tomllib.loads(text.replace(PLACEHOLDER, group))["rule"]


def encoded(command):
    """The shell tool's arguments as Gemini CLI encodes them for matching: each top-level pair between NUL bytes."""
    return "{\x00" + '"command":' + json.dumps(command, ensure_ascii=False) + "\x00}"


def allowed(command, rule_list):
    """Whether an allow rule's pattern matches the command; rules with no pattern match every command."""
    return any(r["decision"] == "allow" and re.search('"command":"' + r["commandRegex"], encoded(command))
               for r in rule_list if "commandRegex" in r)


def first_line(command):
    """A heredoc command's first line without its opener and the '-' before it, as Gemini CLI checks it apart."""
    line = command.split("\n", 1)[0]
    return re.sub(r"\s*(-\s*)?<<['\"]?\w+['\"]?\s*$", "", line)


def name_faults(rule_list, name):
    return [f"rule {i + 1} names {r.get('subagent')!r}, not {name!r}" for i, r in enumerate(rule_list)
            if r.get("subagent") != name]


def shape_faults(rule_list):
    """Faults in the rules' shape; empty when Gemini CLI would load them as the policy intends."""
    faults = []
    for i, r in enumerate(rule_list, 1):
        if r.get("toolName") != SHELL:
            faults.append(f"rule {i} is for {r.get('toolName')!r}, not {SHELL}")
        if not isinstance(r.get("priority"), int) or not 0 <= r["priority"] <= 999:
            faults.append(f"rule {i} has priority {r.get('priority')!r}, not a whole number from 0 to 999")
        pattern = r.get("commandRegex", "")
        if NESTED_QUANTIFIER.search(pattern) or len(pattern) > LONGEST_PATTERN:
            faults.append(f"rule {i}'s pattern is one Gemini CLI's loader refuses")
    allows = [r for r in rule_list if r.get("decision") == "allow"]
    denies = [r for r in rule_list if r.get("decision") == "deny" and "commandRegex" not in r]
    if len(denies) != 1:
        return faults + [f"{len(denies)} rules deny every other command; expected 1"]
    if not allows or any(not a.get("commandRegex") for a in allows):
        faults.append("an allow rule has no pattern, so it allows every command")
    if any(a["priority"] <= denies[0]["priority"] for a in allows):
        faults.append("the deny rule does not sit below every allow rule")
    return faults


def reviewer_commands():
    """Every command the reviewer's files give, filled with the real skill folder, from test_guard's list."""
    given = test_guard.TestReviewingCommands
    out = [c for filled in given.FILLED.values() for c in filled] + given.OTHERS
    return [c.format(s=SKILL) for c in out]


# Commands guard.py refuses whose whole text Gemini CLI matches against the allow rules.
REFUSED = [
    "python3 {s}/scripts/find.py . ; touch x",
    "python3 {s}/scripts/find.py . && touch x",
    "python3 {s}/scripts/find.py . | tee x",
    "python3 {s}/scripts/find.py . > out.json",
    "python3 {s}/scripts/check.py - < persona.md",
    "python3 {s}/scripts/find.py $(touch x)",
    "python3 {s}/scripts/find.py `touch x`",
    "python3 {s}/scripts/questions.py",
    "python3 {s}/scripts/guard.py --help",
    "python3 {s}/scripts/find.py .\ntouch x",
    "python3 {s}/scripts/report.py validate - <<RECORD\n{{}}\nRECORD\n",
    "python3 {s}/scripts/report.py validate - <<'RECORD'\n{{}}\nRECORD\n> made.txt\n",
    "ls",
    "python3 -c 'print(1)'",
    "FOO=1 python3 {s}/scripts/find.py",
    "/usr/bin/python3 {s}/scripts/find.py",
]


class TestGeminiPolicy(ScratchCase):
    def setUp(self):
        super().setUp()
        self.text = POLICY.read_text(encoding="utf-8")
        self.rules = rules(self.text)

    def test_names_the_agent_make_agents_writes(self):
        self.assertEqual(agent_name(), "persona-judge-reviewer")
        self.assertEqual(name_faults(self.rules, agent_name()), [])

    def test_control_another_agent(self):
        planted = rules(self.text.replace('subagent = "persona-judge-reviewer"', 'subagent = "reviewer"', 1))
        self.assertEqual(name_faults(planted, agent_name()), ["rule 1 names 'reviewer', not 'persona-judge-reviewer'"])

    def test_shape(self):
        self.assertEqual(shape_faults(self.rules), [])

    def test_control_deny_above_an_allow(self):
        planted = rules(self.text.replace("priority = 800", "priority = 950"))
        self.assertEqual(shape_faults(planted), ["the deny rule does not sit below every allow rule"])

    def test_placeholder_fills_every_pattern(self):
        self.assertEqual([r for r in self.rules if PLACEHOLDER in r.get("commandRegex", "")], [])
        self.assertEqual(len(re.findall(re.escape(PLACEHOLDER), self.text.split("\n[[rule]]", 1)[1])), 3)

    def test_reviewer_commands_are_allowed(self):
        for command in reviewer_commands():
            with self.subTest(command=command):
                self.assertTrue(allowed(command, self.rules))
                self.assertTrue(allowed(first_line(command), self.rules), first_line(command))

    def test_through_the_installed_link(self):
        link = "/home/someone/.gemini/skills/persona-judge"
        both = rules(self.text, (link, SKILL))
        self.assertTrue(allowed(f"python3 {link}/scripts/report.py schema", both))
        self.assertTrue(allowed(f"python3 {SKILL}/scripts/report.py schema", both))

    def test_control_refused_commands(self):
        for command in REFUSED:
            with self.subTest(command=command):
                self.assertFalse(allowed(command.format(s=SKILL), self.rules))


if __name__ == "__main__":
    unittest.main()
