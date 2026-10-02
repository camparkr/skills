"""Tests for find.py, discovery and kind (SI-1, SI-11), and for personafile.py, the shared reader."""

import json
import sys
import unittest

from support import SCRIPTS, ScratchCase, make_fixtures, run

# Exit codes find.py promises (specification §3b).
FOUND, USAGE, NONE = 0, 2, 3


def rows(proc):
    """Parse find.py's JSON output into (path, kind) pairs."""
    return [(r["path"], r["kind"]) for r in json.loads(proc.stdout)]


class TestFindProject(ScratchCase):
    def test_t1_kind_of_standing_and_delegated(self):
        """T-1: a CLAUDE.md is standing and a .claude/agents/ file is delegated."""
        proj = self.project("si1")
        proc = run("find.py", "--format", "json", cwd=proj)
        self.assertEqual(proc.returncode, FOUND, proc.stderr)
        self.assertEqual(
            rows(proc),
            [(".claude/agents/helper.md", "delegated"), ("CLAUDE.md", "standing")],
        )
        for record in json.loads(proc.stdout):
            self.assertTrue(record["kind_basis"])
            self.assertTrue(record["harness"])

    def test_t11_project_without_path(self):
        """T-11: five persona files, not the README, not the changelog, sorted by path."""
        proj = self.project("si11")
        proc = run("find.py", "--format", "json", cwd=proj)
        self.assertEqual(proc.returncode, FOUND, proc.stderr)
        self.assertEqual(
            [p for p, _ in rows(proc)],
            [
                ".claude/agents/doc-writer.md",
                ".claude/agents/helper.md",
                ".cursor/rules/style.mdc",
                "AGENTS.md",
                "CLAUDE.md",
            ],
        )

    def test_t11_named_folder(self):
        """T-11: naming .claude/agents/ gives the two agent files and no others."""
        proj = self.project("si11")
        proc = run("find.py", ".claude/agents/", "--format", "json", cwd=proj)
        self.assertEqual(proc.returncode, FOUND, proc.stderr)
        self.assertEqual(
            rows(proc),
            [(".claude/agents/doc-writer.md", "delegated"), (".claude/agents/helper.md", "delegated")],
        )

    def test_t11_session_text(self):
        """T-11: '-' reads standard input as one file labelled <session text>."""
        text = (make_fixtures.FILES / "helper-agent.fixture").read_text()
        proc = run("find.py", "-", "--format", "json", stdin=text)
        self.assertEqual(proc.returncode, FOUND, proc.stderr)
        self.assertEqual(rows(proc), [("<session text>", "delegated")])
        self.assertIn("inferred", json.loads(proc.stdout)[0]["kind_basis"])

    def test_text_format(self):
        proj = self.project("si1")
        proc = run("find.py", cwd=proj)
        self.assertEqual(proc.returncode, FOUND, proc.stderr)
        lines = proc.stdout.strip().splitlines()
        self.assertEqual(len(lines), 2)
        self.assertTrue(lines[0].startswith(".claude/agents/helper.md\tdelegated\t"))

    def test_named_file_is_always_returned(self):
        proj = self.project("si11")
        proc = run("find.py", "README.md", "--format", "json", cwd=proj)
        self.assertEqual(proc.returncode, FOUND, proc.stderr)
        self.assertEqual(rows(proc), [("README.md", "standing")])

    def test_named_folder_with_no_table_match(self):
        """A-4: a folder with no file matching the table yields its .md, .mdc and .toml files."""
        proj = self.project("parsing")
        proc = run("find.py", "notes", "--format", "json", cwd=proj)
        self.assertEqual(proc.returncode, FOUND, proc.stderr)
        self.assertEqual(rows(proc), [("notes/odd.md", "delegated")])
        self.assertIn("inferred", json.loads(proc.stdout)[0]["kind_basis"])

    def test_no_backslash_in_output(self):
        """T-P, the scripts' output: every path uses forward slashes."""
        proj = self.project("si11")
        proc = run("find.py", cwd=proj)
        self.assertNotIn("\\", proc.stdout)


class TestFindRejects(ScratchCase):
    def test_empty_project(self):
        """Empty fixture: a project with no files finds nothing, exit 3."""
        proj = self.project("empty")
        proc = run("find.py", cwd=proj)
        self.assertEqual(proc.returncode, NONE)
        self.assertIn("no persona file", proc.stderr)

    def test_empty_session_text(self):
        """Empty fixture: empty standard input, exit 3."""
        proc = run("find.py", "-", stdin="")
        self.assertEqual(proc.returncode, NONE)
        self.assertIn("empty", proc.stderr)

    def test_likeness_project(self):
        """Likeness fixture: a README, an index, a SKILL.md and a command file are never returned."""
        proj = self.project("likeness")
        proc = run("find.py", cwd=proj)
        self.assertEqual(proc.returncode, NONE, proc.stdout)
        self.assertEqual(proc.stdout, "")

    def test_unreadable_path(self):
        proj = self.project("si1")
        proc = run("find.py", "no/such/file.md", cwd=proj)
        self.assertEqual(proc.returncode, USAGE)
        self.assertIn("cannot read no/such/file.md", proc.stderr)
        self.assertIn("check the path", proc.stderr)

    def test_bad_format(self):
        proc = run("find.py", "--format", "yaml")
        self.assertEqual(proc.returncode, USAGE)

    def test_help_is_the_docstring(self):
        proc = run("find.py", "--help")
        self.assertEqual(proc.returncode, 0)
        self.assertIn("find.py", proc.stdout)


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
        f = self.pf.read_path(proj / "CLAUDE.md")
        self.assertTrue(f.empty)


if __name__ == "__main__":
    unittest.main()
