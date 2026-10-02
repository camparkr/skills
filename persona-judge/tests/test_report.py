"""Tests for report.py: schema, validate, render and verify (SI-4, SI-10, SI-11, SI-13), to the review questions
landed for round 3: 33 questions in two sections, persona and instruction writing, each with a subtotal; 'A
dedicated persona' answered first; every finding naming its file, line, question and sources."""

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
INSTRUCTIONS = "project instructions: context for the agent, not a dedicated persona"
WAITING = "sample-review.md awaits its round-3 revision"
VERDICT_WORDS = re.compile(
    r"\b(pass|passes|passed|fail|fails|failed|approve|approved|block|blocked|severity|critical|major|minor)\b",
    re.IGNORECASE,
)

# The 33 questions in review-questions.md's order, by section.
PERSONA_CHECKS = [
    "A dedicated persona",
    "Pointers carry their triggers",
    "Bound parts agree with the prose",
    "Leaves the harness's work to the harness",
    "Enforceable rules enforced",
    "No procedure for one kind of task",
    "No facts the project already holds",
    "No pressure from consequences",
    "One job",
    "Declares its tools",
    "States its output",
    "Boundaries in three tiers",
]
PERSONA_RATINGS = [
    "Rules held in the persona",
    "Directions for when nobody answers",
    "Rules used in every act come first",
    "Tools explained",
    "Commands given exactly",
    "The description says when to choose it",
    "An identity that does the work",
]
IW_CHECKS = [
    "No time-sensitive statements",
    "Consistent with itself",
    "Nothing said twice",
    "Leaves known things unsaid",
    "Plain emphasis",
    "No placeholders",
    "Shows an example",
]
IW_RATINGS = [
    "Terms defined where they are used",
    "Answers defined, edge cases included",
    "Its own criteria met",
    "Instructions an observer can check",
    "What to do, not what to avoid",
    "Reasons given",
    "Each instruction stands alone",
]
ALL = PERSONA_CHECKS + PERSONA_RATINGS + IW_CHECKS + IW_RATINGS
CHECKS = PERSONA_CHECKS + IW_CHECKS
SCRIPT = {
    "Pointers carry their triggers",
    "Bound parts agree with the prose",
    "Leaves the harness's work to the harness",
    "Declares its tools",
    "No time-sensitive statements",
    "Plain emphasis",
    "No placeholders",
}
STANDING_NOT_SCORED = ("One job", "States its output")


def finding(line, quote, note, file=None):
    f = {"line": line, "quote": quote, "note": note}
    if file:
        f["file"] = file
    return f


def place(line, quote, meets, note=None, file=None):
    p = {"line": line, "quote": quote, "meets": meets}
    if not meets:
        p["note"] = note or "It does not meet the question."
    if file:
        p["file"] = file
    return p


def freq(*places):
    return {"scale": "frequency", "places": list(places)}


def quality(point, *findings):
    out = {"scale": "quality", "point": point}
    if findings:
        out["findings"] = list(findings)
    return out


def review(path, answers, standing=False, **extra):
    """A record entry answering every question: a reading check 1, a rating not rated, a script check left to
    check.py's rows; then the answers given in place of those. A finding or place with no file names the
    main file."""
    questions = []
    for title in ALL:
        if title in answers:
            if answers[title] is None:
                continue
            answer = dict(answers[title], question=title)
        elif title in SCRIPT:
            continue
        elif standing and title in STANDING_NOT_SCORED:
            answer = {"question": title, "not_scored": "A standing persona is not scored on this question."}
        elif standing and title == "The description says when to choose it":
            answer = {"question": title, "not_rated": "A standing persona is not chosen."}
        elif title in CHECKS:
            answer = {"question": title, "score": 1}
        else:
            answer = {"question": title, "not_rated": "The file has no place this question applies to."}
        for key in ("findings", "places"):
            if key in answer:
                answer[key] = [dict(item) for item in answer[key]]
                for item in answer[key]:
                    item.setdefault("file", path)
        questions.append(answer)
    return dict({"path": path, "questions": questions}, **extra)


def helper_answers():
    return {
        "Rules held in the persona": freq(
            place(9, "Never edit files; report what you find in a list.", True),
            place(10, "Rate each finding high, medium or low.", True),
            place(11, "If the scope is unclear, ask.", True),
        ),
        "Directions for when nobody answers": freq(
            place(11, "If the scope is unclear, ask.", False, "Nothing covers a run with no one to ask.")
        ),
        "Rules used in every act come first": freq(
            place(9, "Never edit files", True), place(10, "Rate each finding high, medium or low.", True)
        ),
        "Tools explained": freq(
            place(4, "tools: Read, Grep, Edit", False, "Three tools are named with no word on when to use them.")
        ),
        "Commands given exactly": {"not_rated": "The file tells the agent to run no command."},
        "The description says when to choose it": quality(
            2, finding(3, "Reviews pull requests for style problems.", "It names a subject and no task.")
        ),
        "An identity that does the work": quality(
            4, finding(7, "You review code for style and report what you find.", "It states the work and not where it stops.")
        ),
        "Shows an example": {"not_scored": "The file asks for no particular form."},
        "Terms defined where they are used": freq(
            place(10, "Rate each finding high, medium or low.", False, "The scale is named and never defined.")
        ),
        "Answers defined, edge cases included": freq(
            place(10, "high, medium or low", False, "Nothing says what to return when nothing is found."),
            place(7, "report what you find", True),
        ),
        "Its own criteria met": {"not_rated": "The file sets no criterion for the agent's work."},
        "Instructions an observer can check": freq(
            place(9, "Never edit files", True),
            place(10, "Rate each finding high, medium or low.", True),
            place(11, "If the scope is unclear, ask.", False, "Whether the scope is unclear is not something an observer can see."),
        ),
        "What to do, not what to avoid": freq(place(9, "report what you find in a list", True)),
        "Reasons given": freq(place(9, "Never edit files", False, "The rule gives no reason.")),
        "Each instruction stands alone": freq(
            place(9, "Never edit files", True),
            place(10, "Rate each finding high, medium or low.", True),
            place(11, "If the scope is unclear, ask.", True),
        ),
    }


def helper_review(path=".claude/agents/helper.md", **extra):
    """.claude/agents/helper.md with findings: persona 29 out of 48, instruction writing 25 out of 42, total 54
    out of 90, so 3 stars.

    Persona checks: eleven at 1 and 'Bound parts agree with the prose' at 0 from PJ-003, so 11 out of 12.
    Persona ratings: 6, 0, 6, 0, 2 and 4, so 18 out of 36. Instruction-writing checks: six at 1, 'Shows an
    example' not scored, so 6 out of 6. Instruction-writing ratings: 0, 3, 4, 6, 0 and 6, so 19 out of 36.
    """
    return review(path, helper_answers(), **extra)


def doc_writer_review():
    """A clean review of .claude/agents/doc-writer.md: 66 out of 66, so 5 stars."""
    return review(
        ".claude/agents/doc-writer.md",
        {
            "Rules held in the persona": freq(
                place(7, "Read `CHANGELOG.md` when the user asks for release notes", True),
                place(8, "Write each note as one sentence in the past tense.", True),
                place(9, "When the changelog is empty", True),
            ),
            "Directions for when nobody answers": {"not_rated": "No rule asks or waits."},
            "Rules used in every act come first": freq(place(8, "Write each note as one sentence", True)),
            "Tools explained": freq(place(7, "Read `CHANGELOG.md` when the user asks for release notes", True)),
            "The description says when to choose it": quality(6),
            "An identity that does the work": {"not_rated": "The file opens with no identity."},
            "Shows an example": {"not_scored": "The file asks for no particular form."},
            "Answers defined, edge cases included": freq(place(9, "say there is nothing to report", True)),
            "Instructions an observer can check": freq(place(8, "Write each note as one sentence", True)),
            "What to do, not what to avoid": freq(place(8, "Write each note as one sentence", True)),
            "Each instruction stands alone": freq(
                place(7, "Read `CHANGELOG.md`", True), place(8, "Write each note", True), place(9, "When the changelog is empty", True)
            ),
        },
        fit={"statement": "No neighbouring persona files were supplied."},
    )


def triage_review():
    """.github/agents/triage.agent.md, with no tools field and no bound parts: persona 24 out of 29,
    instruction writing 24 out of 24, total 48 out of 53, so 4.5 stars."""
    return review(
        ".github/agents/triage.agent.md",
        {
            "States its output": {
                "score": 0,
                "findings": [finding(6, "Label each issue with one area.", "Nothing says what the agent returns or in what form.")],
            },
            "Boundaries in three tiers": {
                "score": 0,
                "findings": [finding(6, "Label each issue with one area.", "Nothing says what to ask about first or never do.")],
            },
            "Rules held in the persona": freq(place(6, "Label each issue with one area.", True)),
            "Rules used in every act come first": freq(place(6, "Label each issue with one area.", True)),
            "The description says when to choose it": quality(
                4,
                finding(
                    3, "Sorts new issues by area when asked to triage them.",
                    "It names the request in a user's words and not what it is not for.",
                ),
            ),
            "Shows an example": {"not_scored": "The file asks for no particular form."},
            "Instructions an observer can check": freq(place(6, "Label each issue with one area.", True)),
            "What to do, not what to avoid": freq(place(6, "Label each issue with one area.", True)),
            "Each instruction stands alone": freq(place(6, "Label each issue with one area.", True)),
        },
    )


def set_aside_entry(path):
    return {"path": path, "set_aside": True}


def unquoted(text):
    """The text with every quoted line removed, so a check for verdict words reads only the report's own words."""
    return re.sub(r"'[^'\n]*'", "''", text)


def blocks(text):
    """The lines of each fenced text block."""
    return [b.splitlines() for b in re.findall(r"^```text\n(.*?)\n```$", text, re.MULTILINE | re.DOTALL)]


def block(text):
    return blocks(text)[0]


def section(lines, heading):
    """The answer lines under a section heading, up to the next blank line."""
    start = lines.index(heading)
    end = lines.index("", start)
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


def import_report():
    sys.path.insert(0, str(SCRIPTS))
    import report

    return report


class TestQuestions(unittest.TestCase):
    """The 33 questions report.py holds as one constant, against review-questions.md."""

    def setUp(self):
        self.r = import_report()

    @staticmethod
    def limit(para):
        if "Not scored for a standing persona" in para or "Rated for a delegated persona only" in para:
            return "delegated"
        if "Rated where the file opens with an identity" in para:
            return "identity"
        if "Not scored for a file with no settings" in para:
            return "settings"
        if "Not scored for a file that asks for no particular form" in para:
            return "form"
        return None

    def from_file(self):
        text = (REFERENCES / "review-questions.md").read_text(encoding="utf-8")
        out = []
        flags = re.MULTILINE | re.DOTALL
        for heading, name in (("Persona questions", "persona"), ("Instruction-writing questions", "instruction writing")):
            body = re.search(rf"^## {heading}\s*$(.*?)(?=^## |\Z)", text, flags).group(1)
            checks = re.search(r"^### Checks\s*$(.*?)(?=^### |\Z)", body, flags).group(1)
            for para in re.split(r"\n\s*\n", checks):
                m = re.match(r"\*\*(.+?)\*\* \(\*(script|reading)\*\)", para.strip())
                if m:
                    out.append((m.group(1).rstrip("."), name, m.group(2), self.limit(para)))
            ratings = re.search(r"^### Ratings\s*$(.*)", body, flags).group(1)
            for para in re.split(r"\n\s*\n", ratings):
                m = re.match(r"\*\*(.+?)\*\*", para.strip())
                if m:
                    kind = "quality" if "*Exceptional:*" in para else "frequency"
                    out.append((m.group(1).rstrip("."), name, kind, self.limit(para)))
        return out

    def test_constant_matches_the_file(self):
        got = self.from_file()
        self.assertEqual(len(got), 33)
        self.assertEqual(sum(1 for q in got if q[1] == "persona"), 19)
        self.assertEqual(sum(1 for q in got if q[2] == "script"), 7)
        self.assertEqual([tuple(q[:4]) for q in self.r.QUESTIONS], got)
        self.assertEqual([q[0] for q in got], ALL)

    def test_control(self):
        """The comparison can fail: a constant with two questions swapped does not match."""
        swapped = list(self.from_file())
        swapped[0], swapped[1] = swapped[1], swapped[0]
        self.assertNotEqual([tuple(q[:4]) for q in self.r.QUESTIONS], swapped)

    def test_grounding_table(self):
        """Each question's sources, read from bibliography.md's grounding table."""
        grounding = self.r.load_grounding()
        self.assertEqual(sorted(grounding), sorted(ALL))
        self.assertEqual(grounding["A dedicated persona"], "GH4, GO2, AN6")
        self.assertEqual(grounding["Nothing said twice"], "none")


class TestFormula(unittest.TestCase):
    def setUp(self):
        self.r = import_report()

    def test_worked_examples(self):
        """The review questions' two worked examples: 25 out of 40 gives 3 stars; 27 out of 40 gives 3.5."""
        self.assertEqual(self.r.stars(25, 40), Fraction(3))
        self.assertEqual(self.r.stars(27, 40), Fraction(7, 2))

    def test_half_rounds_up(self):
        self.assertEqual(self.r.stars(1, 4), Fraction(3, 2))  # 1.25 is a half between 1 and 1.5
        self.assertEqual(self.r.stars(48, 53), Fraction(9, 2))

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
        self.assertEqual(point(4, 5), 4)  # 80%, inside 'usually'
        self.assertEqual(point(2, 3), 4)
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
        schema = json.loads(proc.stdout)
        self.assertIn("files", schema["properties"])
        entry = schema["properties"]["files"]["items"]["properties"]
        for key in ("loaded_with", "left_out", "set_aside"):
            self.assertIn(key, entry)

    def test_sound_records(self):
        for entry in (helper_review(), doc_writer_review(), triage_review(), set_aside_entry("CLAUDE.md")):
            proc = run("report.py", "validate", self.write([entry]))
            self.assertEqual(proc.returncode, OK, entry["path"] + "\n" + proc.stdout + proc.stderr)

    def test_record_on_standard_input(self):
        record = json.dumps({"root": self.proj.as_posix(), "files": [doc_writer_review()]})
        proc = run("report.py", "validate", "-", stdin=record)
        self.assertEqual(proc.returncode, OK, proc.stdout + proc.stderr)

    def faults(self, entry, project=None):
        path = self.tmp / "faulty.json"
        root = (project or self.proj).as_posix()
        path.write_text(json.dumps({"root": root, "files": [entry]}), encoding="utf-8")
        proc = run("report.py", "validate", path)
        self.assertEqual(proc.returncode, REFUSED, proc.stdout)
        return proc.stdout + proc.stderr

    @staticmethod
    def answer(entry, title):
        return [q for q in entry["questions"] if q["question"] == title][0]

    def test_line_beyond_the_file(self):
        entry = helper_review()
        self.answer(entry, "The description says when to choose it")["findings"][0]["line"] = 88
        self.assertIn(
            ".claude/agents/helper.md, 'The description says when to choose it', finding 1, line: cites line 88, "
            "but .claude/agents/helper.md has 11 lines; quote a line that exists",
            self.faults(entry),
        )

    def test_quote_not_on_its_line(self):
        """Likeness fixture: a paraphrase of the line, cited at the right number, is refused."""
        entry = helper_review()
        self.answer(entry, "The description says when to choose it")["findings"][0]["quote"] = "Reviews code for style"
        self.assertIn("does not appear on line 3", self.faults(entry))

    def test_unknown_question(self):
        entry = helper_review()
        self.answer(entry, "Consistent with itself")["question"] = "Consistent"
        out = self.faults(entry)
        self.assertIn("'Consistent'", out)
        self.assertIn("review-questions.md", out)

    def test_script_check_against_its_rows(self):
        """A script check scored 1 where its row scored 0 is refused, naming the row."""
        entry = helper_review()
        entry["questions"].append({"question": "Bound parts agree with the prose", "score": 1})
        self.assertIn("PJ-003", self.faults(entry))

    def test_script_check_not_scored_against_its_rows(self):
        entry = helper_review()
        entry["questions"].append({"question": "Pointers carry their triggers", "not_scored": "for the test"})
        out = self.faults(entry)
        self.assertIn("'Pointers carry their triggers'", out)
        self.assertIn("rows", out)

    def test_script_check_scored_where_no_row_applies(self):
        """triage.agent.md has no tools field, so no row reads 'Bound parts agree with the prose'."""
        entry = triage_review()
        entry["questions"].append({"question": "Bound parts agree with the prose", "score": 1})
        self.assertIn("not scored", self.faults(entry))

    def test_reading_check_at_zero_without_a_line(self):
        entry = helper_review()
        self.answer(entry, "Consistent with itself")["score"] = 0
        out = self.faults(entry)
        self.assertIn("'Consistent with itself'", out)
        self.assertIn("quot", out)

    def test_point_out_of_range(self):
        entry = helper_review()
        self.answer(entry, "The description says when to choose it")["point"] = 7
        self.assertIn("0 to 6", self.faults(entry))

    def test_quality_below_top_without_lines(self):
        entry = helper_review()
        del self.answer(entry, "An identity that does the work")["findings"]
        self.assertIn("below its top point", self.faults(entry))

    def test_wrong_scale(self):
        entry = helper_review()
        q = self.answer(entry, "Terms defined where they are used")
        q["scale"] = "quality"
        q["point"] = 1
        self.assertIn("frequency", self.faults(entry))

    def test_finding_without_quote(self):
        entry = helper_review()
        del self.answer(entry, "The description says when to choose it")["findings"][0]["quote"]
        self.assertIn("quote", self.faults(entry))

    def test_finding_without_note(self):
        entry = helper_review()
        del self.answer(entry, "The description says when to choose it")["findings"][0]["note"]
        self.assertIn("note", self.faults(entry))

    def test_finding_without_file(self):
        """Every finding names its file (vision v5, SI-13)."""
        entry = helper_review()
        del self.answer(entry, "The description says when to choose it")["findings"][0]["file"]
        out = self.faults(entry)
        self.assertIn("'The description says when to choose it', finding 1, file", out)

    def test_finding_in_a_file_not_reviewed(self):
        entry = helper_review()
        self.answer(entry, "The description says when to choose it")["findings"][0]["file"] = "docs/api.md"
        out = self.faults(entry)
        self.assertIn("docs/api.md", out)
        self.assertIn("not a file this review covers", out)

    def test_place_without_note(self):
        entry = helper_review()
        del self.answer(entry, "Directions for when nobody answers")["places"][0]["note"]
        self.assertIn("note", self.faults(entry))

    def test_check_score_not_one_or_zero(self):
        entry = helper_review()
        self.answer(entry, "Nothing said twice")["score"] = 0.5
        self.assertIn("1 or 0", self.faults(entry))

    def test_missing_question(self):
        entry = helper_review()
        entry["questions"].remove(self.answer(entry, "Consistent with itself"))
        self.assertIn("'Consistent with itself'", self.faults(entry))

    def test_dedicated_persona_missing(self):
        """'A dedicated persona' is answered first; a record without it is refused."""
        entry = helper_review()
        entry["questions"].remove(self.answer(entry, "A dedicated persona"))
        self.assertIn("'A dedicated persona'", self.faults(entry))

    def test_set_aside_carries_no_other_answer(self):
        entry = helper_review()
        q = self.answer(entry, "A dedicated persona")
        q["score"] = 0
        q["findings"] = [finding(7, "You review code for style", "For the test.", ".claude/agents/helper.md")]
        out = self.faults(entry)
        self.assertIn("set aside", out)
        self.assertIn("no other answer", out)

    def test_set_aside_file_with_answers(self):
        """find.py sets CLAUDE.md aside, so a record that scores it is refused."""
        entry = review("CLAUDE.md", {})
        out = self.faults(entry)
        self.assertIn("CLAUDE.md", out)
        self.assertIn(INSTRUCTIONS, out)

    def test_set_aside_where_find_does_not(self):
        out = self.faults(set_aside_entry(".claude/agents/helper.md"))
        self.assertIn("'A dedicated persona'", out)

    def test_standing_persona_scored_on_a_delegated_question(self):
        proj = self.project("standing")
        entry = review("notes/release.md", {}, standing=True)
        self.answer(entry, "One job").pop("not_scored")
        self.answer(entry, "One job")["score"] = 1
        out = self.faults(entry, proj)
        self.assertIn("'One job'", out)
        self.assertIn("standing", out)

    def test_standing_file_rated_on_description(self):
        proj = self.project("standing")
        entry = review("notes/release.md", {}, standing=True)
        q = self.answer(entry, "The description says when to choose it")
        del q["not_rated"]
        q.update(scale="quality", point=6)
        self.assertIn("standing", self.faults(entry, proj))

    def test_loaded_file_missing(self):
        entry = helper_review(loaded_with=[{"path": "docs/no-such.md", "reason": "line 9 loads it"}])
        self.assertIn("docs/no-such.md", self.faults(entry))

    def test_loaded_file_without_reason(self):
        entry = helper_review(loaded_with=[{"path": "docs/api.md"}])
        out = self.faults(entry)
        self.assertIn("docs/api.md", out)
        self.assertIn("reason", out)

    def test_left_out_without_reason(self):
        entry = helper_review(left_out=[{"path": "docs/api.md"}])
        self.assertIn("reason", self.faults(entry))

    def test_question_missing_from_the_grounding_table(self):
        """validate refuses a question that bibliography.md's grounding table does not hold."""
        report = import_report()
        sys.path.insert(0, str(SCRIPTS))
        import check

        grounding = report.load_grounding()
        del grounding["Reasons given"]
        record = {"root": self.proj.as_posix(), "files": [helper_review()]}
        _, faults = report.validate(record, check.load_table(check.DEFAULT_TABLE), grounding)
        self.assertTrue(any("'Reasons given'" in f and "bibliography.md" in f for f in faults), faults)

    def test_empty_record(self):
        """Empty fixture: an empty record is refused."""
        path = self.tmp / "empty.json"
        path.write_text("", encoding="utf-8")
        self.assertEqual(run("report.py", "validate", path).returncode, REFUSED)

    def test_record_with_no_files(self):
        self.assertEqual(run("report.py", "validate", self.write([])).returncode, REFUSED)


class TestRenderT4(ReportCase):
    def test_report_with_findings(self):
        proc = self.render([helper_review()])
        self.assertEqual(proc.returncode, OK, proc.stderr)
        lines = block(proc.stdout)
        # The stars, the total and the two subtotals lead; the header and the files follow.
        self.assertEqual(
            lines[:9],
            [
                "★★★☆☆ (3)",
                "Total: 54 out of 90",
                "Persona: 29 out of 48",
                "Instruction writing: 25 out of 42",
                "",
                "Review: .claude/agents/helper.md (subagent, Claude Code)",
                "Files reviewed:",
                "  .claude/agents/helper.md: the persona's main file",
                "Left out: none",
            ],
        )
        out = "\n".join(lines)
        order = [
            out.index("Lines that lowered the score"),
            out.index("\nPersona\n"),
            out.index("\nInstruction writing\n"),
            out.index("Formula: "),
            out.index(NO_PREDICTION),
            out.index(LINTERS),
        ]
        self.assertEqual(order, sorted(order))
        # Every finding: numbered, its file and line quoted, then its question and note, then its sources.
        items = re.findall(r"^(\d+)\. (\S+), line (\d+): '([^']*)'.*\n   (.+?)\. .*\n   (.+)$", out, re.MULTILINE)
        self.assertEqual(
            [(i[0], i[1], i[2], i[4]) for i in items],
            [
                ("1", ".claude/agents/helper.md", "4", "Bound parts agree with the prose"),
                ("2", ".claude/agents/helper.md", "11", "Directions for when nobody answers"),
                ("3", ".claude/agents/helper.md", "4", "Tools explained"),
                ("4", ".claude/agents/helper.md", "3", "The description says when to choose it"),
                ("5", ".claude/agents/helper.md", "7", "An identity that does the work"),
                ("6", ".claude/agents/helper.md", "10", "Terms defined where they are used"),
                ("7", ".claude/agents/helper.md", "10", "Answers defined, edge cases included"),
                ("8", ".claude/agents/helper.md", "11", "Instructions an observer can check"),
                ("9", ".claude/agents/helper.md", "9", "Reasons given"),
            ],
        )
        self.assertEqual(
            [i[5] for i in items],
            [
                "Rule PJ-003. Sources: AN2, AN3",
                "Sources: RE1",
                "Sources: GO3",
                "Sources: AN3, GO2, OA3, GO3",
                "Sources: ST2",
                "Sources: RE1",
                "Sources: none, reading alone",
                "Sources: AN1, GO3",
                "Sources: AN5",
            ],
        )
        self.assertIn(
            "1. .claude/agents/helper.md, line 4: 'tools: Read, Grep, Edit', against line 9: "
            "'Never edit files; report what you find in a list.'",
            out,
        )
        # Each section's checks then ratings, in the file's order.
        persona = section(lines, "Persona")
        self.assertEqual([next(t for t in ALL if l.startswith(t + " ")) for l in persona], PERSONA_CHECKS + PERSONA_RATINGS)
        writing = section(lines, "Instruction writing")
        self.assertEqual([next(t for t in ALL if l.startswith(t + " ")) for l in writing], IW_CHECKS + IW_RATINGS)
        self.assertRegex(out, r"(?m)^A dedicated persona +yes 1$")
        self.assertRegex(out, r"(?m)^Bound parts agree with the prose +no  0$")
        self.assertRegex(out, r"(?m)^Rules held in the persona +6 of 6   always$")
        self.assertRegex(out, r"(?m)^Answers defined, edge cases included +3 of 6   about half the time$")
        self.assertRegex(out, r"(?m)^Instructions an observer can check +4 of 6   usually$")
        self.assertRegex(out, r"(?m)^The description says when to choose it +2 of 6   fair$")
        self.assertRegex(out, r"(?m)^Its own criteria met +not rated   The file sets no criterion")
        self.assertRegex(out, r"(?m)^Shows an example +not scored   The file asks for no particular form\.$")
        self.assertIn(
            "Formula: each check counts 1 or 0 and each rating its points; persona 29 out of 48, instruction "
            "writing 25 out of 42, total 54 out of 90.",
            lines,
        )
        self.assertIn("Stars: 54 ÷ 90 × 5 = 3.00, to the nearest half star.", lines)
        self.assertNotIn(CLEAN, lines)
        self.assertIsNone(VERDICT_WORDS.search(unquoted(out)), VERDICT_WORDS.search(unquoted(out)))

    def test_columns_aligned(self):
        """The check and rating columns start at one place in both sections."""
        lines = block(self.render([helper_review()]).stdout)
        rows = section(lines, "Persona") + section(lines, "Instruction writing")
        self.assertEqual(len(rows), 33)
        cols = {len(l) - len(l[len(t):].lstrip()) for l in rows for t in ALL if l.startswith(t + " ")}
        self.assertEqual(len(cols), 1, cols)

    def test_clean_report(self):
        proc = self.render([doc_writer_review()])
        self.assertEqual(proc.returncode, OK, proc.stderr)
        lines = block(proc.stdout)
        self.assertEqual(
            lines[:4], ["★★★★★ (5)", "Total: 66 out of 66", "Persona: 36 out of 36", "Instruction writing: 30 out of 30"]
        )
        self.assertEqual(lines[lines.index("Lines that lowered the score") + 1], CLEAN)
        self.assertIn(NO_PREDICTION, lines)
        self.assertIn("Fit with neighbouring files, apart from the score", lines)
        self.assertIn("No neighbouring persona files were supplied.", lines)

    def test_check_row_lines_are_listed(self):
        """A row at 0 lists its line though the record gave the check no finding, with its rule and sources."""
        proc = self.render([triage_review()])
        self.assertEqual(proc.returncode, OK, proc.stdout + proc.stderr)
        lines = block(proc.stdout)
        self.assertEqual(lines[:4], ["★★★★½ (4.5)", "Total: 48 out of 53", "Persona: 24 out of 29", "Instruction writing: 24 out of 24"])
        out = "\n".join(lines)
        self.assertIn(
            "1. .github/agents/triage.agent.md, line 2: 'name: triage'\n"
            "   Declares its tools. The persona declares no tools: the field tools is absent or empty.\n"
            "   Rule PJ-010. Sources: OA2, GO2, GH2",
            out,
        )
        self.assertRegex(out, r"(?m)^Declares its tools +no  0$")
        self.assertRegex(out, r"(?m)^Bound parts agree with the prose +not scored   ")
        self.assertIn("Review: .github/agents/triage.agent.md (custom agent, GitHub Copilot)", lines)

    def test_two_rows_on_one_line_merge(self):
        """PJ-001 and PJ-002 on one line make one finding naming both rules."""
        proj = self.project("pointer")
        path = self.tmp / "pointer.json"
        path.write_text(json.dumps({"root": proj.as_posix(), "files": [review(".claude/agents/pointer.md", {})]}))
        proc = run("report.py", "render", path)
        self.assertEqual(proc.returncode, OK, proc.stdout + proc.stderr)
        out = "\n".join(block(proc.stdout))
        self.assertEqual(out.count("line 7:"), 1, out)
        self.assertIn("Rule PJ-001, PJ-002. Sources: RE1", out)

    def test_no_linters_line_without_bound_parts(self):
        lines = block(self.render([triage_review()]).stdout)
        self.assertNotIn(LINTERS, lines)
        self.assertNotIn("Fit with neighbouring files, apart from the score", lines)

    def test_render_refuses_unsound_record(self):
        entry = helper_review()
        entry["questions"].append({"question": "Bound parts agree with the prose", "score": 1})
        proc = self.render([entry])
        self.assertEqual(proc.returncode, REFUSED)
        self.assertEqual(proc.stdout, "")

    def test_set_aside_by_find(self):
        """A file find.py sets aside: its path, 'set aside' and the reason, and nothing else."""
        proc = self.render([set_aside_entry("CLAUDE.md")])
        self.assertEqual(proc.returncode, NO_SCORE, proc.stderr)
        self.assertEqual(
            block(proc.stdout),
            ["Set aside: CLAUDE.md (project instructions)", "Project instructions: context for the agent, not a dedicated persona."],
        )

    def test_set_aside_by_the_reviewer(self):
        """A file scoring 0 on 'A dedicated persona': set aside, with the line behind it and no stars or total."""
        proj = self.project("standing")
        record = {
            "root": proj.as_posix(),
            "files": [
                {
                    "path": "notes/release.md",
                    "questions": [
                        {
                            "question": "A dedicated persona",
                            "score": 0,
                            "findings": [
                                finding(1, "# Release notes guide", "It is a guide for people and defines no agent of its own.", "notes/release.md")
                            ],
                        }
                    ],
                }
            ],
        }
        path = self.tmp / "aside.json"
        path.write_text(json.dumps(record))
        proc = run("report.py", "render", path)
        self.assertEqual(proc.returncode, NO_SCORE, proc.stdout + proc.stderr)
        self.assertEqual(
            block(proc.stdout),
            [
                "Set aside: notes/release.md (persona)",
                "A dedicated persona. It is a guide for people and defines no agent of its own.",
                "notes/release.md, line 1: '# Release notes guide'",
                "Sources: GH4, GO2, AN6",
            ],
        )

    def test_empty_file(self):
        proj = self.project("empty-file")
        path = self.tmp / "e.json"
        path.write_text(json.dumps({"root": proj.as_posix(), "files": [{"path": ".claude/agents/blank.md", "questions": []}]}))
        proc = run("report.py", "render", path)
        self.assertEqual(proc.returncode, NO_SCORE, proc.stderr)
        lines = block(proc.stdout)
        self.assertEqual(lines[0], EMPTY)
        self.assertIn("Review: .claude/agents/blank.md (subagent, Claude Code)", lines)

    def test_session_text(self):
        text = (make_fixtures.FILES / "helper-agent.fixture").read_text()
        proc = self.render([helper_review(path="<session text>", text=text)])
        self.assertEqual(proc.returncode, OK, proc.stdout + proc.stderr)
        lines = block(proc.stdout)
        self.assertIn("Review: <session text> (persona)", lines)
        out = "\n".join(lines)
        self.assertIn("<session text>, line 11: 'If the scope is unclear, ask.'", out)
        # Session text names no harness, so no row reads these two checks.
        self.assertRegex(out, r"(?m)^Leaves the harness's work to the harness +not scored   ")
        self.assertRegex(out, r"(?m)^Declares its tools +not scored   ")

    def test_render_writes_no_file(self):
        before = make_fixtures.manifest(self.proj)
        run("report.py", "render", self.write([helper_review()]), cwd=self.proj)
        self.assertEqual(make_fixtures.manifest(self.proj), before)


class TestSpreadOverFilesT13(ReportCase):
    """T-13: a persona reviewed as one over its files, every file reviewed and left out named."""

    project_name = "si13"
    LIST_REASON = "personas.txt lists it with the persona"

    def listed_review(self):
        main = "personas/reviewer/reviewer.md"
        scale = "personas/reviewer/scale.md"
        return review(
            main,
            {
                "Rules held in the persona": freq(
                    place(9, "Rate each finding on the scale in scale.md.", True),
                    place(3, "High: the change breaks a user's work.", True, file=scale),
                ),
                "Answers defined, edge cases included": freq(
                    place(4, "Low: the change reads poorly and works.", False, "Nothing says what to return when there is no finding.", file=scale),
                    place(9, "Rate each finding on the scale in scale.md.", True),
                ),
            },
            loaded_with=[
                {"path": scale, "reason": self.LIST_REASON},
                {"path": "personas/reviewer/examples.md", "reason": self.LIST_REASON},
            ],
            left_out=[{"path": "personas/reviewer/missing.md", "reason": "personas.txt lists it, and it does not exist"}],
        )

    def test_listed_persona(self):
        proc = self.render([self.listed_review()])
        self.assertEqual(proc.returncode, OK, proc.stdout + proc.stderr)
        lines = block(proc.stdout)
        start = lines.index("Files reviewed:")
        self.assertEqual(
            lines[start: start + 6],
            [
                "Files reviewed:",
                "  personas/reviewer/reviewer.md: the persona's main file",
                f"  personas/reviewer/scale.md: {self.LIST_REASON}",
                f"  personas/reviewer/examples.md: {self.LIST_REASON}",
                "Left out:",
                "  personas/reviewer/missing.md: personas.txt lists it, and it does not exist",
            ],
        )
        self.assertIn("Review: personas/reviewer/reviewer.md (persona)", lines)
        self.assertIn("1. personas/reviewer/scale.md, line 4: 'Low: the change reads poorly and works.'", lines)

    def test_unattended_persona_names_its_candidates(self):
        stylist = ".claude/agents/stylist.md"
        reason = "the persona names it; no one was there to ask whether it loads with the persona"
        entry = review(
            stylist, {}, left_out=[{"path": "docs/house-style.md", "reason": reason}, {"path": "docs/terms.md", "reason": reason}]
        )
        proc = self.render([entry])
        self.assertEqual(proc.returncode, OK, proc.stdout + proc.stderr)
        lines = block(proc.stdout)
        start = lines.index("Left out:")
        self.assertEqual(lines[start + 1: start + 3], [f"  docs/house-style.md: {reason}", f"  docs/terms.md: {reason}"])
        self.assertEqual(lines[lines.index("Files reviewed:") + 1], f"  {stylist}: the persona's main file")


class TestNothingApplies(unittest.TestCase):
    """The message for a file with text on which no question applies, reached through the rendering function."""

    def test_nothing_applies(self):
        report = import_report()
        p = report.Prepared("notes/x.md")
        p.header = {"kind": "persona", "harness": None, "delegated": False, "bound_parts": []}
        p.answers = [{"title": q[0], "section": q[1], "type": q[2], "findings": [], "not_rated": "for the test", "point": None} for q in report.QUESTIONS]
        text, score = report.render_one(p)
        self.assertIsNone(score)
        self.assertEqual(text.splitlines()[0], NOTHING_APPLIES)


class TestSampleT4(ReportCase):
    """T-4: the record behind sample-review.md's example renders line for line, once its round-3 revision lands."""

    def test_sample_renders_line_for_line(self):
        self.skipTest(WAITING)


class TestSummaryT11(ReportCase):
    def entries(self):
        return [
            doc_writer_review(),
            set_aside_entry("CLAUDE.md"),
            helper_review(),
            triage_review(),
            set_aside_entry("AGENTS.md"),
            set_aside_entry(".claude/output-styles/terse.md"),
            set_aside_entry("README.md"),
        ]

    def test_summary_order(self):
        proc = self.render(self.entries(), "--summary")
        self.assertEqual(proc.returncode, OK, proc.stderr)
        first = block(proc.stdout)
        self.assertEqual(first[0], "Summary: 3 personas reviewed, from the lowest total; 4 files set aside")
        rows = [l for l in first[1:] if l.strip()]
        self.assertEqual(
            [r.split()[0] for r in rows],
            [
                ".claude/agents/helper.md",
                ".github/agents/triage.agent.md",
                ".claude/agents/doc-writer.md",
                ".claude/output-styles/terse.md",
                "AGENTS.md",
                "CLAUDE.md",
                "README.md",
            ],
        )
        self.assertRegex(rows[0], r"^\.claude/agents/helper\.md +subagent +★★★☆☆ \(3\) +54 out of 90$")
        self.assertRegex(rows[1], r"^\.github/agents/triage\.agent\.md +custom agent +★★★★½ \(4\.5\) +48 out of 53$")
        self.assertRegex(rows[5], rf"^CLAUDE\.md +set aside +{re.escape(INSTRUCTIONS)}$")
        # Each report follows the summary, in the summary's order.
        heads = [b[0] for b in blocks(proc.stdout)[1:]]
        self.assertEqual(
            heads[:3],
            ["★★★☆☆ (3)", "★★★★½ (4.5)", "★★★★★ (5)"],
        )
        for row, head in zip(rows[3:], heads[3:]):
            self.assertTrue(head.startswith(f"Set aside: {row.split()[0]} ("), head)
        self.assertEqual(len(heads), 7)

    def test_summary_lists_an_unscored_persona_last(self):
        empty = self.project("empty-file")
        proc = run(
            "report.py", "render", "--summary",
            self.write([{"path": (empty / ".claude/agents/blank.md").as_posix(), "questions": []}, doc_writer_review()]),
        )
        self.assertEqual(proc.returncode, OK, proc.stdout + proc.stderr)
        rows = [l for l in block(proc.stdout)[1:] if l.strip()]
        self.assertTrue(rows[0].startswith(".claude/agents/doc-writer.md"), rows)
        self.assertIn("no stars and no total", rows[1])

    def test_all_set_aside(self):
        """No persona got a score, so render exits 3."""
        proc = self.render([set_aside_entry("CLAUDE.md"), set_aside_entry("README.md")], "--summary")
        self.assertEqual(proc.returncode, NO_SCORE, proc.stderr)
        self.assertEqual(block(proc.stdout)[0], "Summary: 0 personas reviewed, from the lowest total; 2 files set aside")


class TestVerifyT10(ReportCase):
    def rendered(self):
        proc = self.render([doc_writer_review(), helper_review(), triage_review(), set_aside_entry("CLAUDE.md")], "--summary")
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
        bad = self.verify(self.rendered().replace("Total: 54 out of 90", "Total: 55 out of 90"), "altered.md")
        self.assertEqual(bad.returncode, MISMATCH, bad.stdout + bad.stderr)
        out = bad.stdout + bad.stderr
        self.assertIn(".claude/agents/helper.md", out)
        self.assertIn("Total: 55 out of 90", out)

    def test_subtotal_altered(self):
        bad = self.verify(self.rendered().replace("Persona: 29 out of 48", "Persona: 30 out of 48"), "subtotal.md")
        self.assertEqual(bad.returncode, MISMATCH, bad.stdout + bad.stderr)
        out = bad.stdout + bad.stderr
        self.assertIn("Persona: 30 out of 48", out)
        self.assertIn("29 out of 48", out)

    def test_check_flipped(self):
        """A check flipped from 'yes 1' to 'no 0' changes helper.md's persona subtotal and its total."""
        text = self.rendered()
        start = text.index("Review: .claude/agents/helper.md")
        line = re.search(r"(?m)^Pointers carry their triggers +yes 1$", text[start:])
        flipped = text[: start + line.start()] + line.group(0)[:-5] + "no  0" + text[start + line.end():]
        bad = self.verify(flipped, "flipped.md")
        self.assertEqual(bad.returncode, MISMATCH, bad.stdout + bad.stderr)
        out = bad.stdout + bad.stderr
        self.assertIn(".claude/agents/helper.md", out)
        self.assertIn("28 out of 48", out)
        self.assertIn("53 out of 90", out)

    def test_verify_unparsable(self):
        junk = self.tmp / "junk.md"
        junk.write_text("# Not a report\n", encoding="utf-8")
        self.assertEqual(run("report.py", "verify", junk).returncode, REFUSED)

    def test_verify_on_the_sample(self):
        """The sample's own example verifies, once its round-3 revision lands."""
        self.skipTest(WAITING)


if __name__ == "__main__":
    unittest.main()
