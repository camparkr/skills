#!/usr/bin/env python3
"""check.py: run the true/false checks in a table against persona files, without a model.

Usage:
  check.py [PATH ... | -] [--table FILE] [--format text|json] [--exit-zero] [--kind standing|delegated]

With no PATH, it checks what find.py finds in the project; with paths or '-', it takes them as find.py
does. --table names the table of checks; the default is references/failures.tsv beside this folder.
Each row of the table is run against each file, and one line is printed per row and file:

  row ID, score, place, the line quoted, message      (separated by tabs)

The score is 1 or 0, as the review questions score checks; '-' when the row does not apply: to a standing
or delegated persona, to another harness than the row's, to a file with no such field or no harness its path
names, or to a field it could not read. The place is path:line for a 0 and the path otherwise. With
--format json, the same as one JSON array, with every line a row found.

Every kind reads the body through one mask: fenced code, Markdown block quotes and quoted spans (from an
opening ' or " to its closing mark, over the paragraph) become spaces, so quoted examples are not the file's
own instruction and every line keeps its number. A pointer is a path, in backticks or as a link target, with a
/ or a file extension, in a sentence that tells the agent to read it: a base form of read, open, load, see,
consult, follow, refer or look, first in the sentence or after its opening clause, or after 'you', a modal or
'please'; a list item counts when the line ending in a colon that introduces it does.

Before each persona's rows, one line gives its three branches: delegated, the harness its path names, and
the settings it holds, as find.py prints them.

Files set aside (project instructions, output styles, READMEs and skills) are not checked. A persona the
project's list names is checked over all its files, each under the persona's kind and harness, except that a
field-missing row runs on the main file only and prints '-' for the others: a field the persona declares lives
in its main file's front matter.

Adding a row of an existing kind to the table needs no code change. A row names one of the checks the
review questions mark *script*; the checks they mark *reading* are the reviewer's. A row's harness column is
empty for every harness, or names the one harness it applies to. The kinds:
  line-pattern     0 when a body line, read with quoted and example text masked, matches the pattern and
                   not the unless pattern
  missing-path     0 when a pointer names a path that exists neither in the file's folder nor in any
                   folder above it, up to the project root
  field-and-line   0 when the field matches the pattern and a body line matches the unless pattern
  field-missing    0 when the field is absent or empty; the line quoted is the one that names the agent
  harness-default  0 when a body line matches a row of the defaults table named in the data column,
                   for the file's harness, and not that row's unless pattern; a file whose harness its
                   path does not name is not checked. A new default is a new row of that table.

The data column names the defaults table: a file beside the check table, or else in references/. Its
columns: id (HD- and three digits), harness, default, pattern, unless, source.

Exit codes, so a hook or a pre-commit step can call it:
  0 every row scored 1 or did not apply
  1 one or more rows scored 0
  2 a usage error, an unreadable file or a table error, which names the table's line
  3 nothing to check: no persona file found, or an empty input
--exit-zero turns 1 into 0 and leaves the others, so whether a hook blocks is the installer's choice.
This script changes no file.
"""

import csv
import json
import os
import re
import sys

# Write no bytecode beside the scripts: a review changes no file, and an import would otherwise leave __pycache__.
sys.dont_write_bytecode = True
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import find  # noqa: E402
import personafile  # noqa: E402
import questions  # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))
DEFAULT_TABLE = os.path.join(HERE, "..", "references", "failures.tsv")
REFERENCES = os.path.join(HERE, "..", "references")
# The folder of parts questions.py joins into the review questions.
REVIEW_QUESTIONS = os.path.join(REFERENCES, "questions")

# Exit codes, as the docstring states them.
EXIT_CLEAN = 0
EXIT_ZERO_FOUND = 1
EXIT_ERROR = 2
EXIT_NOTHING = 3

COLUMNS = ["id", "question", "kind", "applies_to", "harness", "field", "pattern", "unless", "data", "source", "message"]
KINDS = ("line-pattern", "missing-path", "field-and-line", "field-missing", "harness-default")
# The columns of the defaults table a harness-default row reads.
DEFAULTS_COLUMNS = ["id", "harness", "default", "pattern", "unless", "source"]
DEFAULTS_ID_RE = re.compile(r"^HD-\d{3}$")
# The harnesses find.py names from a file's path; any other file has no known harness.
KNOWN_HARNESSES = frozenset(find.KNOWN_HARNESSES)
APPLIES = ("any", "standing", "delegated")
ID_RE = re.compile(r"^PJ-\d{3}$")
# The scale's score for a check, as the review questions give it: 1 when nothing contradicts the
# check, 0 when anything does.
ONE, ZERO = 1, 0
# The frontmatter field whose line a field-missing 0 quotes, since a missing field has no line of its own:
# the line that names the agent.
NAME_FIELD = "name"
# The kinds that run on a persona's main file only: a field the persona must declare, such as tools, lives in its
# main file's front matter, and a file the persona loads holds none.
MAIN_FILE_KINDS = ("field-missing",)
MAIN_FILE_NOTE = "applies to the persona's main file only"


class TableError(Exception):
    pass


def check_titles(path=REVIEW_QUESTIONS):
    """The checks in the review questions as {title: 'script' or 'reading'}, read by questions.py under their
    markup contract; questions that break the contract are a table error naming the part file and its line."""
    try:
        qs = questions.load_cached(path)
    except OSError as exc:
        raise TableError(f"cannot read the review questions at {find.posix(path)}: {exc.strerror}")
    except questions.ContractError as exc:
        raise TableError(str(exc))
    return {q.title: q.kind for q in qs.questions if q.kind in questions.CHECK_KINDS}


def load_defaults(path, shown):
    """Read and validate a defaults table; return its rows. Raise TableError naming every fault."""
    try:
        with open(path, encoding="utf-8", newline="") as fh:
            rows = list(csv.reader(fh, delimiter="\t", quoting=csv.QUOTE_NONE))
    except OSError as exc:
        raise TableError(f"cannot read the defaults table {shown}: {exc.strerror}; check the data column")
    if not rows or rows[0] != DEFAULTS_COLUMNS:
        raise TableError(f"{shown}, line 1: the header must be {', '.join(DEFAULTS_COLUMNS)}, tab-separated")
    faults, out, seen = [], [], {}
    for n, cells in enumerate(rows[1:], start=2):
        if not any(c.strip() for c in cells):
            continue
        where = f"{shown}, line {n}"
        if len(cells) != len(DEFAULTS_COLUMNS):
            faults.append(f"{where}: {len(cells)} columns; expected {len(DEFAULTS_COLUMNS)}, tab-separated")
            continue
        row = dict(zip(DEFAULTS_COLUMNS, cells))
        if not DEFAULTS_ID_RE.match(row["id"]):
            faults.append(f"{where}, column id: '{row['id']}'; expected HD- and three digits, such as HD-004")
        elif row["id"] in seen:
            faults.append(f"{where}, column id: {row['id']} is already used on line {seen[row['id']]}; expected a unique ID")
        else:
            seen[row["id"]] = n
        if not row["harness"].strip():
            faults.append(f"{where}, column harness: empty; expected a harness as find.py names it, such as Claude Code")
        if not row["pattern"]:
            faults.append(f"{where}, column pattern: empty; a default needs the pattern of a line asking for it")
        for col in ("pattern", "unless"):
            if row[col]:
                try:
                    re.compile(row[col], re.IGNORECASE)
                except re.error as exc:
                    faults.append(f"{where}, column {col}: the regular expression does not compile ({exc})")
        out.append(row)
    if faults:
        raise TableError("\n".join(faults))
    return out


def load_table(path):
    """Read and validate the table; return a list of row dicts. Raise TableError naming every fault."""
    shown = find.posix(path)
    try:
        with open(path, encoding="utf-8", newline="") as fh:
            rows = list(csv.reader(fh, delimiter="\t", quoting=csv.QUOTE_NONE))
    except OSError as exc:
        raise TableError(f"cannot read the table {shown}: {exc.strerror}; check the path")
    if not rows:
        raise TableError(f"{shown}: the table is empty; its first line must be the header")
    if rows[0] != COLUMNS:
        raise TableError(f"{shown}, line 1: the header must be {', '.join(COLUMNS)}, tab-separated")
    titles = check_titles()
    faults, out, seen = [], [], {}
    for n, cells in enumerate(rows[1:], start=2):
        if not any(c.strip() for c in cells):
            continue
        where = f"{shown}, line {n}"
        if len(cells) != len(COLUMNS):
            faults.append(f"{where}: {len(cells)} columns; expected {len(COLUMNS)}, tab-separated")
            continue
        row = dict(zip(COLUMNS, cells))
        if not ID_RE.match(row["id"]):
            faults.append(f"{where}, column id: '{row['id']}'; expected PJ- and three digits, such as PJ-005")
        elif row["id"] in seen:
            faults.append(f"{where}, column id: {row['id']} is already used on line {seen[row['id']]}; expected a unique ID")
        else:
            seen[row["id"]] = n
        if titles.get(row["question"]) != "script":
            what = "a reading check, which the reviewer answers" if row["question"] in titles else "not a check"
            faults.append(
                f"{where}, column question: '{row['question']}' is {what}; expected one of the checks marked "
                f"script in the review questions, word for word: {', '.join(t for t, m in titles.items() if m == 'script')}"
            )
        if row["kind"] not in KINDS:
            faults.append(f"{where}, column kind: '{row['kind']}'; expected one of {', '.join(KINDS)}")
        if row["applies_to"] not in APPLIES:
            faults.append(f"{where}, column applies_to: '{row['applies_to']}'; expected any, standing or delegated")
        if row["harness"] and row["harness"] not in KNOWN_HARNESSES:
            faults.append(
                f"{where}, column harness: '{row['harness']}'; expected empty, or one harness as find.py names it: "
                f"{', '.join(sorted(KNOWN_HARNESSES))}"
            )
        for col in ("pattern", "unless"):
            if row[col]:
                try:
                    re.compile(row[col], re.IGNORECASE)
                except re.error as exc:
                    faults.append(f"{where}, column {col}: the regular expression does not compile ({exc})")
        if row["kind"] in ("line-pattern",) and not row["pattern"]:
            faults.append(f"{where}, column pattern: empty; a line-pattern row needs a pattern")
        if row["kind"] in ("field-and-line", "field-missing") and not row["field"]:
            faults.append(f"{where}, column field: empty; a {row['kind']} row needs a field")
        if row["kind"] == "field-and-line" and not (row["pattern"] and row["unless"]):
            faults.append(f"{where}, columns pattern and unless: a field-and-line row needs both")
        if row["kind"] == "harness-default":
            if not row["data"]:
                faults.append(f"{where}, column data: empty; a harness-default row names its defaults table")
            else:
                # Beside the check table first, so a copied pair of tables reads its own copy; then
                # references/, where the skill keeps its own defaults table.
                beside = os.path.join(os.path.dirname(os.path.abspath(path)), row["data"])
                data_path = beside if os.path.exists(beside) else os.path.join(REFERENCES, row["data"])
                try:
                    row["_defaults"] = load_defaults(data_path, find.posix(row["data"]))
                except TableError as exc:
                    faults.append(f"{where}, column data: {exc}")
        elif row["data"]:
            faults.append(f"{where}, column data: '{row['data']}'; expected empty for a {row['kind']} row")
        out.append(row)
    if faults:
        raise TableError("\n".join(faults))
    return out


def run_row(row, pf, delegated, root, harness=None, main=True):
    """Run one row on one file; return (score, faults, note). Each fault is a dict: line, quote, note and,
    for a field-and-line row, field_line and field_quote, the line where the field is set. main is False for a
    file that loads with a persona, where a field-missing row does not apply."""
    if not main and row["kind"] in MAIN_FILE_KINDS:
        return None, [], MAIN_FILE_NOTE
    kind = find.DELEGATED if delegated else find.STANDING
    if row["applies_to"] not in ("any", kind):
        return None, [], f"applies to {row['applies_to']} personas only"
    if row["harness"] and row["harness"] != harness:
        return None, [], f"applies to {row['harness']} files only"
    flags = re.IGNORECASE
    k = row["kind"]
    # Every kind reads the body through the mask; a finding quotes the line as the file holds it.
    masked = personafile.masked_body(pf)
    original = dict(pf.body)
    if k == "line-pattern":
        pat = re.compile(row["pattern"], flags)
        unless = re.compile(row["unless"], flags) if row["unless"] else None
        faults = [
            fault(n, original[n]) for n, t in masked
            if pat.search(t) and not (unless and unless.search(t))
        ]
    elif k == "missing-path":
        faults, by_line = [], {}
        for n, ref in personafile.pointers(pf):
            if not personafile.resolve_up(ref, pf.folder, root) and ref not in by_line.setdefault(n, []):
                by_line[n].append(ref)
        for n, missing in by_line.items():
            if missing:
                faults.append(fault(n, original[n], f"{', '.join(missing)} does not exist"))
    elif k in ("field-and-line", "field-missing"):
        field = row["field"]
        if field in pf.unparsed:
            return None, [], f"the field {field} could not be read; not scored"
        value = pf.field_text(field)
        if k == "field-missing":
            if value is None:
                at = pf.field_line(NAME_FIELD) or 1
                return ZERO, [fault(at, pf.lines[at - 1] if pf.lines else "", f"its {field} field is missing or empty")], ""
            return ONE, [], ""
        if value is None:
            return None, [], f"the file has no {field} field"
        if not re.search(row["pattern"], value, flags):
            return ONE, [], ""
        unless = re.compile(row["unless"], flags)
        at = pf.field_line(field)
        faults = [
            dict(fault(n, original[n], f"{field}: {value}"), field_line=at, field_quote=pf.lines[at - 1].strip() if at else None)
            for n, t in masked if unless.search(t)
        ]
    elif k == "harness-default":
        if harness not in KNOWN_HARNESSES:
            return None, [], "the file's path names no harness"
        faults = []
        for n, t in masked:
            for d in row["_defaults"]:
                if d["harness"] != harness or not re.search(d["pattern"], t, flags):
                    continue
                if d["unless"] and re.search(d["unless"], t, flags):
                    continue
                faults.append(fault(n, original[n], f"{d['id']}, {harness} {d['default']}"))
                break
    else:  # load_table rejects any other kind
        raise TableError(f"unknown kind {k}")
    return (ZERO if faults else ONE), faults, ""


def fault(line, quote, note=""):
    return {"line": line, "quote": quote.strip() if isinstance(quote, str) else quote, "note": note}


def persona_files(rec, texts):
    """A persona's files as (path shown, PersonaFile): its main file, then the files its list loads with it."""
    main = texts.get(rec["path"]) or personafile.read_path(rec.get("_abspath") or rec["path"], rec["path"])
    out = [(rec["path"], main)]
    for shown, absolute in zip(rec.get("listed") or [], rec.get("_listed_abs") or []):
        out.append((shown, personafile.read_path(absolute, shown)))
    return out


def check_files(records, texts, table, kind_override=None, root=None):
    """Run every row against every file of every persona; return a list of result dicts in persona order,
    then file order, then row order. Files set aside are skipped."""
    results = []
    for rec in records:
        if rec.get("set_aside"):
            continue
        files = persona_files(rec, texts)
        if files[0][1].empty:
            raise EmptyFile(rec["path"])
        delegated = rec["delegated"] if kind_override is None else kind_override == find.DELEGATED
        branches = {"delegated": delegated, "harness": rec.get("harness"), "settings": list(rec.get("settings") or [])}
        line = find.branch_text(dict(rec, delegated=delegated))
        file_root = root or find.project_root(os.getcwd())
        for i, (shown, pf) in enumerate(files):
            for r in check_one(shown, pf, rec["kind"], delegated, rec.get("harness"), table, file_root, main=i == 0):
                r.update(persona=rec["path"], branches=branches, _branch_text=line)
                results.append(r)
    return results


def check_one(shown, pf, kind, delegated, harness, table, root, main=True):
    """Run every row against one file, under its persona's kind, delegation and harness; main is False for a file
    that loads with the persona."""
    results = []
    for row in table:
        score, faults, note = run_row(row, pf, delegated, root, harness, main)
        base = {
            "id": row["id"], "path": shown, "kind": kind, "delegated": delegated, "question": row["question"],
            "source": row["source"], "score": score,
        }
        if score == ZERO:
            first = faults[0]
            more = f" (and {len(faults) - 1} more: lines {', '.join(str(f['line']) for f in faults[1:])})" if len(faults) > 1 else ""
            base.update(
                line=first["line"], quote=first["quote"],
                message=(row["message"] + (f": {first['note']}" if first["note"] else "")) + more,
                row_message=row["message"],
                lines=faults,
            )
        else:
            base.update(line=None, quote=None, message=note or None, row_message=row["message"], lines=[])
        results.append(base)
    return results


class EmptyFile(Exception):
    pass


def text_line(r):
    score = "-" if r["score"] is None else str(r["score"])
    place = f"{r['path']}:{r['line']}" if r["score"] == ZERO and r["line"] else r["path"]
    quote = "'" + r["quote"].replace("\t", " ") + "'" if r["score"] == ZERO and r["quote"] not in (None, "-") else "-"
    message = (r["message"] or "-").replace("\t", " ")
    return "\t".join((r["id"], score, place, quote, message))


def parse_args(argv):
    opts = {"paths": [], "table": DEFAULT_TABLE, "format": "text", "exit_zero": False, "kind": None}
    i = 0
    while i < len(argv):
        a = argv[i]
        if a in ("--table", "--format", "--kind"):
            if i + 1 >= len(argv):
                raise ValueError(f"{a} takes a value")
            v = argv[i + 1]
            if a == "--format" and v not in ("text", "json"):
                raise ValueError("--format takes text or json")
            if a == "--kind" and v not in ("standing", "delegated"):
                raise ValueError(f"--kind takes standing or delegated, not '{v}'")
            opts[a[2:]] = v
            i += 2
            continue
        if a == "--exit-zero":
            opts["exit_zero"] = True
        elif a.startswith("-") and a != "-":
            raise ValueError(f"unknown option {a}; run check.py --help")
        else:
            opts["paths"].append(a)
        i += 1
    return opts


def main(argv):
    if "-h" in argv or "--help" in argv:
        print(__doc__.strip())
        return EXIT_CLEAN
    try:
        opts = parse_args(argv)
    except ValueError as exc:
        print(f"check.py: {exc}", file=sys.stderr)
        return EXIT_ERROR
    try:
        table = load_table(opts["table"])
    except TableError as exc:
        print(f"check.py: table error:\n{exc}", file=sys.stderr)
        return EXIT_ERROR
    try:
        found = find.search(opts["paths"])
    except questions.ContractError as exc:
        print(f"check.py: {exc}", file=sys.stderr)
        return EXIT_ERROR
    except personafile.PersonaError as exc:
        print(f"check.py: {exc}", file=sys.stderr)
        return EXIT_ERROR
    for note in found.notes:
        print(f"check.py: {note}", file=sys.stderr)
    if not found.personas:
        for r in found.set_aside:
            print(f"check.py: {r['path']} is set aside: {r['set_aside']}", file=sys.stderr)
        what = "the input is empty" if opts["paths"] == ["-"] else "no persona found"
        print(f"check.py: nothing to check: {what}; name a file or folder to check", file=sys.stderr)
        return EXIT_NOTHING
    cwd = os.getcwd()
    try:
        results = check_files(found.records, found.texts, table, opts["kind"], find.project_root(cwd))
    except personafile.PersonaError as exc:
        print(f"check.py: {exc}", file=sys.stderr)
        return EXIT_ERROR
    except EmptyFile as exc:
        print(f"check.py: nothing to check: {exc} is empty", file=sys.stderr)
        return EXIT_NOTHING
    if opts["format"] == "json":
        print(json.dumps([{k: v for k, v in r.items() if not k.startswith("_")} for r in results], indent=2))
    else:
        shown = set()
        for r in results:
            if r["persona"] not in shown:
                # The three branches, printed once per persona, so the reader sees how each was read.
                shown.add(r["persona"])
                print(f"{r['persona']}\tbranches: {r['_branch_text']}")
            print(text_line(r))
    if any(r["score"] == ZERO for r in results) and not opts["exit_zero"]:
        return EXIT_ZERO_FOUND
    return EXIT_CLEAN


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
