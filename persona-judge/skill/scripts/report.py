#!/usr/bin/env python3
"""report.py: check a review record, render it as a report with its subtotals, total and stars, and recompute
a report's totals.

Usage:
  report.py schema                       print the JSON shape a review record takes
  report.py validate RECORD.json         check a review record; list every fault
  report.py render [--summary] RECORD.json
                                         validate, then render the report
  report.py verify REPORT                recompute every subtotal, total and star line a rendered report prints

'-' in place of a file reads standard input.

The reviewer writes its answers as a review record, one JSON file in the system's temporary folder and never
inside the reviewed project. 'validate' reads the files the record names, the review questions, the check table
and the bibliography's grounding table, and lists each fault with the file, the question, the finding's number,
the field, what is wrong and the fix. Fix the record and run 'validate' again until it exits 0, at most 3
reruns; past that the fault is in the review, not the record, so return the last messages and no report. Then
run 'render', which validates again before it prints anything, and delete the record.

'A dedicated persona' is answered first. A file scoring 0 on it is set aside, with the line behind it, and
answers nothing else. A file find.py sets aside (project instructions, an output style, a README or a skill)
is given as set_aside, with no answers. A persona spread over files names the files that load with it, each
with its reason, and the files left out, each with its reason; every finding names its file and line.

The script, not the reviewer, sets each check marked script from check.py's rows on every file of the
persona, sets each frequency rating's point from its places, computes the subtotals, the total and the stars,
prints each finding's sources from the bibliography's grounding table and prints the report, so the total
follows from the findings. The formula, from the review questions: each check counts its 1 or 0 and each
rating its point, from 0 to 6; each section, persona and instruction writing, has a subtotal 'x out of y', 1
for each check scored and 6 for each rating given; the two subtotals add to the total; the stars are x divided
by y, times 5, rounded to the nearest half star, a half rounding up. A question not scored or not rated leaves
both x and y.

The report is plain lines in a fenced text block, in this order: the stars, as five places with the number in
brackets, such as ★★★½☆ (3.5); the total; the two subtotals; the persona, its kind and the files reviewed and
left out; the lines that lowered the score, each with its file, line, question, note, rule and sources; the
persona questions and then the instruction-writing questions, each check as 'yes 1' or 'no 0' and each rating
as its point out of 6 with its word; the fit with neighbouring files, when the record gives it; the formula;
and the closing lines. A file set aside prints its path, 'set aside' and the reason, and nothing else.

Exit codes:
  validate  0 the record is sound; 2 it is not, with one message per fault
  render    0 rendered; 2 the record refused, with the reasons; 3 no persona got a total, because each is
            empty, set aside or no question applied to it
  verify    0 every printed subtotal, total and star line matches its checks and ratings; 1 one or more do
            not, each named; 2 the report cannot be parsed
This script changes no file.
"""

import json
import math
import os
import re
import sys
from fractions import Fraction

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import check  # noqa: E402
import find  # noqa: E402
import personafile  # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))
REFERENCES = os.path.join(HERE, "..", "references")
REVIEW_QUESTIONS = os.path.join(REFERENCES, "review-questions.md")
BIBLIOGRAPHY = os.path.join(REFERENCES, "bibliography.md")

# Exit codes, as the docstring states them (build specification §3e).
EXIT_OK = 0
EXIT_MISMATCH = 1
EXIT_REFUSED = 2
EXIT_NO_SCORE = 3

# Past three reruns of validate, a fault is in the review, not the record (build specification §3e).
MAX_VALIDATE_RERUNS = 3

# The question kinds: checks marked script or reading, and ratings on the frequency or quality scale.
SCRIPT, READING, FREQUENCY, QUALITY = "script", "reading", "frequency", "quality"
CHECK_KINDS = (SCRIPT, READING)
# The two sections of review-questions.md, each with its subtotal (review questions, 'Score').
PERSONA, WRITING = "persona", "instruction writing"
SECTIONS = (PERSONA, WRITING)
SECTION_HEADINGS = {PERSONA: "Persona", WRITING: "Instruction writing"}
# Where a question applies, as review-questions.md limits it: to a delegated persona only; where the file
# opens with an identity; not to a file with no settings; not to a file that asks for no particular form.
DELEGATED_ONLY, IDENTITY, SETTINGS, FORM = "delegated", "identity", "settings", "form"

# The thirty-three questions of review-questions.md, in its order: (title, section, kind, limit). A test reads
# review-questions.md and fails if this and the file disagree; at run time, validate refuses every record
# while they disagree.
QUESTIONS = (
    ("A dedicated persona", PERSONA, READING, None),
    ("Pointers carry their triggers", PERSONA, SCRIPT, None),
    ("Bound parts agree with the prose", PERSONA, SCRIPT, SETTINGS),
    ("Leaves the harness's work to the harness", PERSONA, SCRIPT, None),
    ("Enforceable rules enforced", PERSONA, READING, None),
    ("No procedure for one kind of task", PERSONA, READING, None),
    ("No facts the project already holds", PERSONA, READING, None),
    ("No pressure from consequences", PERSONA, READING, None),
    ("One job", PERSONA, READING, DELEGATED_ONLY),
    ("Declares its tools", PERSONA, SCRIPT, DELEGATED_ONLY),
    ("States its output", PERSONA, READING, DELEGATED_ONLY),
    ("Boundaries in three tiers", PERSONA, READING, None),
    ("Rules held in the persona", PERSONA, FREQUENCY, None),
    ("Directions for when nobody answers", PERSONA, FREQUENCY, None),
    ("Rules used in every act come first", PERSONA, FREQUENCY, None),
    ("Tools explained", PERSONA, FREQUENCY, None),
    ("Commands given exactly", PERSONA, FREQUENCY, None),
    ("The description says when to choose it", PERSONA, QUALITY, DELEGATED_ONLY),
    ("An identity that does the work", PERSONA, QUALITY, IDENTITY),
    ("No time-sensitive statements", WRITING, SCRIPT, None),
    ("Consistent with itself", WRITING, READING, None),
    ("Nothing said twice", WRITING, READING, None),
    ("Leaves known things unsaid", WRITING, READING, None),
    ("Plain emphasis", WRITING, SCRIPT, None),
    ("No placeholders", WRITING, SCRIPT, None),
    ("Shows an example", WRITING, READING, FORM),
    ("Terms defined where they are used", WRITING, FREQUENCY, None),
    ("Answers defined, edge cases included", WRITING, FREQUENCY, None),
    ("Its own criteria met", WRITING, FREQUENCY, None),
    ("Instructions an observer can check", WRITING, FREQUENCY, None),
    ("What to do, not what to avoid", WRITING, FREQUENCY, None),
    ("Reasons given", WRITING, FREQUENCY, None),
    ("Each instruction stands alone", WRITING, FREQUENCY, None),
)
BY_TITLE = {q[0]: q for q in QUESTIONS}
ORDER = {q[0]: i for i, q in enumerate(QUESTIONS)}
# Answered first; a 0 sets the file aside (review questions, 'A dedicated persona').
DEDICATED = "A dedicated persona"

# A check counts 1 or 0; a rating counts its point, from 0 to 6, and adds 6 to the points possible
# (review questions, 'Score').
CHECK_POINTS = 1
TOP_POINT = 6
# The scales' words by point (review questions, 'Checks and ratings': Brown's seven-point scales).
FREQUENCY_WORDS = {
    6: "always", 5: "almost always", 4: "usually", 3: "about half the time", 2: "seldom", 1: "almost never", 0: "never",
}
QUALITY_WORDS = {
    6: "exceptional", 5: "excellent", 4: "very good", 3: "good", 2: "fair", 1: "poor", 0: "very poor",
}
# The frequency bands, as the review questions give them: 5 is over 80%, below 100%; 4 is over 60%, up
# to 80%; 3 is 40% to 60%, both included; 2 is 20%, below 40%; 1 is more than none, below 20%.
OVER_FOR_5 = Fraction(80, 100)
OVER_FOR_4 = Fraction(60, 100)
FROM_FOR_3 = Fraction(40, 100)
FROM_FOR_2 = Fraction(20, 100)
# Stars: x divided by y, times 5, to the nearest half star (review questions, 'Score'), printed as five
# places: U+2605 for a full star, U+00BD for a half and U+2606 for an empty place.
STAR_PLACES = 5
FULL_STAR, HALF_STAR, EMPTY_STAR = "★", "½", "☆"
# The formula line shows x / y * 5 to two places (build specification §3e, item 8).
FORMULA_PLACES = 2
# Three spaces between the longest question title and its answer, so the answers align in one column.
COLUMN_GAP = 3
TITLE_WIDTH = max(len(q[0]) for q in QUESTIONS) + COLUMN_GAP
# Files under 'Files reviewed:' and 'Left out:' are indented by two spaces.
FILE_INDENT = "  "
# A finding's question and note, and its rule and sources, sit under it, indented by three spaces.
ITEM_INDENT = "   "

SESSION_TEXT = personafile.SESSION_TEXT
FENCE_OPEN, FENCE_CLOSE = "```text", "```"
LINES_HEADING = "Lines that lowered the score"
CLEAN_LINE = "Nothing was found."
FIT_HEADING = "Fit with neighbouring files, apart from the score"
NO_PREDICTION = "A score does not predict how the agent will behave. The quoted lines are what to act on."
LINTERS = "For secrets, hook scripts and server settings, use a configuration or security linter."
EMPTY_LINE = "This file is empty; no stars and no total."
NOTHING_APPLIES = "No question applies to this file; no stars and no total."
SET_ASIDE_PREFIX = "Set aside: "
SET_ASIDE_WORDS = "set aside"
MAIN_REASON = "the persona's main file"
FILES_HEADING = "Files reviewed:"
LEFT_OUT_HEADING = "Left out:"
NO_TOTAL = "no stars and no total"
NO_ROW_APPLIES = "no row of the check table applies to this file"
# A question with no sources in the grounding table rests on the reading alone (build specification §3e).
NO_SOURCES = "none"
NO_SOURCES_LINE = "Sources: none, reading alone"


# ---------------------------------------------------------------------------------------------------
# The formula


def frequency_point(meeting, counted):
    """The frequency scale's point for meeting places out of counted places."""
    if counted <= 0:
        raise ValueError("a rating with no places is not rated")
    share = Fraction(meeting, counted)
    if share == 1:
        return 6
    if share == 0:
        return 0
    if share > OVER_FOR_5:
        return 5
    if share > OVER_FOR_4:
        return 4
    if share >= FROM_FOR_3:
        return 3
    if share >= FROM_FOR_2:
        return 2
    return 1


def stars(x, y):
    """x out of y as stars: x / y * 5, to the nearest half star, a half rounding up."""
    return Fraction(math.floor(Fraction(2 * STAR_PLACES * x, y) + Fraction(1, 2)), 2)


def star_line(value):
    """Stars as five places with the number in brackets, such as ★★★½☆ (3.5)."""
    full = math.floor(value)
    half = 1 if value - full == Fraction(1, 2) else 0
    number = f"{full}.5" if half else str(full)
    return FULL_STAR * full + HALF_STAR * half + EMPTY_STAR * (STAR_PLACES - full - half) + f" ({number})"


def two_places(value):
    """A fraction to two places, a half rounding up, computed exactly."""
    scale = 10 ** FORMULA_PLACES
    n = math.floor(value * scale + Fraction(1, 2))
    return f"{n // scale}.{n % scale:0{FORMULA_PLACES}d}"


def words_for(kind):
    return FREQUENCY_WORDS if kind == FREQUENCY else QUALITY_WORDS


def plural(n, word):
    return f"{n} {word}" if n == 1 else f"{n} {word}s"


# ---------------------------------------------------------------------------------------------------
# The review questions and the bibliography


def limit_of(para):
    """Where a question applies, from the words review-questions.md uses for it, read across line breaks."""
    para = " ".join(para.split())
    if "Not scored for a standing persona" in para or "Rated for a delegated persona only" in para:
        return DELEGATED_ONLY
    if "Rated where the file opens with an identity" in para:
        return IDENTITY
    if "Not scored for a file with no settings" in para:
        return SETTINGS
    if "Not scored for a file that asks for no particular form" in para:
        return FORM
    return None


def file_questions(path=REVIEW_QUESTIONS):
    """review-questions.md's questions in its order: (title, section, kind, limit)."""
    text = open(path, encoding="utf-8").read()
    flags = re.MULTILINE | re.DOTALL
    out = []
    for heading, section in (("Persona questions", PERSONA), ("Instruction-writing questions", WRITING)):
        body = re.search(rf"^## {heading}\s*$(.*?)(?=^## |\Z)", text, flags)
        if not body:
            raise ValueError(f"review-questions.md has no '## {heading}' section")
        checks = re.search(r"^### Checks\s*$(.*?)(?=^### |\Z)", body.group(1), flags)
        ratings = re.search(r"^### Ratings\s*$(.*)", body.group(1), flags)
        if not checks or not ratings:
            raise ValueError(f"review-questions.md's '{heading}' has no '### Checks' or '### Ratings'")
        for para in re.split(r"\n\s*\n", checks.group(1)):
            m = re.match(r"\*\*(.+?)\*\* \(\*(script|reading)\*\)", para.strip())
            if m:
                out.append((m.group(1).rstrip("."), section, m.group(2), limit_of(para)))
        for para in re.split(r"\n\s*\n", ratings.group(1)):
            m = re.match(r"\*\*(.+?)\*\*", para.strip())
            if m:
                kind = QUALITY if "*Exceptional:*" in para else FREQUENCY
                out.append((m.group(1).rstrip("."), section, kind, limit_of(para)))
    return out


def disagreement(questions):
    """A message when review-questions.md's questions and QUESTIONS disagree, or None."""
    ours = list(QUESTIONS)
    if questions == ours:
        return None
    titles, our_titles = [q[0] for q in questions], [q[0] for q in ours]
    missing = [t for t in titles if t not in our_titles]
    extra = [t for t in our_titles if t not in titles]
    detail = []
    if missing:
        detail.append(f"in the file and not in report.py: {', '.join(missing)}")
    if extra:
        detail.append(f"in report.py and not in the file: {', '.join(extra)}")
    if not detail:
        detail.append("the same titles in another order, section, kind or limit")
    return (
        "review-questions.md and report.py's questions disagree (" + "; ".join(detail) + "); "
        "no record can be scored until report.py follows the file"
    )


def load_grounding(path=BIBLIOGRAPHY):
    """bibliography.md's grounding table as {question: its sources cell}, such as 'AN1, GH1' or 'none'."""
    text = open(path, encoding="utf-8").read()
    m = re.search(r"^## Grounding\s*$(.*?)(?=^## |\Z)", text, re.MULTILINE | re.DOTALL)
    if not m:
        raise ValueError("bibliography.md has no '## Grounding' section; no finding's sources can be printed")
    out, header = {}, None
    for line in m.group(1).splitlines():
        if not line.startswith("|") or re.match(r"^\|[\s|:-]+\|$", line):
            continue
        cells = [c.strip() for c in line.strip().strip("|").split("|")]
        if header is None:
            header = cells
            continue
        row = dict(zip(header, cells))
        if row.get("Question") and "Sources" in row:
            out[row["Question"]] = row["Sources"]
    if not out:
        raise ValueError("bibliography.md's grounding table has no rows; no finding's sources can be printed")
    return out


def sources_line(cell):
    return NO_SOURCES_LINE if cell.strip() == NO_SOURCES else f"Sources: {cell.strip()}"


# ---------------------------------------------------------------------------------------------------
# Validation


def fold(text):
    return " ".join(str(text).split())


def strip_quotes(text):
    text = str(text).strip()
    while len(text) >= 2 and text[0] == text[-1] and text[0] in "'\"":
        text = text[1:-1].strip()
    return text


def sentence(text):
    """Text as a sentence: a capital first letter and a closing full stop."""
    text = str(text).strip()
    if not text:
        return text
    text = text[0].upper() + text[1:]
    return text if text[-1] in ".!?" else text + "."


def kind_label(header):
    """The kind as a report prints it: 'subagent, Claude Code', 'persona' or 'project instructions'."""
    return header["kind"] + (f", {header['harness']}" if header.get("harness") else "")


class Prepared:
    """One persona of a record, validated: its header, its files, its answers and the findings it lists."""

    def __init__(self, path):
        self.path = path
        self.header = {}
        self.files = {}  # shown path -> PersonaFile, the main file first
        self.reviewed = [(path, MAIN_REASON)]  # (path, reason)
        self.left_out = []  # (path, reason)
        self.empty = False
        self.set_aside = None  # {"reason": ...} from find.py, or {"finding": ...} from the reviewer
        self.answers = []  # one per question, in QUESTIONS order
        self.items = []  # (question title, finding), in the order the report lists them
        self.fit = None


def quoted_line(pf, shown, prefix, item, faults):
    """Validate an item's line and quote in its file; return (line, the line's text) or None."""
    line = item.get("line")
    quote = item.get("quote")
    ok = True
    if quote is None or not str(quote).strip():
        faults.append(f"{prefix}, quote: missing; a finding with no quoted line is not reported; quote the line")
        ok = False
    if isinstance(line, bool) or not isinstance(line, int) or line < 1:
        faults.append(f"{prefix}, line: '{line}' is not a line number; give the number of the line quoted")
        return None
    if line > len(pf.lines):
        faults.append(f"{prefix}, line: cites line {line}, but {shown} has {len(pf.lines)} lines; quote a line that exists")
        return None
    if ok and fold(strip_quotes(quote)) not in fold(pf.lines[line - 1]):
        faults.append(
            f"{prefix}, quote: '{strip_quotes(quote)}' does not appear on line {line} of {shown}; "
            f"quote the line word for word, or cite the line that holds it"
        )
        ok = False
    return (line, pf.lines[line - 1].strip()) if ok else None


def file_of(p, prefix, item, faults):
    """The file an item names, as (shown path, PersonaFile), or None with a fault."""
    name = item.get("file")
    if not isinstance(name, str) or not name.strip():
        faults.append(f"{prefix}, file: missing; name the file the line is in, as the record names it")
        return None
    if name not in p.files:
        faults.append(
            f"{prefix}, file: {name} is not a file this review covers; name the persona's main file or a file "
            f"in loaded_with"
        )
        return None
    return name, p.files[name]


def finding(p, title, where, item, faults):
    """Validate one finding: its file, line, quote and note, and an optional second line in the same file it
    is set against. Return the finding the report prints, or None."""
    prefix = f"{p.path}, '{title}', {where}"
    if not isinstance(item, dict):
        faults.append(f"{prefix}: not an object; give file, line, quote and note")
        return None
    got_file = file_of(p, prefix, item, faults)
    got = quoted_line(got_file[1], got_file[0], prefix, item, faults) if got_file else None
    ok = got is not None
    if not str(item.get("note") or "").strip():
        faults.append(f"{prefix}, note: missing; say what in the line lowers the score")
        ok = False
    against = None
    if item.get("against") is not None:
        if not isinstance(item["against"], dict):
            faults.append(f"{prefix}, against: give the line and the quote it is set against")
            ok = False
        elif got_file:
            against = quoted_line(got_file[1], got_file[0], prefix + ", against", item["against"], faults)
            ok = ok and against is not None
    if not ok:
        return None
    return {
        "file": got_file[0], "line": got[0], "text": got[1], "against": against, "note": sentence(item["note"]),
        "rules": [item["rule"]] if item.get("rule") else [],
    }


def load_record(arg):
    """Read a record from a path or '-'. Return (record, faults)."""
    try:
        raw = sys.stdin.read() if arg == "-" else open(arg, encoding="utf-8").read()
    except OSError as exc:
        return None, [f"cannot read {arg}: {exc.strerror}; check the path"]
    if not raw.strip():
        return None, [f"{arg}: the record is empty; write the review record that 'report.py schema' describes"]
    try:
        record = json.loads(raw)
    except ValueError as exc:
        return None, [f"{arg}: the record is not JSON ({exc}); write the shape 'report.py schema' prints"]
    if not isinstance(record, dict) or not isinstance(record.get("files"), list) or not record["files"]:
        return None, [f"{arg}: the record holds no files; give a 'files' list with one entry per persona or file set aside"]
    return record, []


def named_files(entry, key, p, faults, must_exist, root):
    """Validate a list of {path, reason}; return [(path, reason, absolute path)]."""
    out = []
    items = entry.get(key) or []
    if not isinstance(items, list):
        faults.append(f"{p.path}, {key}: give a list of objects, each with a path and a reason")
        return out
    for k, item in enumerate(items, start=1):
        prefix = f"{p.path}, {key} {k}"
        if not isinstance(item, dict) or not isinstance(item.get("path"), str) or not item["path"].strip():
            faults.append(f"{prefix}, path: missing; name the file from the project root")
            continue
        if not str(item.get("reason") or "").strip():
            faults.append(f"{prefix}, reason: missing for {item['path']}; say why the file is {'reviewed' if must_exist else 'left out'}")
            continue
        absolute = item["path"] if os.path.isabs(item["path"]) else os.path.join(root, item["path"])
        if must_exist and not os.path.isfile(absolute):
            faults.append(f"{prefix}, path: {item['path']} does not exist; name a file the persona loads, or leave it out")
            continue
        out.append((item["path"], item["reason"].strip(), absolute))
    return out


def validate(record, table, grounding):
    """Validate a record; return (list of Prepared, list of fault messages)."""
    faults = []
    root = record.get("root") or os.getcwd()
    top = find.project_root(root)
    try:
        listing = find.read_list(record.get("list"), top, root)
    except personafile.PersonaError as exc:
        return [], [f"list: {exc}"]
    prepared = []
    seen_paths = set()
    for fi, entry in enumerate(record["files"], start=1):
        if not isinstance(entry, dict) or not isinstance(entry.get("path"), str) or not entry["path"]:
            faults.append(f"file {fi}, path: missing; name the file as find.py gives it, or {SESSION_TEXT}")
            continue
        path = entry["path"]
        if path in seen_paths:
            faults.append(f"{path}, path: reviewed twice in one record; give each file once")
            continue
        seen_paths.add(path)
        p = Prepared(path)
        try:
            if path == SESSION_TEXT:
                if not isinstance(entry.get("text"), str):
                    faults.append(f"{path}, text: missing; give the session text the review read")
                    continue
                pf = personafile.read_text(entry["text"], folder=root)
                p.header = find.record_for_text(pf)
            else:
                absolute = path if os.path.isabs(path) else os.path.join(root, path)
                p.header = find.classify(absolute, path, root, top, listing)
                pf = None if p.header.get("set_aside") else personafile.read_path(absolute, path)
        except personafile.PersonaError as exc:
            faults.append(f"{path}, path: {exc}")
            continue
        answered = [k for k in ("questions", "loaded_with", "left_out", "fit") if entry.get(k)]
        if p.header.get("set_aside"):
            if not entry.get("set_aside") or answered:
                faults.append(
                    f"{path}: find.py sets this file aside ({p.header['set_aside']}); give set_aside and no answers"
                )
                continue
            p.set_aside = {"reason": p.header["set_aside"]}
            prepared.append(p)
            continue
        if entry.get("set_aside"):
            faults.append(
                f"{path}, set_aside: find.py does not set this file aside; answer '{DEDICATED}' first, and set the "
                f"file aside only by scoring it 0 with the line behind it"
            )
            continue
        if entry.get("kind") and entry["kind"] != p.header["kind"]:
            faults.append(f"{path}, kind: '{entry['kind']}', but find.py gives {p.header['kind']}; copy the kind from find.py")
        p.files = {path: pf}
        for shown, reason, absolute in named_files(entry, "loaded_with", p, faults, True, root):
            if shown in p.files:
                faults.append(f"{path}, loaded_with: {shown} is named twice, or is the main file; give each file once")
                continue
            try:
                p.files[shown] = personafile.read_path(absolute, shown)
            except personafile.PersonaError as exc:
                faults.append(f"{path}, loaded_with: {exc}")
                continue
            p.reviewed.append((shown, reason))
        p.left_out = [(shown, reason) for shown, reason, _ in named_files(entry, "left_out", p, faults, False, root)]
        p.fit = entry.get("fit")
        p.header["bound_parts"] = [b for f in p.files.values() for b in f.bound_parts]
        prepared.append(p)
        questions = entry.get("questions") or []
        if not isinstance(questions, list):
            faults.append(f"{path}, questions: give a list with one answer per question")
            continue
        if pf.empty:
            p.empty = True
            if any(isinstance(q, dict) and not_answered(q) is None for q in questions):
                faults.append(f"{path}, questions: the file is empty; give no score and no rating")
            continue
        answers = {}
        for qi, q in enumerate(questions, start=1):
            if not isinstance(q, dict):
                faults.append(f"{path}, question {qi}: not an object; give the question and its answer")
                continue
            title = q.get("question")
            if title not in BY_TITLE:
                faults.append(
                    f"{path}, '{title}', question: is not a question in review-questions.md; "
                    f"use one of its bold titles word for word, without the full stop"
                )
                continue
            if title in answers:
                faults.append(f"{path}, '{title}', question: answered twice; answer each question once")
                continue
            answers[title] = q
        if not dedicated_answer(p, answers, faults):
            continue
        rows = []
        for shown, f in p.files.items():
            rows += check.check_one(shown, f, p.header["kind"], p.header["delegated"], p.header.get("harness"), table, top)
        resolved = {}
        for title, section, kind, limit in QUESTIONS:
            q = answers.get(title)
            if q is None and kind != SCRIPT:
                faults.append(f"{path}, '{title}', question: missing; answer it, or mark it not scored or not rated with the reason")
                continue
            if title not in grounding:
                faults.append(
                    f"{path}, '{title}', question: bibliography.md's grounding table does not hold it, so its "
                    f"sources cannot be printed; the grounding table needs a row for it"
                )
            own_rows = [r for r in rows if r["question"] == title]
            resolved[title] = resolve(p, title, section, kind, limit, q, own_rows, faults)
        p.answers = [resolved[q[0]] for q in QUESTIONS if q[0] in resolved]
        file_rank = {name: i for i, name in enumerate([path] + sorted(n for n in p.files if n != path))}
        p.items = sorted(
            ((a["title"], f) for a in p.answers for f in a["findings"]),
            key=lambda t: (ORDER[t[0]], file_rank[t[1]["file"]], t[1]["line"]),
        )
        if p.fit is not None:
            check_fit(p, root, faults)
    return prepared, faults


def dedicated_answer(p, answers, faults):
    """'A dedicated persona', answered first. Return True when the review goes on to the other questions;
    False when the record is faulty or the file is set aside on a 0."""
    q = answers.get(DEDICATED)
    if q is None:
        faults.append(f"{p.path}, '{DEDICATED}', question: missing; answer it first, before every other question")
        return False
    score = q.get("score")
    if isinstance(score, bool) or score not in (0, 1):
        faults.append(f"{p.path}, '{DEDICATED}', score: '{score}'; a check scores 1 or 0")
        return False
    if score == 1:
        return True
    others = [t for t in answers if t != DEDICATED]
    if others or p.left_out or len(p.files) > 1 or p.fit is not None:
        faults.append(
            f"{p.path}, '{DEDICATED}': scored 0, so the file is set aside and carries no other answer; "
            f"remove the other answers ({', '.join(others) or 'its files and fit'})"
        )
    given = q.get("findings") or []
    if not given:
        faults.append(f"{p.path}, '{DEDICATED}', findings: a check at 0 quotes the line behind it; add a finding")
        return False
    got = finding(p, DEDICATED, "finding 1", given[0], faults)
    if got:
        p.set_aside = {"finding": got}
    return False


def not_answered(q):
    """The reason a question is not scored or not rated, or None; either key is read for either."""
    for key in ("not_scored", "not_rated"):
        if key in q:
            return q[key] if isinstance(q[key], str) else ""
    return None


def resolve(p, title, section, kind, limit, q, rows, faults):
    """Validate one answer and return what the report prints for it."""
    path = p.path
    out = {"title": title, "section": section, "type": kind, "point": None, "findings": [], "not_rated": None}
    reason = not_answered(q) if q is not None else None
    if kind == SCRIPT:
        return resolve_script(p, out, q, reason, rows, faults)
    if reason is not None:
        if not reason.strip():
            faults.append(f"{path}, '{title}', not_rated: give the reason it is not scored or not rated")
        out["not_rated"] = reason or "not given"
        return out
    if limit == DELEGATED_ONLY and not p.header["delegated"]:
        what = "scored" if kind in CHECK_KINDS else "rated"
        faults.append(
            f"{path}, '{title}', {'score' if kind in CHECK_KINDS else 'scale'}: a standing persona is not {what} on "
            f"this question; mark it not {what} with the reason"
        )
        return out
    if kind == READING:
        score = q.get("score")
        if isinstance(score, bool) or not isinstance(score, int) or score not in (0, 1):
            faults.append(f"{path}, '{title}', score: '{score}'; a check scores 1 or 0")
            return out
        given = q.get("findings") or []
        if score == 1 and given:
            faults.append(f"{path}, '{title}', findings: a check at 1 has no findings; remove them or score 0")
        if score == 0 and not given:
            faults.append(f"{path}, '{title}', findings: a check at 0 quotes the line behind it; add a finding")
        for k, f in enumerate(given, start=1):
            got = finding(p, title, f"finding {k}", f, faults)
            if got:
                out["findings"].append(got)
        out["point"] = score
        return out
    if q.get("scale") != kind:
        faults.append(f"{path}, '{title}', scale: '{q.get('scale')}'; this question is rated on the {kind} scale")
        return out
    if kind == FREQUENCY:
        places = q.get("places")
        if not isinstance(places, list) or not places:
            faults.append(
                f"{path}, '{title}', places: none listed; list every place the question applies to, "
                f"or mark it not rated when there is none"
            )
            return out
        meeting = 0
        for k, place in enumerate(places, start=1):
            prefix = f"{path}, '{title}', place {k}"
            if not isinstance(place, dict) or not isinstance(place.get("meets"), bool):
                faults.append(f"{prefix}, meets: give true or false")
                continue
            if place["meets"]:
                meeting += 1
                got_file = file_of(p, prefix, place, faults)
                if got_file:
                    quoted_line(got_file[1], got_file[0], prefix, place, faults)
                continue
            got = finding(p, title, f"place {k}", place, faults)
            if got:
                out["findings"].append(got)
        out["places"], out["meeting"] = len(places), meeting
        out["point"] = frequency_point(meeting, len(places))
        return out
    point = q.get("point")
    if isinstance(point, bool) or not isinstance(point, int) or not 0 <= point <= TOP_POINT:
        faults.append(f"{path}, '{title}', point: '{point}'; give a whole number from 0 to {TOP_POINT}")
        return out
    given = q.get("findings") or []
    if point < TOP_POINT and not given:
        faults.append(f"{path}, '{title}', findings: a rating below its top point lists its lines; quote them")
    for k, f in enumerate(given, start=1):
        got = finding(p, title, f"finding {k}", f, faults)
        if got:
            out["findings"].append(got)
    out["point"] = point
    return out


def resolve_script(p, out, q, reason, rows, faults):
    """A check marked script takes its score from check.py's rows alone, on every file of the persona
    (build specification §3d)."""
    path, title = p.path, out["title"]
    scored = [r for r in rows if r["score"] is not None]
    zero = [r for r in scored if r["score"] == check.ZERO]
    rows_score = None if not scored else (0 if zero else 1)
    if q is not None:
        if reason is not None and rows_score is not None:
            faults.append(
                f"{path}, '{title}', not_scored: check.py's rows score it {rows_score}; a script check takes its "
                f"score from its rows; give score {rows_score} or leave the question out"
            )
        if reason is None:
            score = q.get("score")
            if isinstance(score, bool) or not isinstance(score, int) or score not in (0, 1):
                faults.append(f"{path}, '{title}', score: '{score}'; a check scores 1 or 0")
            elif rows_score is None:
                faults.append(
                    f"{path}, '{title}', score: {score}, but {NO_ROW_APPLIES}, so it is not scored; "
                    f"mark it not scored or leave the question out"
                )
            elif score != rows_score:
                r = zero[0] if zero else scored[0]
                at = f" at {r['path']}, line {r['line']}" if zero else ""
                faults.append(
                    f"{path}, '{title}', score: scored {score}, but check.py row {r['id']} scored {r['score']}{at}; "
                    f"a script check takes its rows' score; give {rows_score} or leave the question out"
                )
        given = q.get("findings") or []
        if given and rows_score != 0:
            faults.append(f"{path}, '{title}', findings: a check at 1 has no findings; remove them")
        for k, f in enumerate(given, start=1):
            got = finding(p, title, f"finding {k}", f, faults)
            if got:
                out["findings"].append(got)
    if rows_score is None:
        notes = [r["message"] for r in rows if r.get("message")]
        out["not_rated"] = notes[0] if notes else NO_ROW_APPLIES
        return out
    for r in zero:
        for hit in r["lines"]:
            add_row_finding(p, out, r, hit)
    out["point"] = rows_score
    return out


def add_row_finding(p, out, r, hit):
    """Enter a line a row scored 0 under its question, merged with a finding already on that line."""
    pf = p.files[r["path"]]
    if hit.get("field_line"):
        line, text = hit["field_line"], hit["field_quote"]
        against = (hit["line"], pf.lines[hit["line"] - 1].strip())
        note = r["row_message"]
    else:
        line = hit["line"]
        text = pf.lines[line - 1].strip()
        against = None
        note = r["row_message"] + (f": {hit['note']}" if hit.get("note") else "")
    for f in out["findings"]:
        if f["file"] == r["path"] and f["line"] == line:
            if r["id"] not in f["rules"]:
                f["rules"].append(r["id"])
            return
    out["findings"].append(
        {"file": r["path"], "line": line, "text": text, "against": against, "note": sentence(note), "rules": [r["id"]]}
    )


def check_fit(p, root, faults):
    fit = p.fit
    if not isinstance(fit, dict) or not (fit.get("statement") or fit.get("findings")):
        faults.append(f"{p.path}, fit: give a statement, or findings each with a quoted line and a note")
        return
    for k, f in enumerate(fit.get("findings") or [], start=1):
        name = f.get("file") or p.path
        other = p.files.get(name)
        if other is None:
            target = name if os.path.isabs(name) else os.path.join(root, name)
            try:
                other = personafile.read_path(target, name)
            except personafile.PersonaError as exc:
                faults.append(f"{p.path}, fit, finding {k}, file: {exc}")
                continue
        if not str(f.get("note") or "").strip():
            faults.append(f"{p.path}, fit, finding {k}, note: missing; say what the line shows about the fit")
        got = quoted_line(other, name, f"{p.path}, fit, finding {k}", f, faults)
        if got:
            f["_text"] = got[1]


# ---------------------------------------------------------------------------------------------------
# Rendering


def totals(p):
    """{section: (x, y)} and the total (x, y) for a persona: the points given and the points possible."""
    by_section = {s: (0, 0) for s in SECTIONS}
    for a in p.answers:
        if a.get("point") is None:
            continue
        x, y = by_section[a["section"]]
        by_section[a["section"]] = (x + a["point"], y + (CHECK_POINTS if a["type"] in CHECK_KINDS else TOP_POINT))
    total = (sum(x for x, _ in by_section.values()), sum(y for _, y in by_section.values()))
    return by_section, total


def review_lines(p):
    out = [f"Review: {p.path} ({kind_label(p.header)})", FILES_HEADING]
    out += [f"{FILE_INDENT}{name}: {reason}" for name, reason in p.reviewed]
    if p.left_out:
        out += [LEFT_OUT_HEADING] + [f"{FILE_INDENT}{name}: {reason}" for name, reason in p.left_out]
    else:
        out.append(f"{LEFT_OUT_HEADING} none")
    return out


def answer_value(a):
    if a.get("point") is None:
        word = "not scored" if a["type"] in CHECK_KINDS else "not rated"
        return f"{word}{' ' * COLUMN_GAP}{sentence(a.get('not_rated') or NO_ROW_APPLIES)}"
    if a["type"] in CHECK_KINDS:
        return "yes 1" if a["point"] == 1 else "no  0"
    return f"{a['point']} of {TOP_POINT}{' ' * COLUMN_GAP}{words_for(a['type'])[a['point']]}"


def answer_lines(p):
    out = []
    for section in SECTIONS:
        if out:
            out.append("")
        out.append(SECTION_HEADINGS[section])
        out += [f"{a['title']:<{TITLE_WIDTH}}{answer_value(a)}" for a in p.answers if a["section"] == section]
    return out


def item_lines(k, title, f, grounding):
    where = f"{k}. {f['file']}, line {f['line']}: '{f['text']}'"
    if f.get("against"):
        where += f", against line {f['against'][0]}: '{f['against'][1]}'"
    rules = f"Rule {', '.join(f['rules'])}. " if f["rules"] else ""
    return [where, f"{ITEM_INDENT}{title}. {f['note']}", f"{ITEM_INDENT}{rules}{sources_line(grounding.get(title, NO_SOURCES))}"]


def fit_lines(p):
    fit = p.fit or {}
    out = [FIT_HEADING]
    for k, f in enumerate(fit.get("findings") or [], start=1):
        out += [f"{k}. {f.get('file') or p.path}, line {f.get('line')}: '{f.get('_text', '')}'", f"{ITEM_INDENT}{sentence(f.get('note', ''))}"]
    if fit.get("statement"):
        out.append(fit["statement"])
    return out


def set_aside_lines(p, grounding):
    head = f"{SET_ASIDE_PREFIX}{p.path} ({kind_label(p.header)})"
    if "reason" in p.set_aside:
        return [head, sentence(p.set_aside["reason"])]
    f = p.set_aside["finding"]
    return [
        head,
        f"{DEDICATED}. {f['note']}",
        f"{f['file']}, line {f['line']}: '{f['text']}'",
        sources_line(grounding.get(DEDICATED, NO_SOURCES)),
    ]


def set_aside_reason(p):
    """The reason a summary prints for a file set aside."""
    if "reason" in p.set_aside:
        return p.set_aside["reason"]
    return f"not a dedicated persona: {p.set_aside['finding']['note'].rstrip('.')}"


def render_one(p, grounding=None):
    """One file's report, without its fence; return (text, (x, y) or None)."""
    grounding = grounding or {}
    if p.set_aside:
        return "\n".join(set_aside_lines(p, grounding)), None
    if p.empty:
        return "\n".join([EMPTY_LINE, ""] + review_lines(p)), None
    by_section, (x, y) = totals(p)
    if y == 0:
        return "\n".join([NOTHING_APPLIES, ""] + review_lines(p) + [""] + answer_lines(p)), None
    out = [star_line(stars(x, y)), f"Total: {x} out of {y}"]
    out += [f"{SECTION_HEADINGS[s]}: {by_section[s][0]} out of {by_section[s][1]}" for s in SECTIONS]
    out += [""] + review_lines(p) + ["", LINES_HEADING]
    if p.items:
        for k, (title, f) in enumerate(p.items, start=1):
            out += item_lines(k, title, f, grounding)
    else:
        out.append(CLEAN_LINE)
    out += [""] + answer_lines(p) + [""]
    if p.fit is not None:
        out += fit_lines(p) + [""]
    (px, py), (wx, wy) = by_section[PERSONA], by_section[WRITING]
    out += [
        f"Formula: each check counts 1 or 0 and each rating its points; persona {px} out of {py}, "
        f"instruction writing {wx} out of {wy}, total {x} out of {y}.",
        f"Stars: {x} ÷ {y} × {STAR_PLACES} = {two_places(Fraction(x * STAR_PLACES, y))}, to the nearest half star.",
        NO_PREDICTION,
    ]
    if p.header.get("bound_parts"):
        out.append(LINTERS)
    return "\n".join(out), (x, y)


def fenced(text):
    return f"{FENCE_OPEN}\n{text}\n{FENCE_CLOSE}"


def render(prepared, summary, grounding=None):
    """Return (the rendered text, whether no persona got a total)."""
    done = [(p,) + render_one(p, grounding) for p in prepared]
    blocks = []
    if summary:
        personas = sorted(
            (t for t in done if not t[0].set_aside),
            key=lambda t: (t[2] is None, Fraction(t[2][0], t[2][1]) if t[2] else 0, t[0].path),
        )
        aside = sorted((t for t in done if t[0].set_aside), key=lambda t: t[0].path)
        done = personas + aside
        width = max(len(p.path) for p, _, _ in done) + COLUMN_GAP
        kind_width = max([len(SET_ASIDE_WORDS)] + [len(p.header["kind"]) for p, _, _ in personas]) + COLUMN_GAP
        star_width = len(star_line(Fraction(7, 2))) + COLUMN_GAP
        lines = [
            f"Summary: {plural(len(personas), 'persona')} reviewed, from the lowest total; "
            f"{plural(len(aside), 'file')} set aside"
        ]
        for p, _, xy in personas:
            head = f"{p.path:<{width}}{p.header['kind']:<{kind_width}}"
            lines.append(head + (f"{star_line(stars(*xy)):<{star_width}}{xy[0]} out of {xy[1]}" if xy else NO_TOTAL))
        for p, _, _ in aside:
            lines.append(f"{p.path:<{width}}{SET_ASIDE_WORDS:<{kind_width}}{set_aside_reason(p)}")
        blocks.append(fenced("\n".join(lines)))
    blocks += [fenced(text) for _, text, _ in done]
    return "\n\n".join(blocks), all(xy is None for _, _, xy in done)


# ---------------------------------------------------------------------------------------------------
# Verify


STAR_RE = re.compile(rf"^[{FULL_STAR}{HALF_STAR}{EMPTY_STAR}]{{{STAR_PLACES}}} \(\d+(?:\.5)?\)$")
TOTAL_RE = re.compile(r"^Total: (\d+) out of (\d+)$")
SUBTOTAL_RE = {s: re.compile(rf"^{SECTION_HEADINGS[s]}: (\d+) out of (\d+)$") for s in SECTIONS}
REVIEW_RE = re.compile(r"^Review: (.+) \(([^()]+)\)$")
FORMULA_RE = re.compile(
    r"^Formula: .*; persona (\d+) out of (\d+), instruction writing (\d+) out of (\d+), total (\d+) out of (\d+)\.$"
)
STARS_FORMULA_RE = re.compile(r"^Stars: (\d+) ÷ (\d+) × 5 = (\d+\.\d+), to the nearest half star\.$")
RATING_RE = re.compile(rf"^(\d) of {TOP_POINT}\b")


def blocks_of(text):
    found = re.findall(rf"^{re.escape(FENCE_OPEN)}\n(.*?)\n{re.escape(FENCE_CLOSE)}$", text, re.MULTILINE | re.DOTALL)
    return [b.splitlines() for b in found] if found else [text.splitlines()]


def recompute(lines, section):
    """(x, y) from a report's lines under one section heading, or None when they cannot be read."""
    try:
        start = lines.index(SECTION_HEADINGS[section])
    except ValueError:
        return None
    x = y = 0
    for line in lines[start + 1:]:
        if not line.strip():
            break
        q = next((q for q in QUESTIONS if line.startswith(q[0] + " ")), None)
        if q is None:
            return None
        value = line[len(q[0]):].strip()
        if value.startswith(("not scored", "not rated")):
            continue
        if q[2] in CHECK_KINDS:
            if re.fullmatch(r"yes +1", value):
                x, y = x + 1, y + CHECK_POINTS
            elif re.fullmatch(r"no +0", value):
                y += CHECK_POINTS
            else:
                return None
        else:
            m = RATING_RE.match(value)
            if not m:
                return None
            x, y = x + int(m.group(1)), y + TOP_POINT
    return x, y


def verify(text):
    """Return (exit code, messages)."""
    messages, mismatch, computed, reports = [], False, {}, 0
    summary_rows = []
    for lines in blocks_of(text):
        lines = [l.rstrip() for l in lines]
        if not lines:
            continue
        if lines[0].startswith("Summary"):
            summary_rows = lines[1:]
            continue
        if lines[0].startswith(SET_ASIDE_PREFIX):
            reports += 1
            continue
        review = next((REVIEW_RE.match(l) for l in lines if REVIEW_RE.match(l)), None)
        if lines[0] in (EMPTY_LINE, NOTHING_APPLIES):
            if review:
                computed[review.group(1)] = (review.group(2), None)
                reports += 1
            continue
        if not STAR_RE.match(lines[0]):
            continue
        reports += 1
        total = TOTAL_RE.match(lines[1]) if len(lines) > 1 else None
        subtotals = {s: SUBTOTAL_RE[s].match(lines[2 + i]) if len(lines) > 2 + i else None for i, s in enumerate(SECTIONS)}
        parts = {s: recompute(lines, s) for s in SECTIONS}
        if not review or not total or not all(subtotals.values()) or not all(parts.values()):
            return EXIT_REFUSED, ["a report has no review line, no total, no subtotals or unreadable checks and ratings; it cannot be checked"]
        path = review.group(1)
        x, y = sum(v[0] for v in parts.values()), sum(v[1] for v in parts.values())
        if not y:
            return EXIT_REFUSED, [f"{path}: its checks and ratings give no points possible; it cannot be checked"]
        computed[path] = (review.group(2), (x, y))
        for i, s in enumerate(SECTIONS):
            got = (int(subtotals[s].group(1)), int(subtotals[s].group(2)))
            if got != parts[s]:
                mismatch = True
                messages.append(
                    f"{path}: prints '{lines[2 + i]}', but its {SECTION_HEADINGS[s].lower()} checks and ratings give "
                    f"{parts[s][0]} out of {parts[s][1]}"
                )
        want_stars = star_line(stars(x, y))
        if (int(total.group(1)), int(total.group(2))) != (x, y):
            mismatch = True
            messages.append(f"{path}: prints '{lines[1]}', but its checks and ratings give {x} out of {y}")
        if lines[0] != want_stars:
            mismatch = True
            messages.append(f"{path}: prints the stars '{lines[0]}', but its checks and ratings give '{want_stars}'")
        formula = next((FORMULA_RE.match(l) for l in lines if FORMULA_RE.match(l)), None)
        want = (parts[PERSONA] + parts[WRITING] + (x, y))
        if formula and tuple(int(g) for g in formula.groups()) != want:
            mismatch = True
            messages.append(
                f"{path}: the formula line prints persona {formula.group(1)} out of {formula.group(2)}, instruction "
                f"writing {formula.group(3)} out of {formula.group(4)}, total {formula.group(5)} out of "
                f"{formula.group(6)}, but its checks and ratings give persona {want[0]} out of {want[1]}, "
                f"instruction writing {want[2]} out of {want[3]}, total {x} out of {y}"
            )
        sf = next((STARS_FORMULA_RE.match(l) for l in lines if STARS_FORMULA_RE.match(l)), None)
        if sf:
            want_sf = (str(x), str(y), two_places(Fraction(x * STAR_PLACES, y)))
            if sf.groups() != want_sf:
                mismatch = True
                messages.append(
                    f"{path}: the stars line prints {sf.group(1)} ÷ {sf.group(2)} × 5 = {sf.group(3)}, "
                    f"but its checks and ratings give {want_sf[0]} ÷ {want_sf[1]} × 5 = {want_sf[2]}"
                )
    if not reports:
        return EXIT_REFUSED, ["no report found: no line of stars, set-aside line or empty-file line, followed by a review line"]
    for row in summary_rows:
        path = max((p for p in computed if row.startswith(p + " ")), key=len, default=None)
        if path is None:
            continue
        label, xy = computed[path]
        kind = label.split(",")[0]
        want = f"{kind} {NO_TOTAL}" if xy is None else f"{kind} {star_line(stars(*xy))} {xy[0]} out of {xy[1]}"
        rest = row[len(path):]
        if " ".join(rest.split()) != " ".join(want.split()):
            mismatch = True
            messages.append(f"summary, {path}: prints '{rest.strip()}', but its report gives '{want}'")
    if not mismatch:
        messages.append(f"every printed subtotal, total and star line matches its checks and ratings: {reports} reports")
    return (EXIT_MISMATCH if mismatch else EXIT_OK), messages


# ---------------------------------------------------------------------------------------------------
# Schema


FILE_REF = {"type": "string", "description": "The file the line is in: the main path, or a path in loaded_with."}

FINDING = {
    "type": "object",
    "required": ["file", "line", "quote", "note"],
    "properties": {
        "file": FILE_REF,
        "line": {"type": "integer", "minimum": 1},
        "quote": {"type": "string", "description": "The line, or part of it, word for word."},
        "note": {"type": "string", "description": "What in the line lowers the score, in one sentence."},
        "against": {
            "type": "object",
            "description": "A second line in the same file the first is set against, such as the prose a setting contradicts.",
            "required": ["line", "quote"],
            "properties": {"line": {"type": "integer", "minimum": 1}, "quote": {"type": "string"}},
        },
        "rule": {"type": "string", "description": "A check.py row ID, such as PJ-001."},
    },
}

NAMED_FILE = {
    "type": "object",
    "required": ["path", "reason"],
    "properties": {
        "path": {"type": "string", "description": "From the project root."},
        "reason": {"type": "string", "description": "Why the file is reviewed with the persona, or left out."},
    },
}

SCHEMA = {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "title": "persona-judge review record",
    "description": (
        "Written by the reviewer to one file in the system's temporary folder, never inside the reviewed "
        "project. Paths are relative to root. One entry per persona, and one per file find.py sets aside. For "
        "each persona, answer the thirty-three questions of review-questions.md by their bold titles without "
        "the full stop, 'A dedicated persona' first: a 0 there sets the file aside, and the entry then holds that "
        "answer alone. A check marked script may be left out: check.py's rows set it. Every finding and place "
        "names its file and quotes its line word for word with its number. The report prints each finding's "
        "sources from bibliography.md and orders the findings by question, then file, then line."
    ),
    "type": "object",
    "required": ["files"],
    "properties": {
        "root": {"type": "string", "description": "The project's folder; the working folder when absent."},
        "list": {"type": "string", "description": "The project's list when not personas.txt at the root, as --list names it."},
        "files": {
            "type": "array",
            "minItems": 1,
            "items": {
                "type": "object",
                "required": ["path"],
                "properties": {
                    "path": {"type": "string", "description": "As find.py gives it, or <session text>; for a persona, its main file."},
                    "text": {"type": "string", "description": "For <session text> only: the text reviewed."},
                    "set_aside": {
                        "type": "boolean",
                        "description": "true for a file find.py sets aside, with no other field; the report prints find.py's reason.",
                    },
                    "kind": {"type": "string", "description": "Optional; as find.py gives it."},
                    "loaded_with": {
                        "type": "array",
                        "description": "The other files reviewed with the persona, each with why it loads with it.",
                        "items": NAMED_FILE,
                    },
                    "left_out": {
                        "type": "array",
                        "description": "The nearby files not reviewed, each with the reason.",
                        "items": NAMED_FILE,
                    },
                    "questions": {
                        "type": "array",
                        "description": (
                            "One answer per question. A check: score, and findings at 0. A frequency rating: "
                            "scale and places. A quality rating: scale, point and, below 6, findings. Or "
                            "not_scored (a check) or not_rated (a rating) with the reason."
                        ),
                        "items": {
                            "type": "object",
                            "required": ["question"],
                            "properties": {
                                "question": {"type": "string"},
                                "score": {"enum": [0, 1], "description": "Checks only."},
                                "scale": {"enum": ["frequency", "quality"], "description": "Ratings only."},
                                "point": {"type": "integer", "minimum": 0, "maximum": TOP_POINT,
                                          "description": "Quality ratings only; frequency points are counted."},
                                "places": {
                                    "type": "array",
                                    "description": "Frequency ratings: every place the question applies to, in any file of the persona.",
                                    "items": {
                                        "type": "object",
                                        "required": ["file", "line", "quote", "meets"],
                                        "properties": {
                                            "file": FILE_REF,
                                            "line": {"type": "integer", "minimum": 1},
                                            "quote": {"type": "string"},
                                            "meets": {"type": "boolean"},
                                            "note": {"type": "string", "description": "When meets is false: what lowers it."},
                                        },
                                    },
                                },
                                "findings": {"type": "array", "items": FINDING},
                                "not_scored": {"type": "string", "description": "A check: the reason it is not scored."},
                                "not_rated": {"type": "string", "description": "A rating: the reason it is not rated."},
                            },
                        },
                    },
                    "fit": {
                        "type": "object",
                        "description": "Fit with neighbouring files, apart from the score; only when neighbours were supplied.",
                        "properties": {
                            "statement": {"type": "string"},
                            "findings": {
                                "type": "array",
                                "items": {
                                    "type": "object",
                                    "required": ["line", "quote", "note"],
                                    "properties": {
                                        "file": {"type": "string", "description": "The file quoted; the reviewed file when absent."},
                                        "line": {"type": "integer", "minimum": 1},
                                        "quote": {"type": "string"},
                                        "note": {"type": "string"},
                                    },
                                },
                            },
                        },
                    },
                },
            },
        },
    },
}


# ---------------------------------------------------------------------------------------------------


def main(argv):
    if not argv or argv[0] in ("-h", "--help"):
        print(__doc__.strip())
        return EXIT_OK if argv else EXIT_REFUSED
    cmd, args = argv[0], argv[1:]
    if cmd == "schema" and not args:
        print(json.dumps(SCHEMA, indent=2, ensure_ascii=False))
        return EXIT_OK
    if cmd == "verify" and len(args) == 1:
        try:
            text = sys.stdin.read() if args[0] == "-" else open(args[0], encoding="utf-8").read()
        except OSError as exc:
            print(f"report.py: cannot read {args[0]}: {exc.strerror}; check the path", file=sys.stderr)
            return EXIT_REFUSED
        code, messages = verify(text)
        for m in messages:
            print(m, file=sys.stderr if code == EXIT_REFUSED else sys.stdout)
        return code
    summary = False
    if cmd == "render" and args and args[0] == "--summary":
        summary, args = True, args[1:]
    if cmd not in ("validate", "render") or len(args) != 1:
        print("report.py: usage: report.py schema | validate RECORD | render [--summary] RECORD | verify REPORT",
              file=sys.stderr)
        return EXIT_REFUSED
    try:
        problem = disagreement(file_questions())
        table = check.load_table(check.DEFAULT_TABLE)
        grounding = load_grounding()
    except (OSError, ValueError, check.TableError) as exc:
        print(f"report.py: cannot load the review questions, the check table or the bibliography: {exc}", file=sys.stderr)
        return EXIT_REFUSED
    if problem:
        print(f"report.py: {problem}", file=sys.stderr)
        return EXIT_REFUSED
    record, faults = load_record(args[0])
    prepared = []
    if record is not None:
        prepared, faults = validate(record, table, grounding)
    if faults:
        stream = sys.stdout if cmd == "validate" else sys.stderr
        for f in faults:
            print(f, file=stream)
        print(
            f"{len(faults)} faults. Fix the record and run validate again, at most {MAX_VALIDATE_RERUNS} reruns; "
            f"past that, return these messages and no report.",
            file=stream,
        )
        return EXIT_REFUSED
    if cmd == "validate":
        print(f"The record is sound: {plural(len(prepared), 'file')}, every question answered.")
        return EXIT_OK
    text, nothing = render(prepared, summary, grounding)
    print(text)
    return EXIT_NO_SCORE if nothing else EXIT_OK


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
