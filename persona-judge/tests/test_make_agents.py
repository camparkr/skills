"""Tests for tools/make_agents.py, which writes the reviewer's agent file for each harness from reviewer.md.

reviewer.md is the one source of the reviewer's text. The script writes:

- plugin/agents/persona-judge-reviewer.md, the Claude Code plugin agent, with no `hooks` field, since a plugin
  agent's hooks are ignored and the guard is wired in plugin/hooks/hooks.json;
- plugin/harness-agents/gemini/agents/persona-judge-reviewer.md, the Gemini CLI agent in the persona-judge
  extension, with Gemini's read, list, search and shell tools and nothing that writes; and
- plugin/harness-agents/codex/persona-judge-reviewer.toml, the Codex agent, read-only; and
- plugin/harness-agents/opencode/persona-judge-reviewer.md, the OpenCode agent, a subagent that may not edit, fetch
  or start another agent, and whose shell runs only `python3 --version` and the skill's scripts.

The Gemini, Codex and OpenCode files sit outside plugin/agents/, because Claude Code loads every file in a plugin's agents
folder, subfolders included. A regeneration into a scratch folder must match the committed files, with a control that
plants a drift.

Two enforcement tests read the committed files, each with a control that fails: the Codex agent sets
sandbox_mode = "read-only", and the Gemini agent's tools include no tool that writes a file.
"""

import json
import re
import subprocess
import sys
import tomllib
import unittest
from pathlib import Path

from support import PLUGIN, ROOT, SKILL, ScratchCase

TOOL = ROOT / "tools" / "make_agents.py"
REVIEWER_MD = SKILL / "reviewer.md"
OUTPUTS = (
    Path("plugin/agents/persona-judge-reviewer.md"),
    Path("plugin/harness-agents/gemini/agents/persona-judge-reviewer.md"),
    Path("plugin/harness-agents/codex/persona-judge-reviewer.toml"),
    Path("plugin/harness-agents/opencode/persona-judge-reviewer.md"),
)
GEMINI_TOOLS = ["read_file", "read_many_files", "list_directory", "glob", "grep_search", "run_shell_command"]
# Gemini CLI's tools that change no file. The shell is among them because the policy file, not the tool list, limits
# what the reviewer's shell runs; every other tool, such as write_file, replace or save_memory, may write one.
GEMINI_NON_WRITING = {"read_file", "read_many_files", "list_directory", "glob", "grep_search", "run_shell_command"}


def make(out, *extra):
    if not TOOL.is_file():
        raise AssertionError(f"make_agents.py is not built: {TOOL}")
    return subprocess.run([sys.executable, str(TOOL), "--out", str(out), *extra], capture_output=True, text=True,
                          timeout=60)


def reviewer_parts():
    """(front matter lines, body) of reviewer.md."""
    text = REVIEWER_MD.read_text(encoding="utf-8")
    _, front, body = text.split("---\n", 2)
    return front.splitlines(), body


def front_matter(path):
    """The front matter of a generated Markdown agent as a dict of top-level keys, and the body after it."""
    text = Path(path).read_text(encoding="utf-8")
    assert text.startswith("---\n"), path
    _, front, body = text.split("---\n", 2)
    fields = {}
    for line in front.splitlines():
        if line.startswith("#") or not line.strip():
            continue
        key, _, value = line.partition(":")
        fields[key.strip()] = value.strip()
    return front.splitlines(), fields, body


# Characters that may stand between 'python3 ' and the skill's path only to change what python3 runs: whitespace ends
# the path; a quote, $, ` or { can turn what follows into an option, or into other words.
NOT_IN_PATH = (" ", "\t", "\n", '"', "'", "$", "`", "{")
# The three commands Aristarchus's review of 4f4a742 found the allow patterns let through.
REFUSED_COMMANDS = (
    "python3 -c 'import os; os.remove(\"x\")' /h/persona-judge/scripts/find.py",
    "python3 -c\"__import__('os').remove('x')#\"/h/persona-judge/scripts/find.py",
    "python3 /h/.claude/skills/persona-judge/scripts/find.py . > x",
)
ALLOWED_COMMANDS = (
    "python3 --version",
    "python3 /h/.claude/skills/persona-judge/scripts/find.py",
    "python3 /h/.claude/skills/persona-judge/scripts/check.py .claude/agents/helper.md",
    "python3 /h/.claude/skills/persona-judge/scripts/report.py validate - <<'RECORD'\n{\"personas\": []}\nRECORD",
)


def opencode_bash_rules(path):
    """[(pattern, action)] from the bash block of an OpenCode agent's front matter, in file order."""
    front, _, _ = front_matter(path)
    start = front.index("  bash:") + 1
    rules = []
    for line in front[start:]:
        if not line.startswith("    "):
            break
        key, _, action = line.strip().rpartition(":")
        rules.append((json.loads(key), action.strip()))
    return rules


def opencode_match(command, pattern):
    """OpenCode 1.18.30's Wildcard.match: each backslash becomes /, in the command and the pattern; * is any run of
    characters, newlines included, ? is one character; and a pattern ending ' *' also matches the command without its
    last word."""
    command, pattern = command.replace("\\", "/"), pattern.replace("\\", "/")
    regex = re.sub(r"[.+^${}()|\[\]\\]", lambda m: "\\" + m.group(0), pattern).replace("*", ".*").replace("?", ".")
    if regex.endswith(" .*"):
        regex = regex[:-3] + "( .*)?"
    return re.fullmatch(regex, command, re.DOTALL) is not None


def opencode_decision(rules, command):
    """The action of the last rule that matches, as OpenCode 1.18.30's Permission.evaluate takes it."""
    matched = [action for pattern, action in rules if opencode_match(command, pattern)]
    return matched[-1] if matched else "ask"


def drift(committed_root, fresh_root):
    """The outputs that differ between the committed files and a fresh regeneration."""
    return [str(rel) for rel in OUTPUTS
            if not (committed_root / rel).is_file()
            or (committed_root / rel).read_bytes() != (fresh_root / rel).read_bytes()]


class TestMakeAgents(ScratchCase):
    def fresh(self):
        out = self.tmp / "fresh"
        proc = make(out)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        return out

    def test_committed_files_match_a_regeneration(self):
        self.assertEqual(drift(ROOT, self.fresh()), [])

    def test_control_planted_drift(self):
        fresh = self.fresh()
        planted = self.tmp / "planted"
        for rel in OUTPUTS:
            (planted / rel).parent.mkdir(parents=True, exist_ok=True)
            (planted / rel).write_bytes((fresh / rel).read_bytes())
        self.assertEqual(drift(planted, fresh), [])
        codex = planted / OUTPUTS[2]
        codex.write_text(codex.read_text(encoding="utf-8").replace("read-only", "workspace-write"), encoding="utf-8")
        self.assertEqual(drift(planted, fresh), [str(OUTPUTS[2])])

    def test_writes_only_the_four_files(self):
        fresh = self.fresh()
        written = sorted(p.relative_to(fresh) for p in fresh.rglob("*") if p.is_file())
        self.assertEqual(written, sorted(OUTPUTS))

    def test_agents_folder_holds_only_the_claude_agent(self):
        """Claude Code loads every file under a plugin's agents/, subfolders included."""
        found = sorted(p.relative_to(ROOT).as_posix() for p in (PLUGIN / "agents").rglob("*") if p.is_file())
        self.assertEqual(found, ["plugin/agents/persona-judge-reviewer.md"])

    def test_first_comment_says_generated(self):
        fresh = self.fresh()
        for rel in OUTPUTS:
            lines = (fresh / rel).read_text(encoding="utf-8").splitlines()
            comment = next(l for l in lines if l.startswith("#"))
            self.assertIn("Generated by tools/make_agents.py", comment, rel)
            self.assertIn("from skill/reviewer.md", comment, rel)

    def test_claude_agent(self):
        front, fields, body = front_matter(self.fresh() / OUTPUTS[0])
        source_front, source_body = reviewer_parts()
        self.assertEqual(set(fields), {"name", "description", "tools"})
        self.assertEqual(fields["tools"], "Read, Grep, Glob, Bash")
        for key in ("name", "description", "tools"):
            self.assertIn(next(l for l in source_front if l.startswith(key + ":")), front)
        self.assertEqual(body, source_body)

    def test_gemini_agent(self):
        front, fields, body = front_matter(self.fresh() / OUTPUTS[1])
        source_front, source_body = reviewer_parts()
        self.assertEqual(set(fields), {"name", "description", "tools"})
        self.assertEqual(fields["tools"], "[" + ", ".join(GEMINI_TOOLS) + "]")
        self.assertNotIn("write_file", fields["tools"])
        self.assertNotIn("replace", fields["tools"])
        for key in ("name", "description"):
            self.assertIn(next(l for l in source_front if l.startswith(key + ":")), front)
        self.assertEqual(body, source_body)

    def test_codex_agent(self):
        data = tomllib.loads((self.fresh() / OUTPUTS[2]).read_text(encoding="utf-8"))
        source_front, source_body = reviewer_parts()
        name = next(l for l in source_front if l.startswith("name:")).split(":", 1)[1].strip()
        description = next(l for l in source_front if l.startswith("description:")).split(":", 1)[1].strip()
        self.assertEqual(set(data), {"name", "description", "sandbox_mode", "developer_instructions"})
        self.assertEqual(data["name"], name)
        self.assertEqual(data["description"], description)
        self.assertEqual(data["sandbox_mode"], "read-only")
        self.assertEqual(data["developer_instructions"], source_body)

    def test_opencode_agent(self):
        """OpenCode names an agent by its file name, and reads permission rules, not Claude Code's tools list. A
        bash rule matched later wins, so "*": deny comes first and the denies that close the allows' gaps come last. The
        patterns name no install path."""
        text = (self.fresh() / OUTPUTS[3]).read_text(encoding="utf-8")
        source_front, source_body = reviewer_parts()
        description = next(l for l in source_front if l.startswith("description:")).split(":", 1)[1].strip()
        _, front, body = text.split("---\n", 2)
        self.assertEqual(front.splitlines()[1:], [
            f"description: {json.dumps(description, ensure_ascii=False)}",
            "mode: subagent",
            "permission:",
            "  edit: deny",
            "  webfetch: deny",
            "  task: deny",
            "  bash:",
            '    "*": deny',
            '    "python3 --version": allow',
            '    "python3 *persona-judge*/scripts/find.py*": allow',
            '    "python3 *persona-judge*/scripts/check.py*": allow',
            '    "python3 *persona-judge*/scripts/report.py*": allow',
            '    "python3 -*persona-judge*/scripts/*.py******": deny',
            '    "python3 /-*persona-judge*/scripts/*.py*****": deny',
            '    "python3 * *persona-judge*/scripts/*.py*****": deny',
            r'    "python3 *\t*persona-judge*/scripts/*.py*****": deny',
            r'    "python3 *\n*persona-judge*/scripts/*.py*****": deny',
            r'    "python3 *\"*persona-judge*/scripts/*.py*****": deny',
            '    "python3 *\'*persona-judge*/scripts/*.py*****": deny',
            '    "python3 *$*persona-judge*/scripts/*.py*****": deny',
            '    "python3 *`*persona-judge*/scripts/*.py*****": deny',
            '    "python3 *{*persona-judge*/scripts/*.py*****": deny',
            '    "*>' + "*" * 41 + '": deny',
        ])
        self.assertNotIn("tools:", front)
        self.assertNotIn(str(ROOT), front)
        self.assertEqual(body, source_body)

    def test_opencode_shell_denies(self):
        """The deny rules that close the gaps in the allow patterns: python3 with an option first, a character
        between 'python3 ' and the path that no path holds, and any >. OpenCode applies the last rule that matches,
        so each deny comes after every allow, and each is longer than the longest allow, so it would win as well
        were the longest pattern to decide."""
        rules = opencode_bash_rules(ROOT / OUTPUTS[3])
        allows = [i for i, (_, action) in enumerate(rules) if action == "allow"]
        denies = [i for i, (pattern, action) in enumerate(rules) if action == "deny" and pattern != "*"]
        longest_allow = max(len(rules[i][0]) for i in allows)
        patterns = [rules[i][0] for i in denies]
        starts = ["python3 -*persona-judge*", "python3 /-*persona-judge*",
                  *(f"python3 *{c}*persona-judge*" for c in NOT_IN_PATH), "*>*"]
        for start in starts:
            self.assertTrue(any(p.startswith(start) for p in patterns), f"no deny rule starts {start!r}")
        self.assertGreater(min(denies), max(allows))
        self.assertTrue(all(len(p) > longest_allow for p in patterns), patterns)

    def test_opencode_rules_refuse_the_review_commands(self):
        """The committed rules, applied as OpenCode 1.18.30 applies them, refuse the three commands Aristarchus's
        review found allowed, and still allow the skill's own commands."""
        rules = opencode_bash_rules(ROOT / OUTPUTS[3])
        for command in REFUSED_COMMANDS:
            self.assertEqual(opencode_decision(rules, command), "deny", command)
        for command in ALLOWED_COMMANDS:
            self.assertEqual(opencode_decision(rules, command), "allow", command)

    def test_help(self):
        if not TOOL.is_file():
            raise AssertionError(f"make_agents.py is not built: {TOOL}")
        proc = subprocess.run([sys.executable, str(TOOL), "--help"], capture_output=True, text=True, timeout=60)
        self.assertEqual(proc.returncode, 0)
        self.assertIn("reviewer.md", proc.stdout)



def codex_faults(path):
    """Faults in a Codex agent file's sandbox: empty when it sets sandbox_mode = "read-only"."""
    try:
        data = tomllib.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, tomllib.TOMLDecodeError) as err:
        return [f"unreadable: {err}"]
    mode = data.get("sandbox_mode")
    return [] if mode == "read-only" else [f"sandbox_mode is {mode!r}, not 'read-only'"]


def gemini_tool_faults(path):
    """Faults in a Gemini CLI agent's tools: empty when it lists its tools and none of them writes a file. An agent
    with no tool list is given every tool, so a missing list is a fault too."""
    _, fields, _ = front_matter(path)
    if "tools" not in fields:
        return ["no tools field, so the agent is given every tool"]
    tools = [t.strip() for t in fields["tools"].strip("[]").split(",") if t.strip()]
    return [f"{t} may write a file" for t in tools if t not in GEMINI_NON_WRITING]


class TestEnforcement(ScratchCase):
    """The settings that enforce the reviewer's rule to change no file, read from the committed agent files."""

    def test_codex_agent_is_read_only(self):
        self.assertEqual(codex_faults(ROOT / OUTPUTS[2]), [])

    def test_control_codex_workspace_write(self):
        planted = self.tmp / "codex.toml"
        text = (ROOT / OUTPUTS[2]).read_text(encoding="utf-8")
        planted.write_text(text.replace('sandbox_mode = "read-only"', 'sandbox_mode = "workspace-write"'), "utf-8")
        self.assertEqual(codex_faults(planted), ["sandbox_mode is 'workspace-write', not 'read-only'"])
        planted.write_text(text.replace('sandbox_mode = "read-only"\n', ""), "utf-8")
        self.assertEqual(codex_faults(planted), ["sandbox_mode is None, not 'read-only'"])

    def test_gemini_agent_writes_no_file(self):
        self.assertEqual(gemini_tool_faults(ROOT / OUTPUTS[1]), [])

    def test_control_gemini_writing_tools(self):
        planted = self.tmp / "gemini.md"
        text = (ROOT / OUTPUTS[1]).read_text(encoding="utf-8")
        planted.write_text(text.replace("grep_search,", "grep_search, write_file, replace,"), "utf-8")
        self.assertEqual(gemini_tool_faults(planted), ["write_file may write a file", "replace may write a file"])
        planted.write_text(text.replace("tools: [" + ", ".join(GEMINI_TOOLS) + "]\n", ""), "utf-8")
        self.assertEqual(gemini_tool_faults(planted), ["no tools field, so the agent is given every tool"])


if __name__ == "__main__":
    unittest.main()
