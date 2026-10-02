#!/usr/bin/env python3
"""report.py: check a review record, render it as a report with its total and stars, and recompute a
report's totals.

Usage:
  report.py schema                       print the JSON shape a review record takes
  report.py validate RECORD.json         check a review record; list every fault
  report.py render [--summary] RECORD.json
                                         validate, then render the report
  report.py verify REPORT                recompute every total and star line a rendered report prints

'-' in place of a file reads standard input.

The reviewer writes its answers as a review record, one JSON file in the system's temporary folder and
never inside the reviewed project. 'validate' reads the files the record names, the review questions and
the check table, and lists each fault with the file, the question, the finding's number, the field, what
is wrong and the fix. Fix the record and run 'validate' again until it exits 0, at most 3 reruns; past
that the fault is in the review, not the record, so return the last messages and no report. Then run
'render', which validates again before it prints anything, and delete the record.

The script, not the reviewer, sets each check marked script from check.py's rows, sets each frequency
rating's point from its places, computes the total and the stars and prints the report, so the total
follows from the findings. The formula, from the review questions: each check counts its 1 or 0 and each
rating its point, from 0 to 6; the total is the points given out of the points possible, 'x out of y',
1 for each check scored and 6 for each rating given; the stars are x divided by y, times 5, rounded to
the nearest half star, a half rounding up. A question not scored or not rated leaves both x and y.

The report is plain lines in a fenced text block, in this order: the stars, as five places with the
number in brackets, such as ★★★½☆ (3.5); the total; the file and its kind; the lines that lowered the
score; each check as 'yes 1' or 'no 0'; each rating as its point out of 6 with its word; the fit with
neighbouring files, when the record gives it; the formula; and the closing lines.

Exit codes:
  validate  0 the record is sound; 2 it is not, with one message per fault
  render    0 rendered; 2 the record refused, with the reasons; 3 no file got a total, because each is
            empty or no question applied to it
  verify    0 every printed total and star line matches its checks and ratings; 1 one or more do not,
            each named; 2 the report cannot be parsed
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
REVIEW_QUESTIONS = os.path.join(HERE, "..", "references", "review-questions.md")

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

# The seventeen questions of review-questions.md, in its order: (title, kind, rated for a delegated
# persona only). A test reads review-questions.md and fails if this and the file disagree; at run time,
# validate refuses every record while they disagree.
QUESTIONS = (
    ("Pointers carry their triggers", SCRIPT, False),
    ("Bound parts agree with the prose", SCRIPT, False),
    ("Leaves the harness's work to the harness", SCRIPT, False),
    ("No time-sensitive statements", SCRIPT, False),
    ("Consistent with itself", READING, False),
    ("Nothing said twice", READING, False),
    ("Leaves known things unsaid", READING, False),
    ("Enforceable rules enforced", READING, False),
    ("No procedure for one kind of task", READING, False),
    ("No facts the project already holds", READING, False),
    ("Terms defined where they are used", FREQUENCY, False),
    ("Rules held in the file", FREQUENCY, False),
    ("Directions for when nobody answers", FREQUENCY, False),
    ("Answers defined, edge cases included", FREQUENCY, False),
    ("Its own criteria met", FREQUENCY, False),
    ("The description says when to choose it", QUALITY, True),
    ("An identity that does the work", QUALITY, False),
)
BY_TITLE = {t: (k, d) for t, k, d in QUESTIONS}

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
# Three spaces between the longest question title and its answer, as sample-review.md aligns them.
COLUMN_GAP = 3
TITLE_WIDTH = max(len(t) for t, _, _ in QUESTIONS) + COLUMN_GAP

SESSION_TEXT = personafile.SESSION_TEXT
FENCE_OPEN, FENCE_CLOSE = "```text", "```"
LINES_HEADING = "Lines that lowered the score"
CLEAN_LINE = "Nothing was found."
CHECKS_HEADING = "Checks"
RATINGS_HEADING = "Ratings"
FIT_HEADING = "Fit with neighbouring files, apart from the score"
NO_PREDICTION = "A score does not predict how the agent will behave. The quoted lines are what to act on."
LINTERS = "For secrets, hook scripts and server settings, use a configuration or security linter."
EMPTY_LINE = "This file is empty; no stars and no total."
NOTHING_APPLIES = "No question applies to this file; no stars and no total."
SUMMARY_HEADING = "Summary: {n} files, from the lowest total"
NO_TOTAL = "no stars and no total"
NO_ROW_APPLIES = "no row of the check table applies to this file"


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


# ---------------------------------------------------------------------------------------------------
# The review questions


def file_titles(path=REVIEW_QUESTIONS):
    """The bold question titles under '## Checks' and '## Ratings' in review-questions.md, in order."""
    text = open(path, encoding="utf-8").read()
    titles = []
    for section in ("Checks", "Ratings"):
        m = re.search(rf"^## {section}\s*$(.*?)(?=^## |\Z)", text, re.MULTILINE | re.DOTALL)
        if not m:
            raise ValueError(f"review-questions.md has no '## {section}' section")
        titles += [t.rstrip(".") for t in re.findall(r"^\*\*(.+?)\*\*", m.group(1), re.MULTILINE)]
    return titles


def disagreement(titles):
    """A message when review-questions.md's titles and QUESTIONS disagree, or None."""
    ours = [t for t, _, _ in QUESTIONS]
    if titles == ours:
        return None
    missing = [t for t in titles if t not in ours]
    extra = [t for t in ours if t not in titles]
    detail = []
    if missing:
        detail.append(f"in the file and not in report.py: {', '.join(missing)}")
    if extra:
        detail.append(f"in report.py and not in the file: {', '.join(extra)}")
    if not detail:
        detail.append("the same titles in another order")
    return (
        "review-questions.md and report.py's questions disagree (" + "; ".join(detail) + "); "
        "no record can be scored until report.py follows the file"
    )


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


class Prepared:
    """One file of a record, validated: its header, its answers and the findings the report lists."""

    def __init__(self, path):
        self.path = path
        self.header = {}
        self.pf = None
        self.empty = False
        self.answers = []  # one per question, in QUESTIONS order
        self.items = []  # (question title, finding), in the order the report lists them
        self.fit = None


def quoted_line(pf, prefix, item, faults):
    """Validate an item's line and quote; return (line, the line's text) or None."""
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
        faults.append(f"{prefix}, line: cites line {line}, but the file has {len(pf.lines)} lines; quote a line that exists")
        return None
    if ok and fold(strip_quotes(quote)) not in fold(pf.lines[line - 1]):
        faults.append(
            f"{prefix}, quote: '{strip_quotes(quote)}' does not appear on line {line}; "
            f"quote the line word for word, or cite the line that holds it"
        )
        ok = False
    return (line, pf.lines[line - 1].strip()) if ok else None


def finding(pf, path, title, where, item, faults, source_default=None):
    """Validate one finding: its line, quote, note and source, and an optional second line it is set
    against. Return the finding the report prints, or None."""
    prefix = f"{path}, '{title}', {where}"
    if not isinstance(item, dict):
        faults.append(f"{prefix}: not an object; give line, quote, note and source")
        return None
    got = quoted_line(pf, prefix, item, faults)
    ok = got is not None
    if not str(item.get("note") or "").strip():
        faults.append(f"{prefix}, note: missing; say what in the line lowers the score")
        ok = False
    source = item.get("source") or source_default
    if not str(source or "").strip():
        faults.append(f"{prefix}, source: missing; name the question's source")
        ok = False
    against = None
    if item.get("against") is not None:
        if not isinstance(item["against"], dict):
            faults.append(f"{prefix}, against: give the line and the quote it is set against")
            ok = False
        else:
            against = quoted_line(pf, prefix + ", against", item["against"], faults)
            ok = ok and against is not None
    if not ok:
        return None
    return {
        "line": got[0], "text": got[1], "against": against, "note": sentence(item["note"]),
        "source": source, "rules": [item["rule"]] if item.get("rule") else [],
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
        return None, [f"{arg}: the record holds no files; give a 'files' list with one entry per file reviewed"]
    return record, []


def validate(record, table):
    """Validate a record; return (list of Prepared, list of fault messages)."""
    faults = []
    root = record.get("root") or os.getcwd()
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
                p.pf = personafile.read_text(entry["text"], folder=root)
                p.header = find.record_for_text(p.pf)
            else:
                absolute = path if os.path.isabs(path) else os.path.join(root, path)
                p.pf = personafile.read_path(absolute, path)
                p.header = find.record_for(absolute, path)
        except personafile.PersonaError as exc:
            faults.append(f"{path}, path: {exc}")
            continue
        if entry.get("kind") and entry["kind"] != p.header["kind"]:
            faults.append(f"{path}, kind: '{entry['kind']}', but find.py gives {p.header['kind']}; copy the kind from find.py")
        p.header["bound_parts"] = p.pf.bound_parts
        prepared.append(p)
        questions = entry.get("questions") or []
        if not isinstance(questions, list):
            faults.append(f"{path}, questions: give a list with one answer per question")
            continue
        if p.pf.empty:
            p.empty = True
            if any(isinstance(q, dict) and not not_answered(q) for q in questions):
                faults.append(f"{path}, questions: the file is empty; give no score and no rating")
            continue
        texts = {SESSION_TEXT: p.pf} if path == SESSION_TEXT else {}
        rec = dict(p.header, abspath=None if path == SESSION_TEXT else os.path.join(root, path))
        rows = check.check_files([rec], texts, table, root=find.project_root(root))
        answers, order = {}, []
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
            order.append(title)
        # The report lists first the lines of script checks the record leaves to check.py's rows, in the
        # questions' order; then the record's own questions, in the record's order.
        order = [t for t, _, _ in QUESTIONS if t not in answers] + order
        resolved = {}
        for title, kind, delegated_only in QUESTIONS:
            q = answers.get(title)
            if q is None and kind != SCRIPT:
                faults.append(f"{path}, '{title}', question: missing; answer it, or mark it not rated with the reason")
                continue
            own_rows = [r for r in rows if r["question"] == title]
            resolved[title] = resolve(p, title, kind, delegated_only, q, own_rows, faults)
        p.answers = [resolved[t] for t, _, _ in QUESTIONS if t in resolved]
        p.items = [(t, f) for t in order if t in resolved for f in resolved[t]["findings"]]
        p.fit = entry.get("fit")
        if p.fit is not None:
            check_fit(p, root, faults)
    return prepared, faults


def not_answered(q):
    """The reason a question is not scored or not rated, or None; either key is read for either."""
    for key in ("not_scored", "not_rated"):
        if key in q:
            return q[key] if isinstance(q[key], str) else ""
    return None


def resolve(p, title, kind, delegated_only, q, rows, faults):
    """Validate one answer and return what the report prints for it."""
    path = p.path
    out = {"title": title, "type": kind, "point": None, "findings": [], "not_rated": None}
    reason = not_answered(q) if q is not None else None
    if kind == SCRIPT:
        return resolve_script(p, out, q, reason, rows, faults)
    if reason is not None:
        if not reason.strip():
            faults.append(f"{path}, '{title}', not_rated: give the reason it is not rated")
        out["not_rated"] = reason or "not given"
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
            got = finding(p.pf, path, title, f"finding {k}", f, faults, q.get("source"))
            if got:
                out["findings"].append(got)
        out["point"] = score
        return out
    # A rating.
    if delegated_only and p.header["kind"] != "delegated":
        faults.append(
            f"{path}, '{title}', scale: a {p.header['kind']} persona is not rated on this question; mark it not rated"
        )
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
            if not isinstance(place, dict) or not isinstance(place.get("meets"), bool):
                faults.append(f"{path}, '{title}', place {k}, meets: give true or false")
                continue
            if place["meets"]:
                meeting += 1
                quoted_line(p.pf, f"{path}, '{title}', place {k}", place, faults)
                continue
            got = finding(p.pf, path, title, f"place {k}", place, faults, q.get("source"))
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
        got = finding(p.pf, path, title, f"finding {k}", f, faults, q.get("source"))
        if got:
            out["findings"].append(got)
    out["point"] = point
    return out


def resolve_script(p, out, q, reason, rows, faults):
    """A check marked script takes its score from check.py's rows alone (build specification §3d)."""
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
                at = f" at line {r['line']}" if zero else ""
                faults.append(
                    f"{path}, '{title}', score: scored {score}, but check.py row {r['id']} scored {r['score']}{at}; "
                    f"a script check takes its rows' score; give {rows_score} or leave the question out"
                )
        given = q.get("findings") or []
        if given and rows_score != 0:
            faults.append(f"{path}, '{title}', findings: a check at 1 has no findings; remove them")
        for k, f in enumerate(given, start=1):
            got = finding(p.pf, path, title, f"finding {k}", f, faults, q.get("source"))
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
    if hit.get("field_line"):
        line, text = hit["field_line"], hit["field_quote"]
        against = (hit["line"], p.pf.lines[hit["line"] - 1].strip())
        note = r["row_message"]
    else:
        line = hit["line"]
        text = p.pf.lines[line - 1].strip() if line else hit["quote"]
        against = None
        note = r["row_message"] + (f": {hit['note']}" if hit.get("note") else "")
    for f in out["findings"]:
        if f["line"] == line:
            if r["id"] not in f["rules"]:
                f["rules"].append(r["id"])
            return
    out["findings"].append(
        {"line": line, "text": text, "against": against, "note": sentence(note), "source": r["source"], "rules": [r["id"]]}
    )


def check_fit(p, root, faults):
    fit = p.fit
    if not isinstance(fit, dict) or not (fit.get("statement") or fit.get("findings")):
        faults.append(f"{p.path}, fit: give a statement, or findings each with a quoted line and a note")
        return
    for k, f in enumerate(fit.get("findings") or [], start=1):
        other = p.pf
        if f.get("file"):
            target = f["file"] if os.path.isabs(f["file"]) else os.path.join(root, f["file"])
            try:
                other = personafile.read_path(target, f["file"])
            except personafile.PersonaError as exc:
                faults.append(f"{p.path}, fit, finding {k}, file: {exc}")
                continue
        if not str(f.get("note") or "").strip():
            faults.append(f"{p.path}, fit, finding {k}, note: missing; say what the line shows about the fit")
        got = quoted_line(other, f"{p.path}, fit, finding {k}", f, faults)
        if got:
            f["_text"] = got[1]


# ---------------------------------------------------------------------------------------------------
# Rendering


def totals(p):
    """(x, y) for a file: the points given and the points possible, from its answers."""
    x = y = 0
    for a in p.answers:
        if a.get("point") is None:
            continue
        x += a["point"]
        y += CHECK_POINTS if a["type"] in CHECK_KINDS else TOP_POINT
    return x, y


def review_line(p):
    return f"Review: {p.path} ({p.header['kind']} persona)"


def answer_lines(p):
    out = [CHECKS_HEADING]
    for a in (a for a in p.answers if a["type"] in CHECK_KINDS):
        if a.get("point") is None:
            value = f"not scored{' ' * COLUMN_GAP}{sentence(a.get('not_rated') or NO_ROW_APPLIES)}"
        else:
            value = "yes 1" if a["point"] == 1 else "no  0"
        out.append(f"{a['title']:<{TITLE_WIDTH}}{value}")
    out += ["", RATINGS_HEADING]
    for a in (a for a in p.answers if a["type"] not in CHECK_KINDS):
        if a.get("point") is None:
            value = f"not rated{' ' * COLUMN_GAP}{sentence(a.get('not_rated') or 'not given')}"
        else:
            value = f"{a['point']} of {TOP_POINT}{' ' * COLUMN_GAP}{words_for(a['type'])[a['point']]}"
        out.append(f"{a['title']:<{TITLE_WIDTH}}{value}")
    return out


def item_lines(k, title, f):
    where = f"Line {f['line']}: '{f['text']}'" if f["line"] else f"The file: '{f['text']}'"
    if f.get("against"):
        where += f", against line {f['against'][0]}: '{f['against'][1]}'"
    return [f"{k}. {where}", f"   {title}. {f['note']}"]


def fit_lines(p):
    fit = p.fit or {}
    out = [FIT_HEADING]
    for k, f in enumerate(fit.get("findings") or [], start=1):
        out += [f"{k}. {f.get('file') or p.path}, line {f.get('line')}: '{f.get('_text', '')}'", f"   {sentence(f.get('note', ''))}"]
    if fit.get("statement"):
        out.append(fit["statement"])
    return out


def render_one(p):
    """One file's report, without its fence; return (text, (x, y) or None)."""
    if p.empty:
        return "\n".join([EMPTY_LINE, "", review_line(p)]), None
    x, y = totals(p)
    if y == 0:
        return "\n".join([NOTHING_APPLIES, "", review_line(p), ""] + answer_lines(p)), None
    out = [star_line(stars(x, y)), f"Total: {x} out of {y}", "", review_line(p), "", LINES_HEADING]
    if p.items:
        for k, (title, f) in enumerate(p.items, start=1):
            out += item_lines(k, title, f)
    else:
        out.append(CLEAN_LINE)
    out += [""] + answer_lines(p) + [""]
    if p.fit is not None:
        out += fit_lines(p) + [""]
    out += [
        f"Formula: each check counts 1 or 0 and each rating its points, {x} out of {y}.",
        f"Stars: {x} ÷ {y} × {STAR_PLACES} = {two_places(Fraction(x * STAR_PLACES, y))}, to the nearest half star.",
        NO_PREDICTION,
    ]
    if p.header.get("bound_parts"):
        out.append(LINTERS)
    return "\n".join(out), (x, y)


def fenced(text):
    return f"{FENCE_OPEN}\n{text}\n{FENCE_CLOSE}"


def render(prepared, summary):
    """Return (the rendered text, whether no file got a total)."""
    done = [(p,) + render_one(p) for p in prepared]
    blocks = []
    if summary:
        done.sort(key=lambda t: (t[2] is None, Fraction(t[2][0], t[2][1]) if t[2] else 0, t[0].path))
        width = max(len(p.path) for p, _, _ in done) + COLUMN_GAP
        kind_width = len("delegated") + COLUMN_GAP
        star_width = len(star_line(Fraction(7, 2))) + COLUMN_GAP
        lines = [SUMMARY_HEADING.format(n=len(done))]
        for p, _, xy in done:
            head = f"{p.path:<{width}}{p.header['kind']:<{kind_width}}"
            lines.append(head + (f"{star_line(stars(*xy)):<{star_width}}{xy[0]} out of {xy[1]}" if xy else NO_TOTAL))
        blocks.append(fenced("\n".join(lines)))
    blocks += [fenced(text) for _, text, _ in done]
    return "\n\n".join(blocks), all(xy is None for _, _, xy in done)


# ---------------------------------------------------------------------------------------------------
# Verify


STAR_RE = re.compile(rf"^[{FULL_STAR}{HALF_STAR}{EMPTY_STAR}]{{{STAR_PLACES}}} \(\d+(?:\.5)?\)$")
TOTAL_RE = re.compile(r"^Total: (\d+) out of (\d+)$")
REVIEW_RE = re.compile(r"^Review: (.+) \((standing|delegated) persona\)$")
FORMULA_RE = re.compile(r"^Formula: .* (\d+) out of (\d+)\.$")
STARS_FORMULA_RE = re.compile(r"^Stars: (\d+) ÷ (\d+) × 5 = (\d+\.\d+), to the nearest half star\.$")
RATING_RE = re.compile(rf"^(\d) of {TOP_POINT}\b")


def blocks_of(text):
    found = re.findall(rf"^{re.escape(FENCE_OPEN)}\n(.*?)\n{re.escape(FENCE_CLOSE)}$", text, re.MULTILINE | re.DOTALL)
    return [b.splitlines() for b in found] if found else [text.splitlines()]


def recompute(lines):
    """(x, y) from a report's Checks and Ratings lines, or None when they cannot be read."""
    try:
        start = lines.index(CHECKS_HEADING)
    except ValueError:
        return None
    x = y = 0
    section = CHECKS_HEADING
    for line in lines[start + 1:]:
        if line == RATINGS_HEADING:
            section = RATINGS_HEADING
            continue
        title = next((t for t, _, _ in QUESTIONS if line.startswith(t + " ")), None)
        if title is None:
            if section == RATINGS_HEADING and not line.strip():
                break
            continue
        value = line[len(title):].strip()
        if value.startswith(("not scored", "not rated")):
            continue
        if section == CHECKS_HEADING:
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
        review = next((REVIEW_RE.match(l) for l in lines if REVIEW_RE.match(l)), None)
        if lines[0] in (EMPTY_LINE, NOTHING_APPLIES):
            if review:
                computed[review.group(1)] = None
                reports += 1
            continue
        if not STAR_RE.match(lines[0]):
            continue
        reports += 1
        total = TOTAL_RE.match(lines[1]) if len(lines) > 1 else None
        xy = recompute(lines)
        if not review or not total or not xy or not xy[1]:
            return EXIT_REFUSED, ["a report has no review line, no total or no checks and ratings; it cannot be checked"]
        path = review.group(1)
        x, y = xy
        computed[path] = (x, y)
        want_stars = star_line(stars(x, y))
        if (int(total.group(1)), int(total.group(2))) != (x, y):
            mismatch = True
            messages.append(f"{path}: prints '{lines[1]}', but its checks and ratings give {x} out of {y}")
        if lines[0] != want_stars:
            mismatch = True
            messages.append(f"{path}: prints the stars '{lines[0]}', but its checks and ratings give '{want_stars}'")
        formula = next((FORMULA_RE.match(l) for l in lines if FORMULA_RE.match(l)), None)
        if formula and (int(formula.group(1)), int(formula.group(2))) != (x, y):
            mismatch = True
            messages.append(f"{path}: the formula line prints {formula.group(1)} out of {formula.group(2)}, but its checks and ratings give {x} out of {y}")
        sf = next((STARS_FORMULA_RE.match(l) for l in lines if STARS_FORMULA_RE.match(l)), None)
        if sf:
            want = (str(x), str(y), two_places(Fraction(x * STAR_PLACES, y)))
            if sf.groups() != want:
                mismatch = True
                messages.append(
                    f"{path}: the stars line prints {sf.group(1)} ÷ {sf.group(2)} × 5 = {sf.group(3)}, "
                    f"but its checks and ratings give {want[0]} ÷ {want[1]} × 5 = {want[2]}"
                )
    if not reports:
        return EXIT_REFUSED, ["no report found: no line of stars, or the empty-file line, followed by a review line"]
    for row in summary_rows:
        m = re.match(rf"^(.+?) {{{COLUMN_GAP},}}(standing|delegated) +(.+?)$", row)
        if not m or m.group(1) not in computed:
            continue
        rest, xy = m.group(3).strip(), computed[m.group(1)]
        want = NO_TOTAL if xy is None else f"{star_line(stars(*xy))}{' ' * COLUMN_GAP}{xy[0]} out of {xy[1]}"
        if " ".join(rest.split()) != " ".join(want.split()):
            mismatch = True
            messages.append(f"summary, {m.group(1)}: prints '{rest}', but its report gives '{want}'")
    if not mismatch:
        messages.append(f"every printed total and star line matches its checks and ratings: {reports} reports")
    return (EXIT_MISMATCH if mismatch else EXIT_OK), messages


# ---------------------------------------------------------------------------------------------------
# Schema


FINDING = {
    "type": "object",
    "required": ["line", "quote", "note"],
    "properties": {
        "line": {"type": "integer", "minimum": 1},
        "quote": {"type": "string", "description": "The line, or part of it, word for word."},
        "note": {"type": "string", "description": "What in the line lowers the score, in one sentence."},
        "source": {"type": "string", "description": "The question's source; the answer's source when absent."},
        "against": {
            "type": "object",
            "description": "A second line the first is set against, such as the prose a setting contradicts.",
            "required": ["line", "quote"],
            "properties": {"line": {"type": "integer", "minimum": 1}, "quote": {"type": "string"}},
        },
        "rule": {"type": "string", "description": "A check.py row ID, such as PJ-001."},
    },
}

SCHEMA = {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "title": "persona-judge review record",
    "description": (
        "Written by the reviewer to one file in the system's temporary folder, never inside the reviewed "
        "project. Paths are relative to root. Answer the seventeen questions of review-questions.md for each "
        "file, by their bold titles without the full stop: the ten checks and the seven ratings. A check "
        "marked script may be left out: check.py's rows set it. Quote every line word for word with its "
        "number. The report lists the findings in the order the record gives its questions, after the lines "
        "of script checks left to the rows."
    ),
    "type": "object",
    "required": ["files"],
    "properties": {
        "root": {"type": "string", "description": "The project's folder; the working folder when absent."},
        "files": {
            "type": "array",
            "minItems": 1,
            "items": {
                "type": "object",
                "required": ["path", "questions"],
                "properties": {
                    "path": {"type": "string", "description": "As find.py gives it, or <session text>."},
                    "text": {"type": "string", "description": "For <session text> only: the text reviewed."},
                    "kind": {"enum": ["standing", "delegated"], "description": "Optional; as find.py gives it."},
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
                                "source": {"type": "string", "description": "The question's source."},
                                "places": {
                                    "type": "array",
                                    "description": "Frequency ratings: every place the question applies to.",
                                    "items": {
                                        "type": "object",
                                        "required": ["line", "quote", "meets"],
                                        "properties": {
                                            "line": {"type": "integer", "minimum": 1},
                                            "quote": {"type": "string"},
                                            "meets": {"type": "boolean"},
                                            "note": {"type": "string", "description": "When meets is false: what lowers it."},
                                            "source": {"type": "string"},
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
        problem = disagreement(file_titles())
        table = check.load_table(check.DEFAULT_TABLE)
    except (OSError, ValueError, check.TableError) as exc:
        print(f"report.py: cannot load the review questions or the check table: {exc}", file=sys.stderr)
        return EXIT_REFUSED
    if problem:
        print(f"report.py: {problem}", file=sys.stderr)
        return EXIT_REFUSED
    record, faults = load_record(args[0])
    prepared = []
    if record is not None:
        prepared, faults = validate(record, table)
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
        print(f"The record is sound: {len(prepared)} files, every question answered.")
        return EXIT_OK
    text, nothing = render(prepared, summary)
    print(text)
    return EXIT_NO_SCORE if nothing else EXIT_OK


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
