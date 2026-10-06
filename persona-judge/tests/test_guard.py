"""Tests for guard.py, the hook that limits the reviewer's Bash calls to the skill's own scripts.

The guard reads a PreToolUse hook's JSON on standard input. When the call comes from the reviewer and runs Bash, it
allows only `python3 --version` and `python3 <dir>/find.py`, `check.py` or `report.py`, where <dir> resolves to the
guard's own folder, with one trailing quoted heredoc at most. Every other call, from the reviewer's other tools, from
the main session or from any other agent, passes.

Every command `reviewer.md` and its step files in `skill/steps/` give is filled with real paths and must pass; the list
of those commands is read from the files, so a command added there without a case here fails the run.
"""

import json
import os
import re
import shutil
import subprocess
import sys
import unittest
from pathlib import Path

from support import SCRIPTS, SKILL, STEPS, ScratchCase

GUARD = SCRIPTS / "guard.py"
ALLOWED, REFUSED = 0, 2
REVIEWER = "persona-judge-reviewer"
PLUGIN_REVIEWER = "persona-judge:persona-judge-reviewer"


def guard(command, agent_type=PLUGIN_REVIEWER, tool_name="Bash", cwd=None, extra=None, raw=None):
    """Run guard.py on one hook input; return the finished process."""
    if not GUARD.is_file():
        raise AssertionError(f"guard.py is not built: {GUARD}")
    payload = {"hook_event_name": "PreToolUse", "tool_name": tool_name, "tool_input": {"command": command}}
    if agent_type is not None:
        payload["agent_type"] = agent_type
    if cwd is not None:
        payload["cwd"] = str(cwd)
    payload.update(extra or {})
    return subprocess.run(
        [sys.executable, str(GUARD)],
        input=raw if raw is not None else json.dumps(payload),
        capture_output=True,
        text=True,
        timeout=30,
    )


def heredoc(first_line, body="{}", label="RECORD"):
    return f"{first_line}\n{body}\n{label}\n"


class GuardCase(ScratchCase):
    def assertAllowed(self, command, **kw):
        proc = guard(command, **kw)
        self.assertEqual(proc.returncode, ALLOWED, f"{command!r}: {proc.stderr}")
        self.assertEqual(proc.stderr, "", command)

    def assertRefused(self, command, **kw):
        proc = guard(command, **kw)
        self.assertEqual(proc.returncode, REFUSED, f"{command!r} passed")
        lines = proc.stderr.strip().splitlines()
        self.assertEqual(len(lines), 1, proc.stderr)
        self.assertIn("allows only", lines[0])


class TestAllowed(GuardCase):
    def test_python_version(self):
        self.assertAllowed("python3 --version")

    def test_each_script(self):
        for script in ("find.py", "check.py", "report.py"):
            self.assertAllowed(f"python3 {SCRIPTS / script} --help")

    def test_quoted_path(self):
        self.assertAllowed(f'python3 "{SCRIPTS / "find.py"}" . --format json')

    def test_heredoc_single_and_double_quoted(self):
        self.assertAllowed(heredoc(f"python3 {SCRIPTS / 'report.py'} validate - <<'RECORD'"))
        self.assertAllowed(heredoc(f'python3 {SCRIPTS / "report.py"} validate - <<"RECORD"'))

    def test_heredoc_body_may_hold_anything(self):
        body = '{"note": "a; b && c | d > e < f `g` $(h)"}'
        self.assertAllowed(heredoc(f"python3 {SCRIPTS / 'report.py'} validate - <<'RECORD'", body=body))

    def test_relative_path_from_the_hook_cwd(self):
        self.assertAllowed("python3 scripts/check.py . --format json", cwd=SKILL)

    def test_through_a_symlink(self):
        link = self.tmp / "linked-skill"
        link.symlink_to(SKILL, target_is_directory=True)
        self.assertAllowed(f"python3 {link / 'scripts' / 'find.py'} --format json")

    def test_reviewer_without_the_plugin_prefix(self):
        self.assertRefused("ls", agent_type=REVIEWER)
        self.assertAllowed("python3 --version", agent_type=REVIEWER)


class TestRefused(GuardCase):
    def test_chained(self):
        for joiner in (";", "&&", "&", "||", "|"):
            self.assertRefused(f"python3 {SCRIPTS / 'find.py'} . {joiner} touch x")

    def test_redirect(self):
        self.assertRefused(f"python3 {SCRIPTS / 'find.py'} . > out.json")
        self.assertRefused(f"python3 {SCRIPTS / 'check.py'} - < persona.md")

    def test_command_substitution(self):
        self.assertRefused(f"python3 {SCRIPTS / 'find.py'} $(touch x)")
        self.assertRefused(f"python3 {SCRIPTS / 'find.py'} `touch x`")

    def test_script_outside_the_folder(self):
        copy = self.tmp / "scripts"
        shutil.copytree(SCRIPTS, copy, ignore=shutil.ignore_patterns("__pycache__"))
        self.assertRefused(f"python3 {copy / 'find.py'} .")

    def test_other_script_in_the_folder(self):
        self.assertRefused(f"python3 {SCRIPTS / 'questions.py'}")
        self.assertRefused(f"python3 {SCRIPTS / 'guard.py'} --help")

    def test_text_after_the_heredoc_closes(self):
        self.assertRefused(heredoc(f"python3 {SCRIPTS / 'report.py'} validate - <<'RECORD'") + "touch x\n")

    def test_unclosed_heredoc(self):
        self.assertRefused(f"python3 {SCRIPTS / 'report.py'} validate - <<'RECORD'\n{{}}\n")

    def test_unquoted_heredoc(self):
        self.assertRefused(heredoc(f"python3 {SCRIPTS / 'report.py'} validate - <<RECORD"))

    def test_two_heredocs(self):
        self.assertRefused(heredoc(f"python3 {SCRIPTS / 'report.py'} validate - <<'A' <<'RECORD'"))

    def test_second_line_without_heredoc(self):
        self.assertRefused(f"python3 {SCRIPTS / 'find.py'} .\ntouch x")

    def test_other_commands(self):
        for command in ("ls", "cat SKILL.md", "python3 -c 'print(1)'", "python3 --version; ls", "sed -i s/a/b/ x",
                        f"FOO=1 python3 {SCRIPTS / 'find.py'}", f"/usr/bin/python3 {SCRIPTS / 'find.py'}", ""):
            self.assertRefused(command)

    def test_unreadable_input(self):
        proc = guard("", raw="not json")
        self.assertEqual(proc.returncode, REFUSED)


class TestWhoIsGuarded(GuardCase):
    """Only the reviewer is guarded; every other call passes, so the plugin never blocks the user's own commands."""

    def test_main_session(self):
        self.assertAllowed("rm notes.txt; ls > out", agent_type=None)

    def test_other_agents(self):
        for agent in ("Explore", "general-purpose", "other-plugin:persona-judge-reviewer", "persona-judge-reviewer-2"):
            self.assertAllowed("touch x && ls", agent_type=agent)

    def test_reviewer_other_tools(self):
        for tool in ("Read", "Grep", "Glob"):
            self.assertAllowed("", tool_name=tool)

    def test_control_reviewer_is_guarded(self):
        self.assertRefused("touch x && ls")


class TestReviewingCommands(GuardCase):
    """Every command SKILL.md, reviewer.md and the step files give, filled with real paths, passes."""

    # Each command reviewer.md and its step files give, as written there, and the filled form the reviewer runs.
    FILLED = {
        "python3 <skill>/scripts/find.py [PATH ...] [--list FILE] --format json": [
            "python3 {s}/scripts/find.py .claude/agents/reviewer.md --format json",
            "python3 {s}/scripts/find.py .claude/agents docs/agent.md --list team/personas.txt --format json",
            "python3 {s}/scripts/find.py --format json",
            "python3 {s}/scripts/find.py - --format json <<'TEXT'\n---\nname: x\n---\nBody.\nTEXT\n",
        ],
        "python3 <skill>/scripts/find.py - --format json <<'TEXT'": [
            "python3 {s}/scripts/find.py - --format json <<'TEXT'\nYou review pull requests.\nTEXT\n",
        ],
        "python3 <skill>/scripts/check.py [PATH ...] --format json": [
            "python3 {s}/scripts/check.py .claude/agents/reviewer.md --format json",
            "python3 {s}/scripts/check.py - --format json <<'TEXT'\nRead the notes.\nTEXT\n",
        ],
        "python3 <skill>/scripts/check.py - --format json <<'TEXT'": [
            "python3 {s}/scripts/check.py - --format json <<'TEXT'\nYou review pull requests.\nTEXT\n",
        ],
        "python3 <skill>/scripts/report.py schema": ["python3 {s}/scripts/report.py schema"],
        "python3 <skill>/scripts/report.py validate - <<'RECORD'": [
            "python3 {s}/scripts/report.py validate - <<'RECORD'\n{{\"files\": []}}\nRECORD\n",
        ],
        "python3 <skill>/scripts/report.py render - <<'RECORD'": [
            "python3 {s}/scripts/report.py render - <<'RECORD'\n{{\"files\": []}}\nRECORD\n",
            "python3 {s}/scripts/report.py render --summary - <<'RECORD'\n{{\"files\": []}}\nRECORD\n",
        ],
    }
    # The other commands the skill's files give: SKILL.md's version check, the rerun of check.py and the usage every
    # script prints.
    OTHERS = [
        "python3 --version",
        "python3 {s}/scripts/check.py .claude/agents/reviewer.md",
        "python3 {s}/scripts/find.py --help",
        "python3 {s}/scripts/check.py --help",
        "python3 {s}/scripts/report.py --help",
    ]

    @staticmethod
    def reviewer_text():
        """reviewer.md and every step file, joined: the files the reviewer reads its commands from."""
        files = [SKILL / "reviewer.md", *sorted(STEPS.glob("*.md"))]
        return "\n".join(f.read_text(encoding="utf-8") for f in files)

    @classmethod
    def given(cls, text=None):
        """Every `python3 <skill>/...` command reviewer.md and the step files give, in backticks or in a bash block."""
        if text is None:
            text = cls.reviewer_text()
        found = set(re.findall(r"`(python3 <skill>/scripts/[^`]+)`", text))
        found |= set(re.findall(r"^\s*(python3 <skill>/scripts/.+)$", text, re.MULTILINE))
        return found

    def test_the_list_matches_the_reviewer_files(self):
        self.assertEqual(self.given(), set(self.FILLED))

    def test_every_step_file_is_read(self):
        """The step files hold the commands; reviewer.md alone gives none of them."""
        self.assertTrue(list(STEPS.glob("*.md")))
        self.assertEqual(self.given((SKILL / "reviewer.md").read_text(encoding="utf-8")) & set(self.FILLED), set())

    def test_each_filled_command_passes(self):
        for written, filled in self.FILLED.items():
            for command in filled:
                with self.subTest(written=written, command=command):
                    self.assertAllowed(command.format(s=SKILL), cwd=self.tmp)
        for command in self.OTHERS:
            with self.subTest(command=command):
                self.assertAllowed(command.format(s=SKILL), cwd=self.tmp)

    def test_control_a_new_command_is_caught(self):
        step = (STEPS / "report.md").read_text(encoding="utf-8")
        planted = self.reviewer_text() + "\n" + step + "\nRun `python3 <skill>/scripts/report.py totals`.\n"
        self.assertEqual(self.given(planted) - set(self.FILLED), {"python3 <skill>/scripts/report.py totals"})


class TestHelpAndNoWrites(GuardCase):
    def test_help(self):
        proc = subprocess.run([sys.executable, str(GUARD), "--help"], capture_output=True, text=True, timeout=30)
        self.assertEqual(proc.returncode, 0)
        self.assertIn("PreToolUse", proc.stdout)

    def test_changes_no_file(self):
        before = sorted(p.name for p in self.tmp.iterdir())
        for command in ("ls", "python3 --version", f"python3 {SCRIPTS / 'find.py'} . > x"):
            subprocess.run([sys.executable, str(GUARD)], input=json.dumps(
                {"tool_name": "Bash", "tool_input": {"command": command}, "agent_type": PLUGIN_REVIEWER,
                 "cwd": str(self.tmp)}), capture_output=True, text=True, cwd=self.tmp, timeout=30)
        self.assertEqual(sorted(p.name for p in self.tmp.iterdir()), before)


if __name__ == "__main__":
    unittest.main()
