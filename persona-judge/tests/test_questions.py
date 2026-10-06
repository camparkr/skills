"""questions.py reads the review questions at run time under the markup contract its docstring sets out: the parts in
references/questions/, joined in the order questions.py's list of parts gives, with one blank line between them. No script holds a question, a count of
questions or a count of points.

(1) a pinned copy of an earlier single file reads as the contract says; (2) the prose counts equal the counts
questions.py derives; (3) a copy that breaks the contract once is refused with exit 2, naming the part file, its line
and what was expected; (4) a copy with a question added in each section and a weight changed is scored by report.py
with no script changed.
"""

import hashlib
import json
import re
import shutil
import subprocess
import sys
import unittest
from pathlib import Path

from support import QUESTIONS, ROOT, SCRIPTS, ScratchCase, make_fixtures, part_holding, question_parts, questions_text

# A fixture copy of an earlier version of the questions, from when they were one file (committed at 146a82a), pinned
# by its hash, so the tests that check the contract's reading word for word hold while the live parts change.
# questions.py still reads a single file as it stands. Only fixtures pin a known file; every other test reads its
# counts from the live parts.
FIXTURE_MD = make_fixtures.FILES / "review-questions-pinned-copy.fixture"
FIXTURE_SHA256 = "e229cb727fef6a27eeda4ad1514b833d6ce3d64df10dc57cd9530e1e24798b3a"

# The prose counts test (2) compares with the derived ones: each pattern held here, in the test, never in a script.
# A count written in the prose: digits, or number words, hyphenated or not, up to the hundreds.
WORD = r"[A-Za-z]+(?:-[A-Za-z]+)?"
NUMBER = rf"(\d+|{WORD}(?: hundred(?: and {WORD})?)?)"
# Every pattern reads its number through NUMBER, so a count written in words is found as one in digits. The counts of
# questions in each section were stated only in the single file's contents list, which the parts do not keep, so no
# pattern reads them.
PROSE_COUNTS = {
    "questions": rf"All {NUMBER} questions are asked",
    "possible": rf"{NUMBER} points are possible:",
    "persona points": rf"points are possible: {NUMBER} in the persona section",
    "writing points": rf"and {NUMBER} in instruction writing",
}


# A rating as the parts now lay it out: the bold title alone on its line, then the '*Scale model:*' line, which may
# carry a further sentence. The tests that plant a fault in a rating start from this one.
TOOLS_RATING = "**Tools explained** \n*Scale model:* Frequency. "


def load_module():
    sys.path.insert(0, str(SCRIPTS))
    import questions

    return questions


def run_questions(path, *extra):
    return subprocess.run(
        [sys.executable, str(SCRIPTS / "questions.py"), str(path), *extra], capture_output=True, text=True, timeout=60
    )


UNITS = ("zero one two three four five six seven eight nine ten eleven twelve thirteen fourteen fifteen sixteen "
         "seventeen eighteen nineteen").split()
TENS = "twenty thirty forty fifty sixty seventy eighty ninety".split()


def word_number(word):
    """A count the prose writes as digits or in words, such as '35', 'Ten', 'twenty-one' or 'one hundred and eleven'."""
    word = word.lower().strip()
    if word.isdigit():
        return int(word)
    current = 0
    for part in word.replace("-", " ").split():
        if part == "and":
            continue
        if part == "hundred":
            current = (current or 1) * 100
        elif part in UNITS:
            current += UNITS.index(part)
        elif part in TENS:
            current += 20 + 10 * TENS.index(part)
        else:
            raise ValueError(f"'{word}' is not a number the test can read")
    return current


def number_words(n):
    """n in words, as the prose might write it: 'thirty-five', 'one hundred and eleven'."""
    if n < 20:
        return UNITS[n]
    if n < 100:
        tens, unit = divmod(n, 10)
        return TENS[tens - 2] + (f"-{UNITS[unit]}" if unit else "")
    hundreds, rest = divmod(n, 100)
    return f"{UNITS[hundreds]} hundred" + (f" and {number_words(rest)}" if rest else "")


def raw(pattern):
    """A pattern for the file as written, its spaces matching any run of spaces and line breaks."""
    return pattern.replace(" ", r"\s+")


def stated_counts(text):
    """The counts the file's prose states, read with the patterns above and the word counts below."""
    folded = " ".join(text.split())
    out = {}
    for name, pattern in PROSE_COUNTS.items():
        m = re.search(pattern, folded)
        out[name] = word_number(m.group(1)) if m else None
    m = re.search(NUMBER + r" checks count " + NUMBER + r" points", folded)
    out["weighted checks"] = word_number(m.group(1)) if m else None
    out["weighted points"] = word_number(m.group(2)) if m else None
    m = re.search(NUMBER + r" ratings and " + NUMBER + r" checks? apply only where the file holds", folded)
    out["content-test ratings"] = word_number(m.group(1)) if m else None
    out["content-test checks"] = word_number(m.group(2)) if m else None
    # The rating sections no longer count their ratings by scale: the persona ratings name the scales they use, and
    # each instruction-writing rating names its own scale model.
    m = re.search(NUMBER + r" scale-rating models: (\w+) and (\w+)\.", folded)
    out["persona rating scales"] = (word_number(m.group(1)), sorted({m.group(2), m.group(3)})) if m else None
    return out


def derived_counts(qs):
    persona, writing = qs.sections
    in_section = lambda s: [q for q in qs.questions if q.section == s]  # noqa: E731
    weighted = [q for q in qs.questions if q.kind != "rating" and q.weight > 1]
    content = [qs.by_title[t] for t in qs.content_tests]
    return {
        "questions": len(qs.questions),
        "possible": qs.possible,
        "persona points": qs.section_points(persona),
        "writing points": qs.section_points(writing),
        "weighted checks": len(weighted),
        "weighted points": len({q.weight for q in weighted}) == 1 and weighted[0].weight or None,
        "content-test ratings": sum(1 for q in content if q.kind == "rating"),
        "content-test checks": sum(1 for q in content if q.kind != "rating"),
        "persona rating scales": (len({q.scale for q in in_section(persona) if q.kind == "rating"}),
                                  sorted({q.scale for q in in_section(persona) if q.kind == "rating"})),
    }


class TestReadsTheFile(unittest.TestCase):
    """(1) An earlier version of the file, kept as a fixture copy pinned by its hash, reads as the contract says, word
    for word."""

    def setUp(self):
        self.assertEqual(hashlib.sha256(FIXTURE_MD.read_bytes()).hexdigest(), FIXTURE_SHA256, "the fixture copy has moved")
        self.q = load_module()
        self.qs = self.q.load(FIXTURE_MD)

    def test_sections_and_root(self):
        self.assertEqual(self.qs.sections, ["Persona", "Instruction writing"])
        self.assertEqual(self.qs.root, "A dedicated persona")
        self.assertEqual(self.qs.questions[0].title, "A dedicated persona")

    def test_kinds_and_weights(self):
        weights = {q.title: q.weight for q in self.qs.questions if q.kind != "rating" and q.weight != 1}
        self.assertEqual(
            weights,
            {"Bound parts agree with the prose": 3, "Enforceable rules enforced": 3, "Consistent with itself": 3},
        )
        self.assertEqual(self.qs.by_title["Permissions fit the job"].kind, "reading")
        self.assertEqual(self.qs.by_title["Needs no context it is not given"].kind, "reading")
        self.assertEqual(self.qs.by_title["Declares its tools"].kind, "script")
        self.assertEqual(self.qs.by_title["An identity that does the work"].scale, "quality")
        self.assertEqual(self.qs.by_title["Tools explained"].scale, "frequency")
        for q in self.qs.questions:
            self.assertGreater(q.line, 0, q.title)

    def test_scales(self):
        freq, quality = self.qs.scales["frequency"], self.qs.scales["quality"]
        self.assertEqual((freq.top, quality.top), (6, 6))
        self.assertEqual(freq.words[3], "about half the time")
        self.assertEqual(quality.words[0], "very poor")
        self.assertIsNone(quality.bands)
        point = freq.point
        self.assertEqual([point(5, 5), point(9, 10), point(4, 5), point(3, 5), point(2, 5), point(1, 5), point(19, 100), point(0, 5)],
                         [6, 5, 4, 3, 3, 2, 1, 0])

    def test_branches_and_tables(self):
        b = self.qs.branches
        self.assertEqual(list(b), ["delegated", "harness", "settings"])
        self.assertEqual(b["delegated"].removes, ["One job", "States its output", "The description says when to choose it"])
        self.assertEqual(b["delegated"].reason, "not delegated")
        self.assertEqual(b["harness"].removes, ["Leaves the harness's work to the harness", "Declares its tools"])
        self.assertEqual(b["harness"].reason, "path names no harness")
        self.assertEqual(b["settings"].removes, ["Bound parts agree with the prose", "Permissions fit the job"])
        self.assertEqual(b["settings"].reason, "holds no settings")
        self.assertEqual(self.qs.settings_fields, ["tools", "disallowedTools", "permissionMode", "sandbox_mode", "hooks", "mcpServers"])
        self.assertEqual(
            {t: r for t, (_, r) in self.qs.content_tests.items()},
            {
                "Tools explained": "no tool named",
                "Commands given exactly": "no command to run",
                "Directions for when nobody answers": "no instruction to ask, wait or confirm",
                "Answers defined, edge cases included": "no set of answers, scale or choice",
                "Its own criteria met": "no criterion set for the work",
                "Shows an example": "no instruction to give output in a particular form",
            },
        )
        self.assertEqual(self.qs.following, {"Tools explained": ("Declares its tools", "'Declares its tools' scored 0")})
        self.assertEqual(self.qs.exceptions, [("Declares its tools", "Codex", "Codex has no tools field", "OA2")])

    def test_weights_table_names_the_weighted_checks(self):
        """The weights table is not read for scoring; it must name the same checks as the weight marks."""
        weighted = {q.title for q in self.qs.questions if q.kind != "rating" and q.weight > 1}
        self.assertEqual(set(self.qs.weights_table), weighted)

    def test_points_are_derived(self):
        """The points possible are the sum of every check's weight and every rating scale's top point."""
        total = sum(q.weight if q.kind != "rating" else self.qs.scales[q.scale].top for q in self.qs.questions)
        self.assertEqual(self.qs.possible, total)
        self.assertEqual(sum(self.qs.section_points(s) for s in self.qs.sections), total)

    def test_cli(self):
        proc = run_questions(FIXTURE_MD, "--format", "json")
        self.assertEqual(proc.returncode, 0, proc.stderr)
        data = json.loads(proc.stdout)
        self.assertEqual(len(data["questions"]), len(self.qs.questions))
        self.assertEqual(data["possible"], self.qs.possible)


class TestLiveFile(unittest.TestCase):
    """The live review questions meet the contract, and every count the tests use comes from them."""

    def setUp(self):
        self.q = load_module()
        self.qs = self.q.load(QUESTIONS)

    def test_reads_the_parts_joined(self):
        """questions.py reads the parts as the test joins them, and places each line in its part file."""
        text, places = self.q.read_text(QUESTIONS)
        self.assertEqual(text, questions_text())
        self.assertEqual(len(places), len(text.splitlines()))
        parts = {p.name: p.read_text(encoding="utf-8").splitlines() for p in question_parts()}
        for line, (name, n) in zip(text.splitlines(), places):
            if line:
                self.assertEqual(parts[name][n - 1], line, (name, n))
        for q in self.qs.questions:
            self.assertTrue(parts[q.file][q.line - 1].startswith(f"**{q.title}**"), (q.file, q.line))

    def test_meets_the_contract(self):
        proc = run_questions(QUESTIONS, "--format", "json")
        self.assertEqual(proc.returncode, 0, proc.stderr)
        data = json.loads(proc.stdout)
        self.assertEqual(len(data["questions"]), len(self.qs.questions))
        self.assertEqual(data["possible"], self.qs.possible)

    def test_root_and_sections(self):
        self.assertIn(self.qs.questions[0].kind, ("script", "reading"))
        for section in self.qs.sections:
            self.assertTrue(any(q.section == section for q in self.qs.questions), section)

    def test_points_are_derived(self):
        total = sum(q.weight if q.kind != "rating" else self.qs.scales[q.scale].top for q in self.qs.questions)
        self.assertEqual(self.qs.possible, total)
        self.assertEqual(sum(self.qs.section_points(s) for s in self.qs.sections), total)

    def test_weights_table_names_the_weighted_checks(self):
        weighted = {q.title for q in self.qs.questions if q.kind != "rating" and q.weight > 1}
        self.assertEqual(set(self.qs.weights_table), weighted)

    def test_every_table_title_is_a_question(self):
        titles = set(self.qs.by_title)
        named = [t for b in self.qs.branches.values() for t in b.removes] + list(self.qs.content_tests)
        named += list(self.qs.following) + [c for c, _ in self.qs.following.values()] + [e[0] for e in self.qs.exceptions]
        self.assertEqual([t for t in named if t not in titles], [])


class TestNumberWords(unittest.TestCase):
    def test_words_and_digits(self):
        self.assertEqual([word_number(w) for w in ("35", "One", "seven", "Ten", "twelve", "twenty-one", "Thirty five",
                                                   "one hundred and eleven")],
                         [35, 1, 7, 10, 12, 21, 35, 111])
        self.assertEqual([number_words(n) for n in (7, 35, 60, 111)], ["seven", "thirty-five", "sixty", "one hundred and eleven"])

    def test_control(self):
        with self.assertRaises(ValueError):
            word_number("several")


class TestProseCounts(ScratchCase):
    """(2) Every count the prose states equals the count questions.py derives."""

    def test_prose_counts(self):
        q = load_module()
        text = questions_text()
        stated, derived = stated_counts(text), derived_counts(q.load(QUESTIONS))
        for name, value in stated.items():
            self.assertIsNotNone(value, f"the prose count '{name}' was not found")
        self.assertEqual(stated, derived)

    def test_control(self):
        """A copy with one count changed fails, naming it. The count changed is the one the file states, read with the
        test's own pattern, so the control holds whatever the number of questions."""
        q = load_module()
        text = questions_text()
        derived = derived_counts(q.load(QUESTIONS))
        m = re.search(raw(PROSE_COUNTS["questions"]), text)
        self.assertIsNotNone(m, "the stated count of questions was not found")
        changed = text[: m.start(1)] + str(derived["questions"] + 1) + text[m.end(1):]
        self.assertNotEqual(changed, text)
        stated = stated_counts(changed)
        wrong = [name for name in stated if stated[name] != derived[name]]
        self.assertEqual(wrong, ["questions"])

    def test_counts_written_in_words(self):
        """A copy with every count in PROSE_COUNTS written in words is read the same. The copy may equal the file, when
        the file already writes its counts in words."""
        q = load_module()
        text = questions_text()
        derived = derived_counts(q.load(QUESTIONS))
        words = text
        for name, pattern in PROSE_COUNTS.items():
            m = re.search(raw(pattern), words)
            self.assertIsNotNone(m, name)
            words = words[: m.start(1)] + number_words(word_number(m.group(1))) + words[m.end(1):]
        self.assertEqual(stated_counts(words), derived)


class TestContractRefused(ScratchCase):
    """(3) Each copy breaks the contract once and is refused with exit 2, naming the part file, its line and what was
    expected."""

    def broken(self, old, new, count=1):
        """Plant the fault in the one part holding old, in a scratch copy of the parts; return the error and where the
        fault is, as '<part>, line <n>'."""
        folder = self.tmp / "questions"
        shutil.copytree(QUESTIONS, folder)
        path = part_holding(folder, old)
        text = path.read_text(encoding="utf-8")
        path.write_text(text.replace(old, new, count), encoding="utf-8")
        where = f"{path.name}, line {text[: text.index(old)].count(chr(10)) + 1}"
        proc = run_questions(folder)
        self.assertEqual(proc.returncode, 2, proc.stdout + proc.stderr)
        self.assertRegex(proc.stderr, r"\.md, line \d+: ")
        self.assertIn("expected", proc.stderr)
        return proc.stderr, where

    def test_rating_without_scale_mark(self):
        """A rating whose title has no '*Scale model:*' line under it is refused at the title's line."""
        err, where = self.broken(TOOLS_RATING, "**Tools explained** \n")
        self.assertIn(f"{where}:", err)
        self.assertIn("*Scale model:*", err)

    def test_weight_in_words(self):
        err, where = self.broken("(*reading*, weight 3). No two statements", "(*reading*, weight three). No two statements")
        self.assertIn(f"{where}:", err)

    def test_branch_table_without_reason(self):
        old = "| Key | Branch | How it is read | When the answer is no, these do not apply | Reason printed |\n|---|---|---|---|---|"
        err, where = self.broken(old, "| Key | Branch | How it is read | When the answer is no, these do not apply |\n|---|---|---|---|")
        self.assertIn(f"{where}:", err)
        self.assertIn("Reason printed", err)

    def test_table_naming_an_unknown_title(self):
        err, where = self.broken("| Commands given exactly | a command", "| Commands given precisely | a command")
        self.assertIn(f"{where}:", err)
        self.assertIn("Commands given precisely", err)

    def test_duplicate_title(self):
        err, _ = self.broken("**Nothing said twice** (*reading*).", "**Leaves known things unsaid** (*reading*).")
        self.assertIn("Leaves known things unsaid", err)

    def test_band_in_no_listed_form(self):
        err, where = self.broken("| 4 | usually | over 60%, up to 80% |", "| 4 | usually | roughly two thirds |")
        self.assertIn(f"{where}:", err)

    def test_scale_never_defined(self):
        """A '*Scale model:*' line naming no scale defined under '### <Name> scale' is refused at the rating's line."""
        err, where = self.broken("**Reasons given**\n*Scale model:* Frequency.", "**Reasons given**\n*Scale model:* Agreement.")
        self.assertIn(f"{where}:", err)
        self.assertIn("agreement", err)

    def test_unknown_harness(self):
        """A harness-exception row naming a harness find.py does not name is refused: a misspelt
        harness matches no file, so the exception would never apply."""
        err, where = self.broken("| Declares its tools | Codex | Codex has no tools field | OA2 |",
                                "| Declares its tools | Codexx | Codex has no tools field | OA2 |")
        self.assertIn(f"{where}:", err)
        self.assertIn("Codexx", err)

    def test_empty_reason(self):
        """An empty 'Reason printed' cell is refused, since the report must say why a question does not apply."""
        err, where = self.broken("| Commands given exactly | a command the file tells the agent to run | no command to run |",
                                "| Commands given exactly | a command the file tells the agent to run |  |")
        self.assertIn(f"{where}:", err)
        self.assertIn("Reason printed", err)

    def test_empty_branch_reason(self):
        err, where = self.broken("| One job; States its output; The description says when to choose it | not delegated |",
                                "| One job; States its output; The description says when to choose it |  |")
        self.assertIn(f"{where}:", err)

    def test_report_refuses_too(self):
        """report.py and check.py stop with exit 2 when the file they read breaks the contract."""
        skill = self.tmp / "skill"
        shutil.copytree(ROOT / "skill", skill, ignore=shutil.ignore_patterns("__pycache__"))
        path = part_holding(skill / "references" / "questions", TOOLS_RATING)
        path.write_text(path.read_text(encoding="utf-8").replace(TOOLS_RATING, "**Tools explained** \n"), encoding="utf-8")
        record = self.tmp / "r.json"
        record.write_text('{"files": [{"path": "x.md"}]}', encoding="utf-8")
        for args in (["report.py", "validate", str(record)], ["check.py", "-"]):
            proc = subprocess.run(
                [sys.executable, str(skill / "scripts" / args[0]), *args[1:]], input="Read the notes.\n",
                capture_output=True, text=True, cwd=self.tmp,
            )
            self.assertEqual(proc.returncode, 2, args[0] + proc.stdout + proc.stderr)
            self.assertIn(f"{path.name}, line", proc.stderr, args[0])


class TestRatingLayout(ScratchCase):
    """A rating is a bold title on its own line, then a '*Scale model:*' line naming a scale; any further sentence on
    that line stays part of the question, and the fields and a 'Sources:' paragraph below it are not questions."""

    def scale_model_lines(self, folder):
        """Each '*Scale model:*' line in the parts at folder: (part, title above it, its line, the scale it names)."""
        out = []
        for part in question_parts(folder):
            lines = part.read_text(encoding="utf-8").splitlines()
            for n, line in enumerate(lines):
                m = re.match(r"^\*Scale model:\* (\w+)\.", line)
                if m:
                    title = re.match(r"^\*\*([^*]+)\*\*\s*$", lines[n - 1])
                    self.assertIsNotNone(title, f"{part.name}, line {n}: no bold title above the scale model line")
                    out.append((part.name, title.group(1), n, m.group(1).lower()))
        return out

    def test_every_scale_model_line_is_read(self):
        """Every rating in the live parts is read with the scale its '*Scale model:*' line names, at its title's line,
        including those whose line carries 'Follows ...' or 'Applies to ...'; and every rating has such a line."""
        q = load_module()
        qs = q.load(QUESTIONS)
        found = self.scale_model_lines(QUESTIONS)
        self.assertTrue(found, "no *Scale model:* line in the parts")
        ratings = [x for x in qs.questions if x.kind == "rating"]
        self.assertEqual(sorted((r.file, r.title, r.line, r.scale) for r in ratings), sorted(found))

    def test_both_layouts_read_alike(self):
        """A rating rewritten in the earlier layout, '**Title** (*scale*).', is read as the same question, so the
        pinned copy of the single file still reads. The control: the same rewrite naming the other scale reads
        differently."""
        q = load_module()
        live = q.load(QUESTIONS)
        folder = self.tmp / "questions"
        shutil.copytree(QUESTIONS, folder)
        part = part_holding(folder, TOOLS_RATING)
        text = part.read_text(encoding="utf-8")
        part.write_text(text.replace(TOOLS_RATING, "**Tools explained** (*frequency*). "), encoding="utf-8")
        # The rewrite joins two lines, so the lines of the questions after it move; the line is left out.
        shape = lambda qs: [(x.title, x.section, x.kind, x.scale, x.weight, x.file) for x in qs.questions]  # noqa: E731
        self.assertEqual(shape(q.load(folder)), shape(live))
        part.write_text(text.replace(TOOLS_RATING, "**Tools explained** (*quality*). "), encoding="utf-8")
        self.assertNotEqual(shape(q.load(folder)), shape(live))

    def test_fields_and_sources_are_not_questions(self):
        """A field line or a 'Sources:' paragraph is never read as a question: the questions are exactly the bold
        titles under '### Checks' and '### Ratings'. The control: a field line made bold is read as a question,
        and so refused."""
        q = load_module()
        qs = q.load(QUESTIONS)
        text = questions_text()
        sections = re.findall(r"(?ms)^## [^\n]* questions\s*$(.*?)(?=^## |\Z)", text)
        self.assertEqual(len(sections), len(qs.sections))
        self.assertEqual(len(qs.questions), sum(len(re.findall(r"(?m)^\*\*[^*]+\*\*", s)) for s in sections))
        self.assertIn("\nSources: ", text)
        folder = self.tmp / "questions"
        shutil.copytree(QUESTIONS, folder)
        part = part_holding(folder, "**Reasons given**\n*Scale model:* Frequency.\n")
        planted = part.read_text(encoding="utf-8").replace(
            "**Reasons given**\n*Scale model:* Frequency.\n", "**Reasons given**\n*Scale model:* Frequency.\n\n**Places**\n")
        part.write_text(planted, encoding="utf-8")
        proc = run_questions(folder)
        self.assertEqual(proc.returncode, 2, proc.stdout + proc.stderr)
        self.assertIn("Places", proc.stderr)


class TestChangeNeedsNoScriptChange(ScratchCase):
    """(4) One question added in each section and one weight changed; report.py scores and renders a record for the
    changed file, its points possible and section points following the change, and no script changes."""

    ADD_CHECK = (
        "**Boundaries in three tiers** (*reading*).",
        "**Names its owner** (*reading*). The file names who maintains it. *Scores 0 on:* a file with no owner.\n\n"
        "**Boundaries in three tiers** (*reading*).",
    )
    ADD_RATING = (
        "**Each instruction stands alone**\n",
        "**Short sentences**\n*Scale model:* Frequency.\n*Places:* Each sentence.\n*Meets it:* It is under 30 words.\n\n"
        "**Each instruction stands alone**\n",
    )
    WEIGHT = ("**Nothing said twice** (*reading*).", "**Nothing said twice** (*reading*, weight 2).")

    def test_added_questions_and_weight(self):
        q = load_module()
        before = q.load(QUESTIONS)
        skill = self.tmp / "skill"
        shutil.copytree(ROOT / "skill", skill, ignore=shutil.ignore_patterns("__pycache__"))
        hashes = {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted((ROOT / "skill" / "scripts").glob("*.py"))}
        rq = skill / "references" / "questions"
        for old, new in (self.ADD_CHECK, self.ADD_RATING, self.WEIGHT):
            part = part_holding(rq, old)
            text = part.read_text(encoding="utf-8")
            self.assertEqual(text.count(old), 1, old)
            part.write_text(text.replace(old, new), encoding="utf-8")
        bib = skill / "references" / "grounding.md"
        bib_text = bib.read_text(encoding="utf-8")
        anchor = "| Boundaries in three tiers |"
        row = next(l for l in bib_text.splitlines() if l.startswith(anchor))
        bib_text = bib_text.replace(
            row, row + "\n| Names its owner | persona | check, reading | none | reading alone | none | none |"
            "\n| Short sentences | instruction writing | rating, frequency | none | reading alone | none | none |",
        )
        bib.write_text(bib_text, encoding="utf-8")

        after = q.load(rq)
        persona, writing = after.sections
        self.assertEqual(len(after.questions), len(before.questions) + 2)
        self.assertEqual(after.possible, before.possible + 1 + after.scales["frequency"].top + 1)
        self.assertEqual(after.section_points(persona), before.section_points(persona) + 1)
        self.assertEqual(after.section_points(writing), before.section_points(writing) + after.scales["frequency"].top + 1)

        proj = make_fixtures.build("si11", parent=self.tmp)
        record = full_record(after, ".claude/agents/helper.md")
        path = self.tmp / "record.json"
        path.write_text(json.dumps({"root": proj.as_posix(), "files": [record]}), encoding="utf-8")
        proc = subprocess.run([sys.executable, str(skill / "scripts" / "report.py"), "render", str(path)], capture_output=True, text=True)
        self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
        total = next(l for l in proc.stdout.splitlines() if l.startswith("Total: "))
        self.assertIn(f"({after.possible} possible, less ", total)
        self.assertIn("Names its owner ", proc.stdout)
        self.assertIn("Short sentences ", proc.stdout)
        self.assertRegex(proc.stdout, r"(?m)^Nothing said twice +yes 2$")
        verify = subprocess.run(
            [sys.executable, str(skill / "scripts" / "report.py"), "verify", "-"], input=proc.stdout, capture_output=True, text=True
        )
        self.assertEqual(verify.returncode, 0, verify.stdout + verify.stderr)
        self.assertEqual(
            {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted((skill / "scripts").glob("*.py"))}, hashes
        )


def full_record(qs, path):
    """A record for helper.md answering every question the file holds: each reading check met, each rating at its
    top point over one place, a content-test question marked as not applying, the branches as find.py reads them."""
    helper_lines = {7: "You review code for style and report what you find.", 9: "Never edit files; report what you find in a list."}
    out = []
    for q in qs.questions:
        if q.kind == "script":
            continue
        if q.title in qs.content_tests and q.title != "Tools explained":
            out.append({"question": q.title, "does_not_apply": qs.content_tests[q.title][1]})
            continue
        if q.kind == "reading":
            out.append({"question": q.title, "score": 1})
        elif q.scale == "quality":
            out.append({"question": q.title, "scale": "quality", "point": qs.scales["quality"].top})
        else:
            answer = {"question": q.title, "scale": q.scale, "places": [{"file": path, "line": 9, "quote": helper_lines[9], "meets": True}]}
            if q.title == "Tools explained":
                answer["places"] = [{"file": path, "line": 4, "quote": "tools: Read, Grep, Edit", "meets": True}]
            out.append(answer)
    return {
        "path": path,
        "branches": {"delegated": True, "harness": "Claude Code", "settings": ["tools"]},
        "questions": out,
        "fit": {"statement": "Nothing was found on how its remit sits with the nearby files."},
    }



def parts_faults(folder, names):
    """Faults between questions.py's ordered list of parts and the .md files in folder; empty when they agree."""
    held = sorted(p.name for p in Path(folder).glob("*.md"))
    faults = [f"{n} is listed {names.count(n)} times" for n in sorted(set(names)) if names.count(n) > 1]
    faults += [f"{n} is listed and not in the folder" for n in names if n not in held]
    faults += [f"{n} is in the folder and not listed" for n in held if n not in names]
    return faults


class TestPartsList(ScratchCase):
    """questions.py reads the parts from one ordered list of names, so no file name carries a number to set the order.
    The list and the folder must agree: a part left off the list would drop out of every review unseen."""

    def test_list_matches_the_folder(self):
        self.assertEqual(parts_faults(QUESTIONS, list(load_module().PARTS)), [])

    def test_control_extra_and_missing_parts(self):
        folder = self.tmp / "questions"
        shutil.copytree(QUESTIONS, folder)
        (folder / "notes.md").write_text("## Notes\n", encoding="utf-8")
        (folder / "score.md").unlink()
        self.assertEqual(
            parts_faults(folder, list(load_module().PARTS)),
            ["score.md is listed and not in the folder", "notes.md is in the folder and not listed"],
        )

    def test_control_questions_py_refuses_an_unlisted_part(self):
        folder = self.tmp / "questions"
        shutil.copytree(QUESTIONS, folder)
        (folder / "notes.md").write_text("## Notes\n", encoding="utf-8")
        proc = run_questions(folder)
        self.assertEqual(proc.returncode, 2, proc.stdout)
        self.assertIn("notes.md, line 1: a part questions.py's list of parts does not name", proc.stderr)


if __name__ == "__main__":
    unittest.main()
