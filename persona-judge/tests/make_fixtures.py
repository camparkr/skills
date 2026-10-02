#!/usr/bin/env python3
"""Build a scratch project from the stored fixtures, and fingerprint it.

Every fixture is stored in tests/evals/files/ with a .fixture suffix, so no
CLAUDE.md or AGENTS.md lies in the published tree for a harness to load. This
script copies a project's fixtures into a new folder under the system's
temporary folder, without the suffix, at the paths the project names.

Usage:
  make_fixtures.py list                      name every project and its files
  make_fixtures.py build PROJECT [--parent DIR]
                                             build PROJECT, print its folder and
                                             write its manifest beside it
  make_fixtures.py build-eval ID [--parent DIR]
                                             build the project for case ID of
                                             tests/evals/evals.json
  make_fixtures.py manifest DIR              print the SHA-256 of every file in DIR
  make_fixtures.py compare MANIFEST DIR      compare DIR with a saved manifest

The manifest of a project is written to <folder>.manifest.json, beside the
folder and never inside it, so the manifest does not change what it measures.

Exit codes: 0 done, or the manifests match; 1 the manifests differ; 2 a usage
error or an unreadable path.
"""

import hashlib
import json
import os
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
FILES = HERE / "evals" / "files"

# Exit codes, as the docstring states them.
EXIT_OK = 0
EXIT_DIFFERENT = 1
EXIT_USAGE = 2

# Each project maps a path inside the scratch folder to a fixture's stem.
PROJECTS = {
    # SI-1 (T-1): one standing file and one delegated file.
    "si1": {
        "CLAUDE.md": "claude-md",
        "docs/api.md": "api-doc",
        ".claude/agents/helper.md": "helper-agent",
    },
    # SI-11 (T-11) and SI-9 (T-9): five persona files, a README and a file
    # the persona files point to.
    "si11": {
        "CLAUDE.md": "claude-md",
        "docs/api.md": "api-doc",
        "AGENTS.md": "agents-md",
        ".claude/agents/helper.md": "helper-agent",
        ".claude/agents/doc-writer.md": "doc-writer-agent",
        ".cursor/rules/style.mdc": "cursor-rule",
        "README.md": "readme",
        "CHANGELOG.md": "changelog",
    },
    # SI-2 (T-2): one file with a path planted that does not exist, and the
    # same file without it.
    "si2-planted": {".claude/agents/checker.md": "si2-planted"},
    "si2-clean": {".claude/agents/checker.md": "si2-clean"},
    # The likeness fixture: files that look like persona files and are not.
    "likeness": {
        "README.md": "readme",
        "index.md": "index-md",
        "skills/example/SKILL.md": "skill-md",
        ".claude/commands/deploy.md": "command",
    },
    # The empty fixtures: a project with no files, and an empty persona file.
    "empty": {},
    "empty-file": {"CLAUDE.md": "empty"},
    # The shared reader's harder cases.
    "parsing": {
        ".codex/agents/reviewer.toml": "codex-agent",
        "notes/odd.md": "odd-frontmatter",
    },
}

# The project each model-run case in tests/evals/evals.json runs in, by case id.
EVAL_PROJECT = {1: "si1", 2: "si11", 3: "si11", 4: "si1", 5: "si11", 6: "si11", 7: "si11"}


def manifest(folder):
    """Return {relative path: SHA-256} for every file under folder."""
    folder = Path(folder)
    result = {}
    for root, dirs, files in os.walk(folder):
        dirs.sort()
        for name in sorted(files):
            path = Path(root) / name
            rel = path.relative_to(folder).as_posix()
            result[rel] = hashlib.sha256(path.read_bytes()).hexdigest()
    return result


def build(project, parent=None):
    """Build PROJECT under parent (default: the temporary folder); return its folder."""
    if project not in PROJECTS:
        raise KeyError(project)
    base = Path(parent) if parent else Path(tempfile.gettempdir()) / "persona-judge-fixtures"
    base.mkdir(parents=True, exist_ok=True)
    folder = Path(tempfile.mkdtemp(prefix=project + "-", dir=base))
    for dest, stem in PROJECTS[project].items():
        target = folder / dest
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes((FILES / (stem + ".fixture")).read_bytes())
    Path(str(folder) + ".manifest.json").write_text(
        json.dumps(manifest(folder), indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    return folder


def compare(saved, folder):
    """Return a list of lines naming each difference between saved and folder's manifest."""
    now = manifest(folder)
    lines = []
    for rel in sorted(set(saved) | set(now)):
        if rel not in now:
            lines.append(f"removed: {rel}")
        elif rel not in saved:
            lines.append(f"added: {rel}")
        elif saved[rel] != now[rel]:
            lines.append(f"changed: {rel}")
    return lines


def main(argv):
    if not argv or argv[0] in ("-h", "--help"):
        print(__doc__.strip())
        return EXIT_OK if argv else EXIT_USAGE
    cmd, args = argv[0], argv[1:]
    if cmd == "list":
        for name, files in PROJECTS.items():
            print(f"{name}: {', '.join(files) or '(no files)'}")
        return EXIT_OK
    if cmd == "build-eval" and args:
        try:
            args[0] = EVAL_PROJECT[int(args[0])]
        except (KeyError, ValueError):
            print(f"no case {args[0]} in tests/evals/evals.json", file=sys.stderr)
            return EXIT_USAGE
        cmd = "build"
    if cmd == "build" and args:
        parent = None
        if "--parent" in args:
            i = args.index("--parent")
            if i + 1 >= len(args):
                print("--parent takes a folder", file=sys.stderr)
                return EXIT_USAGE
            parent = args[i + 1]
            args = args[:i] + args[i + 2:]
        try:
            print(build(args[0], parent).as_posix())
        except KeyError:
            print(f"no project named {args[0]}; run 'make_fixtures.py list'", file=sys.stderr)
            return EXIT_USAGE
        return EXIT_OK
    if cmd == "manifest" and len(args) == 1:
        if not Path(args[0]).is_dir():
            print(f"cannot read {args[0]}: not a folder", file=sys.stderr)
            return EXIT_USAGE
        print(json.dumps(manifest(args[0]), indent=2, sort_keys=True))
        return EXIT_OK
    if cmd == "compare" and len(args) == 2:
        try:
            saved = json.loads(Path(args[0]).read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            print(f"cannot read {args[0]}: {exc}", file=sys.stderr)
            return EXIT_USAGE
        diff = compare(saved, args[1])
        for line in diff:
            print(line)
        if not diff:
            print("identical: every file and the file list")
        return EXIT_DIFFERENT if diff else EXIT_OK
    print("usage: make_fixtures.py list | build PROJECT | manifest DIR | compare MANIFEST DIR", file=sys.stderr)
    return EXIT_USAGE


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
