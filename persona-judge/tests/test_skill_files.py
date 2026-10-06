"""The skill's own files against Anthropic's skill authoring best practices.

TestDescriptionT_D: the SKILL.md description is in the third person.
TestLinksT_L: every file in skill/ other than the scripts and the tables is reachable by Markdown links that start at
     SKILL.md and pass through reviewer.md and the files in skill/steps/, every such link names a file that exists,
     and a file the reviewer loads tells it to read each part of the review questions in references/questions/ in full.
TestContentsT_C: a reference over 100 lines opens with a contents list, unless the reviewer reads it whole at one
     step; sample-review.md is that case.
TestPathsT_P: no backslash path in SKILL.md, the reviewer file, its steps, the references or the scripts' output.
TestGroundingT_B: grounding.md's table of each question's support and sources.md keep up with the review questions,
     the parts in references/questions/ joined in questions.py's order, so every question keeps its sources; and every
     source key the questions and persona-boundaries.md cite has a row in sources.md.
definitions.md sits beside the README, outside skill/; persona-boundaries.md holds the terms a review uses, the link
rule reaches it, and the two files repeat no table row.
TestEveryLink: every relative link in every Markdown file under skill/ names a file that exists, read from the
     linking file's own folder.
TestQuotedNames: a span in single quotes that its sentence calls a step, section, list, heading, question, check,
     rating or part, by the word just before or just after it, matches a heading, a bold step title or a question
     title under skill/, word for word.
TestSkillSourceKeys: every source key cited under skill/ has a row in grounding.md's 'Sources', and every key with a
     row there is cited under skill/ outside that section.

sample-review.md is read only after its SHA-256 matches the hash it landed with (support.SAMPLE_SHA256).

Each check runs on a control built to show it can fail. A check on a prose file that is not yet in place
is skipped with the reason, so the run says what waits.
"""

import posixpath
import re
import shutil
import unittest
from pathlib import Path

from support import QUESTIONS, ROOT, SKILL, ScratchCase, part_names, questions_text, run, sample_text

SKILL_MD = SKILL / "SKILL.md"
# The folder holding the review questions' parts, relative to the skill folder.
QUESTIONS_FOLDER = "references/questions"
GROUNDING = SKILL / "references" / "grounding.md"
SOURCES = SKILL.parent / "sources.md"
BOUNDARIES = SKILL / "references" / "persona-boundaries.md"
# The section of grounding.md whose table names each question's sources.
GROUNDING_SECTION = "Each question's support"
# The sample report, read once its hash is checked.
SAMPLE = "references/sample-review.md"
# The reviewer file's path inside the skill, named once so a move changes one line.
REVIEWER = SKILL / "reviewer.md"
# The folder of step files the reviewer reads, each at its step.
STEPS_FOLDER = "steps"
# References the reviewer reads whole at one step, so they need no contents list: the step 'Compose the review
# record' in steps/report.md reads the sample for the form a report takes.
READ_WHOLE = {SAMPLE}

# First- and second-person words a third-person description holds none of (best practices,
# 'Writing effective descriptions').
PERSON_WORDS = re.compile(r"\b(I|me|my|we|our|you|your)\b", re.IGNORECASE)
# Over this many lines, a reference opens with a contents list (best practices, 'Structure longer
# reference files with table of contents').
CONTENTS_THRESHOLD = 100
# The contents heading must fall within this many lines of the top to be seen first.
CONTENTS_WITHIN = 30
# A Markdown link's target.
MD_LINK = re.compile(r"\]\(([^)\s#]+)\)")
# A link or a backticked path, as the sample names the files it points to.
LINK = re.compile(r"\]\(([^)\s#]+)\)|`([^`\s]+\.md)`")
# A source key, such as AN1 or ST7, as the questions cite them.
SOURCE_KEY = re.compile(r"\b[A-Z]{2}\d+\b")
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


def model_read_files(skill_dir):
    """Every file in the skill folder other than SKILL.md, the scripts and the tables, relative to the folder."""
    skill_dir = Path(skill_dir)
    return sorted(
        p.relative_to(skill_dir).as_posix() for p in skill_dir.rglob("*")
        if p.is_file() and p.suffix == ".md" and p.name != "SKILL.md" and "scripts" not in p.relative_to(skill_dir).parts
    )


def links(path):
    """The names a file links or names in backticks, as written."""
    names = set()
    for a, b in LINK.findall(Path(path).read_text(encoding="utf-8")):
        names.add((a or b).lstrip("./"))
    return names


def link_targets(skill_dir, rel):
    """The files a skill file's Markdown links point to, relative to the skill folder."""
    text = (Path(skill_dir) / rel).read_text(encoding="utf-8")
    return {posixpath.normpath(posixpath.join(posixpath.dirname(rel), t)) for t in MD_LINK.findall(text) if "://" not in t}


def walked(rel):
    """Whether the link rule follows the links out of rel: reviewer.md's and the step files'."""
    return rel == "reviewer.md" or rel.startswith(STEPS_FOLDER + "/")


def reached(skill_dir):
    """The files reached by links from reviewer.md, following links out of reviewer.md and the step files only, and
    the broken links met on the way, as (file, target)."""
    seen, queue, broken = {"reviewer.md"}, ["reviewer.md"], []
    while queue:
        rel = queue.pop()
        if not walked(rel) or not (Path(skill_dir) / rel).is_file():
            continue
        for target in sorted(link_targets(skill_dir, rel)):
            if not (Path(skill_dir) / target).exists():
                broken.append((rel, target))
            elif target not in seen:
                seen.add(target)
                queue.append(target)
    return seen, broken


def link_faults(skill_dir):
    """The link rules: return a list of faults; empty when every rule holds."""
    skill_dir = Path(skill_dir)
    faults = []
    if "reviewer.md" not in link_targets(skill_dir, "SKILL.md"):
        faults.append("SKILL.md does not link reviewer.md")
    seen, broken = reached(skill_dir)
    faults += [f"{rel} links {target}, which does not exist" for rel, target in broken]
    faults += [f"{rel} is not reached by links from SKILL.md through reviewer.md and steps/"
               for rel in model_read_files(skill_dir) if rel not in seen]
    # The files the reviewer reads, which tell it what else to read.
    text = "\n".join(
        (skill_dir / rel).read_text(encoding="utf-8") for rel in sorted(seen) if walked(rel) and (skill_dir / rel).is_file()
    )
    # Each part of the review questions is named, by its path, in a sentence that says to read it in full.
    sentences = re.split(r"(?<=[.!?])\s+", " ".join(text.split()))
    parts = sorted(p.relative_to(skill_dir).as_posix() for p in (skill_dir / QUESTIONS_FOLDER).glob("*.md"))
    if not parts:
        faults.append(f"{QUESTIONS_FOLDER}/ holds no part of the review questions")
    for part in parts:
        if not any(part in s and re.search(r"\bin full\b", s) for s in sentences):
            faults.append(f"no file the reviewer loads tells it to read {part} in full")
    return faults


def contents_faults(skill_dir):
    """The contents rule: references over the threshold, other than those read whole at one step, without a
    'Contents' heading near the top."""
    faults = []
    for rel in model_read_files(skill_dir):
        if not rel.startswith("references/") or rel in READ_WHOLE:
            continue
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
    """The bold question titles of the review questions, under their two sections' Checks and Ratings."""
    titles = []
    for heading in ("Persona questions", "Instruction-writing questions"):
        m = re.search(rf"^## {heading}\s*$(.*?)(?=^## |\Z)", text, re.MULTILINE | re.DOTALL)
        if m:
            titles += [t.rstrip(".") for t in re.findall(r"^\*\*(.+?)\*\*", m.group(1), re.MULTILINE)]
    return titles


def section_text(text, heading):
    m = re.search(rf"^## {re.escape(heading)}\s*$(.*?)(?=^## |\Z)", text, re.MULTILINE | re.DOTALL)
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


def source_keys(sources_text):
    """The keys sources.md gives a row, from every table in it."""
    return {row[0] for row in table_rows(sources_text)}


def drift_faults(questions_text, grounding_text, sources_text):
    """The grounding rule: return a list of faults; empty when grounding.md and sources.md keep up with the review
    questions."""
    faults = []
    grounding = table_rows(section_text(grounding_text, GROUNDING_SECTION))
    keys = source_keys(sources_text)
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
                faults.append(f"'{row[0]}': source key {key} has no row in sources.md")
    for url in re.findall(r"<(https?://[^>\s]+)>", questions_text):
        if url not in sources_text:
            faults.append(f"{url}, cited in the review questions, is missing from sources.md")
    return faults


def key_faults(cited, sources_text):
    """Every source key cited in the given {name: text} has a row in sources.md; return a fault for each that has
    none, naming the file."""
    keys = source_keys(sources_text)
    return [f"{name} cites {key}, which has no row in sources.md"
            for name, text in cited.items() for key in sorted(set(SOURCE_KEY.findall(text))) if key not in keys]


def cited_texts():
    """The texts whose source keys must have rows: each question part and persona-boundaries.md."""
    texts = {f"questions/{name}": (QUESTIONS / name).read_text(encoding="utf-8") for name in part_names()}
    texts["persona-boundaries.md"] = BOUNDARIES.read_text(encoding="utf-8")
    return texts


def every_link_fault(skill_dir):
    """Every relative link in every Markdown file under skill_dir, read from the linking file's own folder: return a
    fault for each that names no file or folder."""
    skill_dir = Path(skill_dir)
    faults = []
    for rel in sorted(p.relative_to(skill_dir).as_posix() for p in skill_dir.rglob("*.md")):
        for target in sorted(link_targets(skill_dir, rel)):
            if not target.startswith("mailto:") and not (skill_dir / target).exists():
                faults.append(f"{rel} links {target}, which does not exist")
    return faults


# The words that call a quoted span a name the skill holds: a step, a section and so on.
NAME_NOUN = r"(?:steps?|sections?|lists?|headings?|questions?|checks?|ratings?|parts?)"
# A span in single quotes. The opening quote follows no letter, so 'skill's' is no opening; an apostrophe inside the
# span is one followed by a letter; the span ends at a blank line.
QUOTED = re.compile(r"(?<![\w'])'([^'\s](?:[^'\n]|\n(?![ \t]*\n)|'(?=\w))*?)'(?!\w)")
# The noun just before a quoted span, as in 'the step 'Run the script checks''; a step number may stand between.
NOUN_BEFORE = re.compile(rf"\b({NAME_NOUN})(?:\s+\d+)?,?\s+$", re.IGNORECASE)
# The noun just after a quoted span, as in 'the 'Sources' section'.
NOUN_AFTER = re.compile(rf"^\s+({NAME_NOUN})\b", re.IGNORECASE)


def prose_only(text):
    """text with code blocks blanked and inline code replaced by a placeholder, keeping every line in its place."""
    text = re.sub(r"^```.*?^```", lambda m: "\n" * m.group(0).count("\n"), text, flags=re.MULTILINE | re.DOTALL)
    return re.sub(r"`[^`\n]*`", "`code`", text)


def held_names(skill_dir):
    """The names a quoted span may point to: every Markdown heading, and every bold title that opens a line or a list
    item, as the steps and the questions are titled, with its closing full stop left off."""
    names = set()
    for path in Path(skill_dir).rglob("*.md"):
        for line in path.read_text(encoding="utf-8").splitlines():
            heading = re.match(r"#+\s+(.+?)\s*$", line)
            if heading:
                names.add(" ".join(heading.group(1).split()))
            bold = re.match(r"\s*(?:\d+\.\s+|[-*]\s+)?\*\*(.+?)\*\*", line)
            if bold:
                names.add(" ".join(bold.group(1).split()).rstrip("."))
    return names


def quoted_names(skill_dir):
    """Every quoted span under skill_dir that the word just before or just after it calls a step, section, list,
    heading, question, check, rating or part, as (file, line, noun, name)."""
    skill_dir = Path(skill_dir)
    found = []
    for path in sorted(skill_dir.rglob("*.md")):
        text = prose_only(path.read_text(encoding="utf-8"))
        for m in QUOTED.finditer(text):
            noun = NOUN_BEFORE.search(text[max(0, m.start() - 40):m.start()]) or NOUN_AFTER.match(text[m.end():])
            if noun:
                found.append((path.relative_to(skill_dir).as_posix(), text.count("\n", 0, m.start()) + 1,
                              noun.group(1).lower(), " ".join(m.group(1).split())))
    return found


def quoted_name_faults(skill_dir):
    """The quoted-name rule: return a fault for each quoted name that matches no heading, bold step title or question
    title under skill_dir."""
    names = held_names(skill_dir)
    return [f"{rel}:{line}: the {noun} '{name}' matches no heading, bold step title or question title"
            for rel, line, noun, name in quoted_names(skill_dir) if name not in names]


# The section of grounding.md that gives the skill's own source keys their rows.
SKILL_SOURCES_SECTION = "Sources"
# A run of keys, such as 'ST1 to ST4', which cites every key between the two.
KEY_RANGE = re.compile(r"\b([A-Z]{2})(\d+) to \1(\d+)\b")


def cited_keys(text):
    """The source keys text cites, a run such as 'ST1 to ST4' counted as every key in it."""
    keys = set(SOURCE_KEY.findall(text))
    for prefix, low, high in KEY_RANGE.findall(text):
        keys |= {f"{prefix}{n}" for n in range(int(low), int(high) + 1)}
    return keys


def skill_key_faults(skill_dir):
    """The skill's own source keys, both ways: every key cited under skill_dir has a row in grounding.md's 'Sources',
    and every key with a row there is cited under skill_dir outside that section. Return a list of faults."""
    skill_dir = Path(skill_dir)
    grounding = skill_dir / "references" / "grounding.md"
    text = grounding.read_text(encoding="utf-8")
    section = re.search(rf"^## {SKILL_SOURCES_SECTION}\s*$(.*?)(?=^## |\Z)", text, re.MULTILINE | re.DOTALL)
    if not section:
        return [f"references/grounding.md has no '{SKILL_SOURCES_SECTION}' section"]
    first_line = text.count("\n", 0, section.start(1)) + 1
    rows = {}
    for n, line in enumerate(section.group(1).splitlines(), first_line):
        key = re.match(r"\|\s*([A-Z]{2}\d+)\s*\|", line)
        if key:
            rows[key.group(1)] = n
    cited = {}
    for path in sorted(p for p in skill_dir.rglob("*") if p.is_file() and "__pycache__" not in p.parts):
        rel = path.relative_to(skill_dir).as_posix()
        try:
            body = path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            continue
        if path == grounding:
            body = body[:section.start(1)] + body[section.end(1):]
        for key in cited_keys(body):
            cited.setdefault(key, rel)
    faults = [f"{cited[key]} cites {key}, which has no row in grounding.md's '{SKILL_SOURCES_SECTION}'"
              for key in sorted(cited) if key not in rows]
    faults += [f"references/grounding.md:{rows[key]}: {key} has a row in '{SKILL_SOURCES_SECTION}', and nothing under "
               "skill/ outside that section cites it" for key in sorted(rows) if key not in cited]
    return faults


def need(path):
    if not Path(path).exists():
        raise unittest.SkipTest(f"{Path(path).relative_to(ROOT)} is not yet in place; this check waits for it")


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
        """The sample's content: every skill file it links exists, and it links grounding.md, whose Sources give its keys."""
        sample_text()
        files = model_read_files(SKILL)
        named = {Path(f).name: f for f in files}
        targets = links(SKILL / SAMPLE)
        linked = [named[t] if t in named else t for t in targets if t in named or t in files]
        self.assertIn("references/grounding.md", linked)
        for rel in linked:
            self.assertTrue((SKILL / rel).is_file(), rel)

    def test_control(self):
        skill = self.tmp / "skill"
        for sub in ("steps", "references/questions"):
            (skill / sub).mkdir(parents=True)
        (skill / "SKILL.md").write_text("Brief a subagent with [`reviewer.md`](reviewer.md).\n")
        (skill / "reviewer.md").write_text(
            "Read [`references/questions/a-part.md`](references/questions/a-part.md) in full. Then follow\n"
            "[`steps/find.md`](steps/find.md).\n"
        )
        (skill / "steps" / "find.md").write_text(
            "Read [`../references/a.md`](../references/a.md), and\n"
            "[`../references/questions/b-part.md`](../references/questions/b-part.md) when asked, and [x](gone.md).\n"
        )
        (skill / "steps" / "orphan.md").write_text("No file links this step.\n")
        (skill / "references" / "a.md").write_text("Then read [`b.md`](b.md).\n")
        (skill / "references" / "b.md").write_text("Linked only from a reference, whose links are not followed.\n")
        (skill / "references" / "questions" / "a-part.md").write_text("A part.\n")
        (skill / "references" / "questions" / "b-part.md").write_text("Another part.\n")
        self.assertEqual(
            link_faults(skill),
            [
                "steps/find.md links steps/gone.md, which does not exist",
                "references/b.md is not reached by links from SKILL.md through reviewer.md and steps/",
                "steps/orphan.md is not reached by links from SKILL.md through reviewer.md and steps/",
                "no file the reviewer loads tells it to read references/questions/b-part.md in full",
            ],
        )
        (skill / "SKILL.md").write_text("Brief a subagent with the reviewer file.\n")
        self.assertIn("SKILL.md does not link reviewer.md", link_faults(skill))


class TestContentsT_C(ScratchCase):
    def test_real_files(self):
        self.assertEqual(contents_faults(SKILL), [])

    def test_reviewer_file_present(self):
        need(REVIEWER)

    def test_sample(self):
        """The sample, once its hash is checked, is over the threshold and has no contents list, and is exempt because
        a step reads it whole: steps/report.md links it."""
        lines = sample_text().splitlines()
        self.assertGreater(len(lines), CONTENTS_THRESHOLD)
        self.assertFalse(any(re.match(r"#+\s+Contents\b", l) for l in lines[:CONTENTS_WITHIN]))
        self.assertIn(SAMPLE, link_targets(SKILL, "steps/report.md"))
        self.assertEqual([f for f in contents_faults(SKILL) if f.startswith(SAMPLE)], [])

    def test_control(self):
        skill = self.tmp / "skill"
        (skill / "references").mkdir(parents=True)
        (skill / "references" / "long.md").write_text("# Long\n" + "line\n" * 100)
        (skill / "references" / "sample-review.md").write_text("# Sample\n" + "line\n" * 100)
        (skill / "reviewer.md").write_text("# Reviewer\n" + "line\n" * 100)
        self.assertEqual(contents_faults(skill), ["references/long.md has 101 lines and no Contents heading in its first 30"])


class TestPathsT_P(ScratchCase):
    def test_real_prose(self):
        files = [
            p for p in [SKILL_MD, REVIEWER, *sorted((SKILL / STEPS_FOLDER).glob("*.md")),
                        *sorted((SKILL / "references").rglob("*.md"))]
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
        """No backslash path in the sample, once its hash is checked."""
        sample_text()
        self.assertEqual(backslash_faults([SKILL / SAMPLE]), [])

    def test_control(self):
        f = self.tmp / "x.md"
        f.write_text("Run `scripts\\check.py` first.\n")
        self.assertEqual(backslash_faults([f]), ["x.md:1: scripts\\check.py"])


def definitions_faults(root):
    """Return a list of faults in where definitions.md and persona-boundaries.md sit; empty when every rule holds.

    definitions.md sits beside the README, outside skill/, and the agent never loads it; persona-boundaries.md holds
    the terms a review uses, and the link rule reaches it. No table row of persona-boundaries.md appears again in
    definitions.md, so the two files do not repeat each other.
    """
    root = Path(root)
    skill_dir = root / "skill"
    boundaries = skill_dir / "references" / "persona-boundaries.md"
    faults = []
    if not (root / "definitions.md").is_file():
        faults.append("definitions.md is not at the plugin root")
    faults += [f"{p.relative_to(root).as_posix()} is under skill/" for p in sorted(skill_dir.rglob("definitions.md"))]
    if not boundaries.is_file():
        return faults + ["skill/references/persona-boundaries.md is missing"]
    seen, _ = reached(skill_dir)
    if "references/persona-boundaries.md" not in seen:
        faults.append("the reviewer's links do not reach references/persona-boundaries.md")
    faults += [f"{rel} links {t}" for rel in sorted(seen) if walked(rel) and (skill_dir / rel).is_file()
               for t in sorted(link_targets(skill_dir, rel)) if Path(t).name == "definitions.md"]
    if (root / "definitions.md").is_file():
        repeated = table_rows((root / "definitions.md").read_text(encoding="utf-8"))
        for row in table_rows(boundaries.read_text(encoding="utf-8")):
            if row in repeated:
                faults.append(f"the row '{row[0]}' of persona-boundaries.md appears again in definitions.md")
    return faults


class TestDefinitionsPlace(ScratchCase):
    """definitions.md sits at the plugin root for people, and persona-boundaries.md holds what a review uses."""

    def scratch_root(self):
        """A scratch copy of definitions.md and the skill's prose, so a planted fault touches no real file."""
        root = self.tmp / "persona-judge"
        shutil.copytree(SKILL, root / "skill", ignore=shutil.ignore_patterns("scripts", "*.tsv", "__pycache__"))
        shutil.copy(ROOT / "definitions.md", root / "definitions.md")
        return root

    def test_real_files(self):
        self.assertEqual(definitions_faults(ROOT), [])

    def test_control_repeated_row(self):
        root = self.scratch_root()
        row = next(l for l in (root / "skill" / "references" / "persona-boundaries.md").read_text().splitlines()
                   if l.startswith("| Pointer |"))
        with open(root / "definitions.md", "a", encoding="utf-8") as f:
            f.write("\n| Term | What it means in a review |\n|---|---|\n" + row + "\n")
        self.assertEqual(
            definitions_faults(root), ["the row 'Pointer' of persona-boundaries.md appears again in definitions.md"]
        )

    def test_control_definitions_in_the_skill(self):
        root = self.scratch_root()
        shutil.move(root / "definitions.md", root / "skill" / "references" / "definitions.md")
        answer = root / "skill" / "steps" / "answer.md"
        answer.write_text(answer.read_text().replace("references/persona-boundaries.md", "references/definitions.md"))
        self.assertEqual(
            definitions_faults(root),
            [
                "definitions.md is not at the plugin root",
                "skill/references/definitions.md is under skill/",
                "the reviewer's links do not reach references/persona-boundaries.md",
                "steps/answer.md links references/definitions.md",
            ],
        )


class TestGroundingT_B(ScratchCase):
    """The grounding drift test, on the frozen files and on three controls, one per fault; and the source-key test."""

    def setUp(self):
        super().setUp()
        self.questions = questions_text()
        self.grounding = GROUNDING.read_text(encoding="utf-8")
        self.sources = SOURCES.read_text(encoding="utf-8")

    def test_real_files(self):
        import sys

        sys.path.insert(0, str(SKILL / "scripts"))
        import questions

        # The count comes from the parts, through questions.py, so a new question needs no change here.
        self.assertEqual(len(question_titles(self.questions)), len(questions.load(QUESTIONS).questions))
        self.assertEqual(drift_faults(self.questions, self.grounding, self.sources), [])

    def test_control_title_missing_or_twice(self):
        lines = self.grounding.splitlines()
        one_job = next(l for l in lines if l.startswith("| One job |"))
        reasons = next(l for l in lines if l.startswith("| Reasons given |"))
        planted = "\n".join(l for l in lines if l != one_job).replace(reasons, reasons + "\n" + reasons)
        faults = drift_faults(self.questions, planted, self.sources)
        self.assertIn("'One job' is missing from the grounding table", faults)
        self.assertIn("'Reasons given' appears 2 times in the grounding table", faults)

    def test_control_key_without_a_source(self):
        planted = self.grounding.replace("| AN2, AN3 |", "| AN2, AN9 |", 1)
        self.assertNotEqual(planted, self.grounding)
        faults = drift_faults(self.questions, planted, self.sources)
        self.assertEqual(faults, ["'Bound parts agree with the prose': source key AN9 has no row in sources.md"])

    def test_control_url_missing(self):
        planted = self.questions + "\nAlso: <https://example.com/not-in-the-sources>.\n"
        faults = drift_faults(planted, self.grounding, self.sources)
        self.assertEqual(
            faults, ["https://example.com/not-in-the-sources, cited in the review questions, is missing from sources.md"]
        )

    def test_every_cited_key_has_a_source(self):
        self.assertEqual(key_faults(cited_texts(), self.sources), [])

    def test_control_cited_key_without_a_source(self):
        cited = cited_texts()
        cited["persona-boundaries.md"] += "\nSources: AN9.\n"
        cited["questions/score.md"] += "\nSources: ZZ1, AN1.\n"
        self.assertEqual(
            key_faults(cited, self.sources),
            ["questions/score.md cites ZZ1, which has no row in sources.md",
             "persona-boundaries.md cites AN9, which has no row in sources.md"],
        )


class TestEveryLink(ScratchCase):
    """Every link in every Markdown file under skill/, references included, names a file that exists."""

    def test_real_files(self):
        self.assertEqual(every_link_fault(SKILL), [])

    def test_control(self):
        skill = self.tmp / "skill"
        (skill / "references" / "questions").mkdir(parents=True)
        (skill / "reviewer.md").write_text("Read [`references/a.md`](references/a.md).\n")
        (skill / "references" / "a.md").write_text("See [`b.md`](b.md) and [the guide](https://example.com/guide).\n")
        (skill / "references" / "b.md").write_text("Then [`questions/c.md`](questions/c.md).\n")
        (skill / "references" / "questions" / "c.md").write_text("Back to [`../a.md`](../a.md).\n")
        self.assertEqual(every_link_fault(skill), [])
        # A reference linking a file that has left the folder, as grounding.md once linked vendor-terms.md.
        (skill / "references" / "b.md").write_text("Then [`questions/c.md`](questions/c.md) and "
                                                   "[`vendor-terms.md`](vendor-terms.md).\n")
        self.assertEqual(every_link_fault(skill), ["references/b.md links references/vendor-terms.md, which does not exist"])


class TestQuotedNames(ScratchCase):
    """A quoted name that its sentence calls a step, section and so on matches a heading, a bold step title or a
    question title, word for word."""

    def test_real_files(self):
        self.assertEqual(quoted_name_faults(SKILL), [])

    def test_control(self):
        skill = self.tmp / "skill"
        (skill / "references").mkdir(parents=True)
        (skill / "reviewer.md").write_text(
            "# Reviewer\n\n## Before you return\n\nCheck once more.\n\n## Steps\n\n"
            "1. **Run the script checks.** Run `check.py`.\n2. **Answer every other question.** Answer it.\n"
        )
        (skill / "references" / "q.md").write_text("**One job.** The persona does one thing.\n")
        (skill / "references" / "a.md").write_text(
            "Run it again at the step 'Run the script checks', as the 'Before you return' section says; the\n"
            "question 'One job' applies. A quotation such as 'Run the tests' is no name.\n"
        )
        self.assertEqual(
            quoted_names(skill),
            [("references/a.md", 1, "step", "Run the script checks"),
             ("references/a.md", 1, "section", "Before you return"),
             ("references/a.md", 2, "question", "One job")],
        )
        self.assertEqual(quoted_name_faults(skill), [])
        # The step's name with one word changed.
        (skill / "references" / "a.md").write_text("Run it again at the step 'Run the script check'.\n")
        self.assertEqual(
            quoted_name_faults(skill),
            ["references/a.md:1: the step 'Run the script check' matches no heading, bold step title or question title"],
        )


class TestSkillSourceKeys(ScratchCase):
    """The skill's own source keys, in grounding.md's 'Sources', match the keys cited under skill/, both ways. The
    tests of the plugin root's sources.md, in TestGroundingT_B, stay as they are."""

    def scratch_skill(self, cited, rows):
        """A scratch skill folder whose step cites the keys in cited and whose grounding.md gives rows to the keys in
        rows, with a run 'ST1 to ST3' cited in grounding.md outside 'Sources'."""
        skill = self.tmp / "skill"
        (skill / "steps").mkdir(parents=True, exist_ok=True)
        (skill / "references").mkdir(exist_ok=True)
        (skill / "steps" / "answer.md").write_text(f"Sources: {', '.join(cited)}.\n")
        table = "".join(f"| {key} | A source | 1 October 2026 |\n" for key in rows)
        (skill / "references" / "grounding.md").write_text(
            "# Grounding\n\n## Each question's support\n\nThe case rests on ST1 to ST3.\n\n"
            f"## Sources\n\n### Vendor documentation\n\n| Key | Source | Read |\n|---|---|---|\n{table}"
        )
        return skill

    def test_real_files(self):
        self.assertEqual(skill_key_faults(SKILL), [])

    def test_control_cited_key_without_a_row(self):
        skill = self.scratch_skill(["AN1", "AN2"], ["AN1", "AN2", "ST1", "ST2", "ST3"])
        self.assertEqual(skill_key_faults(skill), [])
        skill = self.scratch_skill(["AN1", "AN2", "ZZ9"], ["AN1", "AN2", "ST1", "ST2", "ST3"])
        self.assertEqual(skill_key_faults(skill), ["steps/answer.md cites ZZ9, which has no row in grounding.md's 'Sources'"])

    def test_control_row_nothing_cites(self):
        skill = self.scratch_skill(["AN1", "AN2"], ["AN1", "AN2", "ST1", "ST2", "ST3", "ZZ8"])
        self.assertEqual(
            skill_key_faults(skill),
            ["references/grounding.md:18: ZZ8 has a row in 'Sources', and nothing under skill/ outside that section "
             "cites it"],
        )


if __name__ == "__main__":
    unittest.main()
