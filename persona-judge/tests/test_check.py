"""Tests for check.py, the true/false checks run from a table (SI-2, SI-10)."""

import hashlib
import json
import shutil
import unittest

from support import REFERENCES, SCRIPTS, ScratchCase, make_fixtures, run

# Exit codes check.py promises (specification §3c).
ALL_ONE, SOME_ZERO, ERROR, NOTHING = 0, 1, 2, 3

TABLE = REFERENCES / "failures.tsv"


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
                "PJ-900\tNothing said twice\tline-pattern\tany\t\tbecause it is uncommon\t\t\t"
                "test row\tthe phrase planted for T-2\n"
            )
        proc = run("check.py", "--table", table, "--format", "json", cwd=proj)
        self.assertEqual(proc.returncode, SOME_ZERO, proc.stdout + proc.stderr)
        self.assertEqual(scores(proc)[("PJ-900", ".claude/agents/checker.md")], 0)
        self.assertEqual({p.name: sha(p) for p in SCRIPTS.glob("*.py")}, before)


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
        # AGENTS.md: one sentence said twice.
        self.assertEqual(got[("PJ-004", "AGENTS.md")], 0)
        # doc-writer.md: no row finds anything.
        for rid in ("PJ-001", "PJ-002", "PJ-003", "PJ-004"):
            self.assertEqual(got[(rid, ".claude/agents/doc-writer.md")], 1, rid)
        # A file with no tools field: PJ-003 does not apply.
        self.assertIsNone(got[("PJ-003", "CLAUDE.md")])

    def test_text_line_quotes_the_line(self):
        proj = self.project("si11")
        proc = run("check.py", "CLAUDE.md", cwd=proj)
        line = [l for l in proc.stdout.splitlines() if l.startswith("PJ-002\t")][0]
        self.assertEqual(line.split("\t")[:4], ["PJ-002", "0", "CLAUDE.md:4", "'See also `docs/style.md`.'"])

    def test_description_repeated_in_body(self):
        f = self.tmp / "agent.md"
        f.write_text(
            "---\nname: a\ndescription: Reviews database migrations before they run.\n---\n\n"
            "Reviews database migrations before they run.\nRead each file.\n"
        )
        proc = run("check.py", f, "--format", "json")
        self.assertEqual(scores(proc)[("PJ-004", f.as_posix())], 0)

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

    def test_unknown_kind(self):
        table = self.bad_table("PJ-001\tNothing said twice\tword-count\tany\t\t\t\t\ts\tm")
        proc = run("check.py", "--table", table, cwd=self.project("si1"))
        self.assertEqual(proc.returncode, ERROR)
        self.assertIn("line 2", proc.stderr)
        self.assertIn("kind", proc.stderr)

    def test_bad_id_and_duplicate(self):
        table = self.bad_table(
            "PJ-1\tNothing said twice\tline-pattern\tany\t\tx\t\t\ts\tm\n"
            "PJ-002\tNothing said twice\tline-pattern\tany\t\tx\t\t\ts\tm\n"
            "PJ-002\tNothing said twice\tline-pattern\tany\t\ty\t\t\ts\tm"
        )
        proc = run("check.py", "--table", table, cwd=self.project("si1"))
        self.assertEqual(proc.returncode, ERROR)
        self.assertIn("line 2", proc.stderr)
        self.assertIn("line 4", proc.stderr)

    def test_bad_pattern(self):
        table = self.bad_table("PJ-001\tNothing said twice\tline-pattern\tany\t\t(unclosed\t\t\ts\tm")
        proc = run("check.py", "--table", table, cwd=self.project("si1"))
        self.assertEqual(proc.returncode, ERROR)
        self.assertIn("pattern", proc.stderr)

    def test_bad_min_words(self):
        table = self.bad_table("PJ-001\tNothing said twice\trepeated-sentence\tany\t\t\t\tsix\ts\tm")
        proc = run("check.py", "--table", table, cwd=self.project("si1"))
        self.assertEqual(proc.returncode, ERROR)
        self.assertIn("min_words", proc.stderr)

    def test_unknown_kind_option(self):
        proc = run("check.py", "--kind", "ambient", cwd=self.project("si1"))
        self.assertEqual(proc.returncode, ERROR)

    def test_unreadable_path(self):
        proc = run("check.py", "missing.md", cwd=self.project("si1"))
        self.assertEqual(proc.returncode, ERROR)
        self.assertIn("cannot read missing.md", proc.stderr)


class TestSeedTable(unittest.TestCase):
    def test_four_seed_rows(self):
        lines = TABLE.read_text(encoding="utf-8").splitlines()
        self.assertEqual(
            lines[0].split("\t"),
            ["id", "question", "kind", "applies_to", "field", "pattern", "unless", "min_words", "source", "message"],
        )
        self.assertEqual([l.split("\t")[0] for l in lines[1:]], ["PJ-001", "PJ-002", "PJ-003", "PJ-004"])


if __name__ == "__main__":
    unittest.main()
