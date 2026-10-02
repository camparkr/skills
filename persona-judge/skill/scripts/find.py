#!/usr/bin/env python3
"""find.py: find the persona files in a project, or take the files, folders or text given, and name each one's kind.

Usage:
  find.py [PATH ...] [--format text|json]

With no PATH, the project is searched: the Git top level of the working folder, or the working folder
outside Git. Every file whose path matches a known persona file location is returned, sorted by path,
skipping .git/ and node_modules/.

A named file is always returned. A named folder returns the files in it that match the known locations;
if none match, it returns every .md, .mdc and .toml file in it, except SKILL.md, README.md, index.md and
command files. '-' reads standard input as one file, labelled <session text>.

Each file's kind is standing (loaded every session) or delegated (loaded when chosen). A file in a known
location takes that location's kind; any other file is delegated when its frontmatter holds both name and
description, and standing otherwise, and its basis says the kind was inferred.

Output, one line per file: path, kind, harness and the basis for the kind, separated by tabs. With
--format json, one JSON array of objects with path, kind, harness and kind_basis.

Exit codes: 0 one or more files; 2 a usage error or an unreadable path; 3 no persona file found, or empty
input. This script changes no file.
"""

import json
import os
import subprocess
import sys
from fnmatch import fnmatchcase

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import personafile  # noqa: E402

# Exit codes, as the docstring states them (build specification §3b).
EXIT_FOUND = 0
EXIT_USAGE = 2
EXIT_NONE = 3

STANDING, DELEGATED = "standing", "delegated"

# Known persona file locations, matched against the end of a file's path. Each row: the pattern, the
# kind, the harness. Rows the specification marks as resting on a vendor page alone were kept only where
# the installed harness's own code confirmed the path; see the delivery report for those dropped.
LOCATIONS = (
    ("CLAUDE.md", STANDING, "Claude Code"),
    ("CLAUDE.local.md", STANDING, "Claude Code"),
    ("AGENTS.md", STANDING, "Codex and others"),
    ("GEMINI.md", STANDING, "Gemini CLI"),
    (".claude/output-styles/*.md", STANDING, "Claude Code"),
    (".gemini/system.md", STANDING, "Gemini CLI"),
    (".cursor/rules/*.mdc", STANDING, "Cursor"),
    (".cursor/rules/*.md", STANDING, "Cursor"),
    (".claude/agents/*.md", DELEGATED, "Claude Code"),
    (".gemini/agents/*.md", DELEGATED, "Gemini CLI"),
)

# Never returned from a search: skills stay with skill-judge, and READMEs, indexes and command files are
# not persona files (vision §4; specification A-2).
NEVER_NAMES = ("SKILL.md", "README.md", "index.md")
COMMAND_FOLDERS = (".claude/commands",)
SKIP_FOLDERS = (".git", "node_modules")
# Extensions a named folder falls back to when nothing in it matches a known location (A-4).
FALLBACK_EXTENSIONS = (".md", ".mdc", ".toml")


def posix(path):
    return path.replace(os.sep, "/")


def match_location(path):
    """Return (pattern, kind, harness) for a path, or None. The path's last parts must match the pattern."""
    parts = posix(os.path.abspath(path)).split("/")
    for pattern, kind, harness in LOCATIONS:
        pparts = pattern.split("/")
        if len(parts) >= len(pparts) and all(
            fnmatchcase(part, pp) for part, pp in zip(parts[-len(pparts):], pparts)
        ):
            return pattern, kind, harness
    return None


def is_never(path):
    p = posix(os.path.abspath(path))
    if os.path.basename(p) in NEVER_NAMES:
        return True
    return any(f"/{folder}/" in p for folder in COMMAND_FOLDERS)


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


def infer_kind(pf):
    """Kind from content for a file in no known location (A-5)."""
    if pf.frontmatter.get("name") and pf.frontmatter.get("description"):
        return DELEGATED, "inferred: its frontmatter holds name and description"
    return STANDING, "inferred: its frontmatter does not hold both name and description"


def record_for(path, shown):
    """The record for one file: path, kind, harness and kind_basis."""
    loc = match_location(path)
    if loc:
        pattern, kind, harness = loc
        return {"path": shown, "kind": kind, "harness": harness, "kind_basis": f"its path matches {pattern}"}
    pf = personafile.read_path(path, shown)
    kind, basis = infer_kind(pf)
    return {"path": shown, "kind": kind, "harness": "not named by its path", "kind_basis": basis}


def record_for_text(pf):
    kind, basis = infer_kind(pf)
    return {"path": pf.path, "kind": kind, "harness": "not named by its path", "kind_basis": basis}


class Found:
    """What a search returned: records, and the persona files read from standard input."""

    def __init__(self):
        self.records = []
        self.texts = {}  # label -> PersonaFile, for standard input


def search(paths, stdin=None, cwd=None):
    """Find persona files. Raise personafile.PersonaError for an unreadable path; return a Found."""
    cwd = cwd or os.getcwd()
    found = Found()
    if not paths:
        root = project_root(cwd)
        for f in walk(root):
            if match_location(f) and not is_never(f):
                found.records.append(record_for(f, display(f, root)))
        found.records.sort(key=lambda r: r["path"])
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
            files = [f for f in walk(target) if match_location(f) and not is_never(f)]
            if not files:
                files = [f for f in walk(target) if f.endswith(FALLBACK_EXTENSIONS) and not is_never(f)]
            for f in files:
                found.records.append(record_for(f, display(f, cwd)))
        elif os.path.exists(target):
            found.records.append(record_for(target, display(target, cwd) if not os.path.isabs(given) else shown))
        else:
            raise personafile.PersonaError(f"cannot read {shown}: no such file or folder; check the path")
    return found


def parse_args(argv):
    """Return (paths, format) or raise ValueError with the message."""
    paths, fmt = [], "text"
    i = 0
    while i < len(argv):
        arg = argv[i]
        if arg == "--format":
            if i + 1 >= len(argv) or argv[i + 1] not in ("text", "json"):
                raise ValueError("--format takes text or json")
            fmt = argv[i + 1]
            i += 2
            continue
        if arg.startswith("--") or (arg.startswith("-") and arg != "-"):
            raise ValueError(f"unknown option {arg}; run find.py --help")
        paths.append(arg)
        i += 1
    return paths, fmt


def main(argv):
    if "-h" in argv or "--help" in argv:
        print(__doc__.strip())
        return EXIT_FOUND
    try:
        paths, fmt = parse_args(argv)
    except ValueError as exc:
        print(f"find.py: {exc}", file=sys.stderr)
        return EXIT_USAGE
    try:
        found = search(paths)
    except personafile.PersonaError as exc:
        print(f"find.py: {exc}", file=sys.stderr)
        return EXIT_USAGE
    if not found.records:
        if paths == ["-"]:
            print("find.py: the input is empty; paste the persona text, or name a file", file=sys.stderr)
        else:
            print("find.py: no persona file found; name a file or folder to review", file=sys.stderr)
        return EXIT_NONE
    if fmt == "json":
        print(json.dumps(found.records, indent=2))
    else:
        for r in found.records:
            print("\t".join((r["path"], r["kind"], r["harness"], r["kind_basis"])))
    return EXIT_FOUND


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
