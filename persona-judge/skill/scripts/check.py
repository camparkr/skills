#!/usr/bin/env python3
"""check.py: run the true/false checks in a table against persona files, without a model.

Usage:
  check.py [PATH ... | -] [--table FILE] [--format text|json] [--exit-zero] [--kind standing|delegated]

With no PATH, it checks what find.py finds in the project; with paths or '-', it takes them as find.py
does. --table names the table of checks; the default is references/failures.tsv beside this folder.
Each row of the table is run against each file, and one line is printed per row and file:

  row ID, score, place, the line quoted, message      (separated by tabs)

The score is 1 or 0, as the review questions score checks; '-' when the row does not apply to the
file's kind, or when the field it reads could not be read. The place is path:line for a 0 and the path
otherwise. With --format json, the same as one JSON array, with every line a row found.

Adding a row of an existing kind to the table needs no code change. The kinds:
  line-pattern       0 when a body line matches the pattern and not the unless pattern
  missing-path       0 when a path the body names, in backticks or a link, exists neither beside the file
                     nor from the project root
  field-and-line     0 when the field matches the pattern and a body line matches the unless pattern
  field-missing      0 when the field is absent or empty
  repeated-sentence  0 when a sentence of at least min_words words appears twice in the body, or the
                     description's sentence appears in the body

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

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import find  # noqa: E402
import personafile  # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))
DEFAULT_TABLE = os.path.join(HERE, "..", "references", "failures.tsv")
REVIEW_QUESTIONS = os.path.join(HERE, "..", "references", "review-questions.md")

# Exit codes, as the docstring states them (build specification §3c).
EXIT_CLEAN = 0
EXIT_ZERO_FOUND = 1
EXIT_ERROR = 2
EXIT_NOTHING = 3

COLUMNS = ["id", "question", "kind", "applies_to", "field", "pattern", "unless", "min_words", "source", "message"]
KINDS = ("line-pattern", "missing-path", "field-and-line", "field-missing", "repeated-sentence")
APPLIES = ("any", "standing", "delegated")
ID_RE = re.compile(r"^PJ-\d{3}$")
# The scale's score for a check, as the review questions give it: 1 when nothing contradicts the
# check, 0 when anything does.
ONE, ZERO = 1, 0
# A path the body names: in backticks, or as a Markdown link's target, ending in a file extension of
# one to five letters or digits.
BACKTICK_PATH = re.compile(r"`([^`\s]+\.[A-Za-z0-9]{1,5})`")
LINK_PATH = re.compile(r"\]\(([^)\s#]+\.[A-Za-z0-9]{1,5})(?:#[^)]*)?\)")
# Characters that make a backticked string a pattern or a placeholder rather than a path.
NOT_A_PATH = re.compile(r"[*?<>{}$|]|://|^mailto:")
FENCE = re.compile(r"^\s*(```|~~~)")
SENTENCE = re.compile(r"[^.!?]+[.!?]*")


class TableError(Exception):
    pass


def check_titles(path=REVIEW_QUESTIONS):
    """The titles of the checks in review-questions.md: the bold titles under '## Checks'."""
    try:
        text = open(path, encoding="utf-8").read()
    except OSError as exc:
        raise TableError(f"cannot read the review questions at {find.posix(path)}: {exc.strerror}")
    m = re.search(r"^## Checks\s*$(.*?)^## ", text, re.MULTILINE | re.DOTALL)
    if not m:
        raise TableError("review-questions.md has no '## Checks' section; the table's questions cannot be checked")
    return [t.rstrip(".") for t in re.findall(r"^\*\*(.+?)\*\*", m.group(1), re.MULTILINE)]


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
        if row["question"] not in titles:
            faults.append(
                f"{where}, column question: '{row['question']}'; expected one of the checks in "
                f"review-questions.md, word for word: {', '.join(titles)}"
            )
        if row["kind"] not in KINDS:
            faults.append(f"{where}, column kind: '{row['kind']}'; expected one of {', '.join(KINDS)}")
        if row["applies_to"] not in APPLIES:
            faults.append(f"{where}, column applies_to: '{row['applies_to']}'; expected any, standing or delegated")
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
        if row["kind"] == "repeated-sentence":
            if not row["min_words"].isdigit() or int(row["min_words"]) < 1:
                faults.append(f"{where}, column min_words: '{row['min_words']}'; expected a whole number above 0")
        elif row["min_words"]:
            faults.append(f"{where}, column min_words: '{row['min_words']}'; expected empty for a {row['kind']} row")
        out.append(row)
    if faults:
        raise TableError("\n".join(faults))
    return out


def outside_fences(body):
    """Body lines that are not inside a fenced code block."""
    inside = False
    for n, text in body:
        if FENCE.match(text):
            inside = not inside
            continue
        if not inside:
            yield n, text


def named_paths(text):
    for m in BACKTICK_PATH.finditer(text):
        yield m.group(1)
    for m in LINK_PATH.finditer(text):
        yield m.group(1)


def path_exists(ref, pf, root):
    if NOT_A_PATH.search(ref):
        return True
    ref = ref[2:] if ref.startswith("./") else ref
    if ref.startswith("~"):
        return os.path.exists(os.path.expanduser(ref))
    if os.path.isabs(ref):
        return os.path.exists(ref)
    return os.path.exists(os.path.join(pf.folder, ref)) or os.path.exists(os.path.join(root, ref))


def fold(text):
    """Fold case, Markdown emphasis and runs of space, for comparing sentences."""
    text = re.sub(r"^\s*(?:[-*+]|\d+[.)])\s+", "", text)
    text = re.sub(r"[*_`]", "", text)
    return re.sub(r"\s+", " ", text).strip().lower().rstrip(".!?")


def sentences(body):
    """Yield (line number, sentence) for the body, each sentence placed at the line it starts on."""
    for n, text in body:
        for m in SENTENCE.finditer(text):
            s = m.group(0).strip()
            if s:
                yield n, s


def run_row(row, pf, kind, root):
    """Run one row on one file; return (score, faults) where faults is a list of (line, quote, note)."""
    if row["applies_to"] not in ("any", kind):
        return None, [], f"applies to {row['applies_to']} files only"
    flags = re.IGNORECASE
    k = row["kind"]
    if k == "line-pattern":
        pat = re.compile(row["pattern"], flags)
        unless = re.compile(row["unless"], flags) if row["unless"] else None
        faults = [(n, t, "") for n, t in pf.body if pat.search(t) and not (unless and unless.search(t))]
    elif k == "missing-path":
        faults = []
        for n, t in outside_fences(pf.body):
            missing = [ref for ref in named_paths(t) if not path_exists(ref, pf, root)]
            if missing:
                faults.append((n, t, f"{', '.join(missing)} does not exist"))
    elif k in ("field-and-line", "field-missing"):
        field = row["field"]
        if field in pf.unparsed:
            return None, [], f"the field {field} could not be read; not scored"
        value = pf.field_text(field)
        if k == "field-missing":
            if value is None:
                return ZERO, [(None, "-", f"the field {field} is absent or empty")], ""
            return ONE, [], ""
        if value is None:
            return None, [], f"the file has no {field} field"
        if not re.search(row["pattern"], value, flags):
            return ONE, [], ""
        unless = re.compile(row["unless"], flags)
        faults = [(n, t, f"{field}: {value}") for n, t in pf.body if unless.search(t)]
    elif k == "repeated-sentence":
        minimum = int(row["min_words"])
        seen, faults = {}, []
        for n, s in sentences(pf.body):
            key = fold(s)
            if len(key.split()) < minimum:
                continue
            if key in seen:
                faults.append((n, pf.lines[n - 1], f"also on line {seen[key]}"))
            else:
                seen[key] = n
        description = pf.field_text("description")
        if description:
            for d in (fold(s) for s in SENTENCE.findall(description)):
                if len(d.split()) >= minimum and d in seen:
                    faults.append((seen[d], pf.lines[seen[d] - 1], "repeats the description"))
        faults.sort(key=lambda f: f[0])
    else:  # load_table rejects any other kind
        raise TableError(f"unknown kind {k}")
    return (ZERO if faults else ONE), faults, ""


def check_files(records, texts, table, kind_override=None, root=None):
    """Run every row against every file; return a list of result dicts in file order, then row order."""
    results = []
    for rec in records:
        pf = texts.get(rec["path"]) or personafile.read_path(rec.get("abspath") or rec["path"], rec["path"])
        if pf.empty:
            raise EmptyFile(rec["path"])
        kind = kind_override or rec["kind"]
        file_root = root or find.project_root(os.getcwd())
        for row in table:
            score, faults, note = run_row(row, pf, kind, file_root)
            base = {
                "id": row["id"], "path": rec["path"], "kind": kind, "question": row["question"],
                "source": row["source"], "score": score,
            }
            if score == ZERO:
                first = faults[0]
                more = f" (and {len(faults) - 1} more: lines {', '.join(str(f[0]) for f in faults[1:])})" if len(faults) > 1 else ""
                base.update(
                    line=first[0], quote=first[1].strip(),
                    message=(row["message"] + (f": {first[2]}" if first[2] else "")) + more,
                    lines=[{"line": f[0], "quote": f[1].strip(), "note": f[2]} for f in faults],
                )
            else:
                base.update(line=None, quote=None, message=note or None, lines=[])
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
    except personafile.PersonaError as exc:
        print(f"check.py: {exc}", file=sys.stderr)
        return EXIT_ERROR
    if not found.records:
        what = "the input is empty" if opts["paths"] == ["-"] else "no persona file found"
        print(f"check.py: nothing to check: {what}; name a file or folder to check", file=sys.stderr)
        return EXIT_NOTHING
    cwd = os.getcwd()
    for rec in found.records:
        if rec["path"] not in found.texts:
            rec["abspath"] = rec["path"] if os.path.isabs(rec["path"]) else os.path.join(
                cwd if opts["paths"] else find.project_root(cwd), rec["path"]
            )
    try:
        results = check_files(found.records, found.texts, table, opts["kind"], find.project_root(cwd))
    except personafile.PersonaError as exc:
        print(f"check.py: {exc}", file=sys.stderr)
        return EXIT_ERROR
    except EmptyFile as exc:
        print(f"check.py: nothing to check: {exc} is empty", file=sys.stderr)
        return EXIT_NOTHING
    if opts["format"] == "json":
        print(json.dumps([{k: v for k, v in r.items()} for r in results], indent=2))
    else:
        for r in results:
            print(text_line(r))
    if any(r["score"] == ZERO for r in results) and not opts["exit_zero"]:
        return EXIT_ZERO_FOUND
    return EXIT_CLEAN


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
