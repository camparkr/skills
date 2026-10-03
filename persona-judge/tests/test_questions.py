"""T-K: questions.py reads review-questions.md at run time under its markup contract (specification §3e and §8,
Sophos, 3 October 2026). No script holds a question, a count of questions or a count of points.

(1) the frozen file reads as §3e says; (2) the file's prose counts equal the counts questions.py derives; (3) a copy
that breaks the contract once is refused with exit 2, naming the line and what was expected; (4) a copy with a
question added in each section and a weight changed is scored by report.py with no script changed.
"""

import hashlib
import json
import re
import shutil
import subprocess
import sys
import unittest
from pathlib import Path

from support import REFERENCES, ROOT, SCRIPTS, ScratchCase, make_fixtures

QUESTIONS_MD = REFERENCES / "review-questions.md"
# A fixture copy of the round-4 file (committed at 146a82a), pinned by its hash, so the tests that check §3e's reading
# word for word hold while the live file changes (§8, 'Counts in every test and eval': only fixtures pin a known file).
FIXTURE_MD = make_fixtures.FILES / "review-questions-round-4.fixture"
FIXTURE_SHA256 = "e229cb727fef6a27eeda4ad1514b833d6ce3d64df10dc57cd9530e1e24798b3a"

# The prose counts T-K (2) compares with the derived ones: each pattern held here, in the test, never in a script.
PROSE_COUNTS = {
    "questions": r"All (\d+) questions are asked",
    "possible": r"(\d+) points are possible:",
    "persona points": r"points are possible: (\d+) in the persona section",
    "writing points": r"and (\d+) in instruction\s+writing",
    "persona questions": r"persona questions, (\d+) questions",
    "writing questions": r"instruction-writing questions, (\d+) questions",
}


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
    """A count the prose writes as digits or in words, such as '35', 'Ten' or 'twenty-one'."""
    word = word.lower().strip()
    if word.isdigit():
        return int(word)
    total = 0
    for part in word.replace("-", " ").split():
        if part in UNITS:
            total += UNITS.index(part)
        elif part in TENS:
            total += 20 + 10 * TENS.index(part)
        else:
            raise ValueError(f"'{word}' is not a number the test can read")
    return total


# A count written in the prose: digits, or number words, hyphenated or not.
NUMBER = r"(\d+|[A-Za-z]+(?:-[A-Za-z]+)?)"


def stated_counts(text):
    """The counts the file's prose states, read with the patterns above and the word counts below."""
    folded = " ".join(text.split())
    out = {}
    for name, pattern in PROSE_COUNTS.items():
        m = re.search(pattern, folded)
        out[name] = int(m.group(1)) if m else None
    m = re.search(NUMBER + r" checks count (\d+) points", folded)
    out["weighted checks"] = word_number(m.group(1)) if m else None
    out["weighted points"] = int(m.group(2)) if m else None
    m = re.search(NUMBER + r" ratings and " + NUMBER + r" checks? apply only where the file holds", folded)
    out["content-test ratings"] = word_number(m.group(1)) if m else None
    out["content-test checks"] = word_number(m.group(2)) if m else None
    m = re.search(r"The first " + NUMBER + r" are rated on the frequency scale and the last " + NUMBER + r" on the quality scale", folded)
    out["persona frequency ratings"] = word_number(m.group(1)) if m else None
    out["persona quality ratings"] = word_number(m.group(2)) if m else None
    m = re.search(r"All " + NUMBER + r" are rated on the frequency scale", folded)
    out["writing frequency ratings"] = word_number(m.group(1)) if m else None
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
        "persona questions": len(in_section(persona)),
        "writing questions": len(in_section(writing)),
        "weighted checks": len(weighted),
        "weighted points": len({q.weight for q in weighted}) == 1 and weighted[0].weight or None,
        "content-test ratings": sum(1 for q in content if q.kind == "rating"),
        "content-test checks": sum(1 for q in content if q.kind != "rating"),
        "persona frequency ratings": sum(1 for q in in_section(persona) if q.scale == "frequency"),
        "persona quality ratings": sum(1 for q in in_section(persona) if q.scale == "quality"),
        "writing frequency ratings": sum(1 for q in in_section(writing) if q.scale == "frequency"),
    }


class TestReadsTheFile(unittest.TestCase):
    """T-K (1): the round-4 file, kept as a fixture copy pinned by its hash, reads as §3e says, word for word."""

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
    """The live review-questions.md meets the contract, and every count the tests use comes from it."""

    def setUp(self):
        self.q = load_module()
        self.qs = self.q.load(QUESTIONS_MD)

    def test_meets_the_contract(self):
        proc = run_questions(QUESTIONS_MD, "--format", "json")
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
        self.assertEqual([word_number(w) for w in ("35", "One", "seven", "Ten", "twelve", "twenty-one", "Thirty five")],
                         [35, 1, 7, 10, 12, 21, 35])

    def test_control(self):
        with self.assertRaises(ValueError):
            word_number("several")


class TestProseCounts(ScratchCase):
    """T-K (2): every count the prose states equals the count questions.py derives."""

    def test_prose_counts(self):
        q = load_module()
        text = QUESTIONS_MD.read_text(encoding="utf-8")
        stated, derived = stated_counts(text), derived_counts(q.load(QUESTIONS_MD))
        for name, value in stated.items():
            self.assertIsNotNone(value, f"the prose count '{name}' was not found")
        self.assertEqual(stated, derived)

    def test_control(self):
        """A copy with one count changed fails, naming it."""
        q = load_module()
        text = QUESTIONS_MD.read_text(encoding="utf-8")
        changed = text.replace("All 35 questions are asked", "All 36 questions are asked", 1)
        self.assertNotEqual(changed, text)
        stated, derived = stated_counts(changed), derived_counts(q.load(QUESTIONS_MD))
        wrong = [name for name in stated if stated[name] != derived[name]]
        self.assertEqual(wrong, ["questions"])


class TestContractRefused(ScratchCase):
    """T-K (3): each copy breaks the contract once and is refused with exit 2, naming the line and what was expected."""

    def broken(self, old, new, count=1):
        text = QUESTIONS_MD.read_text(encoding="utf-8")
        self.assertIn(old, text)
        path = self.tmp / "review-questions.md"
        path.write_text(text.replace(old, new, count), encoding="utf-8")
        line = text[: text.index(old)].count("\n") + 1
        proc = run_questions(path)
        self.assertEqual(proc.returncode, 2, proc.stdout + proc.stderr)
        self.assertRegex(proc.stderr, r"line \d+: ")
        self.assertIn("expected", proc.stderr)
        return proc.stderr, line

    def test_rating_without_scale_mark(self):
        err, line = self.broken("**Tools explained** (*frequency*).", "**Tools explained.**")
        self.assertIn(f"line {line}:", err)

    def test_weight_in_words(self):
        err, line = self.broken("(*reading*, weight 3). No two statements", "(*reading*, weight three). No two statements")
        self.assertIn(f"line {line}:", err)

    def test_branch_table_without_reason(self):
        old = "| Key | Branch | How it is read | When the answer is no, these do not apply | Reason printed |\n|---|---|---|---|---|"
        err, line = self.broken(old, "| Key | Branch | How it is read | When the answer is no, these do not apply |\n|---|---|---|---|")
        self.assertIn(f"line {line}:", err)
        self.assertIn("Reason printed", err)

    def test_table_naming_an_unknown_title(self):
        err, line = self.broken("| Commands given exactly | a command", "| Commands given precisely | a command")
        self.assertIn(f"line {line}:", err)
        self.assertIn("Commands given precisely", err)

    def test_duplicate_title(self):
        err, _ = self.broken("**Nothing said twice** (*reading*).", "**Leaves known things unsaid** (*reading*).")
        self.assertIn("Leaves known things unsaid", err)

    def test_band_in_no_listed_form(self):
        err, line = self.broken("| 4 | usually | over 60%, up to 80% |", "| 4 | usually | roughly two thirds |")
        self.assertIn(f"line {line}:", err)

    def test_scale_never_defined(self):
        err, line = self.broken("**Reasons given** (*frequency*).", "**Reasons given** (*agreement*).")
        self.assertIn("agreement", err)

    def test_unknown_harness(self):
        """A harness-exception row naming a harness find.py does not name is refused (the verifier's first gap)."""
        err, line = self.broken("| Declares its tools | Codex | Codex has no tools field | OA2 |",
                                "| Declares its tools | Codexx | Codex has no tools field | OA2 |")
        self.assertIn(f"line {line}:", err)
        self.assertIn("Codexx", err)

    def test_empty_reason(self):
        """An empty 'Reason printed' cell is refused (the verifier's second gap)."""
        err, line = self.broken("| Commands given exactly | a command the file tells the agent to run | no command to run |",
                                "| Commands given exactly | a command the file tells the agent to run |  |")
        self.assertIn(f"line {line}:", err)
        self.assertIn("Reason printed", err)

    def test_empty_branch_reason(self):
        err, line = self.broken("| One job; States its output; The description says when to choose it | not delegated |",
                                "| One job; States its output; The description says when to choose it |  |")
        self.assertIn(f"line {line}:", err)

    def test_report_refuses_too(self):
        """report.py and check.py stop with exit 2 when the file they read breaks the contract."""
        skill = self.tmp / "skill"
        shutil.copytree(ROOT / "skill", skill)
        path = skill / "references" / "review-questions.md"
        path.write_text(path.read_text(encoding="utf-8").replace("**Tools explained** (*frequency*).", "**Tools explained.**"), encoding="utf-8")
        record = self.tmp / "r.json"
        record.write_text('{"files": [{"path": "x.md"}]}', encoding="utf-8")
        for args in (["report.py", "validate", str(record)], ["check.py", "-"]):
            proc = subprocess.run(
                [sys.executable, str(skill / "scripts" / args[0]), *args[1:]], input="Read the notes.\n",
                capture_output=True, text=True, cwd=self.tmp,
            )
            self.assertEqual(proc.returncode, 2, args[0] + proc.stdout + proc.stderr)
            self.assertIn("review-questions.md, line", proc.stderr, args[0])


class TestChangeNeedsNoScriptChange(ScratchCase):
    """T-K (4): one question added in each section and one weight changed; report.py scores and renders a record for the
    changed file, its points possible and section points following the change, and no script changes."""

    ADD_CHECK = (
        "**Boundaries in three tiers** (*reading*).",
        "**Names its owner** (*reading*). The file names who maintains it. *Scores 0 on:* a file with no owner.\n\n"
        "**Boundaries in three tiers** (*reading*).",
    )
    ADD_RATING = (
        "**Each instruction stands alone** (*frequency*).",
        "**Short sentences** (*frequency*). *Places:* each sentence. *Meets it:* it is under 30 words.\n\n"
        "**Each instruction stands alone** (*frequency*).",
    )
    WEIGHT = ("**Nothing said twice** (*reading*).", "**Nothing said twice** (*reading*, weight 2).")

    def test_added_questions_and_weight(self):
        q = load_module()
        before = q.load(QUESTIONS_MD)
        skill = self.tmp / "skill"
        shutil.copytree(ROOT / "skill", skill)
        hashes = {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted((ROOT / "skill" / "scripts").glob("*.py"))}
        rq = skill / "references" / "review-questions.md"
        text = rq.read_text(encoding="utf-8")
        for old, new in (self.ADD_CHECK, self.ADD_RATING, self.WEIGHT):
            self.assertEqual(text.count(old), 1, old)
            text = text.replace(old, new)
        rq.write_text(text, encoding="utf-8")
        bib = skill / "references" / "bibliography.md"
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
    }


if __name__ == "__main__":
    unittest.main()
