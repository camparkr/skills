"""Tests for report.py: schema, validate, render and verify, to the review questions as questions.py reads them
from the parts in references/questions/ at run time: questions, weights, branches and what applies.

Every count here comes from the parts through questions.py, so a change to the questions needs no change to the
tests; the numbers pinned on purpose are the sample's, which the sample test checks by its hash first."""

import json
import re
import sys
import unittest
from fractions import Fraction
from pathlib import Path

from support import QUESTIONS, REFERENCES, SCRIPTS, ScratchCase, make_fixtures, run, sample_text

sys.path.insert(0, str(SCRIPTS))
import questions  # noqa: E402

QS = questions.load(QUESTIONS)
PERSONA, WRITING = QS.sections
TITLES = [q.title for q in QS.questions]
WEIGHTED = [t for t in QS.weights_table]

# Exit codes report.py promises in its docstring.
OK, MISMATCH, REFUSED, NO_SCORE = 0, 1, 2, 3

NO_PREDICTION = "A score does not predict how the agent will behave. The quoted lines are what to act on."
CLEAN = "Nothing was found."
LINTERS = "For secrets, hook scripts and server settings, use a configuration or security linter."
EMPTY = "This file is empty; no stars and no total."
NOTHING_APPLIES = "No question applies to this file; no stars and no total."
INSTRUCTIONS = "project instructions: context for the agent, not a dedicated persona"
TOTAL_RE = re.compile(r"^Total: (\d+) out of (\d+) \((\d+) possible, less (\d+) that do not apply\)$")
VERDICT_WORDS = re.compile(
    r"\b(pass|passes|passed|fail|fails|failed|approve|approved|block|blocked|severity|critical|major|minor)\b",
    re.IGNORECASE,
)

HELPER = ".claude/agents/helper.md"
HELPER_BRANCHES = {"delegated": True, "harness": "Claude Code", "settings": ["tools"]}


def points(title):
    q = QS.by_title[title]
    return q.weight if q.kind != "rating" else QS.scales[q.scale].top


def reason(title):
    """A content-test question's printed reason, read from the file."""
    return QS.content_tests[title][1]


def branch_reason(key):
    return QS.branches[key].reason


def weights_phrase():
    """'A, B and C weigh 3', as the formula names the weighted checks, built from the file."""
    groups = {}
    for title in QS.weights_table:
        groups.setdefault(QS.by_title[title].weight, []).append(title)
    parts = []
    for weight, titles in sorted(groups.items()):
        names = titles[0] if len(titles) == 1 else ", ".join(titles[:-1]) + " and " + titles[-1]
        parts.append(f"{names} {'weighs' if len(titles) == 1 else 'weigh'} {weight}")
    return "; ".join(parts)


def finding(line, quote, note, file):
    return {"file": file, "line": line, "quote": quote, "note": note}


def place(line, quote, meets, file, note=None):
    p = {"file": file, "line": line, "quote": quote, "meets": meets}
    if not meets:
        p["note"] = note or "It does not meet the question."
    return p


def with_subject(answer, path):
    """A content-test answer that applies gives its subject: the line of its first place or finding, when the
    answer does not give one itself."""
    if "does_not_apply" in answer or "subject" in answer:
        return answer
    item = (answer.get("places") or answer.get("findings") or [None])[0]
    if item:
        answer = dict(answer, subject={"file": item.get("file", path), "line": item["line"], "quote": item["quote"]})
    return answer


# The fit statement a fixture record gives when it supplies no fit of its own.
NO_FIT = "Nothing was found on how its remit sits with the nearby files."


def review(path, answers, branches, removed=(), default_place=None, absent=(), **extra):
    """A record entry: the answers given, and for every other question the persona answers, a reading check met, a
    quality rating at its top point, and a frequency rating with default_place meeting it. A content-test question
    named in absent (the fixture's file does not hold its subject) is marked as not applying, with the reason the
    file prints; any other content-test question gives its subject. Questions in removed, and script checks, are
    left out. Which questions are content tests is read from the review questions, so a new row needs no change
    here."""
    out = []
    for title in TITLES:
        q = QS.by_title[title]
        if title in answers:
            if answers[title] is not None:
                answer = dict(answers[title], question=title)
                out.append(with_subject(answer, path) if title in QS.content_tests else answer)
            continue
        if title in removed or q.kind == "script":
            continue
        if title in QS.content_tests and title in absent:
            out.append({"question": title, "does_not_apply": reason(title)})
            continue
        if q.kind == "reading":
            answer = {"question": title, "score": 1}
            if title in QS.content_tests:
                answer["subject"] = {"file": path, "line": default_place[0], "quote": default_place[1]}
        elif q.scale == "quality":
            answer = {"question": title, "scale": "quality", "point": QS.scales["quality"].top}
        else:
            answer = {"question": title, "scale": q.scale, "places": [place(*default_place, True, path)]}
        out.append(with_subject(answer, path) if title in QS.content_tests else answer)
    # Every persona entry carries a fit entry, which validate requires; a test that needs another passes its own.
    extra.setdefault("fit", {"statement": NO_FIT})
    return dict({"path": path, "branches": branches, "questions": out}, **extra)


# The content tests each fixture's file holds no subject for, by the fixture's text (the questions come from the file).
NO_COMMANDS, NO_FORM, NO_CRITERION = "Commands given exactly", "Shows an example", "Its own criteria met"
NO_ASKING, NO_ANSWERS, NO_TOOLS = "Directions for when nobody answers", "Answers defined, edge cases included", "Tools explained"
HELPER_ABSENT = (NO_COMMANDS, NO_FORM, NO_CRITERION)
DOC_WRITER_ABSENT = (NO_COMMANDS, NO_ASKING, NO_CRITERION, NO_FORM)
TRIAGE_ABSENT = (NO_COMMANDS, NO_ASKING, NO_ANSWERS, NO_CRITERION, NO_FORM)
BARE_ABSENT = (NO_TOOLS, NO_COMMANDS, NO_ASKING, NO_ANSWERS, NO_CRITERION, NO_FORM)


def helper_review(path=HELPER, **extra):
    """.claude/agents/helper.md, with findings. Every branch at yes; 'Declares its tools' scores 1, so 'Tools explained'
    applies; three content tests find no subject."""
    f = path
    answers = {
        "Directions for when nobody answers": {
            "scale": "frequency", "subject": {"file": f, "line": 11, "quote": "If the scope is unclear, ask."},
            "places": [place(11, "If the scope is unclear, ask.", False, f, "Nothing covers a run with no one to ask.")],
        },
        "Tools explained": {
            "scale": "quality", "point": 0,
            "findings": [finding(4, "tools: Read, Grep, Edit", "Three tools are named with no word on when to use them.", f)],
        },
        "The description says when to choose it": {
            "scale": "quality", "point": 2,
            "findings": [finding(3, "Reviews pull requests for style problems.", "It names a subject and no task.", f)],
        },
        "An identity that does the work": {
            "scale": "quality", "point": 4,
            "findings": [finding(7, "You review code for style and report what you find.", "It states the work and not where it stops.", f)],
        },
        "Terms defined where they are used": {
            "scale": "frequency",
            "places": [place(10, "Rate each finding high, medium or low.", False, f, "The scale is named and never defined.")],
        },
        "Answers defined, edge cases included": {
            "scale": "frequency", "subject": {"file": f, "line": 10, "quote": "Rate each finding high, medium or low."},
            "places": [
                place(10, "high, medium or low", False, f, "Nothing says what to return when nothing is found."),
                place(7, "report what you find", True, f),
            ],
        },
        "Instructions an observer can check": {
            "scale": "frequency",
            "places": [
                place(9, "Never edit files", True, f),
                place(10, "Rate each finding high, medium or low.", True, f),
                place(11, "If the scope is unclear, ask.", False, f, "Whether the scope is unclear is not something an observer can see."),
            ],
        },
        "Reasons given": {"scale": "frequency", "places": [place(9, "Never edit files", False, f, "The rule gives no reason.")]},
    }
    return review(path, answers, HELPER_BRANCHES, default_place=(9, "Never edit files; report what you find in a list."),
                  absent=HELPER_ABSENT, **extra)


HELPER_DO_NOT_APPLY = [(t, reason(t)) for t in TITLES if t in HELPER_ABSENT]


def doc_writer_review():
    """A clean review of .claude/agents/doc-writer.md: every question that applies at its top."""
    f = ".claude/agents/doc-writer.md"
    answers = {
        "Tools explained": {
            "scale": "quality", "point": QS.scales["quality"].top,
            "subject": {"file": f, "line": 7, "quote": "Read `CHANGELOG.md` when the user asks"},
        },
        "Answers defined, edge cases included": {
            "scale": "frequency", "subject": {"file": f, "line": 9, "quote": "When the changelog is empty"},
            "places": [place(9, "say there is nothing to report", True, f)],
        },
    }
    return review(
        f, answers, {"delegated": True, "harness": "Claude Code", "settings": ["tools"]},
        default_place=(8, "Write each note as one sentence in the past tense."), absent=DOC_WRITER_ABSENT,
        fit={"statement": "No neighbouring persona files were supplied."},
    )


def triage_review():
    """.github/agents/triage.agent.md: no settings, so two questions do not apply; 'Declares its tools' scores 0 from
    PJ-010, so 'Tools explained' does not apply."""
    f = ".github/agents/triage.agent.md"
    line = "Label each issue with one area."
    answers = {
        "States its output": {"score": 0, "findings": [finding(6, line, "Nothing says what the agent returns or in what form.", f)]},
        "Boundaries in three tiers": {"score": 0, "findings": [finding(6, line, "Nothing says what to ask about first or never do.", f)]},
        "The description says when to choose it": {
            "scale": "quality", "point": 4,
            "findings": [finding(3, "Sorts new issues by area when asked to triage them.", "It names the request and not what it is not for.", f)],
        },
        "An identity that does the work": {
            "scale": "quality", "point": 0, "findings": [finding(6, line, "The file states no identity.", f)],
        },
    }
    removed = QS.branches["settings"].removes + ["Tools explained"]
    return review(f, answers, {"delegated": True, "harness": "GitHub Copilot", "settings": []}, removed, (6, line),
                  absent=TRIAGE_ABSENT)


def release_review():
    """notes/release.md, named: every branch at no."""
    f = "notes/release.md"
    removed = [t for b in QS.branches.values() for t in b.removes]
    answers = {
        "An identity that does the work": {
            "scale": "quality", "point": 0, "findings": [finding(1, "# Release notes guide", "The file states no identity.", f)],
        },
    }
    return review(f, answers, {"delegated": False, "harness": None, "settings": []}, removed, absent=BARE_ABSENT,
                  default_place=
                  (3, "Run `make notes` before each release."))


def complete_review(consistent=0):
    """.claude/agents/release-checker.md, to which every question applies: each at its top, except 'Consistent with
    itself' at the score given, so the expected score can be worked out by hand."""
    f = ".claude/agents/release-checker.md"
    subject = lambda n, q: {"file": f, "line": n, "quote": q}  # noqa: E731
    answers = {
        "Tools explained": {
            "scale": "quality", "point": QS.scales["quality"].top, "subject": subject(10, "Always run `pytest -v tests/`"),
        },
        "Commands given exactly": {
            "scale": "frequency", "subject": subject(10, "run `pytest -v tests/`"),
            "places": [place(10, "run `pytest -v tests/`", True, f)],
        },
        "Directions for when nobody answers": {
            "scale": "frequency", "subject": subject(11, "Ask the user which branch to check"),
            "places": [place(11, "when no one answers, check the main branch", True, f)],
        },
        "Answers defined, edge cases included": {
            "scale": "frequency", "subject": subject(12, "Rate each branch ready or not ready"),
            "places": [place(12, "return not ready when the tests fail", True, f)],
        },
        "Its own criteria met": {
            "scale": "frequency", "subject": subject(13, "Every finding cites its file and line"),
            "places": [place(13, "Every finding cites its file and line", True, f)],
        },
        "Shows an example": {"score": 1, "subject": subject(14, "Return a list of findings in this form:")},
        "Consistent with itself": {"score": 1} if consistent else {
            "score": 0,
            "findings": [finding(8, "you never change code", "Set against a rule to change nothing, for the test.", f)],
        },
    }
    return review(f, answers, {"delegated": True, "harness": "Claude Code", "settings": ["tools", "permissionMode"]},
                  default_place=(10, "Always run `pytest -v tests/` before you report"))


def set_aside_entry(path):
    return {"path": path, "set_aside": True}


def unquoted(text):
    return re.sub(r"'[^'\n]*'", "''", text)


def blocks(text):
    return [b.splitlines() for b in re.findall(r"^```text\n(.*?)\n```$", text, re.MULTILINE | re.DOTALL)]


def block(text):
    return blocks(text)[0]


def section(lines, heading):
    """The answer lines under a section heading, up to the next blank line."""
    start = lines.index(heading)
    end = lines.index("", start)
    return lines[start + 1: end]


def row_value(line):
    title = next(t for t in sorted(TITLES, key=len, reverse=True) if line.startswith(t + " "))
    return title, line[len(title):].strip()


def do_not_apply(lines):
    """[(title, reason)] under 'Do not apply:'."""
    start = next(i for i, l in enumerate(lines) if l.startswith("Do not apply:"))
    if lines[start] == "Do not apply: none.":
        return []
    out = []
    for line in lines[start + 1:]:
        if not line.startswith("  "):
            break
        title = next(t for t in TITLES if line.startswith("  " + t + ": "))
        out.append((title, line[len("  " + title + ": "):]))
    return out


class ReportCase(ScratchCase):
    project_name = "si11"

    def setUp(self):
        super().setUp()
        self.proj = self.project(self.project_name)

    def write(self, files, name="record.json", root=None):
        path = self.tmp / name
        path.write_text(json.dumps({"root": (root or self.proj).as_posix(), "files": files}), encoding="utf-8")
        return path

    def render(self, files, *extra, root=None):
        return run("report.py", "render", *extra, self.write(files, root=root))

    def assert_totals_follow(self, lines):
        """The total, the subtotals and the points that do not apply follow from the file and the rows printed."""
        m = TOTAL_RE.match(lines[1])
        self.assertIsNotNone(m, lines[1])
        x, y, possible, n = map(int, m.groups())
        self.assertEqual(possible, QS.possible)
        dna = do_not_apply(lines)
        self.assertEqual(n, sum(points(t) for t, _ in dna))
        self.assertEqual(y, possible - n)
        subtotals = []
        for i, label in enumerate(QS.sections):
            sm = re.match(rf"^{label}: (\d+) out of (\d+)$", lines[2 + i])
            self.assertIsNotNone(sm, lines[2 + i])
            rows = [row_value(l) for l in section(lines, label)]
            self.assertEqual([t for t, _ in rows], [q.title for q in QS.questions if q.section == label])
            sx = sum(int(v.split()[1]) if v.startswith(("yes", "no")) else int(v.split()[0]) for _, v in rows if v != "does not apply")
            sy = QS.section_points(label) - sum(points(t) for t, _ in dna if QS.by_title[t].section == label)
            self.assertEqual((int(sm.group(1)), int(sm.group(2))), (sx, sy), label)
            self.assertEqual({t for t, v in rows if v == "does not apply"}, {t for t, _ in dna if QS.by_title[t].section == label})
            subtotals.append((sx, sy))
        self.assertEqual((x, y), (sum(a for a, _ in subtotals), sum(b for _, b in subtotals)))
        return x, y, n


def import_report():
    import report

    return report


class TestFormula(unittest.TestCase):
    def setUp(self):
        self.r = import_report()

    def test_worked_examples(self):
        """The review questions' two worked examples: 25 out of 40 gives 3 stars; 27 out of 40 gives 3.5."""
        self.assertEqual(self.r.stars(25, 40), Fraction(3))
        self.assertEqual(self.r.stars(27, 40), Fraction(7, 2))

    def test_half_rounds_up(self):
        self.assertEqual(self.r.stars(1, 4), Fraction(3, 2))

    def test_star_display_t_s(self):
        """The star line for 0, 0.5, 3, 3.5 and 5 stars, code point for code point."""
        want = {
            Fraction(0): "☆☆☆☆☆ (0)", Fraction(1, 2): "½☆☆☆☆ (0.5)", Fraction(3): "★★★☆☆ (3)",
            Fraction(7, 2): "★★★½☆ (3.5)", Fraction(5): "★★★★★ (5)",
        }
        for value, line in want.items():
            self.assertEqual([hex(ord(c)) for c in self.r.star_line(value)], [hex(ord(c)) for c in line], value)

    def test_no_question_in_the_script(self):
        """No script holds a question title: the questions live in references/questions/ alone, so editing them needs
        no code change."""
        for script in SCRIPTS.glob("*.py"):
            text = script.read_text(encoding="utf-8")
            held = [t for t in TITLES if t in text]
            self.assertEqual(held, [], script.name)


class TestGrounding(unittest.TestCase):
    def test_grounding_table(self):
        grounding = import_report().load_grounding()
        self.assertEqual(sorted(grounding), sorted(TITLES))
        self.assertEqual(grounding[QS.root], "GH4, GO2, AN6")
        self.assertEqual(grounding["Nothing said twice"], "none")


class TestSchemaAndValidate(ReportCase):
    def test_schema_is_json(self):
        proc = run("report.py", "schema")
        self.assertEqual(proc.returncode, OK, proc.stderr)
        entry = json.loads(proc.stdout)["properties"]["files"]["items"]["properties"]
        for key in ("loaded_with", "left_out", "set_aside", "branches"):
            self.assertIn(key, entry)
        answer = entry["questions"]["items"]["properties"]
        self.assertIn("does_not_apply", answer)
        self.assertIn("subject", answer)
        self.assertNotIn("not_scored", answer)

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
        path.write_text(json.dumps({"root": (project or self.proj).as_posix(), "files": [entry]}), encoding="utf-8")
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
            f"{HELPER}, 'The description says when to choose it', finding 1, line: cites line 88, but {HELPER} has 11 "
            "lines; quote a line that exists",
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
        self.assertIn("review questions", out)

    def test_script_check_against_its_rows(self):
        entry = helper_review()
        entry["questions"].append({"question": "Bound parts agree with the prose", "score": 1})
        self.assertIn("PJ-003", self.faults(entry))

    def test_reading_check_at_zero_without_a_line(self):
        entry = helper_review()
        self.answer(entry, "Consistent with itself")["score"] = 0
        out = self.faults(entry)
        self.assertIn("'Consistent with itself'", out)
        self.assertIn("quot", out)

    def test_point_out_of_range(self):
        entry = helper_review()
        self.answer(entry, "The description says when to choose it")["point"] = 7
        self.assertIn(f"0 to {QS.scales['quality'].top}", self.faults(entry))

    def test_quality_below_top_without_lines(self):
        entry = helper_review()
        del self.answer(entry, "An identity that does the work")["findings"]
        self.assertIn("below its top point", self.faults(entry))

    def test_wrong_scale(self):
        entry = helper_review()
        q = self.answer(entry, "Terms defined where they are used")
        q["scale"], q["point"] = "quality", 1
        self.assertIn("frequency", self.faults(entry))

    def test_finding_without_quote_note_or_file(self):
        for key in ("quote", "note", "file"):
            entry = helper_review()
            del self.answer(entry, "The description says when to choose it")["findings"][0][key]
            self.assertIn(key, self.faults(entry), key)

    def test_finding_in_a_file_not_reviewed(self):
        entry = helper_review()
        self.answer(entry, "The description says when to choose it")["findings"][0]["file"] = "docs/api.md"
        self.assertIn("not a file this review covers", self.faults(entry))

    def test_place_without_note(self):
        entry = helper_review()
        del self.answer(entry, "Reasons given")["places"][0]["note"]
        self.assertIn("note", self.faults(entry))

    def test_check_score_not_one_or_zero(self):
        entry = helper_review()
        self.answer(entry, "Nothing said twice")["score"] = 0.5
        self.assertIn("1 or 0", self.faults(entry))

    def test_root_missing(self):
        entry = helper_review()
        entry["questions"].remove(self.answer(entry, QS.root))
        self.assertIn(f"'{QS.root}'", self.faults(entry))

    def test_set_aside_carries_no_other_answer(self):
        entry = helper_review()
        q = self.answer(entry, QS.root)
        q["score"] = 0
        q["findings"] = [finding(7, "You review code for style", "For the test.", HELPER)]
        out = self.faults(entry)
        self.assertIn("set aside", out)
        self.assertIn("no other answer", out)

    def test_set_aside_file_with_answers(self):
        entry = review("CLAUDE.md", {}, {"delegated": False, "harness": None, "settings": []}, default_place=(3, "Run"))
        out = self.faults(entry)
        self.assertIn(INSTRUCTIONS, out)

    def test_set_aside_where_find_does_not(self):
        self.assertIn(f"'{QS.root}'", self.faults(set_aside_entry(HELPER)))

    def test_old_reason_keys_refused(self):
        """'not scored' and 'not rated' are refused: a question that does not apply carries a reason from the file."""
        entry = helper_review()
        q = self.answer(entry, "Its own criteria met")
        del q["does_not_apply"]
        q["not_rated"] = "The file sets no criterion."
        out = self.faults(entry)
        self.assertIn("'Its own criteria met'", out)
        self.assertIn("does_not_apply", out)

    def test_question_missing_from_the_grounding_table(self):
        report = import_report()
        import check

        grounding = report.load_grounding()
        del grounding["Reasons given"]
        record = {"root": self.proj.as_posix(), "files": [helper_review()]}
        _, faults = report.validate(record, check.load_table(check.DEFAULT_TABLE), grounding)
        self.assertTrue(any("'Reasons given'" in f and "grounding.md" in f for f in faults), faults)

    def test_empty_record(self):
        path = self.tmp / "empty.json"
        path.write_text("", encoding="utf-8")
        self.assertEqual(run("report.py", "validate", path).returncode, REFUSED)

    def test_record_with_no_files(self):
        self.assertEqual(run("report.py", "validate", self.write([])).returncode, REFUSED)

    def test_one_fault_is_singular(self):
        entry = helper_review()
        self.answer(entry, "The description says when to choose it")["point"] = 7
        out = self.faults(entry)
        self.assertIn("1 fault. Fix the record", out)


class TestWhatAppliesT_W(ReportCase):
    """report.py removes exactly the questions the file's tables name for each branch, and validate refuses each wrong
    record."""

    def faults(self, entry, project=None):
        path = self.tmp / "faulty.json"
        path.write_text(json.dumps({"root": (project or self.proj).as_posix(), "files": [entry]}), encoding="utf-8")
        proc = run("report.py", "validate", path)
        self.assertEqual(proc.returncode, REFUSED, proc.stdout)
        return proc.stdout + proc.stderr

    @staticmethod
    def answer(entry, title):
        return [q for q in entry["questions"] if q["question"] == title][0]

    def test_branches_must_match(self):
        entry = helper_review()
        entry["branches"]["settings"] = []
        out = self.faults(entry)
        self.assertIn("branches", out)
        self.assertIn("tools", out)

    def test_answers_a_removed_question(self):
        proj = self.project("standing")
        entry = release_review()
        entry["questions"].append({"question": "One job", "score": 1})
        out = self.faults(entry, proj)
        self.assertIn("'One job'", out)
        self.assertIn(branch_reason("delegated"), out)

    def test_leaves_out_a_question_that_applies(self):
        entry = helper_review()
        entry["questions"].remove(self.answer(entry, "One job"))
        self.assertIn("'One job'", self.faults(entry))

    def test_reason_the_branches_do_not_allow(self):
        entry = helper_review()
        q = self.answer(entry, "Commands given exactly")
        q["does_not_apply"] = branch_reason("delegated")
        out = self.faults(entry)
        self.assertIn("'Commands given exactly'", out)
        self.assertIn(branch_reason("delegated"), out)

    def test_rates_tools_explained_after_declares_scored_0(self):
        entry = triage_review()
        entry["questions"].append({
            "question": "Tools explained", "scale": "quality", "point": QS.scales["quality"].top,
            "subject": {"file": ".github/agents/triage.agent.md", "line": 6, "quote": "Label each issue with one area."},
        })
        out = self.faults(entry)
        self.assertIn("'Tools explained'", out)
        self.assertIn(QS.following["Tools explained"][1], out)

    def test_content_test_with_a_subject_marked_not_applying(self):
        entry = helper_review()
        q = self.answer(entry, "Commands given exactly")
        q["subject"] = {"file": HELPER, "line": 9, "quote": "Never edit files"}
        out = self.faults(entry)
        self.assertIn("'Commands given exactly'", out)
        self.assertIn("subject", out)

    def test_content_test_applying_without_a_subject(self):
        entry = helper_review()
        del self.answer(entry, "Directions for when nobody answers")["subject"]
        self.assertIn("subject", self.faults(entry))

    def test_codex_exception(self):
        """'Declares its tools' does not apply to a Codex custom agent, with the reason the file's exception gives."""
        proj = self.project("branches")
        f = ".codex/agents/auditor.toml"
        entry = review(f, {}, {"delegated": True, "harness": "Codex", "settings": ["sandbox_mode"]},
                       default_place=(5, "Read each changed lockfile entry."), absent=BARE_ABSENT)
        path = self.write([entry], root=proj)
        proc = run("report.py", "render", path)
        self.assertEqual(proc.returncode, OK, proc.stdout + proc.stderr)
        dna = do_not_apply(block(proc.stdout))
        exception = QS.exceptions[0]
        self.assertIn((exception[0], exception[2]), dna)
        self.assertIn(("Tools explained", reason("Tools explained")), dna)

    def test_model_only_holds_no_settings(self):
        proj = self.project("branches")
        f = ".claude/agents/summary-writer.md"
        line = "Return a summary of the change in three sentences."
        entry = review(
            f, {"Tools explained": None}, {"delegated": True, "harness": "Claude Code", "settings": []},
            removed=QS.branches["settings"].removes, default_place=(7, line), absent=TRIAGE_ABSENT,
        )
        proc = run("report.py", "render", self.write([entry], root=proj))
        self.assertEqual(proc.returncode, OK, proc.stdout + proc.stderr)
        dna = do_not_apply(block(proc.stdout))
        for title in QS.branches["settings"].removes:
            self.assertIn((title, branch_reason("settings")), dna)
        self.assertIn(("Tools explained", QS.following["Tools explained"][1]), dna)


class TestNoPlace(ReportCase):
    """A frequency rating with no place in the file: under the content tests the review questions list, it does not
    apply, with the reason the file prints, and no script changed. The test's file holds no rule that limits the
    agent, so 'Reasons given' has no place."""

    project_name = "no-place"

    def test_reasons_given_does_not_apply(self):
        f = ".claude/agents/zeta.md"
        title = "Reasons given"
        self.assertIn(title, QS.content_tests)
        entry = review(
            f, {}, {"delegated": True, "harness": "Claude Code", "settings": ["tools"]},
            default_place=(8, "Report each change as a numbered list item."),
            absent=(NO_COMMANDS, NO_ASKING, NO_ANSWERS, NO_CRITERION, title),
        )
        proc = self.render([entry])
        self.assertEqual(proc.returncode, OK, proc.stdout + proc.stderr)
        lines = block(proc.stdout)
        self.assertIn((title, reason(title)), do_not_apply(lines))
        self.assertRegex("\n".join(lines), rf"(?m)^{re.escape(title)} +does not apply$")
        self.assert_totals_follow(lines)


THIN_LINE = "Most questions do not apply: this file says little, and the score covers only what it says."
THIN = ".claude/agents/reviewer.md"
THIN_TEXT = "You are an expert code reviewer who helps with pull requests."


def thin_review():
    """A one-line persona: an identity and nothing else, so every content test finds no subject."""
    f = THIN
    answers = {
        "The description says when to choose it": {
            "scale": "quality", "point": 0, "findings": [finding(1, THIN_TEXT, "The file has no description.", f)],
        },
        "An identity that does the work": {
            "scale": "quality", "point": 3, "findings": [finding(1, THIN_TEXT, "It states the work, with praise.", f)],
        },
    }
    removed = QS.branches["settings"].removes + [r for r, (c, _) in QS.following.items()]
    return review(f, answers, {"delegated": True, "harness": "Claude Code", "settings": []}, removed,
                  default_place=(1, THIN_TEXT), absent=tuple(QS.content_tests))


class TestThinFile(ReportCase):
    """A file that says little: past half the points possible not applying, the report says so under 'Do not apply',
    so a high score on little text is not read as a good persona. The threshold is half the points the file derives, never a number in code."""

    project_name = "thin"

    def test_thin_file_line(self):
        proc = self.render([thin_review()])
        self.assertEqual(proc.returncode, OK, proc.stdout + proc.stderr)
        lines = block(proc.stdout)
        _, _, n = self.assert_totals_follow(lines)
        self.assertGreater(2 * n, QS.possible)
        # The line directly under the 'Do not apply' block: the first line after it that is not one of its items.
        after = lines.index("Do not apply:") + 1
        while lines[after].startswith("  "):
            after += 1
        self.assertEqual(lines[after], THIN_LINE)
        code = run("report.py", "verify", "-", stdin=proc.stdout)
        self.assertEqual(code.returncode, OK, code.stdout + code.stderr)

    def test_fuller_file_has_no_thin_line(self):
        proc = run("report.py", "render", self.write([helper_review()], root=self.project("si11")))
        self.assertEqual(proc.returncode, OK, proc.stdout + proc.stderr)
        lines = block(proc.stdout)
        _, _, n = self.assert_totals_follow(lines)
        self.assertLessEqual(2 * n, QS.possible)
        self.assertNotIn(THIN_LINE, lines)

    def verify_text(self, text):
        path = self.tmp / "thin-report.md"
        path.write_text(text, encoding="utf-8")
        proc = run("report.py", "verify", path)
        return proc.returncode, proc.stdout + proc.stderr

    def test_verify_thin_line_removed(self):
        """A thin file's report without the line fails verify, naming it."""
        text = self.render([thin_review()]).stdout
        self.assertIn(THIN_LINE, text)
        code, out = self.verify_text(text.replace(THIN_LINE + "\n", "", 1))
        self.assertEqual(code, MISMATCH, out)
        self.assertIn(THIN_LINE, out)
        self.assertIn(THIN, out)

    def test_verify_thin_line_added(self):
        """A fuller file's report with the line added fails verify, naming it."""
        text = run("report.py", "render", self.write([helper_review()], root=self.project("si11"))).stdout
        self.assertNotIn(THIN_LINE, text)
        lines = text.split("\n")
        after = lines.index("Do not apply:") + 1
        while lines[after].startswith("  "):
            after += 1
        code, out = self.verify_text("\n".join(lines[:after] + [THIN_LINE] + lines[after:]))
        self.assertEqual(code, MISMATCH, out)
        self.assertIn(THIN_LINE, out)
        self.assertIn(HELPER, out)

    def test_identity_only_file_validates(self):
        """The two instruction ratings, content tests since 4 October 2026, do not apply to a file holding only an
        identity, each with the reason the file prints."""
        proc = run("report.py", "validate", self.write([thin_review()]))
        self.assertEqual(proc.returncode, OK, proc.stdout + proc.stderr)
        lines = block(self.render([thin_review()]).stdout)
        for title in ("Instructions an observer can check", "Each instruction stands alone"):
            self.assertIn(title, QS.content_tests)
            self.assertIn((title, reason(title)), do_not_apply(lines))


class TestRenderT4(ReportCase):
    def test_report_with_findings(self):
        proc = self.render([helper_review()])
        self.assertEqual(proc.returncode, OK, proc.stderr)
        lines = block(proc.stdout)
        self.assert_totals_follow(lines)
        self.assertEqual(
            lines[len(QS.sections) + 2: len(QS.sections) + 8],
            [
                "",
                f"Review: {HELPER} (subagent, Claude Code)",
                "Branches: delegated yes (folder); harness Claude Code; settings tools",
                "Files reviewed:",
                f"  {HELPER}: the persona's main file",
                "Files left out: none",
            ],
        )
        self.assertEqual(do_not_apply(lines), HELPER_DO_NOT_APPLY)
        out = "\n".join(lines)
        order = [
            out.index("Do not apply:"), out.index("Lines that lowered the score"), out.index("\nPersona\n"),
            out.index("\nInstruction writing\n"), out.index("Formula: "), out.index("At equal weights: "),
            out.index("Stars: "), out.index(NO_PREDICTION), out.index(LINTERS),
        ]
        self.assertEqual(order, sorted(order))
        items = re.findall(r"^(\d+)\. (\S+), line (\d+): '([^']*)'.*\n +(.+?)\. .*\n +(.+)$", out, re.MULTILINE)
        self.assertEqual(
            [(i[2], i[4]) for i in items],
            [
                ("4", "Bound parts agree with the prose"),
                ("11", "Directions for when nobody answers"),
                ("4", "Tools explained"),
                ("3", "The description says when to choose it"),
                ("7", "An identity that does the work"),
                ("10", "Terms defined where they are used"),
                ("10", "Answers defined, edge cases included"),
                ("11", "Instructions an observer can check"),
                ("9", "Reasons given"),
            ],
        )
        self.assertEqual(items[0][5], "Rule PJ-003. Sources: AN2, AN3")
        self.assertRegex(out, rf"(?m)^Bound parts agree with the prose +no  0$")
        self.assertRegex(out, rf"(?m)^Consistent with itself +yes {QS.by_title['Consistent with itself'].weight}$")
        self.assertRegex(out, rf"(?m)^Enforceable rules enforced +yes {QS.by_title['Enforceable rules enforced'].weight}$")
        self.assertRegex(out, r"(?m)^A dedicated persona +yes 1$")
        self.assertRegex(out, r"(?m)^Commands given exactly +does not apply$")
        self.assertRegex(out, r"(?m)^Answers defined, edge cases included +3 of 6   about half the time$")
        persona = section(lines, "Persona")
        writing = section(lines, "Instruction writing")
        x, y, _ = self.assert_totals_follow(lines)
        rows = [row_value(l) for l in persona + writing]
        ex = sum((1 if v.startswith("yes") else 0) if v.startswith(("yes", "no")) else int(v.split()[0])
                 for _, v in rows if v != "does not apply")
        ey = sum((1 if QS.by_title[t].kind != "rating" else QS.scales[QS.by_title[t].scale].top)
                 for t, v in rows if v != "does not apply")
        (px, py), (wx, wy) = [tuple(map(int, re.findall(r"\d+", lines[2 + i]))) for i in range(2)]
        self.assertIn(
            f"Formula: each check counts its weight or 0, and each rating its points; {weights_phrase()}, every other "
            f"check 1; {PERSONA.lower()} {px} out of {py}, {WRITING.lower()} {wx} out of {wy}, total {x} out of {y}.",
            lines,
        )
        self.assertIn(f"At equal weights: {ex} out of {ey}.", lines)
        self.assertIsNone(VERDICT_WORDS.search(unquoted(out)), VERDICT_WORDS.search(unquoted(out)))

    def test_columns_aligned(self):
        lines = block(self.render([helper_review()]).stdout)
        rows = section(lines, "Persona") + section(lines, "Instruction writing")
        self.assertEqual(len(rows), len(TITLES))
        cols = {len(l) - len(l[len(t):].lstrip()) for l in rows for t, _ in [row_value(l)]}
        self.assertEqual(len(cols), 1, cols)

    def test_clean_report(self):
        proc = self.render([doc_writer_review()])
        self.assertEqual(proc.returncode, OK, proc.stderr)
        lines = block(proc.stdout)
        x, y, _ = self.assert_totals_follow(lines)
        self.assertEqual((lines[0], x), ("★★★★★ (5)", y))
        self.assertEqual(lines[lines.index("Lines that lowered the score") + 1], CLEAN)
        self.assertIn("No neighbouring persona files were supplied.", lines)

    def test_declares_its_tools_scores_0(self):
        """'Declares its tools' at 0 from PJ-010: 'Tools explained' does not apply, with the following rating's reason."""
        proc = self.render([triage_review()])
        self.assertEqual(proc.returncode, OK, proc.stdout + proc.stderr)
        lines = block(proc.stdout)
        self.assert_totals_follow(lines)
        dna = do_not_apply(lines)
        self.assertIn(("Tools explained", QS.following["Tools explained"][1]), dna)
        for title in QS.branches["settings"].removes:
            self.assertIn((title, branch_reason("settings")), dna)
        out = "\n".join(lines)
        self.assertIn(
            "1. .github/agents/triage.agent.md, line 2: 'name: triage'\n"
            "   Declares its tools. The persona declares no tools: its tools field is missing or empty.\n"
            "   Rule PJ-010. Sources: OA2, GO2, GH2",
            out,
        )
        self.assertNotIn(LINTERS, lines)

    def test_every_branch_at_no(self):
        proj = self.project("standing")
        proc = self.render([release_review()], root=proj)
        self.assertEqual(proc.returncode, OK, proc.stdout + proc.stderr)
        lines = block(proc.stdout)
        self.assert_totals_follow(lines)
        self.assertIn("Branches: delegated no; harness none; settings none", lines)
        dna = do_not_apply(lines)
        want = []
        for title in TITLES:
            for key in ("delegated", "harness", "settings"):
                if title in QS.branches[key].removes:
                    want.append((title, branch_reason(key)))
                    break
            else:
                if title in QS.content_tests and title in BARE_ABSENT:
                    want.append((title, reason(title)))
        self.assertEqual(dna, want)

    def test_do_not_apply_none(self):
        proj = self.project("complete")
        proc = self.render([complete_review(consistent=1)], root=proj)
        self.assertEqual(proc.returncode, OK, proc.stdout + proc.stderr)
        lines = block(proc.stdout)
        self.assertIn("Do not apply: none.", lines)
        x, y, n = self.assert_totals_follow(lines)
        self.assertEqual((x, y, n), (QS.possible, QS.possible, 0))

    def test_render_refuses_unsound_record(self):
        entry = helper_review()
        entry["questions"].append({"question": "Bound parts agree with the prose", "score": 1})
        proc = self.render([entry])
        self.assertEqual(proc.returncode, REFUSED)
        self.assertEqual(proc.stdout, "")

    def test_set_aside_by_find(self):
        proc = self.render([set_aside_entry("CLAUDE.md")])
        self.assertEqual(proc.returncode, NO_SCORE, proc.stderr)
        self.assertEqual(block(proc.stdout), ["Set aside: CLAUDE.md (project instructions)", INSTRUCTIONS[0].upper() + INSTRUCTIONS[1:] + "."])

    def test_set_aside_by_the_reviewer(self):
        proj = self.project("standing")
        record = {"root": proj.as_posix(), "files": [{
            "path": "notes/release.md",
            "questions": [{"question": QS.root, "score": 0, "findings": [
                finding(1, "# Release notes guide", "It is a guide for people and defines no agent of its own.", "notes/release.md")]}],
        }]}
        path = self.tmp / "aside.json"
        path.write_text(json.dumps(record))
        proc = run("report.py", "render", path)
        self.assertEqual(proc.returncode, NO_SCORE, proc.stdout + proc.stderr)
        self.assertEqual(block(proc.stdout), [
            "Set aside: notes/release.md (persona)",
            f"{QS.root}. It is a guide for people and defines no agent of its own.",
            "notes/release.md, line 1: '# Release notes guide'",
            "Sources: GH4, GO2, AN6",
        ])

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
        entry = helper_review(path="<session text>", text=text)
        entry["branches"] = {"delegated": False, "harness": None, "settings": ["tools"]}
        removed = QS.branches["delegated"].removes + QS.branches["harness"].removes
        entry["questions"] = [q for q in entry["questions"] if q["question"] not in removed]
        # 'Declares its tools' does not apply, so 'Tools explained' takes its content test: the line naming a tool.
        for q in entry["questions"]:
            if q["question"] == "Tools explained":
                q["subject"] = {"file": "<session text>", "line": 4, "quote": "tools: Read, Grep, Edit"}
        proc = self.render([entry])
        self.assertEqual(proc.returncode, OK, proc.stdout + proc.stderr)
        lines = block(proc.stdout)
        self.assertIn("Review: <session text> (persona)", lines)
        dna = do_not_apply(lines)
        for title in QS.branches["harness"].removes:
            self.assertIn((title, branch_reason("harness")), dna)

    def test_two_digit_items_align(self):
        entry = helper_review()
        for q in entry["questions"]:
            if q["question"] == "Nothing said twice":
                q.update(score=0, findings=[finding(9, "Never edit files", "For the test.", HELPER)])
        lines = block(self.render([entry]).stdout)
        ten = next(i for i, l in enumerate(lines) if l.startswith("10. "))
        self.assertTrue(lines[ten + 1].startswith("    ") and not lines[ten + 1].startswith("     "), lines[ten + 1])

    def test_render_writes_no_file(self):
        before = make_fixtures.manifest(self.proj)
        run("report.py", "render", self.write([helper_review()]), cwd=self.proj)
        self.assertEqual(make_fixtures.manifest(self.proj), before)


class TestSpreadOverFilesT13(ReportCase):
    project_name = "si13"
    LIST_REASON = "personas.txt lists it with the persona"

    def test_listed_persona(self):
        main, scale = "personas/reviewer/reviewer.md", "personas/reviewer/scale.md"
        entry = review(
            main,
            {
                "Answers defined, edge cases included": {
                    "scale": "frequency", "subject": {"file": scale, "line": 3, "quote": "High: the change breaks a user's work."},
                    "places": [place(4, "Low: the change reads poorly and works.", False, scale, "Nothing says what to return when there is no finding.")],
                },
                "Tools explained": {
                    "scale": "quality", "point": QS.scales["quality"].top,
                    "subject": {"file": main, "line": 4, "quote": "tools: Read, Grep"},
                },
                "Shows an example": {"does_not_apply": reason("Shows an example")},
            },
            {"delegated": True, "harness": None, "settings": ["tools"]},
            removed=QS.branches["harness"].removes, default_place=(9, "Rate each finding on the scale in scale.md."),
            absent=(NO_COMMANDS, NO_ASKING, NO_CRITERION),
            loaded_with=[{"path": scale, "reason": self.LIST_REASON}, {"path": "personas/reviewer/examples.md", "reason": self.LIST_REASON}],
            left_out=[{"path": "personas/reviewer/missing.md", "reason": "personas.txt lists it, and it does not exist"}],
        )
        proc = self.render([entry])
        self.assertEqual(proc.returncode, OK, proc.stdout + proc.stderr)
        lines = block(proc.stdout)
        start = lines.index("Files reviewed:")
        self.assertEqual(lines[start: start + 6], [
            "Files reviewed:",
            f"  {main}: the persona's main file",
            f"  {scale}: {self.LIST_REASON}",
            f"  personas/reviewer/examples.md: {self.LIST_REASON}",
            "Files left out:",
            "  personas/reviewer/missing.md: personas.txt lists it, and it does not exist",
        ])
        self.assertIn("1. personas/reviewer/scale.md, line 4: 'Low: the change reads poorly and works.'", lines)


class TestNothingApplies(unittest.TestCase):
    def test_nothing_applies(self):
        report = import_report()
        p = report.Prepared("notes/x.md")
        p.header = {"kind": "persona", "harness": None, "delegated": False, "settings": [], "bound_parts": []}
        p.answers = [{"title": q.title, "section": q.section, "type": q.kind, "findings": [], "point": None,
                      "does_not_apply": "for the test"} for q in QS.questions]
        text, score = report.render_one(p)
        self.assertIsNone(score)
        self.assertEqual(text.splitlines()[0], NOTHING_APPLIES)


# The sample record's root reads 'set-by-the-tests': each test that reads the record sets root to its own fixture
# project before passing the record to report.py.
SAMPLE_RECORD = Path(__file__).resolve().parent / "evals" / "sample-record.json"


class TestSampleT4(ReportCase):
    """sample-review.md's three blocks are report.py's render of tests/evals/sample-record.json, line for line, so the
    example a reader sees is what the script prints."""

    def test_sample_renders_line_for_line(self):
        want = blocks(sample_text())
        record = json.loads(SAMPLE_RECORD.read_text(encoding="utf-8"))
        record["root"] = self.proj.as_posix()
        path = self.tmp / "sample-record.json"
        path.write_text(json.dumps(record), encoding="utf-8")
        proc = run("report.py", "render", "--summary", path)
        self.assertEqual(proc.returncode, OK, proc.stdout + proc.stderr)
        self.assertEqual(blocks(proc.stdout), want)


class TestSummaryT11(ReportCase):
    def entries(self):
        return [doc_writer_review(), set_aside_entry("CLAUDE.md"), helper_review(), triage_review(),
                set_aside_entry("AGENTS.md"), set_aside_entry(".claude/output-styles/terse.md"), set_aside_entry("README.md")]

    def test_summary_order(self):
        proc = self.render(self.entries(), "--summary")
        self.assertEqual(proc.returncode, OK, proc.stderr)
        first = block(proc.stdout)
        self.assertEqual(first[0], "Summary: 3 personas reviewed, lowest total first; 4 files set aside")
        rows = [l for l in first[1:] if l.strip()]
        shares = []
        for b in blocks(proc.stdout)[1:4]:
            m = TOTAL_RE.match(b[1])
            shares.append(Fraction(int(m.group(1)), int(m.group(2))))
        self.assertEqual(shares, sorted(shares))
        self.assertEqual([r.split()[0] for r in rows[3:]], [".claude/output-styles/terse.md", "AGENTS.md", "CLAUDE.md", "README.md"])
        self.assertRegex(rows[5], rf"^CLAUDE\.md +set aside +{re.escape(INSTRUCTIONS)}$")
        for row, b in zip(rows[:3], blocks(proc.stdout)[1:4]):
            m = TOTAL_RE.match(b[1])
            self.assertTrue(row.endswith(f"{m.group(1)} out of {m.group(2)}"), row)

    def test_summary_singular(self):
        proc = self.render([helper_review(), set_aside_entry("CLAUDE.md")], "--summary")
        self.assertEqual(block(proc.stdout)[0], "Summary: 1 persona reviewed, lowest total first; 1 file set aside")

    def test_all_set_aside(self):
        proc = self.render([set_aside_entry("CLAUDE.md"), set_aside_entry("README.md")], "--summary")
        self.assertEqual(proc.returncode, NO_SCORE, proc.stderr)


def with_resource_warnings(script, *args):
    """Run a Python script with the warning for a file left open shown; return the finished process."""
    import subprocess

    return subprocess.run([sys.executable, "-W", "always::ResourceWarning", str(script), *map(str, args)],
                          capture_output=True, text=True, timeout=60)


class TestFilesClosed(ReportCase):
    """report.py closes a record or a report it reads by path: with the warning for a file left open shown,
    'validate' on a record and 'verify' on a report print none. The control: a script that leaves a file open prints
    the warning, so the test can see one."""

    def test_record_and_report_closed(self):
        record = self.write([helper_review()])
        rendered = run("report.py", "render", record)
        self.assertEqual(rendered.returncode, OK, rendered.stderr)
        report = self.tmp / "report.md"
        report.write_text(rendered.stdout, encoding="utf-8")
        for args in (("validate", record), ("verify", report)):
            proc = with_resource_warnings(SCRIPTS / "report.py", *args)
            self.assertEqual(proc.returncode, OK, proc.stdout + proc.stderr)
            self.assertNotIn("ResourceWarning", proc.stderr, args[0])

    def test_control(self):
        leaky = self.tmp / "leaky.py"
        leaky.write_text("import sys\nopen(sys.argv[1], encoding='utf-8').read()\n", encoding="utf-8")
        proc = with_resource_warnings(leaky, leaky)
        self.assertIn("ResourceWarning", proc.stderr)


class TestVerifyT10(ReportCase):
    def rendered(self):
        proc = self.render([doc_writer_review(), helper_review(), triage_review(), set_aside_entry("CLAUDE.md")], "--summary")
        self.assertEqual(proc.returncode, OK, proc.stderr)
        return proc.stdout

    def helper_block(self, text):
        return next(b for b in blocks(text) if f"Review: {HELPER} (subagent, Claude Code)" in b)

    def verify(self, text, name="report.md"):
        path = self.tmp / name
        path.write_text(text, encoding="utf-8")
        proc = run("report.py", "verify", path)
        return proc.returncode, proc.stdout + proc.stderr

    def test_verify(self):
        code, out = self.verify(self.rendered())
        self.assertEqual(code, OK, out)

    def test_total_altered(self):
        text = self.rendered()
        total = self.helper_block(text)[1]
        x = int(TOTAL_RE.match(total).group(1))
        code, out = self.verify(text.replace(total, total.replace(f"Total: {x} ", f"Total: {x + 1} ", 1)))
        self.assertEqual(code, MISMATCH, out)
        self.assertIn(HELPER, out)
        self.assertIn(f"Total: {x + 1} ", out)

    def test_subtotal_altered(self):
        text = self.rendered()
        sub = self.helper_block(text)[2]
        px = int(re.search(r"(\d+) out of", sub).group(1))
        code, out = self.verify(text.replace(sub, sub.replace(f"{px} out of", f"{px + 1} out of", 1)))
        self.assertEqual(code, MISMATCH, out)
        self.assertIn(f"{PERSONA}: {px + 1} out of", out)

    def test_equal_weight_total_altered(self):
        text = self.rendered()
        line = next(l for l in self.helper_block(text) if l.startswith("At equal weights: "))
        ex = int(re.search(r"(\d+) out of", line).group(1))
        code, out = self.verify(text.replace(line, line.replace(f"{ex} out of", f"{ex + 1} out of", 1)))
        self.assertEqual(code, MISMATCH, out)
        self.assertIn("At equal weights", out)

    def test_do_not_apply_altered(self):
        text = self.rendered()
        start = text.index(f"Review: {HELPER}")
        entry = f"  Commands given exactly: {reason('Commands given exactly')}\n"
        at = text.index(entry, start)
        code, out = self.verify(text[:at] + text[at + len(entry):])
        self.assertEqual(code, MISMATCH, out)
        self.assertIn("Do not apply", out)

    def flip(self, text, title, weight):
        start = text.index(f"Review: {HELPER}")
        m = re.search(rf"(?m)^{re.escape(title)} +yes {weight}$", text[start:])
        return text[: start + m.start()] + m.group(0)[: -len(f"yes {weight}")] + "no  0" + text[start + m.end():]

    def test_check_flipped(self):
        text = self.rendered()
        x = int(TOTAL_RE.match(self.helper_block(text)[1]).group(1))
        code, out = self.verify(self.flip(text, "Pointers carry their triggers", 1))
        self.assertEqual(code, MISMATCH, out)
        self.assertIn(f"{x - 1} out of", out)

    def test_weighted_check_flipped(self):
        """A weighted flip moves the total by the check's weight and the equal-weight total by 1."""
        text = self.rendered()
        block_lines = self.helper_block(text)
        x = int(TOTAL_RE.match(block_lines[1]).group(1))
        ex = int(re.search(r"At equal weights: (\d+)", "\n".join(block_lines)).group(1))
        w = QS.by_title["Consistent with itself"].weight
        code, out = self.verify(self.flip(text, "Consistent with itself", w))
        self.assertEqual(code, MISMATCH, out)
        self.assertIn(f"{x - w} out of", out)
        self.assertIn(f"{ex - 1} out of", out)

    def test_derived_case(self):
        """Every question at its top except 'Consistent with itself' at 0: M − w out of M, and (M − E) − 1 out of M − E
        at equal weights, where w is the check's weight and E the extra points the weights add."""
        proj = self.project("complete")
        proc = self.render([complete_review(consistent=0)], root=proj)
        self.assertEqual(proc.returncode, OK, proc.stdout + proc.stderr)
        lines = block(proc.stdout)
        M = QS.possible
        w = QS.by_title["Consistent with itself"].weight
        E = sum(q.weight - 1 for q in QS.questions if q.kind != "rating")
        self.assertEqual(TOTAL_RE.match(lines[1]).groups(), (str(M - w), str(M), str(M), "0"))
        self.assertIn(f"At equal weights: {M - E - 1} out of {M - E}.", lines)
        self.assertEqual(lines[0], "★★★★★ (5)" if import_report().stars(M - w, M) == 5 else lines[0])
        code, out = self.verify(proc.stdout)
        self.assertEqual(code, OK, out)

    def test_verify_unparsable(self):
        junk = self.tmp / "junk.md"
        junk.write_text("# Not a report\n", encoding="utf-8")
        self.assertEqual(run("report.py", "verify", junk).returncode, REFUSED)

    def test_verify_on_the_sample(self):
        sample_text()
        ok = run("report.py", "verify", REFERENCES / "sample-review.md")
        self.assertEqual(ok.returncode, OK, ok.stdout + ok.stderr)


class TestFieldChecksOnTheMainFile(ReportCase):
    """A persona spread over files: a check on a front-matter field, such as 'Declares its tools', is scored from the persona's main file
    only. A file the persona loads holds no front matter of its own, so its missing tools field says nothing about the
    persona. The case: PJ-008 used to score a loaded file 0, quoting its '# Sections' heading as the line with no tools
    field."""

    LOADED = ".claude/agents/helper/sections.md"
    LOADED_TEXT = "# Sections\n\nKeep each section of a report under ten lines.\n"

    def loaded(self, entry, path=None):
        target = self.proj / (path or self.LOADED)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(self.LOADED_TEXT, encoding="utf-8")
        entry["loaded_with"] = [{"path": path or self.LOADED, "reason": "the persona's text tells the agent to read it"}]
        return entry

    def test_tools_declared_on_the_main_file(self):
        """helper.md declares 'tools: Read, Grep, Edit' on line 4; the loaded file has no tools field, and the check
        still scores 1 with no finding on the loaded file."""
        entry = self.loaded(helper_review())
        entry["questions"].append({"question": "Declares its tools", "score": 1})
        proc = run("report.py", "validate", self.write([entry]))
        self.assertEqual(proc.returncode, OK, proc.stdout + proc.stderr)
        proc = self.render([self.loaded(helper_review())])
        self.assertEqual(proc.returncode, OK, proc.stdout + proc.stderr)
        out = proc.stdout
        self.assertRegex(out, rf"(?m)^Declares its tools +yes {QS.by_title['Declares its tools'].weight}$")
        self.assertNotIn(f"{self.LOADED}, line 1: '# Sections'", out)
        self.assertNotIn("PJ-008", out)

    def test_control_tools_missing_on_the_main_file(self):
        """Control: triage.agent.md declares no tools, so 'Declares its tools' still scores 0 from PJ-010, quoting the
        main file's line 2, with a loaded file beside it."""
        loaded = ".github/agents/triage/sections.md"
        proc = self.render([self.loaded(triage_review(), loaded)])
        self.assertEqual(proc.returncode, OK, proc.stdout + proc.stderr)
        out = proc.stdout
        self.assertRegex(out, r"(?m)^Declares its tools +no  0$")
        self.assertIn("1. .github/agents/triage.agent.md, line 2: 'name: triage'", out)

    def test_no_field_finding_on_the_loaded_file(self):
        """With the persona's tools missing, the finding quotes the main file once and never the loaded file."""
        loaded = ".github/agents/triage/sections.md"
        out = self.render([self.loaded(triage_review(), loaded)]).stdout
        self.assertNotIn(f"{loaded}, line 1:", out)
        self.assertEqual(out.count("Rule PJ-010."), 1, out)


class TestChecksReachLoadedFiles(ReportCase):
    """reviewer.md's step 'Run the script checks' runs check.py on every file 'Settle the files each persona loads'
    settled for a persona, so the checks reach the files it loads. The case: helper.md tells its agent to read a
    second file in every review, and that second file holds a placeholder. check.py, run on both files, scores 'No placeholders' 0 on the second file, and report.py scores the
    persona's check 0. The control: the same persona with a clean second file scores 1."""

    LOADED = ".claude/agents/helper/scale.md"
    POINTER = f"Read `{LOADED}` in full at the start of every review."
    PLANTED = "# Scale\n\nTODO: define high, medium and low.\n"
    CLEAN = "# Scale\n\nHigh means the change breaks the build.\n"
    TITLE = "No placeholders"

    def persona(self, loaded_text):
        """helper.md with the pointer added after its last line, and the file it points to; return the record entry."""
        main = self.proj / HELPER
        text = main.read_text(encoding="utf-8")
        main.write_text(text + ("" if text.endswith("\n") else "\n") + self.POINTER + "\n", encoding="utf-8")
        loaded = self.proj / self.LOADED
        loaded.parent.mkdir(parents=True, exist_ok=True)
        loaded.write_text(loaded_text, encoding="utf-8")
        entry = helper_review()
        entry["loaded_with"] = [{"path": self.LOADED, "reason": "the persona's text tells the agent to read it in every review"}]
        return entry

    def placeholder_rows(self):
        """check.py on both files, as 'Run the script checks' says: the 'No placeholders' rows, by file."""
        # find.py lists the second file as one the persona may load, so 'Settle the files each persona loads' settles it.
        found = run("find.py", HELPER, "--format", "json", cwd=self.proj)
        self.assertEqual(found.returncode, OK, found.stderr)
        self.assertEqual([c["path"] for c in json.loads(found.stdout)[0]["candidates"]], [self.LOADED])
        proc = run("check.py", HELPER, self.LOADED, "--format", "json", cwd=self.proj)
        # Exit 1 either way: helper.md's own 'Never edit files' beside 'tools: Read, Grep, Edit' scores PJ-003 0.
        self.assertEqual(proc.returncode, MISMATCH, proc.stdout + proc.stderr)
        rows = [r for r in json.loads(proc.stdout) if r["question"] == self.TITLE]
        self.assertEqual(sorted(r["path"] for r in rows), sorted([HELPER, self.LOADED]))
        return {r["path"]: r for r in rows}

    def test_placeholder_in_the_loaded_file_reaches_the_score(self):
        entry = self.persona(self.PLANTED)
        rows = self.placeholder_rows()
        self.assertEqual(rows[HELPER]["score"], 1)
        self.assertEqual((rows[self.LOADED]["score"], rows[self.LOADED]["line"]), (0, 3))
        proc = self.render([entry])
        self.assertEqual(proc.returncode, OK, proc.stdout + proc.stderr)
        self.assertRegex(proc.stdout, rf"(?m)^{self.TITLE} +no  0$")
        self.assertIn(f"{self.LOADED}, line 3: 'TODO: define high, medium and low.'", proc.stdout)

    def test_control_clean_loaded_file(self):
        entry = self.persona(self.CLEAN)
        rows = self.placeholder_rows()
        self.assertEqual((rows[HELPER]["score"], rows[self.LOADED]["score"]), (1, 1))
        proc = self.render([entry])
        self.assertEqual(proc.returncode, OK, proc.stdout + proc.stderr)
        self.assertRegex(proc.stdout, rf"(?m)^{self.TITLE} +yes {QS.by_title[self.TITLE].weight}$")
        self.assertNotIn(f"{self.LOADED}, line", proc.stdout)


class TestFitRequiredSI3(ReportCase):
    """Every persona report carries a fit entry, a finding or a statement that nothing was found; validate refuses
    a persona entry without one and says which to add."""

    def test_persona_with_no_fit_refused(self):
        entry = helper_review()
        entry.pop("fit", None)
        path = self.write([entry])
        proc = run("report.py", "validate", path)
        self.assertEqual(proc.returncode, REFUSED, proc.stdout + proc.stderr)
        out = proc.stdout
        self.assertIn(f"{HELPER}, fit: missing", out)
        self.assertIn("a finding", out)
        self.assertIn("a statement that nothing was found", out)
        render = run("report.py", "render", path)
        self.assertEqual(render.returncode, REFUSED)
        self.assertEqual(render.stdout, "")

    def test_control_persona_with_a_fit_statement(self):
        entry = helper_review(fit={"statement": "Nothing was found on how its remit sits with the nearby files."})
        proc = run("report.py", "validate", self.write([entry]))
        self.assertEqual(proc.returncode, OK, proc.stdout + proc.stderr)

    def test_control_files_set_aside_need_no_fit(self):
        proc = run("report.py", "validate", self.write([set_aside_entry("CLAUDE.md")]))
        self.assertEqual(proc.returncode, OK, proc.stdout + proc.stderr)

    def test_sample_record_has_a_fit_entry(self):
        record = json.loads(SAMPLE_RECORD.read_text(encoding="utf-8"))
        record["root"] = self.proj.as_posix()
        path = self.tmp / "sample-record.json"
        path.write_text(json.dumps(record), encoding="utf-8")
        proc = run("report.py", "validate", path)
        self.assertEqual(proc.returncode, OK, proc.stdout + proc.stderr)


if __name__ == "__main__":
    unittest.main()
