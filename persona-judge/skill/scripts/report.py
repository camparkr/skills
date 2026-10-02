#!/usr/bin/env python3
"""report.py: check a review record, render it as a report with its score, and recompute a report's totals.

Usage:
  report.py schema                       print the JSON shape a review record takes
  report.py validate RECORD.json         check a review record; list every fault
  report.py render [--summary] RECORD.json
                                         validate, then render the report in Markdown
  report.py verify REPORT.md             recompute every total a rendered report prints

'-' in place of a file reads standard input.

The reviewer writes its answers as a review record, one JSON file in the system's temporary folder and
never inside the reviewed project. 'validate' reads the files the record names and the review questions,
and lists each fault with the file, the question, the finding's number, the field, what is wrong and the
fix. Fix the record and run 'validate' again until it exits 0, at most 3 reruns; past that the fault is in
the review, not the record, so return the last messages and no report. Then run 'render', which
validates again before it prints anything, and delete the record.

The script, not the reviewer, counts each rating's places, sets its point, computes the score and stars
and prints the report, so the total follows from the findings. The formula, from the review questions:
each check counts 1 or 0; each rating counts its point divided by 4; the score is the mean of every
question counted; the stars are the score times 5, rounded to the nearest half star, a half rounding up.
A question that is not rated leaves the total.

Exit codes:
  validate  0 the record is sound; 2 it is not, with one message per fault
  render    0 rendered; 2 the record refused, with the reasons; 3 no question applied to a file, or the
            file is empty, so no score
  verify    0 every printed total matches its table; 1 one or more do not, each named; 2 the report
            cannot be parsed
This script changes no file.
"""

import hashlib
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

# The top point of both rating scales, and the divisor that turns a point into what it counts
# (review questions, 'Score': 'Each rating counts its point divided by 4').
TOP_POINT = 4
# Brown's frequency and quality scale words, by point (review questions, 'Checks and ratings').
FREQUENCY_WORDS = {4: "always", 3: "usually", 2: "about half the time", 1: "seldom", 0: "never"}
QUALITY_WORDS = {4: "very good", 3: "good", 2: "acceptable", 1: "poor", 0: "very poor"}
# The frequency bands, as the review questions give them: 'over 60%, below 100%' is 3; '40% to 60%' is 2,
# both ends inside; 'more than none, below 40%' is 1.
BAND_HIGH = Fraction(60, 100)
BAND_LOW = Fraction(40, 100)
# Stars are the score times 5 (review questions, 'Score'); the score prints to two places.
STAR_SCALE = 5
SCORE_PLACES = 2

SESSION_TEXT = personafile.SESSION_TEXT
CLEAN_LINE = "Nothing was found in this file."
NO_NEIGHBOURS = "No neighbouring persona files were supplied."
NO_PREDICTION = "A score does not predict how an agent behaves; the lines above are the review."
LINTERS = (
    "This file has bound parts. Security checks of what they point to are for configuration linters; "
    "this review does not make them."
)
EMPTY_LINE = "This file is empty; no score."
NOTHING_APPLIES = "No question applies to this file; no score."
FORMULA = (
    "each check counts 1 or 0 and each rating its point divided by 4; the score is the mean of the "
    "questions counted; the stars are the score times 5, rounded to the nearest half star, a half rounding up"
)


# ---------------------------------------------------------------------------------------------------
# The formula


def frequency_point(meeting, counted):
    """The frequency scale's point for meeting places out of counted places."""
    if counted <= 0:
        raise ValueError("a rating with no places is not rated")
    share = Fraction(meeting, counted)
    if share == 1:
        return 4
    if share == 0:
        return 0
    if share > BAND_HIGH:
        return 3
    if share >= BAND_LOW:
        return 2
    return 1


def mean(values):
    return sum(values, Fraction(0)) / len(values)


def half_up(x):
    return math.floor(x + Fraction(1, 2))


def stars(score):
    """Stars for a score: score times 5, to the nearest half star, a half rounding up."""
    return Fraction(half_up(score * STAR_SCALE * 2), 2)


def fmt_score(score):
    """The score to two places, a half rounding up, computed exactly."""
    scale = 10 ** SCORE_PLACES
    n = half_up(score * scale)
    return f"{n // scale}.{n % scale:0{SCORE_PLACES}d}"


def fmt_stars(value):
    return str(int(value)) if value.denominator == 1 else f"{float(value):.1f}"


# ---------------------------------------------------------------------------------------------------
# The review questions


class Catalogue:
    """The ten questions, read from review-questions.md so the script follows the ratified text."""

    def __init__(self, path=REVIEW_QUESTIONS):
        raw = open(path, "rb").read()
        self.version = hashlib.sha256(raw).hexdigest()[:12]
        text = raw.decode("utf-8")
        self.questions = []  # dicts: title, type ('check' or 'rating'), scale, delegated_only, needs_settings
        for section, qtype in (("Checks", "check"), ("Ratings", "rating")):
            m = re.search(rf"^## {section}\s*$(.*?)(?=^## |\Z)", text, re.MULTILINE | re.DOTALL)
            if not m:
                raise ValueError(f"review-questions.md has no '## {section}' section")
            paras = re.split(r"\n\s*\n", m.group(1))
            for para in paras:
                t = re.match(r"\*\*(.+?)\*\*", para.strip())
                if not t:
                    continue
                flat = " ".join(para.split())
                self.questions.append({
                    "title": t.group(1).rstrip("."),
                    "type": qtype,
                    "scale": None if qtype == "check" else ("quality" if "quality scale" in flat else "frequency"),
                    "delegated_only": "delegated persona only" in flat,
                    "needs_settings": "Not scored for a file with no settings" in flat,
                })
        self.by_title = {q["title"]: q for q in self.questions}


# ---------------------------------------------------------------------------------------------------
# Validation


def fold(text):
    return " ".join(str(text).split())


def strip_quotes(text):
    text = str(text).strip()
    while len(text) >= 2 and text[0] == text[-1] and text[0] in "'\"":
        text = text[1:-1].strip()
    return text


class Prepared:
    """One file of a record, validated: its header, its answers and its findings."""

    def __init__(self, path):
        self.path = path
        self.header = {}
        self.pf = None
        self.empty = False
        self.rows = []
        self.answers = []  # per catalogue question, in catalogue order
        self.findings = []
        self.fit = None
        self.counted = []


def check_line(pf, path, label, where, item, faults, source_default=None, need_source=True):
    """Validate one finding or place: its line, its quote and its source. Return (line, quote) or None."""
    prefix = f"{path}, '{label}', {where}"
    line = item.get("line")
    quote = item.get("quote")
    ok = True
    if quote is None or not str(quote).strip():
        faults.append(f"{prefix}, quote: missing; a finding with no quoted line is not reported; quote the line")
        ok = False
    if need_source and not (item.get("source") or source_default):
        faults.append(f"{prefix}, source: missing; name the question's source")
        ok = False
    if isinstance(line, bool) or not isinstance(line, int) or line < 1:
        faults.append(f"{prefix}, line: '{line}' is not a line number; give the number of the line quoted")
        return None
    if line > len(pf.lines):
        faults.append(
            f"{prefix}, line: cites line {line}, but the file has {len(pf.lines)} lines; quote a line that exists"
        )
        return None
    if quote is not None and str(quote).strip():
        q = fold(strip_quotes(quote))
        if q not in fold(pf.lines[line - 1]):
            faults.append(
                f"{prefix}, quote: '{strip_quotes(quote)}' does not appear on line {line}; "
                f"quote the line word for word, or cite the line that holds it"
            )
            ok = False
    return (line, pf.lines[line - 1].strip()) if ok else None


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


def validate(record, cat, table):
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
            faults.append(
                f"{path}, kind: '{entry['kind']}', but find.py gives {p.header['kind']}; copy the kind from find.py"
            )
        p.header["bound_parts"] = p.pf.bound_parts
        prepared.append(p)
        questions = entry.get("questions") or []
        if p.pf.empty:
            p.empty = True
            if any(not q.get("not_rated") for q in questions if isinstance(q, dict)):
                faults.append(f"{path}, questions: the file is empty; give no score and no rating")
            continue
        texts = {SESSION_TEXT: p.pf} if path == SESSION_TEXT else {}
        rec = dict(p.header, abspath=None if path == SESSION_TEXT else os.path.join(root, path))
        p.rows = check.check_files([rec], texts, table, root=find.project_root(root))
        zero_rows = {}
        for r in p.rows:
            if r["score"] == check.ZERO:
                zero_rows.setdefault(r["question"], []).append(r)
        answers = {}
        for qi, q in enumerate(questions, start=1):
            if not isinstance(q, dict):
                faults.append(f"{path}, question {qi}: not an object; give question and its answer")
                continue
            title = q.get("question")
            if title not in cat.by_title:
                faults.append(
                    f"{path}, '{title}', question: is not a question in review-questions.md; "
                    f"use one of its bold titles word for word, without the full stop"
                )
                continue
            if title in answers:
                faults.append(f"{path}, '{title}', question: answered twice; answer each question once")
                continue
            answers[title] = q
        for spec in cat.questions:
            title = spec["title"]
            q = answers.get(title)
            if q is None:
                faults.append(f"{path}, '{title}', question: missing; answer it, or mark it not rated with the reason")
                continue
            p.answers.append(resolve(p, spec, q, zero_rows.get(title, []), faults))
        p.fit = entry.get("fit")
        if p.fit is not None:
            check_fit(p, root, faults)
    return prepared, faults


def resolve(p, spec, q, zero_rows, faults):
    """Validate one answer and return what the report prints for it."""
    path, title = p.path, spec["title"]
    kind = p.header["kind"]
    out = {"title": title, "type": spec["type"], "scale": spec["scale"], "counts": None, "findings": []}
    if "not_rated" in q:
        reason = q.get("not_rated")
        if not isinstance(reason, str) or not reason.strip():
            faults.append(f"{path}, '{title}', not_rated: give the reason it is not rated")
        if zero_rows:
            faults.append(
                f"{path}, '{title}', not_rated: check.py row {zero_rows[0]['id']} scored 0 at line "
                f"{zero_rows[0]['line']}; score the check 0"
            )
        out["not_rated"] = reason
        return out
    if spec["type"] == "check":
        score = q.get("score")
        if spec["needs_settings"] and not p.header["bound_parts"]:
            faults.append(f"{path}, '{title}', score: not scored for a file with no settings; mark it not rated")
        if isinstance(score, bool) or score not in (0, 1) or not isinstance(score, int):
            faults.append(f"{path}, '{title}', score: '{score}'; a check scores 1 or 0")
            return out
        if score == 1 and zero_rows:
            r = zero_rows[0]
            faults.append(
                f"{path}, '{title}', score: scored 1, but check.py row {r['id']} scored 0 at line {r['line']}; "
                f"a check with a row at 0 scores 0"
            )
        findings = q.get("findings") or []
        if score == 1 and findings:
            faults.append(f"{path}, '{title}', findings: a check at 1 has no findings; remove them or score 0")
        if score == 0 and not findings and not zero_rows:
            faults.append(f"{path}, '{title}', findings: a check at 0 lists its lines; add a finding quoting each")
        for k, f in enumerate(findings, start=1):
            got = check_line(p.pf, path, title, f"finding {k}", f, faults, q.get("source"))
            if got:
                rules = [f["rule"]] if f.get("rule") else []
                out["findings"].append({"line": got[0], "text": got[1], "rules": rules, "source": f.get("source") or q.get("source")})
        for r in zero_rows:
            for hit in r["lines"]:
                existing = [x for x in out["findings"] if x["line"] == hit["line"]]
                if existing:
                    if r["id"] not in existing[0]["rules"]:
                        existing[0]["rules"].append(r["id"])
                else:
                    text = p.pf.lines[hit["line"] - 1].strip() if hit["line"] else hit["quote"]
                    out["findings"].append({"line": hit["line"], "text": text, "rules": [r["id"]], "source": r["source"]})
        out["point"] = score
        out["counts"] = Fraction(score)
        return out
    # A rating.
    scale = q.get("scale")
    if spec["delegated_only"] and kind != "delegated":
        faults.append(f"{path}, '{title}', scale: a {kind} persona is not rated on this question; mark it not rated")
        return out
    if scale != spec["scale"]:
        faults.append(f"{path}, '{title}', scale: '{scale}'; this question is rated on the {spec['scale']} scale")
        return out
    if scale == "frequency":
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
            need = not place["meets"]
            got = check_line(p.pf, path, title, f"place {k}", place, faults, q.get("source"), need_source=need)
            if place["meets"]:
                meeting += 1
            elif got:
                out["findings"].append({"line": got[0], "text": got[1], "rules": [], "source": place.get("source") or q.get("source")})
        out["places"], out["meeting"] = len(places), meeting
        out["point"] = frequency_point(meeting, len(places))
    else:
        point = q.get("point")
        if isinstance(point, bool) or not isinstance(point, int) or not 0 <= point <= TOP_POINT:
            faults.append(f"{path}, '{title}', point: '{point}'; give a whole number from 0 to 4")
            return out
        findings = q.get("findings") or []
        if point < TOP_POINT and not findings:
            faults.append(f"{path}, '{title}', findings: a rating below its top point lists its lines; quote them")
        for k, f in enumerate(findings, start=1):
            got = check_line(p.pf, path, title, f"finding {k}", f, faults, q.get("source"))
            if got:
                out["findings"].append({"line": got[0], "text": got[1], "rules": [], "source": f.get("source") or q.get("source")})
        out["point"] = point
    out["counts"] = Fraction(out["point"], TOP_POINT)
    return out


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
        got = check_line(other, p.path, "fit", f"finding {k}", f, faults, need_source=False)
        if got:
            f["_text"] = got[1]


# ---------------------------------------------------------------------------------------------------
# Rendering


def cell(text):
    return str(text).replace("|", "\\|").replace("\n", " ")


def file_score(p):
    counted = [a["counts"] for a in p.answers if a.get("counts") is not None]
    return (mean(counted), len(counted)) if counted else (None, 0)


def render_one(p, version, table_rows):
    out = [f"# Review: {p.path}", ""]
    h = p.header
    out.append(f"Kind: {h['kind']} ({h['kind_basis']})  ")
    out.append(f"Harness: {h['harness']}  ")
    out.append(f"Bound parts: {', '.join(h['bound_parts']) if h['bound_parts'] else 'none'}  ")
    out.append(f"Applied: review questions sha256 {version}; check table, {table_rows} rows")
    out.append("")
    if p.empty:
        out += [EMPTY_LINE, ""]
        return "\n".join(out), None
    findings = []
    for a in p.answers:
        for f in sorted(a["findings"], key=lambda x: (x["line"] or 0)):
            findings.append((a["title"], f))
    out += ["## Lines behind the scores", ""]
    if findings:
        out += ["| Question | Line | Line quoted | Row | Source |", "|---|---|---|---|---|"]
        for title, f in findings:
            out.append(
                f"| {cell(title)} | {f['line'] if f['line'] else '-'} | '{cell(f['text'])}' | "
                f"{', '.join(f['rules']) or '-'} | {cell(f['source'])} |"
            )
    else:
        out.append(CLEAN_LINE)
    out += ["", "## Score for each question", ""]
    out += ["| Question | Type | Places counted | Places meeting it | Point | Counts |", "|---|---|---|---|---|---|"]
    for a in p.answers:
        if "not_rated" in a:
            out.append(f"| {cell(a['title'])} | not rated | - | - | - | {cell(a['not_rated'])} |")
        elif a["type"] == "check":
            out.append(f"| {cell(a['title'])} | check | - | - | {a['point']} | {a['point']} |")
        else:
            words = FREQUENCY_WORDS if a["scale"] == "frequency" else QUALITY_WORDS
            counted = a.get("places", "-")
            meeting = a.get("meeting", "-")
            out.append(
                f"| {cell(a['title'])} | rating, {a['scale']} | {counted} | {meeting} | "
                f"{a['point']}, {words[a['point']]} | {a['point']}/{TOP_POINT} |"
            )
    out += ["", "## Fit with neighbouring files", ""]
    fit = p.fit or {}
    if fit.get("findings"):
        out += ["| Line | Line quoted | File | Note |", "|---|---|---|---|"]
        for f in fit["findings"]:
            out.append(
                f"| {f.get('line')} | '{cell(f.get('_text', ''))}' | {cell(f.get('file') or p.path)} | {cell(f.get('note', ''))} |"
            )
        if fit.get("statement"):
            out += ["", fit["statement"]]
    else:
        out.append(fit.get("statement") or NO_NEIGHBOURS)
    out += ["", "## Total", ""]
    score, n = file_score(p)
    if score is None:
        out += [NOTHING_APPLIES, ""]
        return "\n".join(out), None
    st = stars(score)
    out.append(f"Score: {fmt_score(score)}. Stars: {fmt_stars(st)} of {STAR_SCALE}. {n} questions counted.")
    out.append("")
    out.append(
        f"Formula: {FORMULA}. Here: {fmt_frac(score * n)} over {n} questions is {fmt_score(score)}, "
        f"times {STAR_SCALE} is {float(score * STAR_SCALE):.2f}, so {fmt_stars(st)} stars."
    )
    out += ["", NO_PREDICTION]
    if h["bound_parts"]:
        out += ["", LINTERS]
    out.append("")
    return "\n".join(out), score


def fmt_frac(x):
    return str(int(x)) if x.denominator == 1 else f"{float(x):.2f}"


def render(prepared, summary, version, table_rows):
    parts = []
    scored = []
    for p in prepared:
        text, score = render_one(p, version, table_rows)
        scored.append((p, text, score))
    if summary:
        ordered = sorted(
            scored, key=lambda t: (t[2] is None, t[2] if t[2] is not None else 0, t[0].path)
        )
        lines = ["# Summary", "", "| File | Kind | Score | Stars |", "|---|---|---|---|"]
        for p, _, score in ordered:
            if score is None:
                lines.append(f"| {p.path} | {p.header['kind']} | no score | - |")
            else:
                lines.append(f"| {p.path} | {p.header['kind']} | {fmt_score(score)} | {fmt_stars(stars(score))} |")
        parts.append("\n".join(lines) + "\n")
        scored = ordered
    parts += [t for _, t, _ in scored]
    return "\n".join(parts), all(s is None for _, _, s in scored)


# ---------------------------------------------------------------------------------------------------
# Verify


def verify(text):
    """Return (exit code, messages)."""
    reports = re.split(r"^(?=# Review: )", text, flags=re.MULTILINE)
    reports = [r for r in reports if r.startswith("# Review: ")]
    if not reports:
        return EXIT_REFUSED, ["no '# Review:' heading found; this is not a report report.py rendered"]
    messages, mismatch, totals = [], False, {}
    for r in reports:
        path = r.splitlines()[0][len("# Review: "):].strip()
        if EMPTY_LINE in r or NOTHING_APPLIES in r:
            totals[path] = None
            continue
        m = re.search(r"^## Score for each question\s*$(.*?)^## ", r, re.MULTILINE | re.DOTALL)
        t = re.search(r"^Score: (\d+\.\d+)\. Stars: ([\d.]+) of 5\. (\d+) questions counted\.", r, re.MULTILINE)
        if not m or not t:
            return EXIT_REFUSED, [f"{path}: the report has no scores table or no total line; it cannot be checked"]
        counts = []
        for row in m.group(1).splitlines():
            cells = [c.strip() for c in row.strip().strip("|").split("|")]
            if len(cells) != 6 or cells[0] in ("Question",) or set(cells[0]) <= set("-"):
                continue
            if cells[1] == "not rated":
                continue
            try:
                counts.append(Fraction(cells[5]))
            except ValueError:
                return EXIT_REFUSED, [f"{path}: '{cells[5]}' in the Counts column is not a number"]
        if not counts:
            return EXIT_REFUSED, [f"{path}: the scores table counts no question"]
        score = mean(counts)
        want = (fmt_score(score), fmt_stars(stars(score)), str(len(counts)))
        got = (t.group(1), t.group(2), t.group(3))
        totals[path] = want[:2]
        for name, w, g in zip(("score", "stars", "questions counted"), want, got):
            if w != g:
                mismatch = True
                messages.append(f"{path}: prints {name} {g}, but its scores table gives {w}")
    summary = re.search(r"^# Summary\s*$(.*?)(?=^# Review: )", text, re.MULTILINE | re.DOTALL)
    if summary:
        for row in summary.group(1).splitlines():
            cells = [c.strip() for c in row.strip().strip("|").split("|")]
            if len(cells) != 4 or cells[0] == "File" or set(cells[0]) <= set("-"):
                continue
            want = totals.get(cells[0])
            if want and (cells[2], cells[3]) != want:
                mismatch = True
                messages.append(
                    f"summary, {cells[0]}: prints score {cells[2]} and stars {cells[3]}, but its report gives "
                    f"{want[0]} and {want[1]}"
                )
    if not mismatch:
        messages.append(f"every printed total matches its table: {len(reports)} reports")
    return (EXIT_MISMATCH if mismatch else EXIT_OK), messages


# ---------------------------------------------------------------------------------------------------
# Schema


SCHEMA = {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "title": "persona-judge review record",
    "description": (
        "Written by the reviewer to one file in the system's temporary folder, never inside the reviewed "
        "project. Paths are relative to root. Answer all ten questions for each file, by their bold titles "
        "in review-questions.md, without the full stop. Quote every line word for word with its number."
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
                        "description": "One answer per question. A check: score. A frequency rating: scale, "
                        "source and places. A quality rating: scale, point and, below 4, findings. Or not_rated.",
                        "items": {
                            "type": "object",
                            "required": ["question"],
                            "properties": {
                                "question": {"type": "string"},
                                "score": {"enum": [0, 1], "description": "Checks only."},
                                "scale": {"enum": ["frequency", "quality"], "description": "Ratings only."},
                                "point": {"type": "integer", "minimum": 0, "maximum": 4,
                                          "description": "Quality ratings only; frequency points are counted."},
                                "source": {"type": "string", "description": "The question's source."},
                                "places": {
                                    "type": "array",
                                    "items": {
                                        "type": "object",
                                        "required": ["line", "quote", "meets"],
                                        "properties": {
                                            "line": {"type": "integer", "minimum": 1},
                                            "quote": {"type": "string"},
                                            "meets": {"type": "boolean"},
                                        },
                                    },
                                },
                                "findings": {
                                    "type": "array",
                                    "items": {
                                        "type": "object",
                                        "required": ["line", "quote"],
                                        "properties": {
                                            "line": {"type": "integer", "minimum": 1},
                                            "quote": {"type": "string"},
                                            "source": {"type": "string"},
                                            "rule": {"type": "string", "description": "A check.py row ID, such as PJ-001."},
                                        },
                                    },
                                },
                                "not_rated": {"type": "string", "description": "The reason it is not rated."},
                            },
                        },
                    },
                    "fit": {
                        "type": "object",
                        "description": "Fit with neighbouring files; apart from the score.",
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
        print(json.dumps(SCHEMA, indent=2))
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
        cat = Catalogue()
        table = check.load_table(check.DEFAULT_TABLE)
    except (OSError, ValueError, check.TableError) as exc:
        print(f"report.py: cannot load the review questions or the check table: {exc}", file=sys.stderr)
        return EXIT_REFUSED
    record, faults = load_record(args[0])
    prepared = []
    if record is not None:
        prepared, faults = validate(record, cat, table)
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
    text, nothing = render(prepared, summary, cat.version, len(table))
    print(text.rstrip("\n"))
    return EXIT_NO_SCORE if nothing else EXIT_OK


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
