#!/usr/bin/env python3
"""find.py: find the personas in a project, or take the files, folders or text given; name each persona's kind
and set aside, with the reason, each file that is not a persona.

Usage:
  find.py [PATH ...] [--list FILE] [--format text|json]

A persona is a dedicated agent: a file in .claude/agents/ or .gemini/agents/ (a subagent), .codex/agents/*.toml
or .github/agents/*.agent.md (a custom agent), or one the project's list names.

With no PATH, the project is searched: the Git top level of the working folder, or the working folder outside
Git, skipping .git/ and node_modules/. It returns every persona, sorted by path, then every file it sets aside,
sorted by path, each with its reason:
  project instructions (CLAUDE.md, CLAUDE.local.md, AGENTS.md, GEMINI.md, .gemini/system.md, Copilot's
    instructions files and Cursor's rules), an output style (.claude/output-styles/), a README, and a skill
    (SKILL.md), at any depth.
Command files and index.md are neither returned nor set aside.

The project's list is personas.txt at the project root, or the file --list names: one line per persona, the
main file first and then the files that load with it, paths from the project root separated by spaces. Blank
lines and lines starting '#' are ignored. A listed persona is reviewed wherever it lies, and its files are its
own; a listed path that does not exist is reported with its line, and the persona is kept without it.

A named file is returned whatever its name, unless the set-aside table names it. A named folder returns the
personas in it and sets aside what the table names; when neither matches, it returns every .md, .mdc and .toml
file in it. '-' reads standard input as one file, labelled <session text>.

Each persona's kind is its location's (subagent or custom agent, with the harness), or 'persona'. It is
delegated when its location says so, or, elsewhere, when its frontmatter holds both name and description;
standing otherwise, and its basis says the kind was inferred. Session text is never delegated.

Each persona's three branches are printed for the record: delegated (with 'folder' or 'front matter'), the
harness its path names, and the settings it holds, the fields review-questions.md's settings row names. Each persona also lists the files its body names
that exist (candidates, which may load with it) and the files the list loads with it.

Output, one line per file, separated by tabs: for a persona, its path, kind, harness ('-' for none), delegated
or standing and the basis, then indented lines for the files the list loads with it, listed paths that do not
exist and candidates; for a file set aside, its path, 'set aside' and the reason. With --format json, one JSON
array of objects with path, kind, harness, delegated, settings, kind_basis, candidates, listed and list_missing, or, for a
file set aside, set_aside with its reason.

Exit codes: 0 one or more personas; 2 a usage error, an unreadable path or an unreadable list; 3 no persona
found (the files set aside are still listed), or empty input. This script changes no file.
"""

import json
import os
import subprocess
import sys
from fnmatch import fnmatchcase

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import personafile  # noqa: E402
import questions  # noqa: E402

# Exit codes, as the docstring states them (build specification §3b).
EXIT_FOUND = 0
EXIT_USAGE = 2
EXIT_NONE = 3

STANDING, DELEGATED = "standing", "delegated"
PERSONA = "persona"

# Dedicated personas, reviewed: the pattern, the kind and the harness (build specification §3b, round 3;
# vision v5, SI-1 and SI-11). A pattern matches the end of a file's path; '*' matches within one name and
# '**' any number of folders.
DEDICATED = (
    (".claude/agents/*.md", "subagent", "Claude Code"),
    (".gemini/agents/*.md", "subagent", "Gemini CLI"),
    (".codex/agents/*.toml", "custom agent", "Codex"),
    (".github/agents/*.agent.md", "custom agent", "GitHub Copilot"),
)

# Set aside, each with the reason printed (build specification §3b; vision v5, §1, SI-1, SI-11), matched at
# any depth. The table is read before the dedicated one, so a README.md or SKILL.md inside an agents folder is
# set aside.
INSTRUCTIONS_REASON = "project instructions: context for the agent, not a dedicated persona"
SET_ASIDE = (
    ("CLAUDE.md", "project instructions", INSTRUCTIONS_REASON),
    ("CLAUDE.local.md", "project instructions", INSTRUCTIONS_REASON),
    (".claude/CLAUDE.md", "project instructions", INSTRUCTIONS_REASON),
    ("AGENTS.md", "project instructions", INSTRUCTIONS_REASON),
    ("GEMINI.md", "project instructions", INSTRUCTIONS_REASON),
    (".gemini/system.md", "project instructions", INSTRUCTIONS_REASON),
    (".github/copilot-instructions.md", "project instructions", INSTRUCTIONS_REASON),
    (".github/instructions/**/*.instructions.md", "project instructions", INSTRUCTIONS_REASON),
    (".cursor/rules/*.mdc", "project instructions", INSTRUCTIONS_REASON),
    (".cursor/rules/*.md", "project instructions", INSTRUCTIONS_REASON),
    (".claude/output-styles/*.md", "output style", "an output style: it sets the main agent's tone, not a dedicated persona"),
    ("README.md", "README", "a README: documentation for people, not agent instructions"),
    ("SKILL.md", "skill", "a skill: review it with `skill-judge`"),
)

# The harnesses a dedicated location names; a file elsewhere has no known harness.
KNOWN_HARNESSES = tuple(h for _, _, h in DEDICATED)

# The project's list, at the project root unless --list names another (build specification §3b, A-28).
LIST_NAME = "personas.txt"
LIST_COMMENT = "#"

# Neither returned nor set aside: command files and indexes (specification A-2).
NEITHER_NAMES = ("index.md",)
COMMAND_FOLDERS = (".claude/commands",)
SKIP_FOLDERS = (".git", "node_modules")
# Extensions a named folder falls back to when neither table matches a file in it (A-4).
FALLBACK_EXTENSIONS = (".md", ".mdc", ".toml")


def posix(path):
    return path.replace(os.sep, "/")


def _parts_match(parts, pparts):
    """Whether path parts match pattern parts exactly, '**' standing for any number of parts."""
    if not pparts:
        return not parts
    if pparts[0] == "**":
        return any(_parts_match(parts[i:], pparts[1:]) for i in range(len(parts) + 1))
    return bool(parts) and fnmatchcase(parts[0], pparts[0]) and _parts_match(parts[1:], pparts[1:])


def _ends_with(path, pattern):
    parts = posix(os.path.abspath(path)).split("/")
    pparts = pattern.split("/")
    return any(_parts_match(parts[i:], pparts) for i in range(len(parts)))


def match_dedicated(path):
    """Return (pattern, kind, harness) for a dedicated persona's path, or None."""
    for pattern, kind, harness in DEDICATED:
        if _ends_with(path, pattern):
            return pattern, kind, harness
    return None


def match_set_aside(path):
    """Return (pattern, kind, reason) for a path the set-aside table names, or None."""
    for pattern, kind, reason in SET_ASIDE:
        if _ends_with(path, pattern):
            return pattern, kind, reason
    return None


def is_neither(path):
    p = posix(os.path.abspath(path))
    return os.path.basename(p) in NEITHER_NAMES or any(f"/{folder}/" in p for folder in COMMAND_FOLDERS)


def project_root(start="."):
    """The Git top level of start, or start itself outside Git."""
    try:
        out = subprocess.run(
            ["git", "-C", start, "rev-parse", "--show-toplevel"],
            capture_output=True, text=True, timeout=10,
        )
        if out.returncode == 0 and out.stdout.strip():
            return out.stdout.strip()
    except (OSError, subprocess.SubprocessError):
        pass
    return os.path.abspath(start)


def walk(folder):
    """Every file under folder, skipping .git/ and node_modules/, in sorted order."""
    for root, dirs, files in os.walk(folder):
        dirs[:] = sorted(d for d in dirs if d not in SKIP_FOLDERS)
        for name in sorted(files):
            yield os.path.join(root, name)


def display(path, base):
    """A path for output: relative to base when inside it, forward slashes always."""
    absolute = os.path.abspath(path)
    try:
        rel = os.path.relpath(absolute, base)
    except ValueError:
        return posix(absolute)
    return posix(absolute) if rel.startswith("..") else posix(rel)


def same(a, b):
    return os.path.normcase(os.path.realpath(a)) == os.path.normcase(os.path.realpath(b))


# How the delegated branch was read, printed beside its answer (build specification §3b, round 4).
BY_FOLDER, BY_FRONT_MATTER = "folder", "front matter"


def infer_delegated(pf):
    """Whether a persona outside the dedicated locations is delegated, from its frontmatter (A-5)."""
    if pf.frontmatter.get("name") and pf.frontmatter.get("description"):
        return True, "inferred: its frontmatter holds name and description"
    return False, "inferred: its frontmatter does not hold both name and description"


def settings_held(pf):
    """The settings branch: the fields the file holds that grant or restrict what the agent can do, in the order
    review-questions.md's settings row names them (read at run time, never written here)."""
    fields = questions.load_cached().settings_fields
    return [f for f in fields if f in pf.unparsed or pf.field_text(f) is not None]


def branch_text(rec):
    """The three branches as find.py and check.py print them."""
    if rec["delegated"]:
        delegated = f"delegated yes ({rec.get('_delegated_basis') or BY_FRONT_MATTER})"
    else:
        delegated = "delegated no"
    settings = ", ".join(rec.get("settings") or []) or "none"
    return f"{delegated}; harness {rec.get('harness') or 'none'}; settings {settings}"


class Listing:
    """The project's list: each listed persona's main file, with the files that load with it."""

    def __init__(self, name="personas.txt"):
        self.name = name
        self.mains = {}  # real path of a main file -> {"line", "extras": [abs], "missing": [(rel, line)]}
        self.extras = set()  # real paths of the files listed after a main file
        self.notes = []  # what the list says that cannot be followed, for standard error

    def entry(self, path):
        return self.mains.get(os.path.realpath(path))

    def is_extra(self, path):
        return os.path.realpath(path) in self.extras


def read_list(list_path, root, cwd):
    """Read the project's list. A list --list names must be readable; personas.txt need not exist."""
    if list_path is None:
        path, name = os.path.join(root, LIST_NAME), LIST_NAME
        if not os.path.isfile(path):
            return Listing(name)
    else:
        path = list_path if os.path.isabs(list_path) else os.path.join(cwd, list_path)
        name = posix(list_path)
    try:
        with open(path, encoding="utf-8-sig") as fh:
            lines = fh.read().splitlines()
    except FileNotFoundError:
        raise personafile.PersonaError(f"cannot read the list {name}: no such file; check the path --list names")
    except (OSError, UnicodeDecodeError) as exc:
        raise personafile.PersonaError(f"cannot read the list {name}: {getattr(exc, 'strerror', None) or exc}; check the file")
    listing = Listing(name)
    for n, line in enumerate(lines, start=1):
        if not line.strip() or line.lstrip().startswith(LIST_COMMENT):
            continue
        parts = line.split()
        main = os.path.join(root, parts[0])
        if not os.path.isfile(main):
            listing.notes.append(f"{name}, line {n}: {parts[0]} does not exist; that persona cannot be reviewed")
            continue
        entry = {"line": n, "extras": [], "missing": []}
        for rel in parts[1:]:
            extra = os.path.join(root, rel)
            if os.path.isfile(extra):
                entry["extras"].append(os.path.normpath(extra))
                listing.extras.add(os.path.realpath(extra))
            else:
                entry["missing"].append((rel, n))
                listing.notes.append(f"{name}, line {n}: {rel} does not exist; the persona is reviewed without it")
        listing.mains[os.path.realpath(main)] = entry
    return listing


def candidates(pf, path, root, base, skip):
    """The files a persona's body names that exist, other than itself and the files in skip: (path, line)."""
    out, seen = [], set()
    for n, text in personafile.outside_fences(pf.body):
        for ref in personafile.named_paths(text):
            found = personafile.resolve(ref, pf.folder, root)
            if not found or not os.path.isfile(found) or same(found, path):
                continue
            key = os.path.realpath(found)
            if key in seen or key in skip:
                continue
            seen.add(key)
            out.append({"path": display(found, base), "line": n})
    return out


def classify(path, shown, base, root, listing):
    """The record for one file on disk: a persona, or a file set aside with its reason."""
    entry = listing.entry(path)
    if entry is None:
        aside = match_set_aside(path)
        if aside:
            pattern, kind, reason = aside
            return {
                "path": shown, "kind": kind, "harness": None, "delegated": False,
                "kind_basis": f"its path matches {pattern}", "set_aside": reason,
            }
    pf = personafile.read_path(path, shown)
    loc = match_dedicated(path)
    if loc:
        pattern, kind, harness = loc
        delegated, basis, by = True, f"its path matches {pattern}", BY_FOLDER
    else:
        kind, harness = PERSONA, None
        delegated, basis = infer_delegated(pf)
        by = BY_FRONT_MATTER
    extras = entry["extras"] if entry else []
    if entry:
        basis = f"{listing.name}, line {entry['line']} lists it; " + basis
    skip = {os.path.realpath(e) for e in extras}
    return {
        "path": shown, "kind": kind, "harness": harness, "delegated": delegated, "kind_basis": basis,
        "settings": settings_held(pf), "_delegated_basis": by if delegated else None,
        "candidates": candidates(pf, path, root, base, skip),
        "listed": [display(e, base) for e in extras],
        "list_missing": [{"path": rel, "line": n} for rel, n in (entry["missing"] if entry else [])],
        "_abspath": os.path.abspath(path),
        "_listed_abs": list(extras),
    }


# Session text is never delegated: nothing chooses it (build specification §3b, round 4).
SESSION_BASIS = "session text: nothing chooses it, so it is not delegated"


def record_for_text(pf):
    """The record for text read from standard input: a persona that is not delegated."""
    return {
        "path": pf.path, "kind": PERSONA, "harness": None, "delegated": False, "kind_basis": SESSION_BASIS,
        "settings": settings_held(pf), "candidates": [], "listed": [], "list_missing": [],
    }


class Found:
    """What a search returned: personas and files set aside, the persona files read from standard input,
    and what the list says that cannot be followed."""

    def __init__(self):
        self.records = []
        self.texts = {}  # label -> PersonaFile, for standard input
        self.notes = []

    @property
    def personas(self):
        return [r for r in self.records if not r.get("set_aside")]

    @property
    def set_aside(self):
        return [r for r in self.records if r.get("set_aside")]


def search(paths, stdin=None, cwd=None, list_path=None):
    """Find personas. Raise personafile.PersonaError for an unreadable path or list; return a Found."""
    cwd = cwd or os.getcwd()
    root = project_root(cwd)
    listing = read_list(list_path, root, cwd)
    found = Found()
    found.notes = list(listing.notes)
    seen = set()

    def add(path, base):
        key = os.path.realpath(path)
        if key in seen:
            return
        seen.add(key)
        found.records.append(classify(path, display(path, base), base, root, listing))

    if not paths:
        for f in walk(root):
            if listing.is_extra(f) and not listing.entry(f):
                continue
            if listing.entry(f) or match_set_aside(f) or match_dedicated(f):
                add(f, root)
        for main in listing.mains:
            if main not in seen:
                add(main, root)
        personas = sorted(found.personas, key=lambda r: r["path"])
        aside = sorted(found.set_aside, key=lambda r: r["path"])
        found.records = personas + aside
        return found
    for given in paths:
        if given == "-":
            text = (stdin if stdin is not None else sys.stdin).read()
            pf = personafile.read_text(text, folder=cwd)
            if pf.empty:
                continue
            found.texts[pf.path] = pf
            found.records.append(record_for_text(pf))
            continue
        shown = posix(given)
        target = given if os.path.isabs(given) else os.path.join(cwd, given)
        if os.path.isdir(target):
            files = [
                f for f in walk(target)
                if not (listing.is_extra(f) and not listing.entry(f))
                and (listing.entry(f) or match_set_aside(f) or match_dedicated(f))
            ]
            if not files:
                files = [
                    f for f in walk(target)
                    if f.endswith(FALLBACK_EXTENSIONS) and not is_neither(f) and not listing.is_extra(f)
                ]
            for f in files:
                add(f, cwd)
        elif os.path.exists(target):
            key = os.path.realpath(target)
            if key not in seen:
                seen.add(key)
                found.records.append(classify(target, display(target, cwd) if not os.path.isabs(given) else shown, cwd, root, listing))
        else:
            raise personafile.PersonaError(f"cannot read {shown}: no such file or folder; check the path")
    found.records = found.personas + found.set_aside
    return found


def public(record):
    """A record as find.py prints it, without the fields only the other scripts use."""
    return {k: v for k, v in record.items() if not k.startswith("_")}


def text_lines(found, list_name):
    out = []
    for r in found.records:
        if r.get("set_aside"):
            out.append("\t".join((r["path"], "set aside", r["set_aside"])))
            continue
        out.append("\t".join((r["path"], r["kind"], r["harness"] or "-", DELEGATED if r["delegated"] else STANDING, r["kind_basis"])))
        out.append(f"  branches: {branch_text(r)}")
        out += [f"  loads with it: {p} ({list_name})" for p in r["listed"]]
        out += [f"  missing from the list: {m['path']} ({list_name}, line {m['line']})" for m in r["list_missing"]]
        out += [f"  may load: {c['path']} (line {c['line']})" for c in r["candidates"]]
    return out


def parse_args(argv):
    """Return (paths, format, list path) or raise ValueError with the message."""
    paths, fmt, list_path = [], "text", None
    i = 0
    while i < len(argv):
        arg = argv[i]
        if arg in ("--format", "--list"):
            if i + 1 >= len(argv):
                raise ValueError(f"{arg} takes a value")
            if arg == "--format":
                if argv[i + 1] not in ("text", "json"):
                    raise ValueError("--format takes text or json")
                fmt = argv[i + 1]
            else:
                list_path = argv[i + 1]
            i += 2
            continue
        if arg.startswith("--") or (arg.startswith("-") and arg != "-"):
            raise ValueError(f"unknown option {arg}; run find.py --help")
        paths.append(arg)
        i += 1
    return paths, fmt, list_path


def main(argv):
    if "-h" in argv or "--help" in argv:
        print(__doc__.strip())
        return EXIT_FOUND
    try:
        paths, fmt, list_path = parse_args(argv)
    except ValueError as exc:
        print(f"find.py: {exc}", file=sys.stderr)
        return EXIT_USAGE
    try:
        found = search(paths, list_path=list_path)
    except personafile.PersonaError as exc:
        print(f"find.py: {exc}", file=sys.stderr)
        return EXIT_USAGE
    except questions.ContractError as exc:
        print(f"find.py: {exc}", file=sys.stderr)
        return EXIT_USAGE
    for note in found.notes:
        print(f"find.py: {note}", file=sys.stderr)
    if found.records:
        if fmt == "json":
            print(json.dumps([public(r) for r in found.records], indent=2))
        else:
            print("\n".join(text_lines(found, posix(list_path) if list_path else LIST_NAME)))
    if not found.personas:
        if paths == ["-"]:
            print("find.py: the input is empty; paste the persona text, or name a file", file=sys.stderr)
        else:
            print("find.py: no persona found; name a file or folder to review", file=sys.stderr)
        return EXIT_NONE
    return EXIT_FOUND


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
