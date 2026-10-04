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

Every question, weight, scale and count comes from review-questions.md, read at run time by questions.py; this
script holds none. A file that breaks the questions' markup contract stops it with exit 2, naming the line.

The reviewer writes its answers as a review record, one JSON file in the system's temporary folder and never
inside the reviewed project. 'validate' reads the files the record names, the review questions, the check table
and the bibliography's grounding table, and lists each fault with the file, the question, the finding's number,
the field, what is wrong and the fix. Fix the record and run 'validate' again until it exits 0, at most 3
reruns; past that the fault is in the review, not the record, so return the last messages and no report. Then
run 'render', which validates again before it prints anything, and delete the record.

The root question, the first check of review-questions.md, is answered first. A file scoring 0 on it is set
aside, with the line behind it, and answers nothing else. A file find.py sets aside is given as set_aside, with
no answers. Each persona gives its three branches as find.py prints them, which validate checks against the
files. A question does not apply only for a reason review-questions.md's tables give: a branch at no, a harness
exception, a following rating whose check scored 0, or a content test whose subject the file does not hold. Mark
such a question with does_not_apply and that reason, or leave it out where the branches, the rows or the
exception decide it; answer every question that applies. For a content-test question, give the subject line that
holds what it tests for, or mark it as not applying.

The script, not the reviewer, sets each check marked script from check.py's rows on every file of the persona (a
script check that applies and that no row reaches scores 1), sets each frequency rating's point from its places,
computes the subtotals, the total, the total at equal weights and the stars, prints each finding's sources from the
bibliography's grounding table and prints the report. The formula, from the review questions: each check counts
its weight or 0, and each rating its point; the points possible are every check's weight and every rating scale's
top point; a question that does not apply leaves both x and y; each section's subtotal is x out of y; the two add
to the total; the stars are x divided by y, times 5, rounded to the nearest half star, a half rounding up.

The report is plain lines in a fenced text block, in this order: the stars, as five places with the number in
brackets, such as ★★★½☆ (3.5); the total, with the points possible and those that do not apply; each section's
subtotal; the persona, its kind, its branches and the files reviewed and left out; the questions that do not apply,
each with its reason, and, when more than half the points possible do not apply, a line saying the file says
little; the lines that lowered the score, each with its file, line, question, note, rule and
sources; each section's checks as 'yes' with the weight or 'no 0' and its ratings as their point with the word;
the fit with neighbouring files, when the record gives it; the formula with the weights; the total at equal
weights; the stars line; and the closing lines. A file set aside prints its path, 'set aside' and the reason.

Exit codes:
  validate  0 the record is sound; 2 it is not, with one message per fault
  render    0 rendered; 2 the record refused, with the reasons; 3 no persona got a total, because each is
            empty, set aside or no question applied to it
  verify    0 every printed subtotal, total and star line matches its checks and ratings; 1 one or more do
            not, each named; 2 the report cannot be parsed
  any       2 review-questions.md breaks its markup contract, naming the line
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
import questions  # noqa: E402

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

SCRIPT, READING, RATING = questions.SCRIPT, questions.READING, questions.RATING
CHECK_KINDS = questions.CHECK_KINDS
# How a check, weighed as 1, counts in the total at equal weights (review questions, 'Weights').
EQUAL_WEIGHT = 1

# Stars: x divided by y, times 5, to the nearest half star (review questions, 'Score'), printed as five
# places: U+2605 for a full star, U+00BD for a half and U+2606 for an empty place.
STAR_PLACES = 5
FULL_STAR, HALF_STAR, EMPTY_STAR = "★", "½", "☆"
# The formula line shows x / y * 5 to two places (build specification §3e, item 9).
FORMULA_PLACES = 2
# Three spaces between the longest question title and its answer, so the answers align in one column.
COLUMN_GAP = 3
# Files under 'Files reviewed:' and 'Files left out:', and the questions under 'Do not apply:', are indented by
# two spaces.
FILE_INDENT = "  "

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
LEFT_OUT_HEADING = "Files left out:"
DO_NOT_APPLY_HEADING = "Do not apply:"
DO_NOT_APPLY_NONE = "Do not apply: none."
DOES_NOT_APPLY = "does not apply"
# Printed under 'Do not apply' when the points that do not apply exceed THIN_SHARE of the points possible, which
# the file derives; the share is the ruling's, not a count of questions or points (Sophos, 4 October 2026).
THIN_LINE = "Most questions do not apply: this file says little, and the score covers only what it says."
THIN_SHARE = Fraction(1, 2)
BRANCHES_PREFIX = "Branches: "
NO_TOTAL = "no stars and no total"
# A question with no sources in the grounding table rests on the reading alone (build specification §3e).
NO_SOURCES = "none"
NO_SOURCES_LINE = "Sources: none, reading alone"
# The record's key for a question that does not apply, and the keys round 3 used, now refused.
DNA_KEY = "does_not_apply"
OLD_KEYS = ("not_scored", "not_rated")


# ---------------------------------------------------------------------------------------------------
# The formula


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


def plural(n, word):
    return f"{n} {word}" if n == 1 else f"{n} {word}s"


def and_list(names):
    return names[0] if len(names) == 1 else ", ".join(names[:-1]) + " and " + names[-1]


def weights_phrase(qs):
    """The weighted checks as the formula names them, such as 'A, B and C weigh 3', read from the file."""
    groups = {}
    for title in qs.weighted_checks():
        groups.setdefault(qs.by_title[title].weight, []).append(title)
    parts = [f"{and_list(t)} {'weighs' if len(t) == 1 else 'weigh'} {w}" for w, t in sorted(groups.items())]
    return "; ".join(parts) + ", every other check 1" if parts else "every check 1"


# ---------------------------------------------------------------------------------------------------
# The bibliography


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

    def __init__(self, path, qs=None):
        self.path = path
        self.qs = qs or questions.load_cached()
        self.header = {}
        self.files = {}  # shown path -> PersonaFile, the main file first
        self.reviewed = [(path, MAIN_REASON)]  # (path, reason)
        self.left_out = []  # (path, reason)
        self.empty = False
        self.set_aside = None  # {"reason": ...} from find.py, or {"finding": ...} from the reviewer
        self.answers = []  # one per question, in the file's order
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


def branches_of(header):
    """The three branches a header gives, as a record states them."""
    return {"delegated": bool(header["delegated"]), "harness": header.get("harness"), "settings": list(header.get("settings") or [])}


def check_branches(p, entry, faults):
    """The record's branches must match those find.py reads from the files."""
    given = entry.get("branches")
    want = branches_of(p.header)
    if not isinstance(given, dict):
        faults.append(
            f"{p.path}, branches: missing; copy them from find.py: {find.branch_text(p.header)}"
        )
        return
    got = {"delegated": given.get("delegated"), "harness": given.get("harness"),
           "settings": sorted(given.get("settings") or [])}
    if got != dict(want, settings=sorted(want["settings"])):
        faults.append(
            f"{p.path}, branches: the record gives delegated {given.get('delegated')}, harness {given.get('harness')}, "
            f"settings {', '.join(given.get('settings') or []) or 'none'}; find.py reads {find.branch_text(p.header)}; "
            f"copy the branches from find.py"
        )


def validate(record, table, grounding, qs=None):
    """Validate a record; return (list of Prepared, list of fault messages)."""
    qs = qs or questions.load_cached()
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
        p = Prepared(path, qs)
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
                f"{path}, set_aside: find.py does not set this file aside; answer '{qs.root}' first, and set the "
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
        answers_given = entry.get("questions") or []
        if not isinstance(answers_given, list):
            faults.append(f"{path}, questions: give a list with one answer per question")
            continue
        if pf.empty:
            p.empty = True
            if any(isinstance(q, dict) and DNA_KEY not in q for q in answers_given):
                faults.append(f"{path}, questions: the file is empty; give no score and no rating")
            continue
        answers = {}
        for qi, q in enumerate(answers_given, start=1):
            if not isinstance(q, dict):
                faults.append(f"{path}, question {qi}: not an object; give the question and its answer")
                continue
            title = q.get("question")
            if title not in qs.by_title:
                faults.append(
                    f"{path}, '{title}', question: is not a question in review-questions.md; "
                    f"use one of its bold titles word for word"
                )
                continue
            if title in answers:
                faults.append(f"{path}, '{title}', question: answered twice; answer each question once")
                continue
            old = [k for k in OLD_KEYS if k in q]
            if old:
                faults.append(
                    f"{path}, '{title}', {old[0]}: refused; a question that does not apply is marked {DNA_KEY} with a "
                    f"reason review-questions.md gives, and every other question is answered"
                )
                continue
            answers[title] = q
        if not root_answer(p, answers, faults):
            continue
        check_branches(p, entry, faults)
        rows = []
        for shown, f in p.files.items():
            rows += check.check_one(shown, f, p.header["kind"], p.header["delegated"], p.header.get("harness"), table, top)
        resolved = {}
        # Checks first, so a rating that follows a check can read its score.
        for q in sorted(qs.questions, key=lambda q: q.kind == RATING):
            if q.title not in grounding:
                faults.append(
                    f"{path}, '{q.title}', question: bibliography.md's grounding table does not hold it, so its "
                    f"sources cannot be printed; the grounding table needs a row for it"
                )
            own_rows = [r for r in rows if r["question"] == q.title]
            resolved[q.title] = resolve(p, q, answers.get(q.title), own_rows, resolved, faults)
        p.answers = [resolved[q.title] for q in qs.questions]
        order = {q.title: i for i, q in enumerate(qs.questions)}
        file_rank = {name: i for i, name in enumerate([path] + sorted(n for n in p.files if n != path))}
        p.items = sorted(
            ((a["title"], f) for a in p.answers for f in a["findings"]),
            key=lambda t: (order[t[0]], file_rank[t[1]["file"]], t[1]["line"]),
        )
        if p.fit is not None:
            check_fit(p, root, faults)
    return prepared, faults


def root_answer(p, answers, faults):
    """The root question, answered first. Return True when the review goes on to the other questions; False when
    the record is faulty or the file is set aside on a 0."""
    root = p.qs.root
    q = answers.get(root)
    if q is None:
        faults.append(f"{p.path}, '{root}', question: missing; answer it first, before every other question")
        return False
    score = q.get("score")
    if isinstance(score, bool) or score not in (0, 1):
        faults.append(f"{p.path}, '{root}', score: '{score}'; a check scores 1 or 0")
        return False
    if score == 1:
        return True
    others = [t for t in answers if t != root]
    if others or p.left_out or len(p.files) > 1 or p.fit is not None:
        faults.append(
            f"{p.path}, '{root}': scored 0, so the file is set aside and carries no other answer; "
            f"remove the other answers ({', '.join(others) or 'its files and fit'})"
        )
    given = q.get("findings") or []
    if not given:
        faults.append(f"{p.path}, '{root}', findings: a check at 0 quotes the line behind it; add a finding")
        return False
    got = finding(p, root, "finding 1", given[0], faults)
    if got:
        p.set_aside = {"finding": got}
    return False


def removed_by(p, title):
    """The reason a branch or a harness exception gives for a question not applying, or None."""
    qs = p.qs
    no = {"delegated": not p.header["delegated"], "harness": not p.header.get("harness"),
          "settings": not p.header.get("settings")}
    for key, branch in qs.branches.items():
        if no[key] and title in branch.removes:
            return branch.reason
    for question, harness, reason, _ in qs.exceptions:
        if question == title and p.header.get("harness") == harness:
            return reason
    return None


def applies(p, title, resolved):
    """('removed', reason) when the branches, an exception or a following check decide the question does not
    apply; ('content', reason) when its content test decides; ('applies', None) otherwise."""
    qs = p.qs
    reason = removed_by(p, title)
    if reason:
        return "removed", reason
    if title in qs.following:
        check_title, follow_reason = qs.following[title]
        followed = resolved.get(check_title)
        if followed and not followed.get(DNA_KEY) and followed.get("point") is not None:
            return ("removed", follow_reason) if followed["point"] == 0 else ("applies", None)
    if title in qs.content_tests:
        return "content", qs.content_tests[title][1]
    return "applies", None


def resolve(p, q, answer, rows, resolved, faults):
    """Validate one answer and return what the report prints for it."""
    path, title, qs = p.path, q.title, p.qs
    out = {"title": title, "section": q.section, "type": q.kind, "scale": q.scale, "weight": q.weight,
           "point": None, "findings": [], DNA_KEY: None}
    how, reason = applies(p, title, resolved)
    given_dna = answer.get(DNA_KEY) if answer is not None else None
    if how == "removed":
        if answer is not None and given_dna is None:
            faults.append(
                f"{path}, '{title}', question: does not apply here ({reason}); remove the answer, or mark it "
                f"{DNA_KEY} with that reason"
            )
        elif given_dna is not None and given_dna != reason:
            faults.append(
                f"{path}, '{title}', {DNA_KEY}: '{given_dna}', but review-questions.md gives '{reason}' here; "
                f"give that reason"
            )
        out[DNA_KEY] = reason
        return out
    if how == "content":
        if answer is None:
            faults.append(
                f"{path}, '{title}', question: missing; give the subject line that holds what it tests for and "
                f"answer it, or mark it {DNA_KEY} with '{reason}'"
            )
            return out
        if given_dna is not None:
            if answer.get("subject"):
                faults.append(
                    f"{path}, '{title}', subject: the record quotes a line that holds what the question tests for, "
                    f"so it applies; answer it, or remove the subject"
                )
            elif given_dna != reason:
                faults.append(
                    f"{path}, '{title}', {DNA_KEY}: '{given_dna}' is not a reason the branches, the rows or the "
                    f"content test allow here; the content test's reason is '{reason}'"
                )
            out[DNA_KEY] = reason
            return out
        subject = answer.get("subject")
        if not isinstance(subject, dict):
            faults.append(
                f"{path}, '{title}', subject: missing; quote the line that holds what the question tests for, or "
                f"mark it {DNA_KEY} with '{reason}'"
            )
        else:
            got_file = file_of(p, f"{path}, '{title}', subject", subject, faults)
            if got_file:
                quoted_line(got_file[1], got_file[0], f"{path}, '{title}', subject", subject, faults)
    elif given_dna is not None:
        faults.append(
            f"{path}, '{title}', {DNA_KEY}: '{given_dna}' is not a reason the branches, the rows or the content test "
            f"allow here; the question applies, so answer it"
        )
        return out
    if q.kind == SCRIPT:
        return resolve_script(p, out, answer, rows, faults)
    if answer is None:
        faults.append(f"{path}, '{title}', question: missing; it applies, so answer it")
        return out
    if q.kind == READING:
        score = answer.get("score")
        if isinstance(score, bool) or not isinstance(score, int) or score not in (0, 1):
            faults.append(f"{path}, '{title}', score: '{score}'; a check scores 1 or 0")
            return out
        given = answer.get("findings") or []
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
    scale = qs.scales[q.scale]
    if answer.get("scale") != q.scale:
        faults.append(f"{path}, '{title}', scale: '{answer.get('scale')}'; this question is rated on the {q.scale} scale")
        return out
    if scale.bands:
        places = answer.get("places")
        if not isinstance(places, list) or not places:
            faults.append(f"{path}, '{title}', places: none listed; list every place the question applies to")
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
        out["point"] = scale.point(meeting, len(places))
        return out
    point = answer.get("point")
    if isinstance(point, bool) or not isinstance(point, int) or point not in scale.words:
        faults.append(f"{path}, '{title}', point: '{point}'; give a whole number from {min(scale.words)} to {scale.top}")
        return out
    given = answer.get("findings") or []
    if point < scale.top and not given:
        faults.append(f"{path}, '{title}', findings: a rating below its top point lists its lines; quote them")
    for k, f in enumerate(given, start=1):
        got = finding(p, title, f"finding {k}", f, faults)
        if got:
            out["findings"].append(got)
    out["point"] = point
    return out


def resolve_script(p, out, answer, rows, faults):
    """A check marked script takes its score from check.py's rows alone, on every file of the persona; one that
    applies and that no row reaches scores 1, since nothing contradicts it (build specification §3d, §3e)."""
    path, title = p.path, out["title"]
    scored = [r for r in rows if r["score"] is not None]
    zero = [r for r in scored if r["score"] == check.ZERO]
    rows_score = 0 if zero else 1
    if answer is not None:
        score = answer.get("score")
        if isinstance(score, bool) or not isinstance(score, int) or score not in (0, 1):
            faults.append(f"{path}, '{title}', score: '{score}'; a check scores 1 or 0")
        elif score != rows_score:
            r = zero[0] if zero else (scored[0] if scored else None)
            by = f"check.py row {r['id']} scored {r['score']}" + (f" at {r['path']}, line {r['line']}" if zero else "") if r \
                else "no row of the check table reaches it, so it scores 1"
            faults.append(
                f"{path}, '{title}', score: scored {score}, but {by}; a script check takes its rows' score; give "
                f"{rows_score} or leave the question out"
            )
        given = answer.get("findings") or []
        if given and rows_score != 0:
            faults.append(f"{path}, '{title}', findings: a check at 1 has no findings; remove them")
        for k, f in enumerate(given, start=1):
            got = finding(p, title, f"finding {k}", f, faults)
            if got:
                out["findings"].append(got)
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


def answer_points(qs, a, equal=False):
    """(points given, points possible) for one answer, or None when it does not apply or has no point."""
    if a.get(DNA_KEY) or a.get("point") is None:
        return None
    if a["type"] in CHECK_KINDS:
        weight = EQUAL_WEIGHT if equal else qs.by_title[a["title"]].weight
        return a["point"] * weight, weight
    return a["point"], qs.scales[qs.by_title[a["title"]].scale].top


def totals(p, equal=False):
    """{section: (x, y)}, the total (x, y), and the points of the questions that do not apply."""
    qs = p.qs
    by_section = {s: (0, 0) for s in qs.sections}
    not_applying = 0
    for a in p.answers:
        got = answer_points(qs, a, equal)
        if got is None:
            if a.get(DNA_KEY):
                not_applying += qs.points(a["title"]) if not equal else (
                    EQUAL_WEIGHT if a["type"] in CHECK_KINDS else qs.points(a["title"]))
            continue
        x, y = by_section[a["section"]]
        by_section[a["section"]] = (x + got[0], y + got[1])
    total = (sum(x for x, _ in by_section.values()), sum(y for _, y in by_section.values()))
    return by_section, total, not_applying


def review_lines(p):
    out = [f"Review: {p.path} ({kind_label(p.header)})", BRANCHES_PREFIX + find.branch_text(p.header), FILES_HEADING]
    out += [f"{FILE_INDENT}{name}: {reason}" for name, reason in p.reviewed]
    if p.left_out:
        out += [LEFT_OUT_HEADING] + [f"{FILE_INDENT}{name}: {reason}" for name, reason in p.left_out]
    else:
        out.append(f"{LEFT_OUT_HEADING} none")
    return out


def do_not_apply_lines(p):
    listed = [(a["title"], a[DNA_KEY]) for a in p.answers if a.get(DNA_KEY)]
    if not listed:
        return [DO_NOT_APPLY_NONE]
    return [DO_NOT_APPLY_HEADING] + [f"{FILE_INDENT}{t}: {r}" for t, r in listed]


def answer_value(qs, a):
    if a.get(DNA_KEY) or a.get("point") is None:
        return DOES_NOT_APPLY
    if a["type"] in CHECK_KINDS:
        return f"yes {qs.by_title[a['title']].weight}" if a["point"] == 1 else "no  0"
    scale = qs.scales[qs.by_title[a["title"]].scale]
    return f"{a['point']} of {scale.top}{' ' * COLUMN_GAP}{scale.words[a['point']]}"


def answer_lines(p):
    qs = p.qs
    width = max(len(q.title) for q in qs.questions) + COLUMN_GAP
    out = []
    for section in qs.sections:
        if out:
            out.append("")
        out.append(section)
        out += [f"{a['title']:<{width}}{answer_value(qs, a)}" for a in p.answers if a["section"] == section]
    return out


def item_lines(k, title, f, grounding):
    where = f"{k}. {f['file']}, line {f['line']}: '{f['text']}'"
    if f.get("against"):
        where += f", against line {f['against'][0]}: '{f['against'][1]}'"
    rules = f"Rule {', '.join(f['rules'])}. " if f["rules"] else ""
    # The note and sources lines align under the item text, past the number and its full stop.
    indent = " " * len(f"{k}. ")
    return [where, f"{indent}{title}. {f['note']}", f"{indent}{rules}{sources_line(grounding.get(title, NO_SOURCES))}"]


def fit_lines(p):
    fit = p.fit or {}
    out = [FIT_HEADING]
    for k, f in enumerate(fit.get("findings") or [], start=1):
        # The note aligns under the item text, past the number and its full stop.
        indent = " " * len(f"{k}. ")
        out += [f"{k}. {f.get('file') or p.path}, line {f.get('line')}: '{f.get('_text', '')}'", f"{indent}{sentence(f.get('note', ''))}"]
    if fit.get("statement"):
        out.append(fit["statement"])
    return out


def set_aside_lines(p, grounding):
    head = f"{SET_ASIDE_PREFIX}{p.path} ({kind_label(p.header)})"
    if "reason" in p.set_aside:
        return [head, sentence(p.set_aside["reason"])]
    f = p.set_aside["finding"]
    root = p.qs.root
    return [head, f"{root}. {f['note']}", f"{f['file']}, line {f['line']}: '{f['text']}'", sources_line(grounding.get(root, NO_SOURCES))]


def set_aside_reason(p):
    """The reason a summary prints for a file set aside."""
    if "reason" in p.set_aside:
        return p.set_aside["reason"]
    return f"not a dedicated persona: {p.set_aside['finding']['note'].rstrip('.')}"


def total_line(qs, x, y, not_applying):
    return f"Total: {x} out of {y} ({qs.possible} possible, less {not_applying} that do not apply)"


def formula_line(qs, by_section, x, y):
    parts = ", ".join(f"{s.lower()} {by_section[s][0]} out of {by_section[s][1]}" for s in qs.sections)
    return (
        f"Formula: each check counts its weight or 0, and each rating its points; {weights_phrase(qs)}; {parts}, "
        f"total {x} out of {y}."
    )


def render_one(p, grounding=None):
    """One file's report, without its fence; return (text, (x, y) or None)."""
    grounding = grounding or {}
    qs = p.qs
    if p.set_aside:
        return "\n".join(set_aside_lines(p, grounding)), None
    if p.empty:
        return "\n".join([EMPTY_LINE, ""] + review_lines(p)), None
    by_section, (x, y), not_applying = totals(p)
    if y == 0:
        return "\n".join([NOTHING_APPLIES, ""] + review_lines(p) + [""] + answer_lines(p)), None
    _, (ex, ey), _ = totals(p, equal=True)
    out = [star_line(stars(x, y)), total_line(qs, x, y, not_applying)]
    out += [f"{s}: {by_section[s][0]} out of {by_section[s][1]}" for s in qs.sections]
    out += [""] + review_lines(p) + [""] + do_not_apply_lines(p)
    if not_applying > THIN_SHARE * qs.possible:
        out.append(THIN_LINE)
    out += ["", LINES_HEADING]
    if p.items:
        for k, (title, f) in enumerate(p.items, start=1):
            out += item_lines(k, title, f, grounding)
    else:
        out.append(CLEAN_LINE)
    out += [""] + answer_lines(p) + [""]
    if p.fit is not None:
        out += fit_lines(p) + [""]
    out += [
        formula_line(qs, by_section, x, y),
        f"At equal weights: {ex} out of {ey}.",
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
            f"Summary: {plural(len(personas), 'persona')} reviewed, lowest total first; "
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
TOTAL_RE = re.compile(r"^Total: (\d+) out of (\d+) \((\d+) possible, less (\d+) that do not apply\)$")
REVIEW_RE = re.compile(r"^Review: (.+) \(([^()]+)\)$")
EQUAL_RE = re.compile(r"^At equal weights: (\d+) out of (\d+)\.$")
STARS_FORMULA_RE = re.compile(r"^Stars: (\d+) ÷ (\d+) × 5 = (\d+\.\d+), to the nearest half star\.$")


def blocks_of(text):
    found = re.findall(rf"^{re.escape(FENCE_OPEN)}\n(.*?)\n{re.escape(FENCE_CLOSE)}$", text, re.MULTILINE | re.DOTALL)
    return [b.splitlines() for b in found] if found else [text.splitlines()]


def read_rows(qs, lines, section, messages, path):
    """The answers printed under one section heading: [(title, value)], or None when they cannot be read."""
    try:
        start = lines.index(section)
    except ValueError:
        return None
    titles = sorted((q.title for q in qs.questions if q.section == section), key=len, reverse=True)
    out = []
    for line in lines[start + 1:]:
        if not line.strip():
            break
        title = next((t for t in titles if line.startswith(t + " ")), None)
        if title is None:
            return None
        out.append((title, line[len(title):].strip()))
    return out


def recompute(qs, rows, equal=False):
    """(x, y, the titles printed as not applying) from a section's rows, or None when a value cannot be read.
    A check printed 'yes N' must carry its weight from the file."""
    x = y = 0
    dna = []
    for title, value in rows:
        q = qs.by_title[title]
        if value == DOES_NOT_APPLY:
            dna.append(title)
            continue
        if q.kind in CHECK_KINDS:
            m = re.fullmatch(r"(yes|no) +(\d+)", value)
            if not m or (m.group(1) == "yes" and int(m.group(2)) != q.weight) or (m.group(1) == "no" and m.group(2) != "0"):
                return None
            weight = EQUAL_WEIGHT if equal else q.weight
            x, y = x + (weight if m.group(1) == "yes" else 0), y + weight
        else:
            m = re.match(r"^(\d+) of (\d+)\b", value)
            scale = qs.scales[q.scale]
            if not m or int(m.group(2)) != scale.top:
                return None
            x, y = x + int(m.group(1)), y + scale.top
    return x, y, dna


def listed_not_applying(lines):
    """The titles under 'Do not apply:', or None when the block is missing."""
    for i, line in enumerate(lines):
        if line == DO_NOT_APPLY_NONE:
            return []
        if line == DO_NOT_APPLY_HEADING:
            out = []
            for item in lines[i + 1:]:
                if not item.startswith(FILE_INDENT):
                    break
                out.append(item[len(FILE_INDENT):].rsplit(": ", 1)[0] if ": " in item else item.strip())
            return out
    return None


def verify(text, qs=None):
    """Return (exit code, messages)."""
    qs = qs or questions.load_cached()
    messages, mismatch, computed, reports = [], False, {}, 0
    summary_rows = []
    sections = qs.sections

    def differ(message):
        nonlocal mismatch
        mismatch = True
        messages.append(message)

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
        subtotal_lines = lines[2: 2 + len(sections)]
        subtotals = [re.match(rf"^{re.escape(s)}: (\d+) out of (\d+)$", l) for s, l in zip(sections, subtotal_lines)]
        rows = {s: read_rows(qs, lines, s, messages, None) for s in sections}
        if not review or not total or len(subtotals) != len(sections) or not all(subtotals) or not all(r is not None for r in rows.values()):
            return EXIT_REFUSED, ["a report has no review line, no total, no subtotals or unreadable checks and ratings; it cannot be checked"]
        path = review.group(1)
        parts = {s: recompute(qs, rows[s]) for s in sections}
        equal = {s: recompute(qs, rows[s], equal=True) for s in sections}
        if not all(parts.values()):
            differ(f"{path}: a check prints a weight other than the one review-questions.md gives it, or a rating's top point differs")
            continue
        x, y = sum(v[0] for v in parts.values()), sum(v[1] for v in parts.values())
        ex, ey = sum(v[0] for v in equal.values()), sum(v[1] for v in equal.values())
        dna = [t for s in sections for t in parts[s][2]]
        not_applying = sum(qs.points(t) for t in dna)
        computed[path] = (review.group(2), (x, y))
        listed = listed_not_applying(lines)
        if listed is None:
            return EXIT_REFUSED, [f"{path}: the report has no 'Do not apply' line; it cannot be checked"]
        if sorted(listed) != sorted(dna):
            differ(
                f"{path}: 'Do not apply' lists {', '.join(listed) or 'none'}, but the rows print as not applying "
                f"{', '.join(dna) or 'none'}"
            )
        for s, sm, line in zip(sections, subtotals, subtotal_lines):
            sx, sy = parts[s][0], parts[s][1]
            if (int(sm.group(1)), int(sm.group(2))) != (sx, sy):
                differ(f"{path}: prints '{line}', but its {s.lower()} rows give {sx} out of {sy}")
        want_total = total_line(qs, x, y, not_applying)
        if lines[1] != want_total:
            differ(f"{path}: prints '{lines[1]}', but its checks and ratings give '{want_total[len('Total: '):]}'")
        if not y:
            return EXIT_REFUSED, [f"{path}: its checks and ratings give no points possible; it cannot be checked"]
        want_stars = star_line(stars(x, y))
        if lines[0] != want_stars:
            differ(f"{path}: prints the stars '{lines[0]}', but its checks and ratings give '{want_stars}'")
        formula = next((l for l in lines if l.startswith("Formula: ")), None)
        want_formula = formula_line(qs, {s: parts[s][:2] for s in sections}, x, y)
        if formula is not None and formula != want_formula:
            differ(f"{path}: the formula line prints '{formula}', but its checks and ratings give '{want_formula}'")
        eq = next((EQUAL_RE.match(l) for l in lines if EQUAL_RE.match(l)), None)
        if eq is None:
            differ(f"{path}: the report gives no total at equal weights; its rows give {ex} out of {ey}")
        elif (int(eq.group(1)), int(eq.group(2))) != (ex, ey):
            differ(f"{path}: prints 'At equal weights: {eq.group(1)} out of {eq.group(2)}.', but at equal weights its rows give {ex} out of {ey}")
        sf = next((STARS_FORMULA_RE.match(l) for l in lines if STARS_FORMULA_RE.match(l)), None)
        if sf:
            want_sf = (str(x), str(y), two_places(Fraction(x * STAR_PLACES, y)))
            if sf.groups() != want_sf:
                differ(
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
            differ(f"summary, {path}: prints '{rest.strip()}', but its report gives '{want}'")
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
        "each persona, give its branches as find.py prints them and answer the questions of "
        "review-questions.md by their bold titles, the root question (the file's first check) first: a 0 there "
        "sets the file aside, and the entry then holds that answer alone. A check marked script may be left out: "
        "check.py's rows set it. A question that does not apply is marked does_not_apply with the reason the "
        "file's tables print. Every finding and place names its file and quotes its line word for word with its "
        "number. The report prints each finding's sources from bibliography.md and orders the findings by "
        "question, then file, then line."
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
                    "branches": {
                        "type": "object",
                        "description": "The three branches as find.py prints them; validate checks them against the files.",
                        "required": ["delegated", "harness", "settings"],
                        "properties": {
                            "delegated": {"type": "boolean"},
                            "harness": {"type": ["string", "null"], "description": "The harness the path names, or null."},
                            "settings": {"type": "array", "items": {"type": "string"}, "description": "The settings fields the file holds."},
                        },
                    },
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
                            "One answer per question that applies. A check: score (1 met, 0 not), and findings at "
                            "0. A rating on a scale with bands: scale and places. A rating on another scale: scale, "
                            "point and, below its top point, findings. A content-test question that applies also "
                            "gives its subject. A question that does not apply: does_not_apply with the reason "
                            "review-questions.md prints; one the branches, an exception or the rows remove may also "
                            "be left out."
                        ),
                        "items": {
                            "type": "object",
                            "required": ["question"],
                            "properties": {
                                "question": {"type": "string"},
                                "score": {"enum": [0, 1], "description": "Checks only."},
                                "scale": {"type": "string", "description": "Ratings only: the scale review-questions.md names."},
                                "point": {"type": "integer", "minimum": 0,
                                          "description": "Ratings on a scale without bands only; the others are counted."},
                                "subject": {
                                    "type": "object",
                                    "description": "A content-test question that applies: the line holding what it tests for.",
                                    "required": ["file", "line", "quote"],
                                    "properties": {"file": FILE_REF, "line": {"type": "integer", "minimum": 1}, "quote": {"type": "string"}},
                                },
                                "does_not_apply": {"type": "string", "description": "The reason review-questions.md prints for it here."},
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


# ---------------------------------------------------------------------------------------------------


def main(argv):
    if not argv or argv[0] in ("-h", "--help"):
        print(__doc__.strip())
        return EXIT_OK if argv else EXIT_REFUSED
    cmd, args = argv[0], argv[1:]
    if cmd == "schema" and not args:
        print(json.dumps(SCHEMA, indent=2, ensure_ascii=False))
        return EXIT_OK
    try:
        qs = questions.load_cached(REVIEW_QUESTIONS)
    except questions.ContractError as exc:
        print(f"report.py: {exc}", file=sys.stderr)
        return EXIT_REFUSED
    except OSError as exc:
        print(f"report.py: cannot read the review questions: {exc.strerror}", file=sys.stderr)
        return EXIT_REFUSED
    if cmd == "verify" and len(args) == 1:
        try:
            text = sys.stdin.read() if args[0] == "-" else open(args[0], encoding="utf-8").read()
        except OSError as exc:
            print(f"report.py: cannot read {args[0]}: {exc.strerror}; check the path", file=sys.stderr)
            return EXIT_REFUSED
        code, messages = verify(text, qs)
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
        table = check.load_table(check.DEFAULT_TABLE)
        grounding = load_grounding()
    except (OSError, ValueError, check.TableError) as exc:
        print(f"report.py: cannot load the check table or the bibliography: {exc}", file=sys.stderr)
        return EXIT_REFUSED
    record, faults = load_record(args[0])
    prepared = []
    if record is not None:
        prepared, faults = validate(record, table, grounding, qs)
    if faults:
        stream = sys.stdout if cmd == "validate" else sys.stderr
        for f in faults:
            print(f, file=stream)
        print(
            f"{plural(len(faults), 'fault')}. Fix the record and run validate again, at most {MAX_VALIDATE_RERUNS} reruns; "
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
