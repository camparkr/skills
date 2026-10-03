#!/usr/bin/env python3
"""questions.py: read review-questions.md under its markup contract, and give every question, weight, scale and
table the other scripts score with.

Usage:
  questions.py [FILE] [--format text|json]

FILE defaults to references/review-questions.md beside this folder. No script holds a question, a count of
questions or a count of points: report.py and check.py read them through this module each time they run, so a
change to the questions needs no change to the scripts.

The contract, the only markup read:
  question sections   a level-2 heading ending 'questions', such as '## Persona questions'; its label drops
                      ' questions' and reads '-' as a space
  groups              '### Checks' and '### Ratings' within a question section
  a check             a paragraph opening '**Title** (*script*).' or '**Title** (*reading*).', with ', weight N'
                      inside the brackets for a weight above 1
  a rating            a paragraph opening '**Title** (*scale*).', the scale defined under 'Scales'
  the root question   the first check of the first question section
  scales              within '## Checks and ratings', a heading '### <Name> scale' and a table whose first two
                      columns are Point and Word; a third column, 'Share of places that meet the question', gives
                      bands: 'all', 'none', 'over A%, below B%', 'over A%, up to B%', 'A% to B%', 'A%, below B%'
                      or 'more than none, below B%'
  tables              in '## Which questions apply, and their weights': the branches (Key, Branch, How it is
                      read, When the answer is no, these do not apply, Reason printed); the content tests
                      (Question, Applies when the file holds, Reason printed); the following ratings (Rating,
                      Follows check, Reason printed); the harness exceptions (Question, Harness, Reason printed,
                      Source); and the weights (Check, Why it weighs more, Evidence), read only for the order in
                      which the formula names the weighted checks
Every title a table names must be a question's title, word for word.

Output: the questions, sections, weights, scales, tables and points, as text or, with --format json, as one JSON
object.

Exit codes: 0 the file meets the contract; 2 it does not, with the line and what was expected, or a usage error.
This script changes no file.
"""

import json
import os
import re
import sys
from dataclasses import dataclass, field
from fractions import Fraction

HERE = os.path.dirname(os.path.abspath(__file__))
REVIEW_QUESTIONS = os.path.join(HERE, "..", "references", "review-questions.md")

# Exit codes, as the docstring states them (build specification §3e).
EXIT_OK = 0
EXIT_REFUSED = 2

CHECK, RATING = "check", "rating"
SCRIPT, READING = "script", "reading"
CHECK_KINDS = (SCRIPT, READING)
# The branch keys the contract names, in the order a question's first reason is taken (§3e).
BRANCH_KEYS = ("delegated", "harness", "settings")
# The headings and table columns the contract names.
SECTION_SUFFIX = " questions"
SCALES_SECTION = "Checks and ratings"
APPLY_SECTION = "Which questions apply, and their weights"
SHARE_COLUMN = "Share of places that meet the question"
BRANCH_COLUMNS = ["Key", "Branch", "How it is read", "When the answer is no, these do not apply", "Reason printed"]
CONTENT_COLUMNS = ["Question", "Applies when the file holds", "Reason printed"]
FOLLOWING_COLUMNS = ["Rating", "Follows check", "Reason printed"]
EXCEPTION_COLUMNS = ["Question", "Harness", "Reason printed", "Source"]
WEIGHT_COLUMNS = ["Check", "Why it weighs more", "Evidence"]
# A table is known by its first column; its columns must then be exactly the contract's.
TABLES_BY_FIRST = {
    "Key": ("branches", BRANCH_COLUMNS),
    "Rating": ("following", FOLLOWING_COLUMNS),
    "Check": ("weights", WEIGHT_COLUMNS),
}
TITLES_SEPARATOR = "; "

CHECK_MARK = re.compile(r"^\*\*([^*]+)\*\* \(\*(script|reading)\*(?:, weight (\d+))?\)\.(?:\s|$)")
RATING_MARK = re.compile(r"^\*\*([^*]+)\*\* \(\*([a-z]+)\*\)\.(?:\s|$)")
SCALE_HEADING = re.compile(r"^### (\w+) scale\s*$")
# The band forms the contract lists: each gives (low, low included, high, high included) as percentages.
BAND_FORMS = (
    (re.compile(r"^all$"), lambda m: (100, True, 100, True)),
    (re.compile(r"^none$"), lambda m: (0, True, 0, True)),
    (re.compile(r"^over (\d+)%, below (\d+)%$"), lambda m: (int(m[1]), False, int(m[2]), False)),
    (re.compile(r"^over (\d+)%, up to (\d+)%$"), lambda m: (int(m[1]), False, int(m[2]), True)),
    (re.compile(r"^(\d+)% to (\d+)%$"), lambda m: (int(m[1]), True, int(m[2]), True)),
    (re.compile(r"^(\d+)%, below (\d+)%$"), lambda m: (int(m[1]), True, int(m[2]), False)),
    (re.compile(r"^more than none, below (\d+)%$"), lambda m: (0, False, int(m[1]), False)),
)


class ContractError(Exception):
    """review-questions.md breaks the contract; the message names the line and what was expected."""

    def __init__(self, name, line, problem, expected):
        self.line = line
        super().__init__(f"{name}, line {line}: {problem}; expected {expected}")


@dataclass
class Question:
    title: str
    section: str
    kind: str  # 'script', 'reading' or 'rating'
    scale: str = None  # a rating's scale
    weight: int = 1  # a check's weight
    line: int = 0


@dataclass
class Scale:
    name: str
    words: dict  # point -> word
    bands: list = None  # [(point, low, low included, high, high included)] for a share-based scale
    line: int = 0

    @property
    def top(self):
        return max(self.words)

    def point(self, meeting, counted):
        """The point for meeting places out of counted places, from the bands."""
        if not self.bands:
            raise ValueError(f"the {self.name} scale has no bands; its point is chosen, not counted")
        if counted <= 0:
            raise ValueError("a rating with no places has no share")
        share = Fraction(100 * meeting, counted)
        for point, low, low_in, high, high_in in self.bands:
            above = share > low or (low_in and share == low)
            below = share < high or (high_in and share == high)
            if above and below:
                return point
        raise ValueError(f"no band of the {self.name} scale holds {float(share):.1f}%")


@dataclass
class Branch:
    key: str
    removes: list
    reason: str
    fields: list = field(default_factory=list)


@dataclass
class Questions:
    questions: list
    sections: list
    scales: dict
    branches: dict
    content_tests: dict  # title -> (what the file must hold, reason)
    following: dict  # rating -> (check, reason)
    exceptions: list  # (question, harness, reason, source)
    weights_table: list
    path: str = ""

    def __post_init__(self):
        self.by_title = {q.title: q for q in self.questions}

    @property
    def root(self):
        return self.questions[0].title

    @property
    def settings_fields(self):
        return self.branches["settings"].fields

    def points(self, title):
        """A question's points: a check's weight, or a rating scale's top point."""
        q = self.by_title[title]
        return q.weight if q.kind in CHECK_KINDS else self.scales[q.scale].top

    @property
    def possible(self):
        return sum(self.points(q.title) for q in self.questions)

    def section_points(self, section):
        return sum(self.points(q.title) for q in self.questions if q.section == section)

    def weighted_checks(self):
        """The checks weighing more than 1, in the order the weights table names them, then any it does not."""
        weighted = [q.title for q in self.questions if q.kind in CHECK_KINDS and q.weight > 1]
        return [t for t in self.weights_table if t in weighted] + [t for t in weighted if t not in self.weights_table]


def _cells(line):
    return [c.strip() for c in line.strip().strip("|").split("|")]


def _is_rule(line):
    return bool(re.match(r"^\|[\s|:-]+\|$", line.strip()))


def _tables(lines, start, end):
    """Each Markdown table between start and end: (header line number, header cells, [(line number, cells)])."""
    out, i = [], start
    while i < end:
        if lines[i].startswith("|") and i + 1 < end and _is_rule(lines[i + 1]):
            header, rows, j = _cells(lines[i]), [], i + 2
            while j < end and lines[j].startswith("|"):
                rows.append((j + 1, _cells(lines[j])))
                j += 1
            out.append((i + 1, header, rows))
            i = j
        else:
            i += 1
    return out


def _paragraph_starts(lines, start, end):
    """The line indexes that open a paragraph between start and end."""
    return [i for i in range(start, end) if lines[i].strip() and (i == start or not lines[i - 1].strip())]


def load(path=REVIEW_QUESTIONS):
    """Read review-questions.md under the contract; raise ContractError naming the line when it breaks it."""
    name = os.path.basename(os.fspath(path))
    with open(path, encoding="utf-8") as fh:
        lines = fh.read().splitlines()

    def fail(index, problem, expected):
        raise ContractError(name, index + 1, problem, expected)

    headings = [(i, l[3:].strip()) for i, l in enumerate(lines) if l.startswith("## ")]
    bounds = {h: (i, headings[k + 1][0] if k + 1 < len(headings) else len(lines)) for k, (i, h) in enumerate(headings)}

    # Scales.
    if SCALES_SECTION not in bounds:
        raise ContractError(name, 1, f"no '## {SCALES_SECTION}' section", f"a '## {SCALES_SECTION}' section holding the scales")
    s0, s1 = bounds[SCALES_SECTION]
    scales = {}
    for i in range(s0, s1):
        m = SCALE_HEADING.match(lines[i])
        if not m:
            continue
        scale_name = m.group(1).lower()
        following = [t for t in _tables(lines, i + 1, s1) if t[0] > i + 1]
        if not following:
            fail(i, f"the {scale_name} scale has no table", "a table with columns Point and Word after the heading")
        hline, header, rows = following[0]
        if header[:2] != ["Point", "Word"] or len(header) > 3 or (len(header) == 3 and header[2] != SHARE_COLUMN):
            fail(hline - 1, f"the {scale_name} scale's table has columns {', '.join(header)}",
                 f"Point, Word and, for bands, '{SHARE_COLUMN}'")
        words, bands = {}, [] if len(header) == 3 else None
        for rline, cells in rows:
            if len(cells) != len(header) or not cells[0].isdigit():
                fail(rline - 1, f"a row of the {scale_name} scale reads '{' | '.join(cells)}'", "a whole-number point and a word")
            point = int(cells[0])
            if point in words:
                fail(rline - 1, f"point {point} is given twice", "each point once")
            words[point] = cells[1]
            if bands is not None:
                for pattern, read in BAND_FORMS:
                    bm = pattern.match(cells[2])
                    if bm:
                        bands.append((point,) + read(bm))
                        break
                else:
                    fail(rline - 1, f"the band '{cells[2]}' is in no listed form",
                         "'all', 'none', 'over A%, below B%', 'over A%, up to B%', 'A% to B%', 'A%, below B%' or "
                         "'more than none, below B%'")
        if not words:
            fail(hline - 1, f"the {scale_name} scale's table has no rows", "one row per point")
        scales[scale_name] = Scale(scale_name, words, bands, i + 1)

    # Questions.
    questions, sections, seen = [], [], {}
    for h, (h0, h1) in bounds.items():
        if not h.endswith(SECTION_SUFFIX):
            continue
        label = h[: -len(SECTION_SUFFIX)].replace("-", " ")
        label = label[:1].upper() + label[1:].lower()
        sections.append(label)
        group = None
        for i in range(h0 + 1, h1):
            line = lines[i]
            if line.startswith("### "):
                group = {"### Checks": CHECK, "### Ratings": RATING}.get(line.strip())
                if group is None:
                    fail(i, f"the heading '{line.strip()}' in a question section", "'### Checks' or '### Ratings'")
                continue
            if not line.startswith("**") or (i > h0 + 1 and lines[i - 1].strip()):
                continue
            if group is None:
                fail(i, "a question before '### Checks' or '### Ratings'", "the question under one of those headings")
            if group == CHECK:
                m = CHECK_MARK.match(line)
                if not m:
                    fail(i, f"the check '{line[:60]}' has no mark in the contract's form",
                         "'**Title** (*script*).' or '**Title** (*reading*).', with ', weight N' for a weight above 1")
                weight = int(m.group(3)) if m.group(3) else 1
                if m.group(3) and weight < 2:
                    fail(i, f"the check '{m.group(1)}' is marked weight {weight}", "', weight N' only for a weight above 1")
                q = Question(m.group(1), label, m.group(2), None, weight, i + 1)
            else:
                m = RATING_MARK.match(line)
                if not m:
                    fail(i, f"the rating '{line[:60]}' has no scale mark",
                         "'**Title** (*scale*).', the scale one defined under '### <Name> scale'")
                q = Question(m.group(1), label, RATING, m.group(2), 1, i + 1)
            if q.title in seen:
                fail(i, f"the title '{q.title}' is given twice (first at line {seen[q.title]})", "each question's title once")
            seen[q.title] = i + 1
            questions.append(q)
    if not questions:
        raise ContractError(name, 1, "no question section", "a '## … questions' section with '### Checks'")
    if questions[0].kind not in CHECK_KINDS:
        fail(questions[0].line - 1, f"the first question, '{questions[0].title}', is a rating", "the root question to be a check")
    for q in questions:
        if q.kind == RATING and q.scale not in scales:
            fail(q.line - 1, f"the rating '{q.title}' names the scale '{q.scale}', which the file never defines",
                 f"one of the scales defined under '## {SCALES_SECTION}': {', '.join(sorted(scales))}")
    for label in sections:
        if not any(q.section == label for q in questions):
            fail(bounds[label + SECTION_SUFFIX][0] if label + SECTION_SUFFIX in bounds else 0,
                 f"the section '{label}' holds no question", "at least one check or rating")
    titles = {q.title for q in questions}

    # The tables of what applies.
    if APPLY_SECTION not in bounds:
        raise ContractError(name, 1, f"no '## {APPLY_SECTION}' section", "the section holding the branch table")
    a0, a1 = bounds[APPLY_SECTION]
    found = {}
    for hline, header, rows in _tables(lines, a0, a1):
        first = header[0]
        if first == "Question":
            kind, columns = ("exceptions", EXCEPTION_COLUMNS) if "Harness" in header else ("content", CONTENT_COLUMNS)
        elif first in TABLES_BY_FIRST:
            kind, columns = TABLES_BY_FIRST[first]
        else:
            continue
        if header != columns:
            fail(hline - 1, f"the {kind} table's columns are {', '.join(header)}", f"the columns {', '.join(columns)}")
        if kind in found:
            fail(hline - 1, f"a second {kind} table", f"one {kind} table")
        for rline, cells in rows:
            if len(cells) != len(columns):
                fail(rline - 1, f"a row of the {kind} table has {len(cells)} cells", f"{len(columns)} cells")
        found[kind] = rows

    def known(rline, title, what):
        if title not in titles:
            fail(rline - 1, f"the {what} names '{title}', which is not a question's title",
                 "a question's title, word for word")
        return title

    if "branches" not in found:
        raise ContractError(name, a0 + 1, "no branch table", f"a table with the columns {', '.join(BRANCH_COLUMNS)}")
    branches = {}
    for rline, cells in found["branches"]:
        key = cells[0]
        if key not in BRANCH_KEYS or key in branches:
            fail(rline - 1, f"the branch key '{key}'", f"each of {', '.join(BRANCH_KEYS)} once")
        removes = [known(rline, t.strip(), "branch table") for t in cells[3].split(TITLES_SEPARATOR.strip()) if t.strip()]
        fields = re.findall(r"`([^`]+)`", cells[2]) if key == "settings" else []
        branches[key] = Branch(key, removes, cells[4], fields)
    for key in BRANCH_KEYS:
        if key not in branches:
            fail(found["branches"][0][0] - 2 if found["branches"] else a0,
                 f"the branch table has no '{key}' row", f"a row for each of {', '.join(BRANCH_KEYS)}")
    if not branches["settings"].fields:
        fail(found["branches"][0][0] - 1, "the settings row names no field in backticks", "the settings fields in backticks")
    ordered = {k: branches[k] for k in BRANCH_KEYS}

    content = {}
    for rline, cells in found.get("content", []):
        content[known(rline, cells[0], "content-test table")] = (cells[1], cells[2])
    following = {}
    for rline, cells in found.get("following", []):
        rating, check = known(rline, cells[0], "following table"), known(rline, cells[1], "following table")
        by = {q.title: q for q in questions}
        if by[rating].kind != RATING or by[check].kind not in CHECK_KINDS:
            fail(rline - 1, f"'{rating}' follows '{check}'", "a rating that follows a check")
        following[rating] = (check, cells[2])
    exceptions = [
        (known(rline, cells[0], "harness-exception table"), cells[1], cells[2], cells[3])
        for rline, cells in found.get("exceptions", [])
    ]
    weights_table = [known(rline, cells[0], "weights table") for rline, cells in found.get("weights", [])]
    return Questions(questions, sections, scales, ordered, content, following, exceptions, weights_table, os.fspath(path))


_CACHE = {}


def load_cached(path=REVIEW_QUESTIONS):
    """load(), once per path and modification time in one run."""
    key = (os.path.abspath(path), os.path.getmtime(path))
    if key not in _CACHE:
        _CACHE[key] = load(path)
    return _CACHE[key]


def as_dict(qs):
    return {
        "sections": qs.sections,
        "root": qs.root,
        "questions": [
            {"title": q.title, "section": q.section, "kind": q.kind, "scale": q.scale, "weight": q.weight,
             "points": qs.points(q.title), "line": q.line}
            for q in qs.questions
        ],
        "scales": {
            s.name: {"points": {str(p): w for p, w in sorted(s.words.items())}, "top": s.top,
                     "bands": [list(b) for b in s.bands] if s.bands else None}
            for s in qs.scales.values()
        },
        "branches": {k: {"removes": b.removes, "reason": b.reason, "fields": b.fields} for k, b in qs.branches.items()},
        "content_tests": {t: {"holds": h, "reason": r} for t, (h, r) in qs.content_tests.items()},
        "following": {t: {"check": c, "reason": r} for t, (c, r) in qs.following.items()},
        "exceptions": [{"question": q, "harness": h, "reason": r, "source": s} for q, h, r, s in qs.exceptions],
        "weighted": [{"title": t, "weight": qs.by_title[t].weight} for t in qs.weighted_checks()],
        "possible": qs.possible,
        "section_points": {s: qs.section_points(s) for s in qs.sections},
    }


def main(argv):
    if "-h" in argv or "--help" in argv:
        print(__doc__.strip())
        return EXIT_OK
    fmt, paths = "text", []
    i = 0
    while i < len(argv):
        if argv[i] == "--format":
            if i + 1 >= len(argv) or argv[i + 1] not in ("text", "json"):
                print("questions.py: --format takes text or json", file=sys.stderr)
                return EXIT_REFUSED
            fmt = argv[i + 1]
            i += 2
            continue
        paths.append(argv[i])
        i += 1
    if len(paths) > 1:
        print("questions.py: name one file, or none for references/review-questions.md", file=sys.stderr)
        return EXIT_REFUSED
    path = paths[0] if paths else REVIEW_QUESTIONS
    try:
        qs = load(path)
    except OSError as exc:
        print(f"questions.py: cannot read {path}: {exc.strerror}; check the path", file=sys.stderr)
        return EXIT_REFUSED
    except ContractError as exc:
        print(f"questions.py: {exc}", file=sys.stderr)
        return EXIT_REFUSED
    data = as_dict(qs)
    if fmt == "json":
        print(json.dumps(data, indent=2, ensure_ascii=False))
        return EXIT_OK
    for section in qs.sections:
        print(f"{section}: {sum(1 for q in qs.questions if q.section == section)} questions, {qs.section_points(section)} points")
        for q in (q for q in qs.questions if q.section == section):
            what = q.kind + (f", weight {q.weight}" if q.kind in CHECK_KINDS and q.weight > 1 else "") if q.kind in CHECK_KINDS else q.scale
            print(f"  {q.title} ({what})")
    print(f"Points possible: {qs.possible}")
    for key, b in qs.branches.items():
        print(f"Branch {key}: removes {', '.join(b.removes)}; reason '{b.reason}'" + (f"; fields {', '.join(b.fields)}" if b.fields else ""))
    return EXIT_OK


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
