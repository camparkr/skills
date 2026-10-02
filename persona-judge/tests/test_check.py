"""Tests for check.py, the true/false checks run from a table (SI-2, SI-10)."""

import hashlib
import json
import shutil
import unittest

from support import REFERENCES, SCRIPTS, ScratchCase, make_fixtures, run

# Exit codes check.py promises (specification §3c).
ALL_ONE, SOME_ZERO, ERROR, NOTHING = 0, 1, 2, 3

TABLE = REFERENCES / "failures.tsv"
DEFAULTS = REFERENCES / "harness-defaults.tsv"


def scores(proc):
    """Map (row id, path) to score from check.py's JSON output."""
    return {(r["id"], r["path"]): r["score"] for r in json.loads(proc.stdout)}


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


class TestT2(ScratchCase):
    """T-2: a planted path scores 0; the clean file scores 1; a new row needs no code change."""

    def test_planted_path(self):
        proj = self.project("si2-planted")
        proc = run("check.py", cwd=proj)
        self.assertEqual(proc.returncode, SOME_ZERO, proc.stdout + proc.stderr)
        line = [l for l in proc.stdout.splitlines() if l.startswith("PJ-001\t")][0]
        self.assertEqual(
            line.split("\t")[:3], ["PJ-001", "0", ".claude/agents/checker.md:7"]
        )
        self.assertIn("notes/missing.md", line)

    def test_clean_file(self):
        proj = self.project("si2-clean")
        proc = run("check.py", cwd=proj)
        self.assertEqual(proc.returncode, ALL_ONE, proc.stdout + proc.stderr)
        self.assertNotIn("\t0\t", proc.stdout)

    def test_new_row_needs_no_code_change(self):
        proj = self.project("si2-clean")
        before = {p.name: sha(p) for p in SCRIPTS.glob("*.py")}
        table = self.tmp / "failures.tsv"
        shutil.copy(TABLE, table)
        with table.open("a", encoding="utf-8") as fh:
            fh.write(
                "PJ-900\tNo time-sensitive statements\tline-pattern\tany\t\tbecause it is uncommon\t\t\t"
                "test row\tthe phrase planted for T-2\n"
            )
        proc = run("check.py", "--table", table, "--format", "json", cwd=proj)
        self.assertEqual(proc.returncode, SOME_ZERO, proc.stdout + proc.stderr)
        self.assertEqual(scores(proc)[("PJ-900", ".claude/agents/checker.md")], 0)
        self.assertEqual({p.name: sha(p) for p in SCRIPTS.glob("*.py")}, before)

    def test_new_harness_default_needs_no_code_change(self):
        """T-2 (4): a new row in a copy of harness-defaults.tsv scores PJ-005 0 and names the row."""
        proj = self.project("si2-clean")
        before = {p.name: sha(p) for p in SCRIPTS.glob("*.py")}
        folder = self.tmp / "tables"
        folder.mkdir()
        shutil.copy(TABLE, folder / "failures.tsv")
        shutil.copy(DEFAULTS, folder / "harness-defaults.tsv")
        with (folder / "harness-defaults.tsv").open("a", encoding="utf-8") as fh:
            fh.write(
                "HD-900\tClaude Code\treports misspelt words by itself, for the test\t"
                "\\breport each misspelt word\\b\t\ttest row\n"
            )
        proc = run("check.py", "--table", folder / "failures.tsv", "--format", "json", cwd=proj)
        self.assertEqual(proc.returncode, SOME_ZERO, proc.stdout + proc.stderr)
        row = [r for r in json.loads(proc.stdout) if r["id"] == "PJ-005"][0]
        self.assertEqual(row["score"], 0)
        self.assertEqual(row["line"], 7)
        self.assertIn("HD-900", row["message"])
        self.assertEqual({p.name: sha(p) for p in SCRIPTS.glob("*.py")}, before)
        # The same project with the seed table: PJ-005 scores 1.
        seed = run("check.py", "--format", "json", cwd=proj)
        self.assertEqual(scores(seed)[("PJ-005", ".claude/agents/checker.md")], 1)


class TestSeedRows(ScratchCase):
    def test_rows_on_the_si11_project(self):
        proj = self.project("si11")
        proc = run("check.py", "--format", "json", cwd=proj)
        self.assertEqual(proc.returncode, SOME_ZERO, proc.stderr)
        got = scores(proc)
        # CLAUDE.md: 'See also `docs/style.md`.' names a missing path and gives no trigger.
        self.assertEqual(got[("PJ-001", "CLAUDE.md")], 0)
        self.assertEqual(got[("PJ-002", "CLAUDE.md")], 0)
        # helper.md: tools include Edit; the prose says never edit files.
        self.assertEqual(got[("PJ-003", ".claude/agents/helper.md")], 0)
        # doc-writer.md: no row finds anything.
        for rid in ("PJ-001", "PJ-002", "PJ-003", "PJ-005", "PJ-006", "PJ-007"):
            self.assertEqual(got[(rid, ".claude/agents/doc-writer.md")], 1, rid)
        # A file with no tools field: PJ-003 does not apply.
        self.assertIsNone(got[("PJ-003", "CLAUDE.md")])
        # A harness with no row in harness-defaults.tsv: nothing contradicts the check.
        self.assertEqual(got[("PJ-005", ".cursor/rules/style.mdc")], 1)
        # 'Nothing said twice' is a reading check now; no row reads it.
        self.assertNotIn(("PJ-004", "AGENTS.md"), got)

    def test_time_and_harness_defaults(self):
        """PJ-005, PJ-006 and PJ-007 on the lines the review questions give as examples."""
        proj = self.project("time-defaults")
        proc = run("check.py", "--format", "json", cwd=proj)
        self.assertEqual(proc.returncode, SOME_ZERO, proc.stderr)
        rows = {r["id"]: r for r in json.loads(proc.stdout)}
        self.assertEqual((rows["PJ-005"]["score"], rows["PJ-005"]["line"]), (0, 6))
        self.assertIn("HD-001", rows["PJ-005"]["message"])
        self.assertEqual((rows["PJ-006"]["score"], rows["PJ-006"]["line"]), (0, 7))
        self.assertEqual(rows["PJ-007"]["score"], 0)
        self.assertEqual([l["line"] for l in rows["PJ-007"]["lines"]], [8, 9])

    def test_time_and_harness_likeness(self):
        """Likeness fixture: 'before you start', 'until the user replies', 'by name' and 'the API' score 1."""
        proj = self.project("time-likeness")
        proc = run("check.py", "--format", "json", cwd=proj)
        self.assertEqual(proc.returncode, ALL_ONE, proc.stdout + proc.stderr)
        got = scores(proc)
        for rid in ("PJ-005", "PJ-006", "PJ-007"):
            self.assertEqual(got[(rid, ".claude/agents/planner.md")], 1, rid)

    def test_codex_default(self):
        """HD-002: a Codex agent file asking the agent to read AGENTS.md."""
        proj = self.project("codex-defaults")
        proc = run("check.py", "--format", "json", cwd=proj)
        row = [r for r in json.loads(proc.stdout) if r["id"] == "PJ-005"][0]
        self.assertEqual((row["score"], row["line"]), (0, 4))
        self.assertIn("HD-002", row["message"])

    def test_text_line_quotes_the_line(self):
        proj = self.project("si11")
        proc = run("check.py", "CLAUDE.md", cwd=proj)
        line = [l for l in proc.stdout.splitlines() if l.startswith("PJ-002\t")][0]
        self.assertEqual(line.split("\t")[:4], ["PJ-002", "0", "CLAUDE.md:4", "'See also `docs/style.md`.'"])

    def test_exit_zero(self):
        proj = self.project("si2-planted")
        proc = run("check.py", "--exit-zero", cwd=proj)
        self.assertEqual(proc.returncode, ALL_ONE)
        self.assertIn("PJ-001\t0\t", proc.stdout)

    def test_kind_override(self):
        proj = self.project("si11")
        proc = run("check.py", "CLAUDE.md", "--kind", "delegated", "--format", "json", cwd=proj)
        self.assertIn(proc.returncode, (ALL_ONE, SOME_ZERO), proc.stderr)
        self.assertEqual({r["kind"] for r in json.loads(proc.stdout)}, {"delegated"})

    def test_session_text(self):
        text = (make_fixtures.FILES / "si2-planted.fixture").read_text()
        proc = run("check.py", "-", stdin=text, cwd=self.tmp)
        self.assertEqual(proc.returncode, SOME_ZERO, proc.stderr)
        self.assertIn("<session text>:7", proc.stdout)
        # Session text names no harness, so PJ-005 does not apply to it.
        line = [l for l in proc.stdout.splitlines() if l.startswith("PJ-005\t")][0]
        self.assertEqual(line.split("\t")[1], "-")


class TestT10Determinism(ScratchCase):
    def test_two_runs_byte_identical(self):
        proj = self.project("si11")
        first = run("check.py", "CLAUDE.md", cwd=proj)
        second = run("check.py", "CLAUDE.md", cwd=proj)
        self.assertEqual(first.stdout, second.stdout)
        self.assertEqual(first.returncode, second.returncode)
        self.assertTrue(first.stdout)


class TestT9ChangesNothing(ScratchCase):
    def test_read_only_copy(self):
        proj = self.project("si11")
        before = make_fixtures.manifest(proj)
        self.read_only(proj)
        proc = run("check.py", cwd=proj)
        self.assertEqual(proc.returncode, SOME_ZERO, proc.stderr)
        self.assertEqual(make_fixtures.manifest(proj), before)


class TestRejects(ScratchCase):
    def bad_table(self, row):
        table = self.tmp / "bad.tsv"
        header = TABLE.read_text(encoding="utf-8").splitlines()[0]
        table.write_text(header + "\n" + row + "\n", encoding="utf-8")
        return table

    def test_empty_project(self):
        """Empty fixture: nothing to check, exit 3."""
        proc = run("check.py", cwd=self.project("empty"))
        self.assertEqual(proc.returncode, NOTHING)

    def test_empty_file(self):
        """Empty fixture: an empty persona file, exit 3."""
        proc = run("check.py", "CLAUDE.md", cwd=self.project("empty-file"))
        self.assertEqual(proc.returncode, NOTHING)
        self.assertIn("empty", proc.stderr)

    def test_empty_session_text(self):
        proc = run("check.py", "-", stdin="")
        self.assertEqual(proc.returncode, NOTHING)

    def test_likeness_project(self):
        """Likeness fixture: a project of look-alikes holds nothing to check."""
        proc = run("check.py", cwd=self.project("likeness"))
        self.assertEqual(proc.returncode, NOTHING)

    def test_unknown_question(self):
        table = self.bad_table("PJ-001\tPointers carry triggers\tmissing-path\tany\t\t\t\t\ts\tm")
        proc = run("check.py", "--table", table, cwd=self.project("si1"))
        self.assertEqual(proc.returncode, ERROR)
        self.assertIn("line 2", proc.stderr)
        self.assertIn("question", proc.stderr)

    def test_reading_check_is_a_table_error(self):
        """A row may name only a check marked script; 'Nothing said twice' is a reading check."""
        table = self.bad_table("PJ-001\tNothing said twice\tline-pattern\tany\t\tx\t\t\ts\tm")
        proc = run("check.py", "--table", table, cwd=self.project("si1"))
        self.assertEqual(proc.returncode, ERROR)
        self.assertIn("line 2", proc.stderr)
        self.assertIn("script", proc.stderr)

    def test_unknown_kind(self):
        table = self.bad_table("PJ-001\tNo time-sensitive statements\tword-count\tany\t\t\t\t\ts\tm")
        proc = run("check.py", "--table", table, cwd=self.project("si1"))
        self.assertEqual(proc.returncode, ERROR)
        self.assertIn("line 2", proc.stderr)
        self.assertIn("kind", proc.stderr)

    def test_withdrawn_kind(self):
        """Round 1's repeated-sentence kind is withdrawn with its row."""
        table = self.bad_table("PJ-001\tNo time-sensitive statements\trepeated-sentence\tany\t\t\t\t\ts\tm")
        proc = run("check.py", "--table", table, cwd=self.project("si1"))
        self.assertEqual(proc.returncode, ERROR)
        self.assertIn("kind", proc.stderr)

    def test_bad_id_and_duplicate(self):
        table = self.bad_table(
            "PJ-1\tNo time-sensitive statements\tline-pattern\tany\t\tx\t\t\ts\tm\n"
            "PJ-002\tNo time-sensitive statements\tline-pattern\tany\t\tx\t\t\ts\tm\n"
            "PJ-002\tNo time-sensitive statements\tline-pattern\tany\t\ty\t\t\ts\tm"
        )
        proc = run("check.py", "--table", table, cwd=self.project("si1"))
        self.assertEqual(proc.returncode, ERROR)
        self.assertIn("line 2", proc.stderr)
        self.assertIn("line 4", proc.stderr)

    def test_bad_pattern(self):
        table = self.bad_table("PJ-001\tNo time-sensitive statements\tline-pattern\tany\t\t(unclosed\t\t\ts\tm")
        proc = run("check.py", "--table", table, cwd=self.project("si1"))
        self.assertEqual(proc.returncode, ERROR)
        self.assertIn("pattern", proc.stderr)

    def test_harness_default_without_data(self):
        table = self.bad_table("PJ-005\tLeaves the harness's work to the harness\tharness-default\tany\t\t\t\t\ts\tm")
        proc = run("check.py", "--table", table, cwd=self.project("si1"))
        self.assertEqual(proc.returncode, ERROR)
        self.assertIn("line 2", proc.stderr)
        self.assertIn("data", proc.stderr)

    def test_data_on_another_kind(self):
        table = self.bad_table(
            "PJ-006\tNo time-sensitive statements\tline-pattern\tany\t\tx\t\tharness-defaults.tsv\ts\tm"
        )
        proc = run("check.py", "--table", table, cwd=self.project("si1"))
        self.assertEqual(proc.returncode, ERROR)
        self.assertIn("data", proc.stderr)

    def test_missing_data_table(self):
        table = self.bad_table(
            "PJ-005\tLeaves the harness's work to the harness\tharness-default\tany\t\t\t\tno-such.tsv\ts\tm"
        )
        proc = run("check.py", "--table", table, cwd=self.project("si1"))
        self.assertEqual(proc.returncode, ERROR)
        self.assertIn("column data", proc.stderr)
        self.assertIn("no-such.tsv", proc.stderr)

    def test_bad_defaults_row(self):
        """An error in the defaults table names that table's line and column."""
        folder = self.tmp / "tables"
        folder.mkdir()
        shutil.copy(TABLE, folder / "failures.tsv")
        text = DEFAULTS.read_text(encoding="utf-8")
        (folder / "harness-defaults.tsv").write_text(
            text + "HD-9\tClaude Code\tsomething\t(unclosed\t\tsource\n", encoding="utf-8"
        )
        proc = run("check.py", "--table", folder / "failures.tsv", cwd=self.project("si1"))
        self.assertEqual(proc.returncode, ERROR)
        self.assertIn("harness-defaults.tsv, line 5", proc.stderr)
        self.assertIn("column id", proc.stderr)
        self.assertIn("column pattern", proc.stderr)

    def test_unknown_kind_option(self):
        proc = run("check.py", "--kind", "ambient", cwd=self.project("si1"))
        self.assertEqual(proc.returncode, ERROR)

    def test_unreadable_path(self):
        proc = run("check.py", "missing.md", cwd=self.project("si1"))
        self.assertEqual(proc.returncode, ERROR)
        self.assertIn("cannot read missing.md", proc.stderr)


class TestSeedTable(unittest.TestCase):
    def test_seed_rows(self):
        """Round 2's rows: PJ-004 withdrawn and its ID not reused; new rows from PJ-005."""
        lines = TABLE.read_text(encoding="utf-8").splitlines()
        self.assertEqual(
            lines[0].split("\t"),
            ["id", "question", "kind", "applies_to", "field", "pattern", "unless", "data", "source", "message"],
        )
        rows = [l.split("\t") for l in lines[1:]]
        self.assertEqual([r[0] for r in rows], ["PJ-001", "PJ-002", "PJ-003", "PJ-005", "PJ-006", "PJ-007"])
        self.assertEqual(
            [(r[1], r[2]) for r in rows],
            [
                ("Pointers carry their triggers", "missing-path"),
                ("Pointers carry their triggers", "line-pattern"),
                ("Bound parts agree with the prose", "field-and-line"),
                ("Leaves the harness's work to the harness", "harness-default"),
                ("No time-sensitive statements", "line-pattern"),
                ("No time-sensitive statements", "line-pattern"),
            ],
        )
        self.assertEqual(rows[3][7], "harness-defaults.tsv")

    def test_defaults_rows(self):
        lines = DEFAULTS.read_text(encoding="utf-8").splitlines()
        self.assertEqual(lines[0].split("\t"), ["id", "harness", "default", "pattern", "unless", "source"])
        rows = [l.split("\t") for l in lines[1:]]
        self.assertEqual(
            [(r[0], r[1]) for r in rows],
            [("HD-001", "Claude Code"), ("HD-002", "Codex"), ("HD-003", "Gemini CLI")],
        )


if __name__ == "__main__":
    unittest.main()
