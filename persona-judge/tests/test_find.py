"""Tests for find.py, discovery and kind (SI-1, SI-11, SI-13), and for personafile.py, the shared reader.

Round 3 (vision v5): the default run reviews dedicated personas only, in .claude/agents/, .gemini/agents/,
.codex/agents/ and .github/agents/, and any persona the project's list names; project instructions files,
output styles, READMEs and skills are set aside, each with its reason.
"""

import json
import sys
import unittest

from support import SCRIPTS, ScratchCase, make_fixtures, run

# Exit codes find.py promises (specification §3b).
FOUND, USAGE, NONE = 0, 2, 3

# The reasons the set-aside table prints (specification §3b).
INSTRUCTIONS = "project instructions: context for the agent, not a dedicated persona"
OUTPUT_STYLE = "an output style: it sets the main agent's tone, not a dedicated persona"
README = "a README: documentation for people, not agent instructions"
SKILL = "a skill: review it with `skill-judge`"


def records(proc):
    return json.loads(proc.stdout)


def reviewed(proc):
    """(path, kind, harness, delegated) for each persona find.py returns."""
    return [(r["path"], r["kind"], r["harness"], r["delegated"]) for r in records(proc) if not r.get("set_aside")]


def set_aside(proc):
    """(path, reason) for each file find.py sets aside."""
    return [(r["path"], r["set_aside"]) for r in records(proc) if r.get("set_aside")]


class TestFindProject(ScratchCase):
    def test_t1_four_named_files(self):
        """T-1: two dedicated personas are reviewed and named; a CLAUDE.md and an output style are set aside."""
        proj = self.project("si1")
        proc = run(
            "find.py", ".claude/agents/helper.md", ".github/agents/triage.agent.md", "CLAUDE.md",
            ".claude/output-styles/terse.md", "--format", "json", cwd=proj,
        )
        self.assertEqual(proc.returncode, FOUND, proc.stderr)
        self.assertEqual(
            reviewed(proc),
            [
                (".claude/agents/helper.md", "subagent", "Claude Code", True),
                (".github/agents/triage.agent.md", "custom agent", "GitHub Copilot", True),
            ],
        )
        self.assertEqual(set_aside(proc), [("CLAUDE.md", INSTRUCTIONS), (".claude/output-styles/terse.md", OUTPUT_STYLE)])
        for record in records(proc):
            self.assertTrue(record["kind_basis"])
            self.assertIn("delegated", record)

    def test_t11_project_without_path(self):
        """T-11: the three agent files, sorted by path; then the other four set aside, each with its reason."""
        proj = self.project("si11")
        proc = run("find.py", "--format", "json", cwd=proj)
        self.assertEqual(proc.returncode, FOUND, proc.stderr)
        self.assertEqual(
            [r[0] for r in reviewed(proc)],
            [".claude/agents/doc-writer.md", ".claude/agents/helper.md", ".github/agents/triage.agent.md"],
        )
        self.assertEqual(
            set_aside(proc),
            [
                (".claude/output-styles/terse.md", OUTPUT_STYLE),
                ("AGENTS.md", INSTRUCTIONS),
                ("CLAUDE.md", INSTRUCTIONS),
                ("README.md", README),
            ],
        )
        # The personas come first, then the files set aside.
        flags = [bool(r.get("set_aside")) for r in records(proc)]
        self.assertEqual(flags, sorted(flags))
        # Neither the changelog nor docs/api.md is listed: neither table names them.
        paths = [r["path"] for r in records(proc)]
        self.assertNotIn("CHANGELOG.md", paths)
        self.assertNotIn("docs/api.md", paths)

    def test_t11_named_folder(self):
        """T-11: naming .claude/agents/ gives the two agent files and no others."""
        proj = self.project("si11")
        proc = run("find.py", ".claude/agents/", "--format", "json", cwd=proj)
        self.assertEqual(proc.returncode, FOUND, proc.stderr)
        self.assertEqual([r[0] for r in reviewed(proc)], [".claude/agents/doc-writer.md", ".claude/agents/helper.md"])
        self.assertEqual(set_aside(proc), [])

    def test_t11_session_text(self):
        """T-11: '-' reads standard input as one file labelled <session text>, its kind inferred."""
        text = (make_fixtures.FILES / "helper-agent.fixture").read_text()
        proc = run("find.py", "-", "--format", "json", stdin=text)
        self.assertEqual(proc.returncode, FOUND, proc.stderr)
        # Session text is never delegated (round 4, the delegated branch).
        self.assertEqual(reviewed(proc), [("<session text>", "persona", None, False)])
        self.assertIn("inferred", records(proc)[0]["kind_basis"])

    def test_text_format(self):
        proj = self.project("si11")
        proc = run("find.py", cwd=proj)
        self.assertEqual(proc.returncode, FOUND, proc.stderr)
        lines = [l for l in proc.stdout.splitlines() if l and not l.startswith(" ")]
        self.assertEqual(len(lines), 7)
        self.assertTrue(lines[0].startswith(".claude/agents/doc-writer.md\tsubagent\tClaude Code\tdelegated\t"), lines[0])
        self.assertEqual(lines[-1], f"README.md\tset aside\t{README}")

    def test_named_set_aside_file(self):
        """A named CLAUDE.md or README is set aside even when named; with no persona left, exit 3."""
        proj = self.project("si11")
        proc = run("find.py", "README.md", "CLAUDE.md", "--format", "json", cwd=proj)
        self.assertEqual(proc.returncode, NONE, proc.stderr)
        self.assertEqual(set_aside(proc), [("README.md", README), ("CLAUDE.md", INSTRUCTIONS)])
        self.assertIn("no persona", proc.stderr)

    def test_named_skill(self):
        proj = self.project("github-codex")
        proc = run("find.py", "skills/example/SKILL.md", "--format", "json", cwd=proj)
        self.assertEqual(proc.returncode, NONE)
        self.assertEqual(set_aside(proc), [("skills/example/SKILL.md", SKILL)])

    def test_named_file_in_no_table(self):
        """A named file in neither table is a persona; standing when its frontmatter lacks name and description."""
        proj = self.project("standing")
        proc = run("find.py", "notes/release.md", "--format", "json", cwd=proj)
        self.assertEqual(proc.returncode, FOUND, proc.stderr)
        self.assertEqual(reviewed(proc), [("notes/release.md", "persona", None, False)])
        self.assertIn("inferred", records(proc)[0]["kind_basis"])

    def test_named_folder_with_no_table_match(self):
        """A-4: a folder with no file matching either table yields its .md, .mdc and .toml files."""
        proj = self.project("parsing")
        proc = run("find.py", "notes", "--format", "json", cwd=proj)
        self.assertEqual(proc.returncode, FOUND, proc.stderr)
        self.assertEqual(reviewed(proc), [("notes/odd.md", "persona", None, True)])

    def test_dedicated_locations_and_set_aside_rows(self):
        """The four dedicated locations, and Copilot's, Cursor's and a skill's files set aside at any depth."""
        proj = self.project("github-codex")
        proc = run("find.py", "--format", "json", cwd=proj)
        self.assertEqual(proc.returncode, FOUND, proc.stderr)
        self.assertEqual(
            reviewed(proc),
            [
                (".codex/agents/reviewer.toml", "custom agent", "Codex", True),
                (".gemini/agents/summariser.md", "subagent", "Gemini CLI", True),
                (".github/agents/triage.agent.md", "custom agent", "GitHub Copilot", True),
            ],
        )
        self.assertEqual(
            set_aside(proc),
            [
                (".cursor/rules/style.mdc", INSTRUCTIONS),
                (".github/copilot-instructions.md", INSTRUCTIONS),
                (".github/instructions/frontend/react/hooks.instructions.md", INSTRUCTIONS),
                (".github/instructions/top.instructions.md", INSTRUCTIONS),
                ("skills/example/SKILL.md", SKILL),
            ],
        )

    def test_dedicated_locations_likeness(self):
        """Likeness fixture: .md files beside the Copilot files that end as neither table's patterns do."""
        proj = self.project("github-codex")
        paths = [r["path"] for r in records(run("find.py", "--format", "json", cwd=proj))]
        self.assertNotIn(".github/instructions/notes.md", paths)
        self.assertNotIn(".github/agents/notes.md", paths)

    def test_no_backslash_in_output(self):
        """T-P, the scripts' output: every path uses forward slashes."""
        proj = self.project("si13")
        proc = run("find.py", cwd=proj)
        self.assertNotIn("\\", proc.stdout + proc.stderr)


class TestSpreadOverFiles(ScratchCase):
    """T-13: a persona spread over files (vision v5, SI-13)."""

    def persona(self, proc, path):
        return [r for r in records(proc) if r["path"] == path][0]

    def test_candidates_and_the_list(self):
        proj = self.project("si13")
        proc = run("find.py", "--format", "json", cwd=proj)
        self.assertEqual(proc.returncode, FOUND, proc.stderr)
        self.assertEqual(
            [r[0] for r in reviewed(proc)], [".claude/agents/stylist.md", "personas/reviewer/reviewer.md"]
        )
        # Step 1: the files the persona's body refers to that exist, with the line that names each.
        stylist = self.persona(proc, ".claude/agents/stylist.md")
        self.assertEqual(
            stylist["candidates"], [{"path": "docs/house-style.md", "line": 9}, {"path": "docs/terms.md", "line": 10}]
        )
        self.assertEqual(stylist["listed"], [])
        # Step 2: the project's list names a persona outside every location, with the files that load with it.
        listed = self.persona(proc, "personas/reviewer/reviewer.md")
        self.assertEqual(listed["listed"], ["personas/reviewer/scale.md", "personas/reviewer/examples.md"])
        self.assertEqual(listed["list_missing"], [{"path": "personas/reviewer/missing.md", "line": 3}])
        self.assertEqual((listed["kind"], listed["delegated"]), ("persona", True))
        self.assertIn("personas.txt", listed["kind_basis"])
        # The missing listed path is reported with its line, and the run goes on.
        self.assertIn("personas.txt, line 3: personas/reviewer/missing.md does not exist", proc.stderr)
        # The listed files load with their persona and are not reviewed on their own; nor is the list.
        paths = [r["path"] for r in records(proc)]
        for path in ("personas/reviewer/scale.md", "personas/reviewer/examples.md", "personas.txt", "docs/terms.md"):
            self.assertNotIn(path, paths)

    def test_text_format_names_the_files(self):
        proj = self.project("si13")
        proc = run("find.py", cwd=proj)
        self.assertIn("  may load: docs/house-style.md (line 9)", proc.stdout)
        self.assertIn("  loads with it: personas/reviewer/scale.md (personas.txt)", proc.stdout)

    def test_list_option(self):
        """--list names another list in place of personas.txt."""
        proj = self.project("si13")
        other = self.tmp / "other.txt"
        other.write_text("# one persona\n\npersonas/reviewer/scale.md personas/reviewer/examples.md\n")
        proc = run("find.py", "--list", other, "--format", "json", cwd=proj)
        self.assertEqual(proc.returncode, FOUND, proc.stderr)
        self.assertIn("personas/reviewer/scale.md", [r[0] for r in reviewed(proc)])
        self.assertNotIn("personas/reviewer/reviewer.md", [r[0] for r in reviewed(proc)])

    def test_unreadable_list(self):
        proj = self.project("si13")
        proc = run("find.py", "--list", "no-such-list.txt", cwd=proj)
        self.assertEqual(proc.returncode, USAGE)
        self.assertIn("no-such-list.txt", proc.stderr)

    def test_no_list_no_candidates(self):
        """Likeness fixture: a persona naming paths that do not exist has no candidates."""
        proj = self.project("si2-planted")
        rec = records(run("find.py", "--format", "json", cwd=proj))[0]
        self.assertEqual((rec["candidates"], rec["listed"], rec["list_missing"]), ([], [], []))


class TestBranchesT_W(ScratchCase):
    """T-W: find.py prints the three branches for each persona (specification §3b, round 4)."""

    WANT = {
        ".claude/agents/helper.md": (True, "Claude Code", ["tools"], "delegated yes (folder); harness Claude Code; settings tools"),
        ".claude/agents/planner.md": (True, "Claude Code", [], "delegated yes (folder); harness Claude Code; settings none"),
        ".claude/agents/summary-writer.md": (True, "Claude Code", [], "delegated yes (folder); harness Claude Code; settings none"),
        ".codex/agents/auditor.toml": (True, "Codex", ["sandbox_mode"], "delegated yes (folder); harness Codex; settings sandbox_mode"),
        "notes/release.md": (False, None, [], "delegated no; harness none; settings none"),
    }

    def run_branches(self):
        proj = self.project("branches")
        named = [".claude/agents/helper.md", ".claude/agents/planner.md", ".claude/agents/summary-writer.md",
                 ".codex/agents/auditor.toml", "notes/release.md"]
        return proj, run("find.py", *named, "--format", "json", cwd=proj), run("find.py", *named, cwd=proj)

    def test_json_fields(self):
        _, proc, _ = self.run_branches()
        self.assertEqual(proc.returncode, FOUND, proc.stderr)
        got = {r["path"]: (r["delegated"], r["harness"], r["settings"]) for r in records(proc)}
        self.assertEqual(got, {k: v[:3] for k, v in self.WANT.items()})

    def test_text_lines(self):
        _, _, proc = self.run_branches()
        lines = proc.stdout.splitlines()
        for path, want in self.WANT.items():
            i = next(n for n, l in enumerate(lines) if l.startswith(path + "\t"))
            self.assertEqual(lines[i + 1], f"  branches: {want[3]}", path)

    def test_model_only_holds_no_settings(self):
        """A file holding only `model` has no settings for this branch (A-32)."""
        _, proc, _ = self.run_branches()
        self.assertEqual([r for r in records(proc) if r["path"] == ".claude/agents/summary-writer.md"][0]["settings"], [])

    def test_listed_persona_and_session_text(self):
        proj = self.project("si13")
        rec = [r for r in records(run("find.py", "--format", "json", cwd=proj)) if r["path"] == "personas/reviewer/reviewer.md"][0]
        self.assertEqual((rec["delegated"], rec["harness"], rec["settings"]), (True, None, ["tools"]))
        text = run("find.py", cwd=proj).stdout
        self.assertIn("  branches: delegated yes (front matter); harness none; settings tools", text)
        session = run("find.py", "-", stdin=(make_fixtures.FILES / "helper-agent.fixture").read_text())
        self.assertIn("  branches: delegated no; harness none; settings tools", session.stdout)


class TestFindRejects(ScratchCase):
    def test_empty_project(self):
        """Empty fixture: a project with no files finds nothing, exit 3."""
        proc = run("find.py", cwd=self.project("empty"))
        self.assertEqual(proc.returncode, NONE)
        self.assertIn("no persona", proc.stderr)

    def test_empty_session_text(self):
        """Empty fixture: empty standard input, exit 3."""
        proc = run("find.py", "-", stdin="")
        self.assertEqual(proc.returncode, NONE)
        self.assertIn("empty", proc.stderr)

    def test_likeness_project(self):
        """Likeness fixture: an index, a command file and a document are neither reviewed nor set aside."""
        proc = run("find.py", cwd=self.project("likeness"))
        self.assertEqual(proc.returncode, NONE, proc.stdout)
        self.assertEqual(proc.stdout, "")

    def test_unreadable_path(self):
        proc = run("find.py", "no/such/file.md", cwd=self.project("si1"))
        self.assertEqual(proc.returncode, USAGE)
        self.assertIn("cannot read no/such/file.md", proc.stderr)
        self.assertIn("check the path", proc.stderr)

    def test_bad_format(self):
        self.assertEqual(run("find.py", "--format", "yaml").returncode, USAGE)

    def test_help_is_the_docstring(self):
        proc = run("find.py", "--help")
        self.assertEqual(proc.returncode, 0)
        self.assertIn("find.py", proc.stdout)
        self.assertIn("--list", proc.stdout)


class TestFindChangesNothing(ScratchCase):
    def test_t9_read_only_copy(self):
        """T-9: find.py runs on a read-only copy and the manifest is unchanged."""
        proj = self.project("si11")
        before = make_fixtures.manifest(proj)
        self.read_only(proj)
        proc = run("find.py", cwd=proj)
        self.assertEqual(proc.returncode, FOUND, proc.stderr)
        self.assertEqual(make_fixtures.manifest(proj), before)


class TestReader(ScratchCase):
    """The shared reader, personafile.py."""

    def setUp(self):
        super().setUp()
        sys.path.insert(0, str(SCRIPTS))
        import personafile  # noqa: F401  (imported here so a missing module fails each test)

        self.pf = personafile

    def test_frontmatter_forms(self):
        proj = self.project("parsing")
        f = self.pf.read_path(proj / "notes/odd.md")
        self.assertEqual(f.frontmatter["name"], "odd one")
        self.assertEqual(f.frontmatter["description"], "Answers questions about the build when asked about the build.")
        self.assertEqual(f.frontmatter["tools"], ["Read", "Grep"])
        self.assertIn("hooks", f.unparsed)
        self.assertEqual(sorted(f.bound_parts), ["hooks", "permissionMode", "tools"])
        self.assertEqual(f.body[0], (14, ""))
        self.assertIn((15, "Answer from the build files only."), f.body)

    def test_toml_agent(self):
        proj = self.project("parsing")
        f = self.pf.read_path(proj / ".codex/agents/reviewer.toml")
        self.assertEqual(f.frontmatter["name"], "reviewer")
        self.assertEqual(sorted(f.bound_parts), ["model", "sandbox_mode"])
        self.assertIn((7, "Never run a migration yourself."), f.body)

    def test_session_text(self):
        f = self.pf.read_text("Line one.\nLine two.\n")
        self.assertEqual(f.path, "<session text>")
        self.assertEqual(f.lines, ["Line one.", "Line two."])

    def test_empty_file(self):
        proj = self.project("empty-file")
        self.assertTrue(self.pf.read_path(proj / ".claude/agents/blank.md").empty)

    def test_mask(self):
        """The mask (specification §3c): spaces in place of quoted spans, block quotes and fenced code, every line
        kept with its number; an apostrophe masks nothing; a span may wrap across lines of one paragraph."""
        text = (
            "Flag 'CRITICAL: You\n"
            "MUST run it.' when seen.\n"
            "Keep the harness's CRITICAL step.\n"
            "\n"
            "> Deploy steps: TODO.\n"
            "```\n"
            "TODO\n"
            "```\n"
            "An 'unclosed quote stays.\n"
        )
        pf = self.pf.read_text(text)
        masked = self.pf.masked_body(pf)
        self.assertEqual([n for n, _ in masked], [n for n, _ in pf.body])
        self.assertEqual([len(t) for _, t in masked], [len(t) for _, t in pf.body])
        got = [t.rstrip() for _, t in masked]
        self.assertEqual(got[0], "Flag")
        self.assertEqual(got[1].strip(), "when seen.")
        self.assertEqual(got[2], "Keep the harness's CRITICAL step.")
        self.assertEqual(got[4:8], ["", "", "", ""])
        self.assertEqual(got[8], "An 'unclosed quote stays.")

    def test_named_paths(self):
        """The paths a line names, in backticks or as a link, skipping patterns and placeholders."""
        got = list(self.pf.named_paths("Read `docs/a.md`, [b](../b.md), `src/*.ts`, `<your>.md` and `https://x.io/c.md`."))
        self.assertEqual(got, ["docs/a.md", "../b.md"])


if __name__ == "__main__":
    unittest.main()
