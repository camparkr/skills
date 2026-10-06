"""Tests for check.py, the true/false checks run from a table, to the current table: a harness column, and rows
for 'Declares its tools', 'Plain emphasis' and 'No placeholders'."""

import hashlib
import json
import shutil
import subprocess
import sys
import unittest

from support import REFERENCES, ROOT, SCRIPTS, ScratchCase, make_fixtures, run

# Exit codes check.py promises in its docstring.
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
    """A missing path: a planted path scores 0; the clean file scores 1; a new row needs no code change."""

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
                "", "", "test row", "the phrase this test plants",
            ) + "\n")
        proc = run("check.py", "--table", table, "--format", "json", cwd=proj)
        self.assertEqual(proc.returncode, SOME_ZERO, proc.stdout + proc.stderr)
        self.assertEqual(scores(proc)[("PJ-900", ".claude/agents/checker.md")], 0)
        self.assertEqual({p.name: sha(p) for p in SCRIPTS.glob("*.py")}, before)

    def test_new_harness_default_needs_no_code_change(self):
        """A new row in a copy of harness-defaults.tsv scores PJ-005 0 and names the row."""
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
        # A Codex custom agent is not scored on 'Declares its tools': failures.tsv has no Codex row for it.
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
        """A listed persona's files are checked with it, under the persona's kind and harness."""
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
    """Quoted text: check.py reads quoted and example text as masked, and scores only real pointers, so a persona is
    not marked down for the examples it quotes. Each case scores 1; each control is still caught."""

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
        """A pointer named from the skill's root, as reviewer.md names references/questions/scales.md."""
        got = scores(self.checked("tq-skill-root", "skill/agents/judge.md"))
        self.assertEqual(got[("PJ-001", "skill/agents/judge.md")], 1)

    def test_case_6_the_frozen_files(self):
        """review-questions.md and agents/reviewer.md as they stood at commit 1764a6c give no row at 0 on either file,
        and so none at the five places listed below."""
        questions, reviewer = "skill/references/review-questions.md", "skill/agents/reviewer.md"
        frozen = {
            questions: "aea58eacbcc15b29345865cd2897f942617a092cf705bff155fffe2005ede835",
            reviewer: "77c42965947cef7cad6009fb49fd8395cdd367bf487c3676b9ff005ab5fd379f",
        }
        # Case (6) is defined on the files at 1764a6c; review-questions.md has changed since, so the files are
        # read from Git at that commit into a scratch copy of the skill, never from the working tree.
        # A release archive or a copy without .git, or a clone that lacks the commit, cannot read them; the case is then
        # skipped with its reason, since it tests files that are not there to test.
        try:
            have = subprocess.run(["git", "-C", str(ROOT), "cat-file", "-e", "1764a6c^{commit}"], capture_output=True)
        except OSError:
            self.skipTest("case 6 reads its files from Git at commit 1764a6c, and git is not installed")
        if have.returncode != 0:
            self.skipTest(
                "case 6 reads its files from Git at commit 1764a6c, and this copy has no Git history holding that commit"
            )
        tree = self.tmp / "at-1764a6c"
        tree.mkdir()
        archive = subprocess.run(["git", "-C", str(ROOT), "archive", "1764a6c", "--", "."], capture_output=True, check=True)
        subprocess.run(["tar", "-x", "-C", str(tree)], input=archive.stdout, check=True)
        for rel, digest in frozen.items():
            self.assertEqual(sha(tree / rel), digest, f"{rel} at 1764a6c is not the file case (6) names")
        proc = run("check.py", questions, reviewer, "--format", "json", cwd=tree)
        got = zeros(proc)
        listed = [
            ("PJ-001", questions, 11), ("PJ-001", reviewer, 10), ("PJ-007", questions, 191),
            ("PJ-011", questions, 208), ("PJ-012", questions, 213),
        ]
        for rid, path, line in listed:
            self.assertNotIn(line, got.get((rid, path), []), (rid, path, line))
        self.assertEqual(got, {})

    def test_case_7_a_form_that_is_not_base(self):
        """'A standing persona, such as `CLAUDE.md`, loads every session.': 'loads' is not a base form."""
        self.assertEqual(scores(self.checked("tq-c7"))[("PJ-001", ".claude/agents/namer.md")], 1)

    def test_case_8_following(self):
        """'Run `build.sh` with the following flags.': 'following' is not a base form."""
        self.assertEqual(scores(self.checked("tq-c8"))[("PJ-001", ".claude/agents/builder.md")], 1)

    def test_case_9_another_file_reads_it(self):
        """grounding.md's sentence, under 'Leaves the harness's work to the harness': 'tells Claude in words to read
        `AGENTS.md`' is not addressed to the agent."""
        self.assertEqual(scores(self.checked("tq-c9"))[("PJ-001", ".claude/agents/explainer.md")], 1)

    def test_case_10_read_after_to(self):
        """reviewer.md line 19's sentence: 'tells the agent to read' is not an instruction to read."""
        self.assertEqual(scores(self.checked("tq-c10"))[("PJ-001", ".claude/agents/gatherer.md")], 1)

    def test_case_11_follows(self):
        """reviewer.md line 30's sentence: 'the score follows' has a subject that is not the agent."""
        self.assertEqual(scores(self.checked("tq-c11"))[("PJ-001", ".claude/agents/scorer.md")], 1)

    def test_case_12_addressed_instructions(self):
        """'You must open `notes/missing.md`' and 'once you have read `notes/other-missing.md`': both addressed to the
        agent, so both missing files score 0."""
        got = zeros(self.checked("tq-c12"))
        self.assertEqual(got[("PJ-001", ".claude/agents/checker.md")], [7, 8])

    def test_case_13_link_first(self):
        """'[Read the guide](missing.md) before you rate.': a sentence opening with a link counts; the target is the
        pointer."""
        got = zeros(self.checked("tq-c13"))
        self.assertEqual(got[("PJ-001", ".claude/agents/guide-reader.md")], [7])

    def test_case_14_you_inside_a_clause(self):
        """'The file you see in `notes/missing.md` lists the rows.': 'you' follows 'file', so it opens no clause."""
        self.assertEqual(scores(self.checked("tq-c14"))[("PJ-001", ".claude/agents/row-reader.md")], 1)

    def test_case_15_open_source(self):
        """'Open source code lives in `vendor/missing/`.': 'Open source' is not an instruction."""
        self.assertEqual(scores(self.checked("tq-c15"))[("PJ-001", ".claude/agents/vendor-reader.md")], 1)

    def test_case_16_known_limits(self):
        """'read in full' after the path, and 'refer to it' in a later clause: the stated limit, not counted."""
        self.assertEqual(scores(self.checked("tq-c16"))[("PJ-001", ".claude/agents/limit-reader.md")], 1)

    def test_round_4_controls(self):
        """'When you need more, you must open …' and 'Open … when a note is old.': still caught."""
        got = zeros(self.checked("tq-controls-4"))
        self.assertEqual(got[("PJ-001", ".claude/agents/checker.md")], [7, 9])

    def test_controls_still_caught(self):
        """A real pointer, a list under 'Open these when you need more:', real capitals, a real placeholder, a real
        dated statement, an apostrophe beside capitals, and 'Before you rate, open …': each still scores 0, on its
        own line."""
        got = zeros(self.checked("tq-controls"))
        path = ".claude/agents/checker.md"
        self.assertEqual(got[("PJ-001", path)], [7, 10, 20])
        self.assertEqual(got[("PJ-011", path)], [12, 18])
        self.assertEqual(got[("PJ-012", path)], [14])
        self.assertEqual(got[("PJ-007", path)], [16])


class TestBranchesT_W(ScratchCase):
    """check.py prints the three branches for each persona, as find.py does."""

    def test_text_and_json(self):
        proj = self.project("branches")
        text = run("check.py", ".claude/agents/summary-writer.md", ".codex/agents/auditor.toml", "notes/release.md", cwd=proj)
        self.assertIn(".claude/agents/summary-writer.md\tbranches: delegated yes (folder); harness Claude Code; settings none", text.stdout)
        self.assertIn(".codex/agents/auditor.toml\tbranches: delegated yes (folder); harness Codex; settings sandbox_mode", text.stdout)
        self.assertIn("notes/release.md\tbranches: delegated no; harness none; settings none", text.stdout)
        proc = run("check.py", ".codex/agents/auditor.toml", "--format", "json", cwd=proj)
        rows = json.loads(proc.stdout)
        self.assertTrue(rows)
        for r in rows:
            self.assertEqual(r["branches"], {"delegated": True, "harness": "Codex", "settings": ["sandbox_mode"]})

    def test_rows_read_the_weighted_titles(self):
        """The check table's questions are matched against the review questions' titles, weight marks included."""
        proc = run("check.py", cwd=self.project("si2-clean"))
        self.assertEqual(proc.returncode, ALL_ONE, proc.stderr)


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
        """The older ten-column header, with no harness column, is a table error naming line 1."""
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
        """The three newer checks marked script, 'Declares its tools', 'Plain emphasis' and 'No placeholders', may each
        have a row."""
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
        """The seed rows: PJ-004 withdrawn and its ID not reused; PJ-008 to PJ-012 added, each naming its harness."""
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


class TestFieldChecksOnTheMainFile(ScratchCase):
    """A persona spread over files, as report.py scores it: a field-missing row, such as PJ-008 'Declares its tools', runs on a persona's main
    file only. A persona the project's list names with extra files is checked over all of them, but the extra files
    hold no front matter of their own, so a missing tools field there says nothing about the persona."""

    SECTIONS = "# Sections\n\nKeep each section of a report under ten lines.\n"

    def listed_project(self, main_text):
        proj = self.tmp / "listed"
        files = {
            ".claude/agents/releaser.md": main_text,
            ".claude/agents/release/sections.md": self.SECTIONS,
            "personas.txt": ".claude/agents/releaser.md .claude/agents/release/sections.md\n",
        }
        for rel, text in files.items():
            (proj / rel).parent.mkdir(parents=True, exist_ok=True)
            (proj / rel).write_text(text, encoding="utf-8")
        return proj

    def checked(self, main_text):
        proc = run("check.py", "--format", "json", cwd=self.listed_project(main_text))
        self.assertIn(proc.returncode, (ALL_ONE, SOME_ZERO), proc.stdout + proc.stderr)
        return proc

    def test_tools_declared_on_the_main_file(self):
        proc = self.checked("---\nname: releaser\ndescription: Drafts release notes.\ntools: Read, Grep\n---\n\n"
                            "You draft release notes from the merged changes.\n")
        got = scores(proc)
        self.assertEqual(got[("PJ-008", ".claude/agents/releaser.md")], 1)
        self.assertIsNone(got[("PJ-008", ".claude/agents/release/sections.md")])
        self.assertEqual(proc.returncode, ALL_ONE, proc.stdout)

    def test_no_field_row_at_0_on_the_extra_file(self):
        """With the persona's tools missing, only the main file scores 0 on PJ-008."""
        got = scores(self.checked("---\nname: releaser\ndescription: Drafts release notes.\n---\n\n"
                                  "You draft release notes from the merged changes.\n"))
        self.assertIsNone(got[("PJ-008", ".claude/agents/release/sections.md")])

    def test_control_tools_missing_on_the_main_file(self):
        """Control: a listed persona with no tools field still scores 0 on PJ-008, quoting its main file's name line."""
        proc = self.checked("---\nname: releaser\ndescription: Drafts release notes.\n---\n\n"
                            "You draft release notes from the merged changes.\n")
        self.assertEqual(scores(proc)[("PJ-008", ".claude/agents/releaser.md")], 0)
        self.assertEqual(row_for(proc, "PJ-008", ".claude/agents/releaser.md")["line"], 2)
        self.assertEqual(proc.returncode, SOME_ZERO)


@unittest.skipUnless(shutil.which("git"), "git is not installed, and these tests call it to build their copies")
class TestCase6WithoutHistory(ScratchCase):
    """Case 6 reads its files from Git at 1764a6c. In a copy with no .git, or in a repository without that commit, it
    is skipped with a stated reason instead of erroring; in this repository, with the commit, it runs. These tests
    call git themselves, so they are skipped when git is not installed."""

    CASE = "test_check.TestTQ.test_case_6_the_frozen_files"

    def copy(self):
        """A copy of the skill folder with no .git above it, as a release archive gives it."""
        dest = self.tmp / "persona-judge"
        shutil.copytree(ROOT, dest, ignore=shutil.ignore_patterns("__pycache__", ".git"))
        return dest

    def run_case(self, folder):
        return subprocess.run(
            [sys.executable, "-m", "unittest", "-v", self.CASE], cwd=folder / "tests", capture_output=True, text=True,
            timeout=120,
        )

    def assert_skipped(self, proc):
        out = proc.stdout + proc.stderr
        self.assertEqual(proc.returncode, 0, out)
        self.assertIn("skipped", out)
        self.assertIn("1764a6c", out)
        self.assertNotIn("Error", out)

    def test_no_git(self):
        folder = self.copy()
        probe = subprocess.run(["git", "-C", str(folder), "rev-parse", "--git-dir"], capture_output=True, text=True)
        if probe.returncode == 0:
            self.skipTest(f"the scratch folder {folder} lies inside a Git repository, so it cannot stand for a copy without one")
        self.assert_skipped(self.run_case(folder))

    def test_commit_missing(self):
        folder = self.copy()
        for args in (["init", "-q"], ["add", "-A"],
                     ["-c", "user.name=test", "-c", "user.email=test@example.invalid", "commit", "-q", "-m", "copy"]):
            subprocess.run(["git", "-C", str(folder), *args], check=True, capture_output=True)
        self.assert_skipped(self.run_case(folder))

    def test_control_runs_with_the_commit(self):
        """Control: in this repository the commit is present, so case 6 runs and passes, and is not skipped."""
        have = subprocess.run(["git", "-C", str(ROOT), "cat-file", "-e", "1764a6c^{commit}"], capture_output=True)
        if have.returncode != 0:
            self.skipTest("this copy holds no commit 1764a6c, so the control cannot run here")
        proc = self.run_case(ROOT)
        out = proc.stdout + proc.stderr
        self.assertEqual(proc.returncode, 0, out)
        self.assertIn("... ok", out)
        self.assertNotIn("skipped", out)


if __name__ == "__main__":
    unittest.main()
