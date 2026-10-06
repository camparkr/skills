#!/usr/bin/env python3
"""Limit the persona-judge reviewer's shell commands to the skill's own scripts.

A Claude Code PreToolUse hook. It reads the hook's JSON on standard input and acts only when the input's
`agent_type` names the reviewer, `persona-judge-reviewer`, with or without the `persona-judge:` prefix. For the
reviewer's Bash calls it allows only:

  python3 --version
  python3 <dir>/find.py ...
  python3 <dir>/check.py ...
  python3 <dir>/report.py ...

where <dir> resolves, through any symlink, to the folder this file is in. The first line may hold no ';', '&', '|',
backtick, '$(', '>' or '<', except one trailing quoted heredoc opener such as <<'RECORD'; the heredoc must close,
and nothing may follow the line that closes it.

Every other call passes: the reviewer's other tools, and every call from the main session or any other agent.

Exit codes: 0 allowed; 2 refused, with one line on standard error saying what the guard allows.
The guard changes no file.

Usage: guard.py < hook-input.json
       guard.py --help
"""

import json
import os
import re
import shlex
import sys

REVIEWER = "persona-judge-reviewer"
REVIEWER_NAMES = {REVIEWER, f"persona-judge:{REVIEWER}"}
SCRIPTS = {"find.py", "check.py", "report.py"}
HERE = os.path.dirname(os.path.realpath(__file__))
REFUSAL = (
    "persona-judge guard: the reviewer's Bash allows only `python3 --version` and `python3 <skill>/scripts/find.py`, "
    "`check.py` or `report.py`, with no ; & | ` $( > or < except one trailing quoted heredoc such as <<'RECORD'"
)
# One trailing quoted heredoc opener: <<'LABEL' or <<"LABEL".
HEREDOC = re.compile(r"""\s*<<(['"])([A-Za-z_][A-Za-z0-9_]*)\1\s*$""")
FORBIDDEN = (";", "&", "|", "`", "$(", ">", "<")


def is_reviewer(agent_type):
    return isinstance(agent_type, str) and agent_type in REVIEWER_NAMES


def split_heredoc(command):
    """Return (first line, ok): the first line without its heredoc opener, and whether the rest of the command is
    allowed. With no heredoc the command must be one line; with one, the heredoc must close and nothing may follow."""
    lines = command.split("\n")
    first = lines[0]
    match = HEREDOC.search(first)
    if not match:
        return first, all(not line.strip() for line in lines[1:])
    label = match.group(2)
    rest = lines[1:]
    if label not in rest:
        return first[: match.start()], False
    after = rest[rest.index(label) + 1 :]
    return first[: match.start()], all(not line.strip() for line in after)


def script_allowed(token, cwd):
    """Whether token names find.py, check.py or report.py in this file's folder, through any symlink."""
    if os.path.basename(token) not in SCRIPTS:
        return False
    path = token if os.path.isabs(token) else os.path.join(cwd, token)
    return os.path.realpath(os.path.dirname(path)) == HERE


def command_allowed(command, cwd):
    if not isinstance(command, str):
        return False
    first, rest_ok = split_heredoc(command)
    if not rest_ok or any(mark in first for mark in FORBIDDEN):
        return False
    try:
        words = shlex.split(first)
    except ValueError:
        return False
    if words == ["python3", "--version"]:
        return True
    return len(words) >= 2 and words[0] == "python3" and script_allowed(words[1], cwd)


def main(argv):
    if argv[1:] in (["--help"], ["-h"]):
        print(__doc__.strip())
        return 0
    if argv[1:]:
        print("guard.py takes no arguments; see --help", file=sys.stderr)
        return 2
    try:
        hook = json.loads(sys.stdin.read())
    except (ValueError, UnicodeDecodeError):
        print(REFUSAL + "; the hook input was not JSON", file=sys.stderr)
        return 2
    if not isinstance(hook, dict) or not is_reviewer(hook.get("agent_type")) or hook.get("tool_name") != "Bash":
        return 0
    tool_input = hook.get("tool_input") if isinstance(hook.get("tool_input"), dict) else {}
    cwd = hook.get("cwd") if isinstance(hook.get("cwd"), str) else os.getcwd()
    if command_allowed(tool_input.get("command"), cwd):
        return 0
    print(REFUSAL, file=sys.stderr)
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv))
