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
    # Discovery: two dedicated personas, a project instructions file and an output style.
    "si1": {
        ".claude/agents/helper.md": "helper-agent",
        ".github/agents/triage.agent.md": "copilot-agent",
        "CLAUDE.md": "claude-md",
        "docs/api.md": "api-doc",
        ".claude/output-styles/terse.md": "output-style",
    },
    # Discovery and a read-only run: three dedicated personas and four files set aside, beside files the
    # personas point to.
    "si11": {
        "CLAUDE.md": "claude-md",
        "AGENTS.md": "agents-md",
        ".claude/agents/helper.md": "helper-agent",
        ".claude/agents/doc-writer.md": "doc-writer-agent",
        ".github/agents/triage.agent.md": "copilot-agent",
        ".claude/output-styles/terse.md": "output-style",
        "README.md": "readme",
        "docs/api.md": "api-doc",
        "CHANGELOG.md": "changelog",
    },
    # A persona spread over files: a persona whose body refers to two files that exist, and a persona the project's list
    # names as three files, with a listed path that does not exist.
    "si13": {
        ".claude/agents/stylist.md": "stylist-agent",
        "docs/house-style.md": "house-style",
        "docs/terms.md": "terms",
        "personas/reviewer/reviewer.md": "list-reviewer",
        "personas/reviewer/scale.md": "list-scale",
        "personas/reviewer/examples.md": "list-examples",
        "personas.txt": "personas-txt",
    },
    # A missing path: one file with a path planted that does not exist, and the same file without it.
    "si2-planted": {".claude/agents/checker.md": "si2-planted"},
    "si2-clean": {".claude/agents/checker.md": "si2-clean"},
    # The likeness fixture: files that look like persona files and are neither reviewed nor set aside.
    "likeness": {
        "index.md": "index-md",
        ".claude/commands/deploy.md": "command",
        "docs/api.md": "api-doc",
    },
    # The empty fixtures: a project with no files, and an empty persona file.
    "empty": {},
    "empty-file": {".claude/agents/blank.md": "empty"},
    # The shared reader's harder cases.
    "parsing": {
        ".codex/agents/reviewer.toml": "codex-agent",
        "notes/odd.md": "odd-frontmatter",
    },
    # The subagent behind sample-review.md's example.
    "sample": {".claude/agents/code-reviewer.md": "sample-reviewer"},
    # Two script checks: a request the harness already meets, and statements that go
    # out of date; then a look-alike of each that scores 1.
    "time-defaults": {".claude/agents/planner.md": "planner-agent"},
    "time-likeness": {".claude/agents/planner.md": "planner-likeness"},
    "codex-defaults": {".codex/agents/reviewer.toml": "codex-reads-agents"},
    # More script checks: 'Declares its tools' in each harness that has a row, 'Plain emphasis' and
    # 'No placeholders', then a look-alike that scores 1 on the last two.
    "declares-tools": {
        ".claude/agents/planner.md": "planner-agent",
        ".gemini/agents/summariser.md": "gemini-agent",
        ".github/agents/triage.agent.md": "copilot-agent",
        ".codex/agents/reviewer.toml": "codex-agent",
        ".claude/agents/doc-writer.md": "doc-writer-agent",
        "CHANGELOG.md": "changelog",
    },
    "emphasis": {".claude/agents/tester.md": "emphasis-agent"},
    # Two rows scoring 0 on one line, PJ-001 and PJ-002, which the report merges into one finding.
    "pointer": {".claude/agents/pointer.md": "pointer-agent"},
    "emphasis-likeness": {".claude/agents/tester.md": "emphasis-likeness"},
    # Quoted text: quoted and example text is not the file's own instruction, and only a pointer is checked for
    # its path. Cases (1) to (5), then the controls still caught.
    "tq-names": {".claude/agents/runner.md": "tq-names"},
    "tq-quoted-pointer": {".claude/agents/rater.md": "tq-quoted-pointer"},
    "tq-quoted-examples": {".claude/agents/linter.md": "tq-quoted-examples"},
    "tq-blockquote": {".claude/agents/linter.md": "tq-blockquote"},
    "tq-skill-root": {
        "skill/agents/judge.md": "tq-skill-root-agent",
        "skill/references/rules.md": "tq-skill-root-rules",
    },
    "tq-controls": {".claude/agents/checker.md": "tq-controls"},
    # Quoted text, cases (7) to (12): a read verb makes a pointer only when it is addressed to the agent as an
    # instruction.
    "tq-c7": {".claude/agents/namer.md": "tq-c7"},
    "tq-c8": {".claude/agents/builder.md": "tq-c8"},
    "tq-c9": {".claude/agents/explainer.md": "tq-c9"},
    "tq-c10": {".claude/agents/gatherer.md": "tq-c10"},
    "tq-c11": {".claude/agents/scorer.md": "tq-c11"},
    "tq-c12": {".claude/agents/checker.md": "tq-c12"},
    # Quoted text, cases (13) to (16) and two more controls: a link that opens a sentence, 'you' inside a clause,
    # 'Open source' and the stated limits.
    "tq-c13": {".claude/agents/guide-reader.md": "tq-c13"},
    "tq-c14": {".claude/agents/row-reader.md": "tq-c14"},
    "tq-c15": {".claude/agents/vendor-reader.md": "tq-c15"},
    "tq-c16": {".claude/agents/limit-reader.md": "tq-c16"},
    "tq-controls-4": {".claude/agents/checker.md": "tq-controls-4"},
    # A pointer that resolves only above the project root, and its control, a pointer that resolves nowhere. The
    # test makes the project a Git repository and writes x/y.md in the folder above it.
    "pointer-above-root": {".claude/agents/climber.md": "pointer-above-root"},
    "pointer-nowhere": {".claude/agents/climber.md": "pointer-nowhere"},
    # A path that opens a line or list item and is followed by a dash or colon and a description: an index entry.
    "index-entry-missing": {".claude/agents/indexer.md": "index-entry-missing"},
    "index-entry-forms": {".claude/agents/indexer.md": "index-entry-forms"},
    "index-entry-write": {".claude/agents/reporter.md": "index-entry-write"},
    # An entry whose description says how to write something, not to write to the path.
    "index-entry-describes-writing": {".claude/agents/committer.md": "index-entry-describes-writing"},
    "index-entry-exists": {
        ".claude/agents/indexer.md": "index-entry-exists",
        "notes/memory.md": "index-entry-notes",
    },
    # A persona with no rule that limits the agent, so 'Reasons given' has no place.
    "no-place": {".claude/agents/zeta.md": "no-place-agent"},
    # A one-line persona: an identity and nothing else.
    "thin": {".claude/agents/reviewer.md": "thin-agent"},
    # A persona to which every question applies, so its score can be worked out by hand from the formula.
    "complete": {".claude/agents/release-checker.md": "complete-agent"},
    # The three branches, delegated, harness and settings, each at yes and at no.
    "branches": {
        ".claude/agents/helper.md": "helper-agent",
        ".claude/agents/planner.md": "planner-agent",
        ".claude/agents/summary-writer.md": "model-only",
        ".codex/agents/auditor.toml": "codex-sandbox",
        "notes/release.md": "notes-standing",
    },
    # A named file in no table: a standing persona, which 'Declares its tools' does not apply to.
    "standing": {"notes/release.md": "notes-standing"},
    # The discovery rows: the four dedicated locations and the set-aside Copilot and Cursor files, beside
    # look-alikes that match neither table.
    "github-codex": {
        ".codex/agents/reviewer.toml": "codex-agent",
        ".gemini/agents/summariser.md": "gemini-agent",
        ".github/copilot-instructions.md": "copilot-instructions",
        ".github/instructions/top.instructions.md": "copilot-path",
        ".github/instructions/frontend/react/hooks.instructions.md": "copilot-path",
        ".github/instructions/notes.md": "changelog",
        ".github/agents/triage.agent.md": "copilot-agent",
        ".github/agents/notes.md": "changelog",
        ".cursor/rules/style.mdc": "cursor-rule",
        "skills/example/SKILL.md": "skill-md",
    },
}

# The project each model-run case in tests/evals/evals.json runs in, by case id.
EVAL_PROJECT = {1: "si1", 2: "si11", 3: "si11", 4: "si11", 5: "si11", 6: "si11", 7: "si11", 8: "si13", 9: "si13"}


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
