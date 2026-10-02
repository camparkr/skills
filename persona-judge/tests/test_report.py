"""Tests for report.py: schema, validate, render and verify (SI-4, SI-10, SI-11)."""

import copy
import json
import re
import sys
import unittest
from fractions import Fraction

from support import SCRIPTS, ScratchCase, make_fixtures, run

# Exit codes report.py promises (specification §3e).
OK, MISMATCH, REFUSED, NO_SCORE = 0, 1, 2, 3

NO_PREDICTION = "A score does not predict how an agent behaves; the lines above are the review."
CLEAN = "Nothing was found in this file."
VERDICT_WORDS = re.compile(
    r"\b(pass|passes|passed|fail|fails|failed|approve|approved|block|blocked|severity|critical|major|minor)\b",
    re.IGNORECASE,
)

SRC_PERMISSIONS = "Anthropic, 'Permission rules are enforced by Claude Code, not by the model'"
SRC_RECORD = "the record kept while this skill was built"
SRC_SUBAGENTS = "Anthropic, 'Claude uses each subagent's description to decide when to delegate tasks'"


def helper_review():
    """A review of .claude/agents/helper.md with findings; it scores 5 of 9, so 0.56 and 3 stars."""
    return {
        "path": ".claude/agents/helper.md",
        "questions": [
            {"question": "Pointers carry their triggers", "score": 1},
            {"question": "Consistent with itself", "score": 1},
            {"question": "Nothing said twice", "score": 1},
            {
                "question": "Bound parts agree with the prose",
                "score": 0,
                "findings": [{"line": 9, "quote": "Never edit files", "source": SRC_PERMISSIONS, "rule": "PJ-003"}],
            },
            {
                "question": "Terms defined where they are used",
                "scale": "frequency",
                "source": SRC_RECORD,
                "places": [{"line": 10, "quote": "Rate each finding high, medium or low.", "meets": False}],
            },
            {
                "question": "Rules held in the file",
                "scale": "frequency",
                "source": SRC_RECORD,
                "places": [
                    {"line": 9, "quote": "Never edit files; report what you find in a list.", "meets": True},
                    {"line": 10, "quote": "Rate each finding high, medium or low.", "meets": True},
                    {"line": 11, "quote": "If the scope is unclear, ask.", "meets": True},
                ],
            },
            {
                "question": "Directions for when nobody answers",
                "scale": "frequency",
                "source": SRC_RECORD,
                "places": [{"line": 11, "quote": "If the scope is unclear, ask.", "meets": False}],
            },
            {
                "question": "Answers defined, edge cases included",
                "scale": "frequency",
                "source": "the review questions",
                "places": [
                    {"line": 10, "quote": "high, medium or low", "meets": False},
                    {"line": 7, "quote": "report what you find", "meets": True},
                ],
            },
            {"question": "Its own criteria met", "not_rated": "The file sets no criterion for the agent's work."},
            {
                "question": "The description says when to choose it",
                "scale": "quality",
                "point": 2,
                "findings": [{"line": 3, "quote": "Reviews pull requests for style problems.", "source": SRC_SUBAGENTS}],
            },
        ],
        "fit": {"statement": "No neighbouring persona files were supplied."},
    }


def doc_writer_review():
    """A clean review of .claude/agents/doc-writer.md; it scores 1.00 and 5 stars."""
    return {
        "path": ".claude/agents/doc-writer.md",
        "questions": [
            {"question": "Pointers carry their triggers", "score": 1},
            {"question": "Consistent with itself", "score": 1},
            {"question": "Nothing said twice", "score": 1},
            {"question": "Bound parts agree with the prose", "score": 1},
            {"question": "Terms defined where they are used", "not_rated": "The rules name no scale or term."},
            {
                "question": "Rules held in the file",
                "scale": "frequency",
                "source": SRC_RECORD,
                "places": [
                    {"line": 7, "quote": "Read `CHANGELOG.md` when the user asks for release notes", "meets": True},
                    {"line": 8, "quote": "Write each note as one sentence in the past tense.", "meets": True},
                    {"line": 9, "quote": "When the changelog is empty", "meets": True},
                ],
            },
            {"question": "Directions for when nobody answers", "not_rated": "No rule asks or waits."},
            {
                "question": "Answers defined, edge cases included",
                "scale": "frequency",
                "source": "the review questions",
                "places": [{"line": 9, "quote": "say there is nothing to report", "meets": True}],
            },
            {"question": "Its own criteria met", "not_rated": "The file sets no criterion for the agent's work."},
            {"question": "The description says when to choose it", "scale": "quality", "point": 4},
        ],
    }


def claude_md_review():
    """A review of the standing CLAUDE.md, which has no bound parts; it scores 3 of 5, so 0.60 and 3 stars."""
    return {
        "path": "CLAUDE.md",
        "questions": [
            {
                "question": "Pointers carry their triggers",
                "score": 0,
                "findings": [{"line": 4, "quote": "See also `docs/style.md`.", "source": SRC_RECORD}],
            },
            {"question": "Consistent with itself", "score": 1},
            {"question": "Nothing said twice", "score": 1},
            {"question": "Bound parts agree with the prose", "not_rated": "The file has no settings."},
            {
                "question": "Terms defined where they are used",
                "scale": "frequency",
                "source": SRC_RECORD,
                "places": [{"line": 6, "quote": "small, medium or large", "meets": False}],
            },
            {
                "question": "Rules held in the file",
                "scale": "frequency",
                "source": SRC_RECORD,
                "places": [
                    {"line": 3, "quote": "Run the tests with `make test` before every commit.", "meets": True},
                    {"line": 6, "quote": "Rate each change as small, medium or large", "meets": True},
                ],
            },
            {"question": "Directions for when nobody answers", "not_rated": "No rule asks or waits."},
            {"question": "Answers defined, edge cases included", "not_rated": "The file names no closed set of answers."},
            {"question": "Its own criteria met", "not_rated": "The file sets no criterion."},
            {"question": "The description says when to choose it", "not_rated": "A standing persona is not chosen."},
        ],
    }


class ReportCase(ScratchCase):
    def setUp(self):
        super().setUp()
        self.proj = self.project("si11")

    def write(self, files, name="record.json"):
        path = self.tmp / name
        path.write_text(json.dumps({"root": self.proj.as_posix(), "files": files}), encoding="utf-8")
        return path

    def render(self, files, *extra):
        return run("report.py", "render", *extra, self.write(files))


class TestSchemaAndValidate(ReportCase):
    def test_schema_is_json(self):
        proc = run("report.py", "schema")
        self.assertEqual(proc.returncode, OK, proc.stderr)
        self.assertIn("files", json.loads(proc.stdout)["properties"])

    def test_sound_records(self):
        for review in (helper_review(), doc_writer_review(), claude_md_review()):
            proc = run("report.py", "validate", self.write([review]))
            self.assertEqual(proc.returncode, OK, review["path"] + "\n" + proc.stdout + proc.stderr)

    def test_record_on_standard_input(self):
        record = json.dumps({"root": self.proj.as_posix(), "files": [doc_writer_review()]})
        proc = run("report.py", "validate", "-", stdin=record)
        self.assertEqual(proc.returncode, OK, proc.stdout + proc.stderr)

    def faults(self, review):
        proc = run("report.py", "validate", self.write([review]))
        self.assertEqual(proc.returncode, REFUSED, proc.stdout)
        return proc.stdout + proc.stderr

    def test_line_beyond_the_file(self):
        review = helper_review()
        review["questions"][3]["findings"][0]["line"] = 88
        out = self.faults(review)
        self.assertIn(
            ".claude/agents/helper.md, 'Bound parts agree with the prose', finding 1, line: cites line 88, "
            "but the file has 11 lines; quote a line that exists",
            out,
        )

    def test_quote_not_on_its_line(self):
        """Likeness fixture: a paraphrase of the line, cited at the right number, is refused."""
        review = helper_review()
        review["questions"][3]["findings"][0]["quote"] = "Do not change any file"
        self.assertIn("does not appear on line 9", self.faults(review))

    def test_unknown_question(self):
        review = helper_review()
        review["questions"][1]["question"] = "Consistent"
        out = self.faults(review)
        self.assertIn("'Consistent'", out)
        self.assertIn("review-questions.md", out)

    def test_check_one_against_row_zero(self):
        review = helper_review()
        review["questions"][3] = {"question": "Bound parts agree with the prose", "score": 1}
        self.assertIn("PJ-003", self.faults(review))

    def test_point_out_of_range(self):
        review = helper_review()
        review["questions"][9]["point"] = 5
        self.assertIn("0 to 4", self.faults(review))

    def test_wrong_scale(self):
        review = helper_review()
        review["questions"][4]["scale"] = "quality"
        review["questions"][4]["point"] = 1
        self.assertIn("frequency", self.faults(review))

    def test_finding_without_quote(self):
        review = helper_review()
        del review["questions"][3]["findings"][0]["quote"]
        self.assertIn("quote", self.faults(review))

    def test_finding_without_source(self):
        review = helper_review()
        del review["questions"][3]["findings"][0]["source"]
        self.assertIn("source", self.faults(review))

    def test_check_score_not_one_or_zero(self):
        review = helper_review()
        review["questions"][0]["score"] = 0.5
        self.assertIn("1 or 0", self.faults(review))

    def test_missing_question(self):
        review = helper_review()
        del review["questions"][1]
        self.assertIn("'Consistent with itself'", self.faults(review))

    def test_standing_file_rated_on_description(self):
        review = claude_md_review()
        review["questions"][9] = {
            "question": "The description says when to choose it",
            "scale": "quality",
            "point": 4,
        }
        self.assertIn("standing", self.faults(review))

    def test_empty_record(self):
        """Empty fixture: an empty record is refused."""
        path = self.tmp / "empty.json"
        path.write_text("", encoding="utf-8")
        proc = run("report.py", "validate", path)
        self.assertEqual(proc.returncode, REFUSED)

    def test_record_with_no_files(self):
        proc = run("report.py", "validate", self.write([]))
        self.assertEqual(proc.returncode, REFUSED)


class TestRenderT4(ReportCase):
    def test_report_with_findings(self):
        proc = self.render([helper_review()])
        self.assertEqual(proc.returncode, OK, proc.stderr)
        out = proc.stdout
        # Header.
        self.assertIn(".claude/agents/helper.md", out.splitlines()[0])
        self.assertIn("Kind: delegated", out)
        self.assertIn("Harness: Claude Code", out)
        self.assertIn("Bound parts: tools", out)
        self.assertRegex(out, r"review questions sha256 [0-9a-f]{12}")
        self.assertIn("check table, 4 rows", out)
        # Order of the sections.
        order = [
            out.index("## Lines behind the scores"),
            out.index("## Score for each question"),
            out.index("## Fit with neighbouring files"),
            out.index("## Total"),
            out.index(NO_PREDICTION),
            out.index("configuration linters"),
        ]
        self.assertEqual(order, sorted(order))
        # Every finding row has a quoted line, a question and a source.
        section = out[out.index("## Lines behind the scores"): out.index("## Score for each question")]
        rows = [l for l in section.splitlines() if l.startswith("| ") and not l.startswith("| Question")]
        self.assertEqual(len(rows), 5)
        for row in rows:
            cells = [c.strip() for c in row.strip("|").split("|")]
            self.assertEqual(len(cells), 5, row)
            question, line, quoted, rule, source = cells
            self.assertTrue(question and line.isdigit() and quoted.startswith("'") and source, row)
        self.assertIn("PJ-003", section)
        # Every check shows 1 or 0; every rating its point and scale word.
        self.assertRegex(out, r"\| Pointers carry their triggers \| check \| - \| - \| 1 \| 1 \|")
        self.assertRegex(out, r"\| Bound parts agree with the prose \| check \| - \| - \| 0 \| 0 \|")
        self.assertRegex(out, r"\| Rules held in the file \| rating, frequency \| 3 \| 3 \| 4, always \| 4/4 \|")
        self.assertRegex(out, r"\| Answers defined, edge cases included \| rating, frequency \| 2 \| 1 \| 2, about half the time \| 2/4 \|")
        self.assertRegex(out, r"\| The description says when to choose it \| rating, quality \| - \| - \| 2, acceptable \| 2/4 \|")
        self.assertIn("| Its own criteria met | not rated |", out)
        # Total.
        self.assertIn("Score: 0.56", out)
        self.assertIn("Stars: 3 of 5", out)
        self.assertIn("9 questions counted", out)
        self.assertNotIn(CLEAN, out)
        self.assertIsNone(VERDICT_WORDS.search(out), VERDICT_WORDS.search(out))

    def test_clean_report(self):
        proc = self.render([doc_writer_review()])
        self.assertEqual(proc.returncode, OK, proc.stderr)
        self.assertIn(CLEAN, proc.stdout)
        self.assertIn("Score: 1.00", proc.stdout)
        self.assertIn("Stars: 5 of 5", proc.stdout)
        self.assertIn(NO_PREDICTION, proc.stdout)
        self.assertIn("No neighbouring persona files were supplied.", proc.stdout)

    def test_check_row_lines_are_listed(self):
        """A row at 0 lists its line even when the review omitted it."""
        review = claude_md_review()
        review["questions"][0]["findings"] = []
        proc = self.render([review])
        self.assertEqual(proc.returncode, OK, proc.stdout + proc.stderr)
        self.assertIn("| Pointers carry their triggers | 4 | 'See also `docs/style.md`.' | PJ-001", proc.stdout)

    def test_no_linters_line_without_bound_parts(self):
        proc = self.render([claude_md_review()])
        self.assertEqual(proc.returncode, OK, proc.stderr)
        self.assertIn("Bound parts: none", proc.stdout)
        self.assertNotIn("configuration linters", proc.stdout)
        self.assertIn("Score: 0.60", proc.stdout)

    def test_render_refuses_unsound_record(self):
        review = helper_review()
        review["questions"][3] = {"question": "Bound parts agree with the prose", "score": 1}
        proc = self.render([review])
        self.assertEqual(proc.returncode, REFUSED)
        self.assertEqual(proc.stdout, "")

    def test_empty_file(self):
        proj = self.project("empty-file")
        path = self.tmp / "e.json"
        path.write_text(json.dumps({"root": proj.as_posix(), "files": [{"path": "CLAUDE.md", "questions": []}]}))
        proc = run("report.py", "render", path)
        self.assertEqual(proc.returncode, NO_SCORE, proc.stderr)
        self.assertIn("This file is empty; no score.", proc.stdout)

    def test_no_question_applies(self):
        review = {
            "path": ".claude/agents/doc-writer.md",
            "questions": [{"question": q["question"], "not_rated": "for the test"} for q in doc_writer_review()["questions"]],
        }
        proc = self.render([review])
        self.assertEqual(proc.returncode, NO_SCORE, proc.stdout + proc.stderr)
        self.assertIn("No question applies to this file; no score.", proc.stdout)

    def test_session_text(self):
        text = (make_fixtures.FILES / "helper-agent.fixture").read_text()
        review = helper_review()
        review["path"] = "<session text>"
        review["text"] = text
        proc = self.render([review])
        self.assertEqual(proc.returncode, OK, proc.stdout + proc.stderr)
        self.assertIn("<session text>", proc.stdout.splitlines()[0])

    def test_render_writes_no_file(self):
        before = make_fixtures.manifest(self.proj)
        record = self.write([helper_review()])
        run("report.py", "render", record, cwd=self.proj)
        self.assertEqual(make_fixtures.manifest(self.proj), before)


class TestSummaryT11(ReportCase):
    def test_summary_order(self):
        proc = self.render([doc_writer_review(), claude_md_review(), helper_review()], "--summary")
        self.assertEqual(proc.returncode, OK, proc.stderr)
        out = proc.stdout
        table = out[: out.index("\n# ")]
        paths = re.findall(r"^\| (\S+) \| (?:standing|delegated) \|", table, re.MULTILINE)
        self.assertEqual(paths, [".claude/agents/helper.md", "CLAUDE.md", ".claude/agents/doc-writer.md"])
        heads = re.findall(r"^# Review: (\S+)", out, re.MULTILINE)
        self.assertEqual(heads, paths)


class TestVerifyT10(ReportCase):
    def test_verify(self):
        proc = self.render([doc_writer_review(), helper_review()], "--summary")
        report = self.tmp / "report.md"
        report.write_text(proc.stdout, encoding="utf-8")
        ok = run("report.py", "verify", report)
        self.assertEqual(ok.returncode, OK, ok.stdout + ok.stderr)
        altered = self.tmp / "altered.md"
        altered.write_text(proc.stdout.replace("Score: 0.56", "Score: 0.66"), encoding="utf-8")
        bad = run("report.py", "verify", altered)
        self.assertEqual(bad.returncode, MISMATCH)
        self.assertIn("0.66", bad.stdout + bad.stderr)
        self.assertIn(".claude/agents/helper.md", bad.stdout + bad.stderr)

    def test_verify_unparsable(self):
        junk = self.tmp / "junk.md"
        junk.write_text("# Not a report\n", encoding="utf-8")
        self.assertEqual(run("report.py", "verify", junk).returncode, REFUSED)


class TestFormula(unittest.TestCase):
    def setUp(self):
        sys.path.insert(0, str(SCRIPTS))
        import report

        self.r = report

    def test_worked_examples(self):
        """The review questions' two worked examples: 0.83 gives 4 stars and 0.85 gives 4.5."""
        self.assertEqual(self.r.stars(Fraction(83, 100)), Fraction(4))
        self.assertEqual(self.r.stars(Fraction(85, 100)), Fraction(9, 2))

    def test_frequency_bands(self):
        point = self.r.frequency_point
        self.assertEqual(point(5, 5), 4)
        self.assertEqual(point(4, 5), 3)  # 80%
        self.assertEqual(point(61, 100), 3)
        self.assertEqual(point(3, 5), 2)  # 60%, inside 'about half the time'
        self.assertEqual(point(2, 5), 2)  # 40%, inside 'about half the time'
        self.assertEqual(point(39, 100), 1)
        self.assertEqual(point(0, 5), 0)

    def test_score_is_mean(self):
        self.assertEqual(self.r.mean([Fraction(1), Fraction(0), Fraction(3, 4)]), Fraction(7, 12))


if __name__ == "__main__":
    unittest.main()
