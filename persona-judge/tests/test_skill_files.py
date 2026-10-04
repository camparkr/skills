"""The skill's own files against Anthropic's skill authoring best practices (specification §5b).

T-D: the SKILL.md description is in the third person.
T-L: every file under skill/agents/ and skill/references/ that a model reads is linked from SKILL.md, one
     level deep, and SKILL.md tells the subagent to read review-questions.md in full.
T-C: every such file over 100 lines opens with a contents list.
T-P: no backslash path in SKILL.md, the reviewer file, the references or the scripts' output.
T-B: bibliography.md's grounding table and sources keep up with review-questions.md (round-3 brief, item 6).

sample-review.md is read only after its SHA-256 matches the hash it landed with (support.SAMPLE_SHA256).

Each check runs on a control built to show it can fail. A check on a prose file that is not yet in place
is skipped with the reason, so the run says what waits.
"""

import re
import sys
import tempfile
import unittest
from pathlib import Path

from support import SKILL, ScratchCase, run, sample_text

SKILL_MD = SKILL / "SKILL.md"
REVIEW_QUESTIONS = SKILL / "references" / "review-questions.md"
BIBLIOGRAPHY = SKILL / "references" / "bibliography.md"
# The sample report, landed for round 3 and read once its hash is checked.
SAMPLE = "references/sample-review.md"
# The reviewer file's path inside the skill, named once (specification §0).
REVIEWER = SKILL / "agents" / "reviewer.md"

# First- and second-person words a third-person description holds none of (best practices,
# 'Writing effective descriptions').
PERSON_WORDS = re.compile(r"\b(I|me|my|we|our|you|your)\b", re.IGNORECASE)
# Over this many lines, a reference opens with a contents list (best practices, 'Structure longer
# reference files with table of contents').
CONTENTS_THRESHOLD = 100
# The contents heading must fall within this many lines of the top to be seen first.
CONTENTS_WITHIN = 30
# A link: a Markdown link target, or a backticked path, as the precedent's SKILL.md writes them.
LINK = re.compile(r"\]\(([^)\s#]+)\)|`([^`\s]+\.md)`")
# A Windows-style path: a word, a backslash and another word with a file extension or folder name.
BACKSLASH_PATH = re.compile(r"[A-Za-z0-9_.-]+\\[A-Za-z0-9_.-]+")


def description(skill_md):
    """Return the description from a SKILL.md's frontmatter, folded scalars joined."""
    text = Path(skill_md).read_text(encoding="utf-8").splitlines()
    if not text or text[0].strip() != "---":
        return ""
    out, inside = [], False
    for line in text[1:]:
        if line.strip() == "---":
            break
        if line.startswith("description:"):
            inside = True
            value = line[len("description:"):].strip()
            if value not in (">", "|", ">-", "|-"):
                out.append(value.strip("'\""))
            continue
        if inside and line.startswith((" ", "\t")):
            out.append(line.strip())
        else:
            inside = False
    return " ".join(out)


def person_words(skill_md):
    return PERSON_WORDS.findall(description(skill_md))


def model_read_files(skill_dir, unread=()):
    """Every .md file under agents/ and references/, relative to the skill folder, less any whose content no
    test reads yet."""
    skill_dir = Path(skill_dir)
    found = []
    for sub in ("agents", "references"):
        if (skill_dir / sub).is_dir():
            found += sorted(p.relative_to(skill_dir).as_posix() for p in (skill_dir / sub).rglob("*.md"))
    return [f for f in found if f not in unread]


def links(path):
    names = set()
    for a, b in LINK.findall(Path(path).read_text(encoding="utf-8")):
        names.add((a or b).lstrip("./"))
    return names


def link_faults(skill_dir):
    """T-L: return a list of faults; empty when every rule holds."""
    skill_dir = Path(skill_dir)
    faults = []
    top = links(skill_dir / "SKILL.md")
    files = model_read_files(skill_dir)
    # The sample's link is checked; its content is not read until its round-3 revision lands.
    if (skill_dir / SAMPLE).exists() and SAMPLE not in top:
        faults.append(f"{SAMPLE} is not linked from SKILL.md")
    for rel in files:
        if rel not in top:
            faults.append(f"{rel} is not linked from SKILL.md")
        for target in links(skill_dir / rel):
            # A link to another skill file, by its path in the skill or by its bare name.
            for other in files:
                if other != rel and (target == other or target == Path(other).name) and other not in top:
                    faults.append(f"{rel} links {other}, which SKILL.md does not link")
    text = (skill_dir / "SKILL.md").read_text(encoding="utf-8")
    if not re.search(r"review-questions\.md[^\n]*\bin full\b|\bin full\b[^\n]*review-questions\.md", text):
        faults.append("SKILL.md does not tell the subagent to read review-questions.md in full")
    return faults


def contents_faults(skill_dir):
    """T-C: files over the threshold without a 'Contents' heading near the top."""
    faults = []
    for rel in model_read_files(skill_dir):
        lines = (Path(skill_dir) / rel).read_text(encoding="utf-8").splitlines()
        if len(lines) > CONTENTS_THRESHOLD and not any(
            re.match(r"#+\s+Contents\b", l) for l in lines[:CONTENTS_WITHIN]
        ):
            faults.append(f"{rel} has {len(lines)} lines and no Contents heading in its first {CONTENTS_WITHIN}")
    return faults


def backslash_faults(paths):
    faults = []
    for path in paths:
        for n, line in enumerate(Path(path).read_text(encoding="utf-8").splitlines(), 1):
            # Escapes inside regular expressions in code blocks are not paths; only path-shaped text counts.
            for m in BACKSLASH_PATH.finditer(line):
                if re.search(r"\.[A-Za-z0-9]{1,5}$|^[A-Za-z]+\\[A-Za-z]+$", m.group(0)) and not re.match(r"^\\[a-z]$", m.group(0)):
                    faults.append(f"{Path(path).name}:{n}: {m.group(0)}")
    return faults


def question_titles(text):
    """The bold question titles of review-questions.md, under its two sections' Checks and Ratings."""
    titles = []
    for heading in ("Persona questions", "Instruction-writing questions"):
        m = re.search(rf"^## {heading}\s*$(.*?)(?=^## |\Z)", text, re.MULTILINE | re.DOTALL)
        if m:
            titles += [t.rstrip(".") for t in re.findall(r"^\*\*(.+?)\*\*", m.group(1), re.MULTILINE)]
    return titles


def section_text(text, heading):
    m = re.search(rf"^## {heading}\s*$(.*?)(?=^## |\Z)", text, re.MULTILINE | re.DOTALL)
    return m.group(1) if m else ""


def table_rows(text):
    """The cells of each body row of every Markdown table in text, header and rule rows left out."""
    rows, previous = [], ""
    for line in text.splitlines():
        if line.startswith("|") and not re.match(r"^\|[\s|:-]+\|$", line):
            cells = [c.strip() for c in line.strip().strip("|").split("|")]
            if previous.startswith("|"):
                rows.append(cells)
        previous = line if line.startswith("|") else ""
    return rows


def drift_faults(questions_text, bibliography_text):
    """T-B: return a list of faults; empty when the bibliography keeps up with the review questions."""
    faults = []
    grounding = table_rows(section_text(bibliography_text, "Grounding"))
    sources_text = section_text(bibliography_text, "Sources")
    keys = {row[0] for row in table_rows(sources_text)}
    grounded = [row[0] for row in grounding]
    for title in question_titles(questions_text):
        count = grounded.count(title)
        if count == 0:
            faults.append(f"'{title}' is missing from the grounding table")
        elif count > 1:
            faults.append(f"'{title}' appears {count} times in the grounding table")
    for row in grounding:
        for key in (k.strip() for k in row[3].split(",")):
            if key and key != "none" and key not in keys:
                faults.append(f"'{row[0]}': source key {key} has no row in the Sources tables")
    for url in re.findall(r"<(https?://[^>\s]+)>", questions_text):
        if url not in sources_text:
            faults.append(f"{url}, cited in review-questions.md, is missing from the Sources tables")
    return faults


def need(path):
    if not Path(path).exists():
        raise unittest.SkipTest(f"{Path(path).relative_to(SKILL.parent)} is not yet in place; this check waits for it")


class TestDescriptionT_D(ScratchCase):
    def test_real_description(self):
        need(SKILL_MD)
        self.assertTrue(description(SKILL_MD), "SKILL.md has no description")
        self.assertEqual(person_words(SKILL_MD), [])

    def test_control(self):
        f = self.tmp / "SKILL.md"
        f.write_text("---\nname: x\ndescription: You can review persona files.\n---\n")
        self.assertEqual(person_words(f), ["You"])


class TestLinksT_L(ScratchCase):
    def test_real_links(self):
        need(SKILL_MD)
        self.assertEqual(link_faults(SKILL), [])

    def test_sample_content(self):
        """The sample's content: every skill file it links exists, so SKILL.md can link it too (test_real_links
        checks that once SKILL.md lands)."""
        sample_text()
        files = model_read_files(SKILL)
        named = {Path(f).name: f for f in files}
        targets = links(SKILL / SAMPLE)
        linked = [named[t] if t in named else t for t in targets if t in named or t in files]
        self.assertIn("references/bibliography.md", linked)
        for rel in linked:
            self.assertTrue((SKILL / rel).is_file(), rel)

    def test_control(self):
        skill = self.tmp / "skill"
        (skill / "references").mkdir(parents=True)
        (skill / "SKILL.md").write_text("Read `references/a.md` in full, and review-questions.md in full.\n")
        (skill / "references" / "a.md").write_text("Then read `b.md`.\n")
        (skill / "references" / "b.md").write_text("Linked only from a.md.\n")
        faults = link_faults(skill)
        self.assertIn("references/b.md is not linked from SKILL.md", faults)
        self.assertIn("references/a.md links references/b.md, which SKILL.md does not link", faults)


class TestContentsT_C(ScratchCase):
    def test_real_files(self):
        # The references already in place are measured now; the reviewer file once it lands.
        self.assertEqual(contents_faults(SKILL), [])

    def test_reviewer_file_present(self):
        need(REVIEWER)

    def test_sample(self):
        """T-C on the sample, once its hash is checked: a contents heading within its first lines, by T-C's own rule
        and not a pinned line number, so the sample's prose can move."""
        lines = sample_text().splitlines()
        self.assertGreater(len(lines), CONTENTS_THRESHOLD)
        self.assertTrue(any(re.match(r"#+\s+Contents\b", l) for l in lines[:CONTENTS_WITHIN]))
        self.assertEqual([f for f in contents_faults(SKILL) if f.startswith(SAMPLE)], [])

    def test_control(self):
        skill = self.tmp / "skill"
        (skill / "references").mkdir(parents=True)
        (skill / "references" / "long.md").write_text("# Long\n" + "line\n" * 100)
        self.assertEqual(len(contents_faults(skill)), 1)


class TestPathsT_P(ScratchCase):
    def test_real_prose(self):
        files = [
            p for p in [SKILL_MD, REVIEWER, *sorted((SKILL / "references").glob("*.md"))]
            if p.exists()
        ]
        self.assertTrue(files)
        self.assertEqual(backslash_faults(files), [])

    def test_scripts_help(self):
        for script in ("find.py", "check.py", "report.py"):
            proc = run(script, "--help")
            self.assertEqual(proc.returncode, 0, script)
            self.assertEqual(BACKSLASH_PATH.findall(proc.stdout), [], script)

    def test_sample(self):
        """T-P on the sample, once its hash is checked."""
        sample_text()
        self.assertEqual(backslash_faults([SKILL / SAMPLE]), [])

    def test_control(self):
        f = self.tmp / "x.md"
        f.write_text("Run `scripts\\check.py` first.\n")
        self.assertEqual(backslash_faults([f]), ["x.md:1: scripts\\check.py"])


class TestDefinitions(unittest.TestCase):
    """definitions.md replaces persona-boundaries.md and absorbs its content (Sophos, 4 October 2026): the new file is
    in place and linked from SKILL.md, and the old one is gone, so no test or reader can find it."""

    def test_definitions_replace_persona_boundaries(self):
        self.assertTrue((SKILL / "references" / "definitions.md").is_file())
        self.assertFalse((SKILL / "references" / "persona-boundaries.md").exists())
        self.assertIn("references/definitions.md", links(SKILL_MD))
        self.assertNotIn("references/persona-boundaries.md", links(SKILL_MD))


class TestBibliographyT_B(ScratchCase):
    """T-B: the bibliography drift test, on the frozen files and on three controls, one per fault."""

    def setUp(self):
        super().setUp()
        self.questions = REVIEW_QUESTIONS.read_text(encoding="utf-8")
        self.bibliography = BIBLIOGRAPHY.read_text(encoding="utf-8")

    def copy(self, name, text):
        """Plant a fault in a scratch copy, so no reference file is touched."""
        path = self.tmp / name
        path.write_text(text, encoding="utf-8")
        return path.read_text(encoding="utf-8")

    def test_real_files(self):
        sys.path.insert(0, str(SKILL / "scripts"))
        import questions

        # The count comes from the file, through questions.py (specification §8, round 4).
        self.assertEqual(len(question_titles(self.questions)), len(questions.load(REVIEW_QUESTIONS).questions))
        self.assertEqual(drift_faults(self.questions, self.bibliography), [])

    def test_control_title_missing_or_twice(self):
        lines = self.bibliography.splitlines()
        one_job = next(l for l in lines if l.startswith("| One job |"))
        reasons = next(l for l in lines if l.startswith("| Reasons given |"))
        planted = "\n".join(
            l for l in lines if l != one_job
        ).replace(reasons, reasons + "\n" + reasons)
        faults = drift_faults(self.questions, self.copy("bibliography.md", planted))
        self.assertIn("'One job' is missing from the grounding table", faults)
        self.assertIn("'Reasons given' appears 2 times in the grounding table", faults)

    def test_control_key_without_a_source(self):
        planted = self.bibliography.replace("| AN2, AN3 |", "| AN2, AN9 |", 1)
        self.assertNotEqual(planted, self.bibliography)
        faults = drift_faults(self.questions, self.copy("bibliography.md", planted))
        self.assertEqual(faults, ["'Bound parts agree with the prose': source key AN9 has no row in the Sources tables"])

    def test_control_url_missing(self):
        planted = self.questions + "\nAlso: <https://example.com/not-in-the-bibliography>.\n"
        faults = drift_faults(self.copy("review-questions.md", planted), self.bibliography)
        self.assertEqual(
            faults, ["https://example.com/not-in-the-bibliography, cited in review-questions.md, is missing from the Sources tables"]
        )


if __name__ == "__main__":
    unittest.main()
