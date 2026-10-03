"""Tests for check.py, the true/false checks run from a table (SI-2, SI-10), to the round-3 table: a harness
column, and rows for 'Declares its tools', 'Plain emphasis' and 'No placeholders'."""

import hashlib
import json
import shutil
import unittest

from support import REFERENCES, ROOT, SCRIPTS, ScratchCase, make_fixtures, run

# Exit codes check.py promises (specification §3c).
ALL_ONE, SOME_ZERO, ERROR, NOTHING = 0, 1, 2, 3

TABLE = REFERENCES / "failures.tsv"
DEFAULTS = REFERENCES / "harness-defaults.tsv"
HEADER = ["id", "question", "kind", "applies_to", "harness", "field", "pattern", "unless", "data", "source", "message"]


def scores(proc):
    """Map (row id, path) to score from check.py's JSON output."""
    return {(r["id"], r["path"]): r["score"] for r in json.loads(proc.stdout)}


def row_for(proc, rid, path=None):
    return [r for r in json.loads(proc.stdout) if r["id"] == rid and (path is None or r["path"] == path)][0]


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def table_row(*cells):
    """A table row of eleven tab-separated cells."""
    assert len(cells) == len(HEADER), cells
    return "\t".join(cells)


class TestT2(ScratchCase):
    """T-2: a planted path scores 0; the clean file scores 1; a new row needs no code change."""

    def test_planted_path(self):
        proj = self.project("si2-planted")
        proc = run("check.py", cwd=proj)
        self.assertEqual(proc.returncode, SOME_ZERO, proc.stdout + proc.stderr)
        line = [l for l in proc.stdout.splitlines() if l.startswith("PJ-001\t")][0]
        self.assertEqual(line.split("\t")[:3], ["PJ-001", "0", ".claude/agents/checker.md:7"])
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
            fh.write(table_row(
                "PJ-900", "No time-sensitive statements", "line-pattern", "any", "", "", "because it is uncommon",
                "", "", "test row", "the phrase planted for T-2",
            ) + "\n")
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
        row = row_for(proc, "PJ-005")
        self.assertEqual((row["score"], row["line"]), (0, 7))
        self.assertIn("HD-900", row["message"])
        self.assertEqual({p.name: sha(p) for p in SCRIPTS.glob("*.py")}, before)
        seed = run("check.py", "--format", "json", cwd=proj)
        self.assertEqual(scores(seed)[("PJ-005", ".claude/agents/checker.md")], 1)


class TestSeedRows(ScratchCase):
    def test_rows_on_the_si11_project(self):
        proj = self.project("si11")
        proc = run("check.py", "--format", "json", cwd=proj)
        self.assertEqual(proc.returncode, SOME_ZERO, proc.stderr)
        got = scores(proc)
        # helper.md: tools include Edit; the prose says never edit files.
        self.assertEqual(got[("PJ-003", ".claude/agents/helper.md")], 0)
        # doc-writer.md: no row finds anything; the Gemini CLI and Copilot rows do not apply to it.
        for rid in ("PJ-001", "PJ-002", "PJ-003", "PJ-005", "PJ-006", "PJ-007", "PJ-008", "PJ-011", "PJ-012"):
            self.assertEqual(got[(rid, ".claude/agents/doc-writer.md")], 1, rid)
        for rid in ("PJ-009", "PJ-010"):
            self.assertIsNone(got[(rid, ".claude/agents/doc-writer.md")], rid)
        # triage.agent.md: a Copilot custom agent with no tools field.
        self.assertEqual(got[("PJ-010", ".github/agents/triage.agent.md")], 0)
        self.assertIsNone(got[("PJ-003", ".github/agents/triage.agent.md")])
        # A harness with no row in harness-defaults.tsv: nothing contradicts the check.
        self.assertEqual(got[("PJ-005", ".github/agents/triage.agent.md")], 1)
        # The files set aside are not checked.
        for path in ("CLAUDE.md", "AGENTS.md", "README.md", ".claude/output-styles/terse.md"):
            self.assertNotIn(("PJ-001", path), got)
        self.assertNotIn(("PJ-004", ".claude/agents/helper.md"), got)

    def test_time_and_harness_defaults(self):
        """PJ-005, PJ-006 and PJ-007 on the lines the review questions give as examples."""
        proj = self.project("time-defaults")
        proc = run("check.py", "--format", "json", cwd=proj)
        self.assertEqual(proc.returncode, SOME_ZERO, proc.stderr)
        rows = {r["id"]: r for r in json.loads(proc.stdout)}
        self.assertEqual((rows["PJ-005"]["score"], rows["PJ-005"]["line"]), (0, 6))
        self.assertIn("HD-001", rows["PJ-005"]["message"])
        self.assertEqual((rows["PJ-006"]["score"], rows["PJ-006"]["line"]), (0, 7))
        self.assertEqual(rows["PJ-006"]["message"], "the line stops being true after a date it names")
        self.assertEqual(rows["PJ-007"]["score"], 0)
        self.assertEqual([l["line"] for l in rows["PJ-007"]["lines"]], [8, 9])

    def test_time_and_harness_likeness(self):
        """Likeness fixture: 'before you start', 'until the user replies', 'by name' and 'the API' score 1."""
        proj = self.project("time-likeness")
        proc = run("check.py", "--format", "json", cwd=proj)
        got = scores(proc)
        for rid in ("PJ-005", "PJ-006", "PJ-007"):
            self.assertEqual(got[(rid, ".claude/agents/planner.md")], 1, rid)

    def test_codex_default(self):
        """HD-002: a Codex agent file asking the agent to read AGENTS.md."""
        proj = self.project("codex-defaults")
        row = row_for(run("check.py", "--format", "json", cwd=proj), "PJ-005")
        self.assertEqual((row["score"], row["line"]), (0, 4))
        self.assertIn("HD-002", row["message"])

    def test_declares_its_tools(self):
        """PJ-008 to PJ-010: a delegated persona with no tools field, each in its own harness; none for Codex."""
        proj = self.project("declares-tools")
        proc = run("check.py", "--format", "json", cwd=proj)
        self.assertEqual(proc.returncode, SOME_ZERO, proc.stderr)
        got = scores(proc)
        self.assertEqual(got[("PJ-008", ".claude/agents/planner.md")], 0)
        self.assertEqual(got[("PJ-009", ".gemini/agents/summariser.md")], 0)
        self.assertEqual(got[("PJ-010", ".github/agents/triage.agent.md")], 0)
        self.assertEqual(got[("PJ-008", ".claude/agents/doc-writer.md")], 1)
        # Each row applies to its own harness only.
        self.assertIsNone(got[("PJ-009", ".claude/agents/planner.md")])
        self.assertIsNone(got[("PJ-008", ".github/agents/triage.agent.md")])
        # A Codex custom agent is not scored on 'Declares its tools' (A-27).
        for rid in ("PJ-008", "PJ-009", "PJ-010"):
            self.assertIsNone(got[(rid, ".codex/agents/reviewer.toml")], rid)
        # A 0 quotes the line that names the agent, since the missing field has no line of its own.
        row = row_for(proc, "PJ-008", ".claude/agents/planner.md")
        self.assertEqual((row["line"], row["quote"]), (2, "name: planner"))
        self.assertEqual(row["message"], "the persona declares no tools: its tools field is missing or empty")

    def test_declares_its_tools_standing(self):
        """A standing persona is not scored on 'Declares its tools'."""
        proj = self.project("standing")
        got = scores(run("check.py", "notes/release.md", "--format", "json", cwd=proj))
        for rid in ("PJ-008", "PJ-009", "PJ-010"):
            self.assertIsNone(got[(rid, "notes/release.md")], rid)

    def test_plain_emphasis_and_placeholders(self):
        """PJ-011 and PJ-012 on the review questions' examples; a fenced block is an example, not an instruction."""
        proj = self.project("emphasis")
        proc = run("check.py", "--format", "json", cwd=proj)
        self.assertEqual(proc.returncode, SOME_ZERO, proc.stderr)
        emphasis = row_for(proc, "PJ-011")
        self.assertEqual((emphasis["score"], [l["line"] for l in emphasis["lines"]]), (0, [7]))
        self.assertEqual(emphasis["quote"], "CRITICAL: You MUST run the tests.")
        placeholders = row_for(proc, "PJ-012")
        self.assertEqual((placeholders["score"], [l["line"] for l in placeholders["lines"]]), (0, [8, 9, 10]))

    def test_plain_emphasis_likeness(self):
        """Likeness fixture: 'critical' and 'must' in lower case, a todo list and a bracketed link score 1."""
        proj = self.project("emphasis-likeness")
        proc = run("check.py", "--format", "json", cwd=proj)
        self.assertEqual(proc.returncode, ALL_ONE, proc.stdout + proc.stderr)
        got = scores(proc)
        for rid in ("PJ-011", "PJ-012"):
            self.assertEqual(got[(rid, ".claude/agents/tester.md")], 1, rid)

    def test_spread_over_files(self):
        """T-13: a listed persona's files are checked with it, under the persona's kind and harness."""
        proj = self.project("si13")
        proc = run("check.py", "--format", "json", cwd=proj)
        paths = {r["path"] for r in json.loads(proc.stdout)}
        self.assertEqual(
            paths,
            {
                ".claude/agents/stylist.md",
                "personas/reviewer/reviewer.md",
                "personas/reviewer/scale.md",
                "personas/reviewer/examples.md",
            },
        )
        self.assertIn("personas/reviewer/missing.md", proc.stderr)

    def test_text_line_quotes_the_line(self):
        proj = self.project("time-defaults")
        proc = run("check.py", ".claude/agents/planner.md", cwd=proj)
        line = [l for l in proc.stdout.splitlines() if l.startswith("PJ-006\t")][0]
        self.assertEqual(
            line.split("\t")[:4],
            ["PJ-006", "0", ".claude/agents/planner.md:7", "'Keep the old changelog format until August.'"],
        )

    def test_exit_zero(self):
        proc = run("check.py", "--exit-zero", cwd=self.project("si2-planted"))
        self.assertEqual(proc.returncode, ALL_ONE)
        self.assertIn("PJ-001\t0\t", proc.stdout)

    def test_kind_override(self):
        """--kind standing makes a delegated file standing, so 'Declares its tools' no longer applies."""
        proj = self.project("time-defaults")
        proc = run("check.py", "--kind", "standing", "--format", "json", cwd=proj)
        self.assertIn(proc.returncode, (ALL_ONE, SOME_ZERO), proc.stderr)
        self.assertEqual({r["delegated"] for r in json.loads(proc.stdout)}, {False})
        self.assertIsNone(scores(proc)[("PJ-008", ".claude/agents/planner.md")])

    def test_session_text(self):
        text = (make_fixtures.FILES / "si2-planted.fixture").read_text()
        proc = run("check.py", "-", stdin=text, cwd=self.tmp)
        self.assertEqual(proc.returncode, SOME_ZERO, proc.stderr)
        self.assertIn("<session text>:7", proc.stdout)
        # Session text names no harness, so neither PJ-005 nor the 'Declares its tools' rows apply to it.
        for rid in ("PJ-005", "PJ-008", "PJ-009", "PJ-010"):
            line = [l for l in proc.stdout.splitlines() if l.startswith(rid + "\t")][0]
            self.assertEqual(line.split("\t")[1], "-", rid)

    def test_named_set_aside_file(self):
        """A named CLAUDE.md is set aside, so there is nothing to check: exit 3, with the reason."""
        proc = run("check.py", "CLAUDE.md", cwd=self.project("si11"))
        self.assertEqual(proc.returncode, NOTHING)
        self.assertIn("CLAUDE.md is set aside", proc.stderr)
        self.assertIn("project instructions", proc.stderr)


def zeros(proc):
    """{(row id, path): the lines that row scored 0 on} from check.py's JSON output."""
    return {(r["id"], r["path"]): sorted(l["line"] for l in r["lines"]) for r in json.loads(proc.stdout) if r["score"] == 0}


class TestTQ(ScratchCase):
    """T-Q: check.py reads quoted and example text as masked, and scores only real pointers (specification §3c and
    §8, Sophos, 3 October 2026). Each case scores 1; each control is still caught."""

    def checked(self, project, *paths):
        proc = run("check.py", *paths, "--format", "json", cwd=self.project(project))
        self.assertIn(proc.returncode, (ALL_ONE, SOME_ZERO), proc.stderr)
        return proc

    def test_case_1_names_not_pointers(self):
        """'Run `find.py`' and 'such as `CLAUDE.md`', neither file present: no read verb, so not pointers."""
        got = scores(self.checked("tq-names"))
        self.assertEqual(got[("PJ-001", ".claude/agents/runner.md")], 1)

    def test_case_2_quoted_pointer(self):
        """'Rate findings on the scale in `severity.md`', quoted, with no such file: masked."""
        got = scores(self.checked("tq-quoted-pointer"))
        self.assertEqual(got[("PJ-001", ".claude/agents/rater.md")], 1)

    def test_case_3_quoted_examples(self):
        """The three quoted examples, the first wrapping across two lines: masked."""
        got = scores(self.checked("tq-quoted-examples"))
        for rid in ("PJ-007", "PJ-011", "PJ-012"):
            self.assertEqual(got[(rid, ".claude/agents/linter.md")], 1, rid)

    def test_case_4_block_quote(self):
        """The same three in a block quote: masked."""
        got = scores(self.checked("tq-blockquote"))
        for rid in ("PJ-007", "PJ-011", "PJ-012"):
            self.assertEqual(got[(rid, ".claude/agents/linter.md")], 1, rid)

    def test_case_5_pointer_from_the_skill_root(self):
        """A pointer named from the skill's root, as agents/reviewer.md names references/review-questions.md."""
        got = scores(self.checked("tq-skill-root", "skill/agents/judge.md"))
        self.assertEqual(got[("PJ-001", "skill/agents/judge.md")], 1)

    def test_case_6_the_frozen_files(self):
        """The frozen review-questions.md and agents/reviewer.md give none of §3c's five rows at 0."""
        questions, reviewer = "skill/references/review-questions.md", "skill/agents/reviewer.md"
        frozen = {
            questions: "aea58eacbcc15b29345865cd2897f942617a092cf705bff155fffe2005ede835",
            reviewer: "77c42965947cef7cad6009fb49fd8395cdd367bf487c3676b9ff005ab5fd379f",
        }
        for rel, digest in frozen.items():
            self.assertEqual(sha(ROOT / rel), digest, f"{rel} has moved")
        proc = run("check.py", questions, reviewer, "--format", "json", cwd=ROOT)
        got = zeros(proc)
        listed = [
            ("PJ-001", questions, 11), ("PJ-001", reviewer, 10), ("PJ-007", questions, 191),
            ("PJ-011", questions, 208), ("PJ-012", questions, 213),
        ]
        for rid, path, line in listed:
            self.assertNotIn(line, got.get((rid, path), []), (rid, path, line))

    def test_controls_still_caught(self):
        """A real pointer, a list under 'Open these when you need more:', real capitals, a real placeholder, a real
        dated statement, and an apostrophe beside capitals: each still scores 0, on its own line."""
        got = zeros(self.checked("tq-controls"))
        path = ".claude/agents/checker.md"
        self.assertEqual(got[("PJ-001", path)], [7, 10])
        self.assertEqual(got[("PJ-011", path)], [12, 18])
        self.assertEqual(got[("PJ-012", path)], [14])
        self.assertEqual(got[("PJ-007", path)], [16])


class TestT10Determinism(ScratchCase):
    def test_two_runs_byte_identical(self):
        proj = self.project("si11")
        first = run("check.py", ".claude/agents/helper.md", cwd=proj)
        second = run("check.py", ".claude/agents/helper.md", cwd=proj)
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
    def bad_table(self, *rows):
        table = self.tmp / "bad.tsv"
        table.write_text("\t".join(HEADER) + "\n" + "\n".join(rows) + "\n", encoding="utf-8")
        return table

    def checked(self, table):
        return run("check.py", "--table", table, cwd=self.project("si2-clean"))

    def test_empty_project(self):
        """Empty fixture: nothing to check, exit 3."""
        self.assertEqual(run("check.py", cwd=self.project("empty")).returncode, NOTHING)

    def test_empty_file(self):
        """Empty fixture: an empty persona file, exit 3."""
        proc = run("check.py", ".claude/agents/blank.md", cwd=self.project("empty-file"))
        self.assertEqual(proc.returncode, NOTHING)
        self.assertIn("empty", proc.stderr)

    def test_empty_session_text(self):
        self.assertEqual(run("check.py", "-", stdin="").returncode, NOTHING)

    def test_likeness_project(self):
        """Likeness fixture: a project of look-alikes holds nothing to check."""
        self.assertEqual(run("check.py", cwd=self.project("likeness")).returncode, NOTHING)

    def test_old_header(self):
        """Round 2's ten-column header, with no harness column, is a table error naming line 1."""
        table = self.tmp / "old.tsv"
        table.write_text(
            "id\tquestion\tkind\tapplies_to\tfield\tpattern\tunless\tdata\tsource\tmessage\n", encoding="utf-8"
        )
        proc = self.checked(table)
        self.assertEqual(proc.returncode, ERROR)
        self.assertIn("line 1", proc.stderr)
        self.assertIn("harness", proc.stderr)

    def test_unknown_question(self):
        proc = self.checked(self.bad_table(table_row(
            "PJ-001", "Pointers carry triggers", "missing-path", "any", "", "", "", "", "", "s", "m")))
        self.assertEqual(proc.returncode, ERROR)
        self.assertIn("line 2", proc.stderr)
        self.assertIn("question", proc.stderr)

    def test_reading_check_is_a_table_error(self):
        """A row may name only a check marked script; 'Nothing said twice' is a reading check."""
        proc = self.checked(self.bad_table(table_row(
            "PJ-001", "Nothing said twice", "line-pattern", "any", "", "", "x", "", "", "s", "m")))
        self.assertEqual(proc.returncode, ERROR)
        self.assertIn("line 2", proc.stderr)
        self.assertIn("script", proc.stderr)

    def test_new_script_checks_are_accepted(self):
        """The three checks marked script in round 3 may each have a row."""
        proc = self.checked(self.bad_table(
            table_row("PJ-901", "Declares its tools", "field-missing", "delegated", "Claude Code", "tools", "", "", "", "s", "m"),
            table_row("PJ-902", "Plain emphasis", "line-pattern", "any", "", "", "x", "", "", "s", "m"),
            table_row("PJ-903", "No placeholders", "line-pattern", "any", "", "", "x", "", "", "s", "m"),
        ))
        self.assertNotEqual(proc.returncode, ERROR, proc.stderr)

    def test_unknown_harness(self):
        proc = self.checked(self.bad_table(table_row(
            "PJ-001", "Declares its tools", "field-missing", "delegated", "Copilot", "tools", "", "", "", "s", "m")))
        self.assertEqual(proc.returncode, ERROR)
        self.assertIn("line 2, column harness", proc.stderr)

    def test_unknown_kind(self):
        proc = self.checked(self.bad_table(table_row(
            "PJ-001", "No time-sensitive statements", "word-count", "any", "", "", "", "", "", "s", "m")))
        self.assertEqual(proc.returncode, ERROR)
        self.assertIn("kind", proc.stderr)

    def test_bad_id_and_duplicate(self):
        proc = self.checked(self.bad_table(
            table_row("PJ-1", "No time-sensitive statements", "line-pattern", "any", "", "", "x", "", "", "s", "m"),
            table_row("PJ-002", "No time-sensitive statements", "line-pattern", "any", "", "", "x", "", "", "s", "m"),
            table_row("PJ-002", "No time-sensitive statements", "line-pattern", "any", "", "", "y", "", "", "s", "m"),
        ))
        self.assertEqual(proc.returncode, ERROR)
        self.assertIn("line 2", proc.stderr)
        self.assertIn("line 4", proc.stderr)

    def test_bad_pattern(self):
        proc = self.checked(self.bad_table(table_row(
            "PJ-001", "No time-sensitive statements", "line-pattern", "any", "", "", "(unclosed", "", "", "s", "m")))
        self.assertEqual(proc.returncode, ERROR)
        self.assertIn("pattern", proc.stderr)

    def test_harness_default_without_data(self):
        proc = self.checked(self.bad_table(table_row(
            "PJ-005", "Leaves the harness's work to the harness", "harness-default", "any", "", "", "", "", "", "s", "m")))
        self.assertEqual(proc.returncode, ERROR)
        self.assertIn("data", proc.stderr)

    def test_data_on_another_kind(self):
        proc = self.checked(self.bad_table(table_row(
            "PJ-006", "No time-sensitive statements", "line-pattern", "any", "", "", "x", "", "harness-defaults.tsv",
            "s", "m")))
        self.assertEqual(proc.returncode, ERROR)
        self.assertIn("data", proc.stderr)

    def test_missing_data_table(self):
        proc = self.checked(self.bad_table(table_row(
            "PJ-005", "Leaves the harness's work to the harness", "harness-default", "any", "", "", "", "",
            "no-such.tsv", "s", "m")))
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
        proc = self.checked(folder / "failures.tsv")
        self.assertEqual(proc.returncode, ERROR)
        self.assertIn("harness-defaults.tsv, line 5", proc.stderr)
        self.assertIn("column id", proc.stderr)
        self.assertIn("column pattern", proc.stderr)

    def test_unknown_kind_option(self):
        self.assertEqual(run("check.py", "--kind", "ambient", cwd=self.project("si1")).returncode, ERROR)

    def test_unreadable_path(self):
        proc = run("check.py", "missing.md", cwd=self.project("si1"))
        self.assertEqual(proc.returncode, ERROR)
        self.assertIn("cannot read missing.md", proc.stderr)


class TestSeedTable(unittest.TestCase):
    def test_seed_rows(self):
        """Round 3's rows: PJ-004 withdrawn and its ID not reused; PJ-008 to PJ-012 added, each naming its harness."""
        lines = TABLE.read_text(encoding="utf-8").splitlines()
        self.assertEqual(lines[0].split("\t"), HEADER)
        rows = [l.split("\t") for l in lines[1:]]
        self.assertEqual(
            [(r[0], r[1], r[2], r[3], r[4]) for r in rows],
            [
                ("PJ-001", "Pointers carry their triggers", "missing-path", "any", ""),
                ("PJ-002", "Pointers carry their triggers", "line-pattern", "any", ""),
                ("PJ-003", "Bound parts agree with the prose", "field-and-line", "any", ""),
                ("PJ-005", "Leaves the harness's work to the harness", "harness-default", "any", ""),
                ("PJ-006", "No time-sensitive statements", "line-pattern", "any", ""),
                ("PJ-007", "No time-sensitive statements", "line-pattern", "any", ""),
                ("PJ-008", "Declares its tools", "field-missing", "delegated", "Claude Code"),
                ("PJ-009", "Declares its tools", "field-missing", "delegated", "Gemini CLI"),
                ("PJ-010", "Declares its tools", "field-missing", "delegated", "GitHub Copilot"),
                ("PJ-011", "Plain emphasis", "line-pattern", "any", ""),
                ("PJ-012", "No placeholders", "line-pattern", "any", ""),
            ],
        )
        by_id = {r[0]: dict(zip(HEADER, r)) for r in rows}
        self.assertEqual(by_id["PJ-005"]["data"], "harness-defaults.tsv")
        for rid in ("PJ-008", "PJ-009", "PJ-010"):
            self.assertEqual(by_id[rid]["field"], "tools")
        self.assertEqual(
            by_id["PJ-011"]["pattern"], r"(?-i:\b(CRITICAL|IMPORTANT|MUST|NEVER|ALWAYS|REQUIRED|WARNING)\b)"
        )
        self.assertEqual(
            by_id["PJ-012"]["pattern"],
            r"(?-i:\b(TODO|TBD|FIXME|XXX)\b)|\[(insert|add|your|placeholder)[^\]]*\]|<(insert|your)[^>]*>|\{\{[^}]*\}\}",
        )

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
