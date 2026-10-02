"""Tests for report.py: schema, validate, render and verify (SI-4, SI-10, SI-11), to the review questions
as rewritten on 2 October 2026: ten checks and seven ratings, a total of x out of y and stars from it."""

import json
import re
import sys
import unittest
from fractions import Fraction

from support import REFERENCES, SCRIPTS, ScratchCase, make_fixtures, run

# Exit codes report.py promises (specification §3e).
OK, MISMATCH, REFUSED, NO_SCORE = 0, 1, 2, 3

NO_PREDICTION = "A score does not predict how the agent will behave. The quoted lines are what to act on."
CLEAN = "Nothing was found."
LINTERS = "For secrets, hook scripts and server settings, use a configuration or security linter."
EMPTY = "This file is empty; no stars and no total."
NOTHING_APPLIES = "No question applies to this file; no stars and no total."
FENCE_OPEN, FENCE_CLOSE = "```text", "```"
VERDICT_WORDS = re.compile(
    r"\b(pass|passes|passed|fail|fails|failed|approve|approved|block|blocked|severity|critical|major|minor)\b",
    re.IGNORECASE,
)

SRC_PERMISSIONS = "Anthropic, 'Permission rules are enforced by Claude Code, not by the model'"
SRC_RECORD = "the record kept while this skill was built"
SRC_SUBAGENTS = "Anthropic, 'Claude uses each subagent's description to decide when to delegate tasks'"
SRC_MEMORY = "Anthropic, 'If the instruction is something that must run at a specific point … write it as a hook'"
SRC_PERSONA = "Cao, Sun and Yue, https://arxiv.org/abs/2602.12285"

# The ten checks and seven ratings in review-questions.md's order.
CHECKS = [
    "Pointers carry their triggers",
    "Bound parts agree with the prose",
    "Leaves the harness's work to the harness",
    "No time-sensitive statements",
    "Consistent with itself",
    "Nothing said twice",
    "Leaves known things unsaid",
    "Enforceable rules enforced",
    "No procedure for one kind of task",
    "No facts the project already holds",
]
READING = CHECKS[4:]
RATINGS = [
    "Terms defined where they are used",
    "Rules held in the file",
    "Directions for when nobody answers",
    "Answers defined, edge cases included",
    "Its own criteria met",
    "The description says when to choose it",
    "An identity that does the work",
]


def reading_all_one(skip=()):
    return [{"question": q, "score": 1} for q in READING if q not in skip]


def place(line, quote, meets, note=None, source=SRC_RECORD):
    p = {"line": line, "quote": quote, "meets": meets}
    if not meets:
        p.update(note=note or "It does not meet the question.", source=source)
    return p


def helper_review():
    """A review of .claude/agents/helper.md with findings: 24 out of 46, so 2.5 stars.

    Checks: nine at 1 and 'Bound parts agree with the prose' at 0 from PJ-003, so 9 out of 10.
    Ratings: 0, 6, 0, 3, 2 and 4 on six ratings given, so 15 out of 36.
    """
    return {
        "path": ".claude/agents/helper.md",
        "questions": reading_all_one()
        + [
            {
                "question": "Terms defined where they are used",
                "scale": "frequency",
                "places": [place(10, "Rate each finding high, medium or low.", False, "The scale is named and never defined.")],
            },
            {
                "question": "Rules held in the file",
                "scale": "frequency",
                "places": [
                    place(9, "Never edit files; report what you find in a list.", True),
                    place(10, "Rate each finding high, medium or low.", True),
                    place(11, "If the scope is unclear, ask.", True),
                ],
            },
            {
                "question": "Directions for when nobody answers",
                "scale": "frequency",
                "places": [place(11, "If the scope is unclear, ask.", False, "Nothing covers a run with no one to ask.")],
            },
            {
                "question": "Answers defined, edge cases included",
                "scale": "frequency",
                "places": [
                    place(10, "high, medium or low", False, "Nothing says what to return when nothing is found."),
                    place(7, "report what you find", True),
                ],
            },
            {"question": "Its own criteria met", "not_rated": "The file sets no criterion for the agent's work."},
            {
                "question": "The description says when to choose it",
                "scale": "quality",
                "point": 2,
                "findings": [
                    {
                        "line": 3,
                        "quote": "Reviews pull requests for style problems.",
                        "note": "It names a subject and no task.",
                        "source": SRC_SUBAGENTS,
                    }
                ],
            },
            {
                "question": "An identity that does the work",
                "scale": "quality",
                "point": 4,
                "findings": [
                    {
                        "line": 7,
                        "quote": "You review code for style and report what you find.",
                        "note": "It states the work and not where it stops.",
                        "source": SRC_PERSONA,
                    }
                ],
            },
        ],
    }


def doc_writer_review():
    """A clean review of .claude/agents/doc-writer.md: 28 out of 28, so 5 stars."""
    return {
        "path": ".claude/agents/doc-writer.md",
        "questions": reading_all_one()
        + [
            {"question": "Terms defined where they are used", "not_rated": "The rules name no scale or term."},
            {
                "question": "Rules held in the file",
                "scale": "frequency",
                "places": [
                    place(7, "Read `CHANGELOG.md` when the user asks for release notes", True),
                    place(8, "Write each note as one sentence in the past tense.", True),
                    place(9, "When the changelog is empty", True),
                ],
            },
            {"question": "Directions for when nobody answers", "not_rated": "No rule asks or waits."},
            {
                "question": "Answers defined, edge cases included",
                "scale": "frequency",
                "places": [place(9, "say there is nothing to report", True)],
            },
            {"question": "Its own criteria met", "not_rated": "The file sets no criterion for the agent's work."},
            {"question": "The description says when to choose it", "scale": "quality", "point": 6},
            {"question": "An identity that does the work", "not_rated": "The file opens with no identity."},
        ],
        "fit": {"statement": "No neighbouring persona files were supplied."},
    }


def claude_md_review():
    """A review of the standing CLAUDE.md, which has no bound parts: 14 out of 21, so 3.5 stars.

    Checks: 'Bound parts agree with the prose' not scored (no row applies); 'Pointers carry their
    triggers' at 0 from PJ-001 and PJ-002; the other eight at 1, so 8 out of 9.
    Ratings: 0 and 6 on two ratings given, so 6 out of 12.
    """
    return {
        "path": "CLAUDE.md",
        "questions": reading_all_one()
        + [
            {
                "question": "Terms defined where they are used",
                "scale": "frequency",
                "places": [place(6, "small, medium or large", False, "The sizes are named and never defined.")],
            },
            {
                "question": "Rules held in the file",
                "scale": "frequency",
                "places": [
                    place(3, "Run the tests with `make test` before every commit.", True),
                    place(6, "Rate each change as small, medium or large", True),
                ],
            },
            {"question": "Directions for when nobody answers", "not_rated": "No rule asks or waits."},
            {"question": "Answers defined, edge cases included", "not_rated": "The file names no closed set of answers."},
            {"question": "Its own criteria met", "not_rated": "The file sets no criterion."},
            {"question": "The description says when to choose it", "not_rated": "A standing persona is not chosen."},
            {"question": "An identity that does the work", "not_rated": "The file opens with no identity."},
        ],
    }


def sample_review():
    """The record behind sample-review.md's example: 33 out of 52, so 3 stars.

    The questions are given in the order the sample lists its lines; the script checks are left to
    check.py's rows, which score 'Bound parts agree with the prose' 0 from PJ-003.
    """
    return {
        "path": ".claude/agents/code-reviewer.md",
        "questions": [
            {
                "question": "Terms defined where they are used",
                "scale": "frequency",
                "places": [
                    place(14, "Rate each issue high, medium or low.", False, "The scale is named and never defined."),
                    place(18, "Return Approve, Comment or Request changes.", True),
                ],
            },
            {
                "question": "Directions for when nobody answers",
                "scale": "frequency",
                "places": [place(22, "If the scope is unclear, ask.", False, "Nothing covers a run with no one to ask.")],
            },
            {"question": "Bound parts agree with the prose", "score": 0},
            {
                "question": "Enforceable rules enforced",
                "score": 0,
                "findings": [
                    {
                        "line": 11,
                        "quote": "Never push to main.",
                        "note": "A setting or hook could enforce this, and none does.",
                        "source": SRC_MEMORY,
                    }
                ],
            },
            {
                "question": "Answers defined, edge cases included",
                "scale": "frequency",
                "places": [
                    place(
                        18,
                        "Return Approve, Comment or Request changes.",
                        False,
                        "Nothing says what to return for an empty diff.",
                    ),
                    place(15, "Give each issue its file and line number.", True),
                    place(17, "List each issue once, in file order.", True),
                    place(19, "Return Comment when the diff only renames.", True),
                    place(20, "Say which tests cover each changed function.", True),
                ],
            },
            {
                "question": "The description says when to choose it",
                "scale": "quality",
                "point": 3,
                "findings": [
                    {
                        "line": 2,
                        "quote": "description: Reviews code changes.",
                        "note": "It names the task in its own terms.",
                        "source": SRC_SUBAGENTS,
                    }
                ],
            },
            {
                "question": "An identity that does the work",
                "scale": "quality",
                "point": 3,
                "findings": [
                    {
                        "line": 7,
                        "quote": "You are a meticulous senior reviewer who checks diffs.",
                        "note": "It states the work, with praise.",
                        "source": SRC_PERSONA,
                    }
                ],
            },
            {
                "question": "Rules held in the file",
                "scale": "frequency",
                "places": [
                    place(9, "Never change files.", True),
                    place(11, "Never push to main.", True),
                    place(14, "Rate each issue high, medium or low.", True),
                ],
            },
            {
                "question": "Its own criteria met",
                "scale": "frequency",
                "places": [place(15, "Give each issue its file and line number.", True)],
            },
        ]
        + reading_all_one(skip=("Enforceable rules enforced",)),
    }


def unquoted(text):
    """The text with every quoted line removed, so a check for verdict words reads only the report's own words."""
    return re.sub(r"'[^'\n]*'", "''", text)


def block(text):
    """The lines inside the first fenced text block."""
    lines = text.splitlines()
    start = lines.index(FENCE_OPEN)
    end = lines.index(FENCE_CLOSE, start + 1)
    return lines[start + 1: end]


class ReportCase(ScratchCase):
    project_name = "si11"

    def setUp(self):
        super().setUp()
        self.proj = self.project(self.project_name)

    def write(self, files, name="record.json"):
        path = self.tmp / name
        path.write_text(json.dumps({"root": self.proj.as_posix(), "files": files}), encoding="utf-8")
        return path

    def render(self, files, *extra):
        return run("report.py", "render", *extra, self.write(files))


class TestQuestions(unittest.TestCase):
    """The seventeen questions report.py holds as one constant, against review-questions.md."""

    def setUp(self):
        sys.path.insert(0, str(SCRIPTS))
        import report

        self.r = report

    def from_file(self):
        text = (REFERENCES / "review-questions.md").read_text(encoding="utf-8")
        out = []
        checks = re.search(r"^## Checks\s*$(.*?)^## ", text, re.MULTILINE | re.DOTALL).group(1)
        for m in re.finditer(r"^\*\*(.+?)\*\* \(\*(script|reading)\*\)", checks, re.MULTILINE):
            out.append((m.group(1).rstrip("."), m.group(2)))
        ratings = re.search(r"^## Ratings\s*$(.*?)^## ", text, re.MULTILINE | re.DOTALL).group(1)
        for para in re.split(r"\n\s*\n", ratings):
            m = re.match(r"\*\*(.+?)\*\*", para.strip())
            if m:
                out.append((m.group(1).rstrip("."), "quality" if "*Exceptional:*" in para else "frequency"))
        return out

    def test_constant_matches_the_file(self):
        self.assertEqual(len(self.from_file()), 17)
        self.assertEqual([(q[0], q[1]) for q in self.r.QUESTIONS], self.from_file())

    def test_control(self):
        """The comparison can fail: a constant with two questions swapped does not match."""
        swapped = list(self.from_file())
        swapped[0], swapped[1] = swapped[1], swapped[0]
        self.assertNotEqual([(q[0], q[1]) for q in self.r.QUESTIONS], swapped)


class TestFormula(unittest.TestCase):
    def setUp(self):
        sys.path.insert(0, str(SCRIPTS))
        import report

        self.r = report

    def test_worked_examples(self):
        """The review questions' two worked examples: 25 out of 40 gives 3 stars; 27 out of 40 gives 3.5."""
        self.assertEqual(self.r.stars(25, 40), Fraction(3))
        self.assertEqual(self.r.stars(27, 40), Fraction(7, 2))

    def test_half_rounds_up(self):
        self.assertEqual(self.r.stars(1, 4), Fraction(3, 2))  # 1.25 is a half between 1 and 1.5
        self.assertEqual(self.r.stars(33, 52), Fraction(3))

    def test_star_display_t_s(self):
        """T-S: the ratified form, code point for code point."""
        want = {
            Fraction(0): "☆☆☆☆☆ (0)",
            Fraction(1, 2): "½☆☆☆☆ (0.5)",
            Fraction(3): "★★★☆☆ (3)",
            Fraction(7, 2): "★★★½☆ (3.5)",
            Fraction(5): "★★★★★ (5)",
        }
        for value, line in want.items():
            got = self.r.star_line(value)
            self.assertEqual([hex(ord(c)) for c in got], [hex(ord(c)) for c in line], value)

    def test_frequency_bands(self):
        point = self.r.frequency_point
        self.assertEqual(point(5, 5), 6)  # all
        self.assertEqual(point(9, 10), 5)  # over 80%, below 100%
        self.assertEqual(point(81, 100), 5)
        self.assertEqual(point(4, 5), 4)  # 80%, inside 'usually'
        self.assertEqual(point(61, 100), 4)
        self.assertEqual(point(3, 5), 3)  # 60%, inside 'about half the time'
        self.assertEqual(point(2, 5), 3)  # 40%, inside 'about half the time'
        self.assertEqual(point(39, 100), 2)
        self.assertEqual(point(1, 5), 2)  # 20%, inside 'seldom'
        self.assertEqual(point(19, 100), 1)
        self.assertEqual(point(0, 5), 0)

    def test_words(self):
        self.assertEqual(self.r.FREQUENCY_WORDS[3], "about half the time")
        self.assertEqual(self.r.QUALITY_WORDS[6], "exceptional")
        self.assertEqual(self.r.QUALITY_WORDS[0], "very poor")


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

    def answer(self, review, title):
        return [q for q in review["questions"] if q["question"] == title][0]

    def test_line_beyond_the_file(self):
        review = helper_review()
        self.answer(review, "The description says when to choose it")["findings"][0]["line"] = 88
        out = self.faults(review)
        self.assertIn(
            ".claude/agents/helper.md, 'The description says when to choose it', finding 1, line: cites line 88, "
            "but the file has 11 lines; quote a line that exists",
            out,
        )

    def test_quote_not_on_its_line(self):
        """Likeness fixture: a paraphrase of the line, cited at the right number, is refused."""
        review = helper_review()
        self.answer(review, "The description says when to choose it")["findings"][0]["quote"] = "Reviews code for style"
        self.assertIn("does not appear on line 3", self.faults(review))

    def test_unknown_question(self):
        review = helper_review()
        self.answer(review, "Consistent with itself")["question"] = "Consistent"
        out = self.faults(review)
        self.assertIn("'Consistent'", out)
        self.assertIn("review-questions.md", out)

    def test_script_check_against_its_rows(self):
        """A script check scored 1 where its row scored 0 is refused, naming the row."""
        review = helper_review()
        review["questions"].append({"question": "Bound parts agree with the prose", "score": 1})
        self.assertIn("PJ-003", self.faults(review))

    def test_script_check_not_scored_against_its_rows(self):
        review = helper_review()
        review["questions"].append({"question": "Pointers carry their triggers", "not_scored": "for the test"})
        out = self.faults(review)
        self.assertIn("'Pointers carry their triggers'", out)
        self.assertIn("rows", out)

    def test_script_check_scored_where_no_row_applies(self):
        """CLAUDE.md has no tools field, so no row reads 'Bound parts agree with the prose'."""
        review = claude_md_review()
        review["questions"].append({"question": "Bound parts agree with the prose", "score": 1})
        out = self.faults(review)
        self.assertIn("not scored", out)

    def test_reading_check_at_zero_without_a_line(self):
        review = helper_review()
        self.answer(review, "Consistent with itself")["score"] = 0
        out = self.faults(review)
        self.assertIn("'Consistent with itself'", out)
        self.assertIn("quot", out)

    def test_point_out_of_range(self):
        review = helper_review()
        self.answer(review, "The description says when to choose it")["point"] = 7
        self.assertIn("0 to 6", self.faults(review))

    def test_quality_below_top_without_lines(self):
        review = helper_review()
        del self.answer(review, "An identity that does the work")["findings"]
        self.assertIn("below its top point", self.faults(review))

    def test_wrong_scale(self):
        review = helper_review()
        q = self.answer(review, "Terms defined where they are used")
        q["scale"] = "quality"
        q["point"] = 1
        self.assertIn("frequency", self.faults(review))

    def test_finding_without_quote(self):
        review = helper_review()
        del self.answer(review, "The description says when to choose it")["findings"][0]["quote"]
        self.assertIn("quote", self.faults(review))

    def test_finding_without_source(self):
        review = helper_review()
        del self.answer(review, "The description says when to choose it")["findings"][0]["source"]
        self.assertIn("source", self.faults(review))

    def test_finding_without_note(self):
        review = helper_review()
        del self.answer(review, "The description says when to choose it")["findings"][0]["note"]
        self.assertIn("note", self.faults(review))

    def test_place_without_note(self):
        review = helper_review()
        del self.answer(review, "Directions for when nobody answers")["places"][0]["note"]
        self.assertIn("note", self.faults(review))

    def test_check_score_not_one_or_zero(self):
        review = helper_review()
        self.answer(review, "Nothing said twice")["score"] = 0.5
        self.assertIn("1 or 0", self.faults(review))

    def test_missing_question(self):
        review = helper_review()
        review["questions"].remove(self.answer(review, "Consistent with itself"))
        self.assertIn("'Consistent with itself'", self.faults(review))

    def test_standing_file_rated_on_description(self):
        review = claude_md_review()
        q = self.answer(review, "The description says when to choose it")
        del q["not_rated"]
        q.update(scale="quality", point=6)
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
        lines = block(proc.stdout)
        # The stars and the total lead; the header follows.
        self.assertEqual(lines[0], "★★½☆☆ (2.5)")
        self.assertEqual(lines[1], "Total: 24 out of 46")
        self.assertEqual(lines[3], "Review: .claude/agents/helper.md (delegated persona)")
        out = "\n".join(lines)
        # Order of the parts.
        order = [
            out.index("Lines that lowered the score"),
            out.index("\nChecks\n"),
            out.index("\nRatings\n"),
            out.index("Formula: "),
            out.index(NO_PREDICTION),
            out.index(LINTERS),
        ]
        self.assertEqual(order, sorted(order))
        # Every finding: a numbered line quoted, then its question and what lowers it.
        items = re.findall(r"^(\d+)\. Line (\d+): '([^']*)'.*\n   (.+)$", out, re.MULTILINE)
        self.assertEqual([i[0] for i in items], ["1", "2", "3", "4", "5", "6"])
        self.assertEqual(
            [(i[1], i[3].split(". ")[0]) for i in items],
            [
                ("4", "Bound parts agree with the prose"),
                ("10", "Terms defined where they are used"),
                ("11", "Directions for when nobody answers"),
                ("10", "Answers defined, edge cases included"),
                ("3", "The description says when to choose it"),
                ("7", "An identity that does the work"),
            ],
        )
        self.assertIn("1. Line 4: 'tools: Read, Grep, Edit', against line 9: 'Never edit files; report what you find in a list.'", out)
        # Every check as 'yes 1' or 'no 0'; every rating as its point out of 6 with its word.
        self.assertRegex(out, r"(?m)^Pointers carry their triggers +yes 1$")
        self.assertRegex(out, r"(?m)^Bound parts agree with the prose +no  0$")
        self.assertRegex(out, r"(?m)^Rules held in the file +6 of 6   always$")
        self.assertRegex(out, r"(?m)^Answers defined, edge cases included +3 of 6   about half the time$")
        self.assertRegex(out, r"(?m)^The description says when to choose it +2 of 6   fair$")
        self.assertRegex(out, r"(?m)^Its own criteria met +not rated   The file sets no criterion")
        self.assertIn("Formula: each check counts 1 or 0 and each rating its points, 24 out of 46.", out)
        self.assertIn("Stars: 24 ÷ 46 × 5 = 2.61, to the nearest half star.", out)
        self.assertNotIn(CLEAN, out)
        self.assertIsNone(VERDICT_WORDS.search(unquoted(out)), VERDICT_WORDS.search(unquoted(out)))

    def test_columns_aligned(self):
        """The check and rating columns start at one place, as in sample-review.md."""
        lines = block(self.render([helper_review()]).stdout)
        start = lines.index("Checks")
        rows = [l for l in lines[start:] if any(l.startswith(t + " ") for t in CHECKS + RATINGS)]
        self.assertEqual(len(rows), 17)
        cols = {len(l) - len(l[len(t):].lstrip()) for l in rows for t in CHECKS + RATINGS if l.startswith(t + " ")}
        self.assertEqual(len(cols), 1, cols)

    def test_clean_report(self):
        proc = self.render([doc_writer_review()])
        self.assertEqual(proc.returncode, OK, proc.stderr)
        lines = block(proc.stdout)
        self.assertEqual(lines[:2], ["★★★★★ (5)", "Total: 28 out of 28"])
        self.assertEqual(lines[lines.index("Lines that lowered the score") + 1], CLEAN)
        self.assertIn(NO_PREDICTION, lines)
        self.assertIn("Fit with neighbouring files, apart from the score", lines)
        self.assertIn("No neighbouring persona files were supplied.", lines)

    def test_check_row_lines_are_listed(self):
        """A row at 0 lists its line though the record gave the check no finding; two rows on one line merge."""
        proc = self.render([claude_md_review()])
        self.assertEqual(proc.returncode, OK, proc.stdout + proc.stderr)
        out = "\n".join(block(proc.stdout))
        self.assertIn("1. Line 4: 'See also `docs/style.md`.'\n   Pointers carry their triggers. ", out)
        self.assertEqual(out.count("Line 4:"), 1)
        self.assertRegex(out, r"(?m)^Pointers carry their triggers +no  0$")
        self.assertRegex(out, r"(?m)^Bound parts agree with the prose +not scored   ")

    def test_no_linters_line_without_bound_parts(self):
        proc = self.render([claude_md_review()])
        self.assertEqual(proc.returncode, OK, proc.stderr)
        lines = block(proc.stdout)
        self.assertNotIn(LINTERS, lines)
        self.assertNotIn("Fit with neighbouring files, apart from the score", lines)
        self.assertEqual(lines[:2], ["★★★½☆ (3.5)", "Total: 14 out of 21"])

    def test_render_refuses_unsound_record(self):
        review = helper_review()
        review["questions"].append({"question": "Bound parts agree with the prose", "score": 1})
        proc = self.render([review])
        self.assertEqual(proc.returncode, REFUSED)
        self.assertEqual(proc.stdout, "")

    def test_empty_file(self):
        proj = self.project("empty-file")
        path = self.tmp / "e.json"
        path.write_text(json.dumps({"root": proj.as_posix(), "files": [{"path": "CLAUDE.md", "questions": []}]}))
        proc = run("report.py", "render", path)
        self.assertEqual(proc.returncode, NO_SCORE, proc.stderr)
        lines = block(proc.stdout)
        self.assertEqual(lines[0], EMPTY)
        self.assertIn("Review: CLAUDE.md (standing persona)", lines)

    def test_session_text(self):
        text = (make_fixtures.FILES / "helper-agent.fixture").read_text()
        review = helper_review()
        review["path"] = "<session text>"
        review["text"] = text
        proc = self.render([review])
        self.assertEqual(proc.returncode, OK, proc.stdout + proc.stderr)
        lines = block(proc.stdout)
        self.assertEqual(lines[3], "Review: <session text> (delegated persona)")
        # Session text names no harness, so no row reads 'Leaves the harness's work to the harness'.
        self.assertRegex("\n".join(lines), r"(?m)^Leaves the harness's work to the harness +not scored   ")

    def test_render_writes_no_file(self):
        before = make_fixtures.manifest(self.proj)
        record = self.write([helper_review()])
        run("report.py", "render", record, cwd=self.proj)
        self.assertEqual(make_fixtures.manifest(self.proj), before)


class TestNothingApplies(unittest.TestCase):
    """The message for a file with text on which no question applies. With the seed table a row always
    applies, so this is reached through the rendering function itself."""

    def test_nothing_applies(self):
        sys.path.insert(0, str(SCRIPTS))
        import report

        p = report.Prepared("notes/x.md")
        p.header = {"kind": "standing", "harness": "not named by its path", "bound_parts": []}
        p.answers = [
            {"title": t, "type": k, "findings": [], "not_rated": "for the test"} for t, k, *_ in report.QUESTIONS
        ]
        text, score = report.render_one(p)
        self.assertIsNone(score)
        self.assertEqual(text.splitlines()[0], NOTHING_APPLIES)


class TestSampleT4(ReportCase):
    """T-4: the record behind sample-review.md's example renders line for line."""

    project_name = "sample"

    def test_sample_renders_line_for_line(self):
        proc = self.render([sample_review()])
        self.assertEqual(proc.returncode, OK, proc.stdout + proc.stderr)
        want = block((REFERENCES / "sample-review.md").read_text(encoding="utf-8"))
        got = block(proc.stdout)
        self.assertEqual(got, want)
        self.assertEqual(proc.stdout.strip().splitlines()[0], FENCE_OPEN)
        self.assertEqual(proc.stdout.strip().splitlines()[-1], FENCE_CLOSE)


class TestSummaryT11(ReportCase):
    def test_summary_order(self):
        proc = self.render([doc_writer_review(), claude_md_review(), helper_review()], "--summary")
        self.assertEqual(proc.returncode, OK, proc.stderr)
        first = block(proc.stdout)
        self.assertTrue(first[0].startswith("Summary"), first[0])
        paths = [l.split()[0] for l in first[1:] if l.strip()]
        self.assertEqual(paths, [".claude/agents/helper.md", "CLAUDE.md", ".claude/agents/doc-writer.md"])
        self.assertRegex(first[1], r"^\.claude/agents/helper\.md +delegated +★★½☆☆ \(2\.5\) +24 out of 46$")
        heads = re.findall(r"^Review: (\S+) \(", proc.stdout, re.MULTILINE)
        self.assertEqual(heads, paths)

    def test_summary_lists_an_unscored_file_last(self):
        empty = self.project("empty-file")
        proc = run(
            "report.py", "render", "--summary",
            self.write([{"path": (empty / "CLAUDE.md").as_posix(), "questions": []}, doc_writer_review()]),
        )
        self.assertEqual(proc.returncode, OK, proc.stdout + proc.stderr)
        first = [l for l in block(proc.stdout)[1:] if l.strip()]
        self.assertTrue(first[0].startswith(".claude/agents/doc-writer.md"), first)
        self.assertIn("no stars and no total", first[1])


class TestVerifyT10(ReportCase):
    def rendered(self):
        proc = self.render([doc_writer_review(), helper_review(), claude_md_review()], "--summary")
        self.assertEqual(proc.returncode, OK, proc.stderr)
        return proc.stdout

    def verify(self, text, name):
        path = self.tmp / name
        path.write_text(text, encoding="utf-8")
        return run("report.py", "verify", path)

    def test_verify(self):
        ok = self.verify(self.rendered(), "report.md")
        self.assertEqual(ok.returncode, OK, ok.stdout + ok.stderr)

    def test_total_altered(self):
        bad = self.verify(self.rendered().replace("Total: 24 out of 46", "Total: 25 out of 46"), "altered.md")
        self.assertEqual(bad.returncode, MISMATCH, bad.stdout + bad.stderr)
        out = bad.stdout + bad.stderr
        self.assertIn(".claude/agents/helper.md", out)
        self.assertIn("Total: 25 out of 46", out)

    def test_check_flipped(self):
        """A check flipped from 'yes 1' to 'no 0' changes CLAUDE.md's total and its stars."""
        text = self.rendered()
        start = text.index("Review: CLAUDE.md")
        line = re.search(r"(?m)^Leaves the harness's work to the harness +yes 1$", text[start:])
        flipped = text[: start + line.start()] + line.group(0)[:-5] + "no  0" + text[start + line.end():]
        bad = self.verify(flipped, "flipped.md")
        self.assertEqual(bad.returncode, MISMATCH, bad.stdout + bad.stderr)
        out = bad.stdout + bad.stderr
        self.assertIn("CLAUDE.md", out)
        self.assertIn("13 out of 21", out)
        self.assertIn("★★★☆☆ (3)", out)

    def test_verify_unparsable(self):
        junk = self.tmp / "junk.md"
        junk.write_text("# Not a report\n", encoding="utf-8")
        self.assertEqual(run("report.py", "verify", junk).returncode, REFUSED)

    def test_verify_on_the_sample(self):
        """The sample's own example, as sample-review.md prints it, verifies."""
        ok = run("report.py", "verify", REFERENCES / "sample-review.md")
        self.assertEqual(ok.returncode, OK, ok.stdout + ok.stderr)


if __name__ == "__main__":
    unittest.main()
