#!/usr/bin/env python3
"""run_triggers.py: measure whether a harness chooses persona-judge for each request in triggers.json.

Usage:
  run_triggers.py --harness claude|codex|gemini [--triggers FILE] [--max-turns N] [--timeout SECONDS]
                  [--probe] [--dry-run]

Each request runs in a fresh non-interactive session of the harness, in its own empty scratch project
under the system's temporary folder, read-only as far as the harness allows, with the skill installed as
a user installs it (setup.sh). The session runs to its end within the turn limit; it is not stopped at
the first tool call. The runner reads the session's own output to decide whether persona-judge was
chosen, counting only tool calls, never the prompt's own words. In Claude Code the skill shows as loaded in
either of two ways: a Skill tool call naming it, or, after a '/persona-judge' request, which loads the
skill's text with no Skill call, a tool call of any kind that names a file in the skill's folder, such as a
Read of persona-judge/reviewer.md or a Bash command that prints it.

Skill-creator's run_eval.py and run_loop.py are not used: they install a slash command, not the skill,
and stop at the first tool call (issue #6253 in anthropics/claude-plugins-official).

Before measuring, the runner proves its detector: one request names the skill explicitly and one
control cannot choose it. The detector must report the first and not the second, or the harness is not
measured. --probe runs only that proof.

It first prints the skills installed for the harness and their count; the measure needs at least ten
others beside persona-judge, so the skill is chosen from among others rather than alone. It then prints each request's result, the raw counts and, per threshold,
yes or no: at least 8 of the 10 yes-requests choose the skill; at most 1 of the 10 no-requests does.
Each session's output is kept in the run folder it names, as evidence.

--dry-run prints the commands it would run and runs none.

Exit codes: 0 measured and both thresholds met; 1 measured and a threshold not met; 2 a usage error or a
triggers file that is not 10 yes-requests and 10 no-requests; 3 not measured: the harness is not
installed, the skill is not installed for it, or the detector was not proven.
"""

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
SKILL_NAME = "persona-judge"

# Exit codes, as the docstring states them.
EXIT_MET = 0
EXIT_SHORT = 1
EXIT_USAGE = 2
EXIT_NOT_MEASURED = 3
# --help exits 0, as argparse does.
EXIT_OK_HELP = 0

# The thresholds the skill must meet: at least 8 of the 10 yes-requests; at most 1 of the 10 no-requests.
YES_NEEDED = 8
NO_ALLOWED = 1
# skill-creator's trigger-eval format, with 10 requests that should choose the skill and 10 that should not.
YES_COUNT = NO_COUNT = 10
# The skill is measured among others: at least ten other skills installed.
OTHERS_NEEDED = 10
# A session's turn limit and wall-clock limit; enough for a harness to choose and load a skill.
DEFAULT_MAX_TURNS = 6
DEFAULT_TIMEOUT = 300

PROBE_YES = {
    "claude": f"/{SKILL_NAME} review the CLAUDE.md in this folder",
    "codex": f"${SKILL_NAME} review the AGENTS.md in this folder",
    "gemini": f"Use the {SKILL_NAME} skill to review the GEMINI.md in this folder.",
}
PROBE_NO = "What is 17 plus 25? Answer with the number only."
# A path into the skill's folder, as a tool call names it: the folder name between path separators. The name alone,
# as a search pattern or in other words, does not match.
IN_SKILL_FOLDER = re.compile(rf"(?:^|[/\\\s\"'`=])({re.escape(SKILL_NAME)})[/\\]")


def skill_dirs(harness):
    home = Path.home()
    if harness == "claude":
        return [home / ".claude" / "skills"]
    if harness == "codex":
        return [Path(os.environ.get("CODEX_HOME", home / ".codex")) / "skills", home / ".agents" / "skills"]
    return [home / ".gemini" / "skills", home / ".agents" / "skills"]


def installed_skills(harness):
    """Names of the skills installed for a harness: folders holding a SKILL.md, up to three deep."""
    names = set()
    for base in skill_dirs(harness):
        if not base.is_dir():
            continue
        for depth in ("*/SKILL.md", "*/*/SKILL.md", "*/*/*/SKILL.md"):
            for f in base.glob(depth):
                if ".system" not in f.parts:
                    names.add(f.parent.name)
    return sorted(names)


def command(harness, prompt, max_turns):
    if harness == "claude":
        return ["claude", "-p", prompt, "--output-format", "stream-json", "--verbose",
                "--max-turns", str(max_turns), "--disallowedTools", "Edit,Write,NotebookEdit"]
    if harness == "codex":
        return ["codex", "exec", "--json", "--sandbox", "read-only", "--skip-git-repo-check", prompt]
    return ["gemini", "-p", prompt, "--output-format", "stream-json"]


def events(output):
    for line in output.splitlines():
        line = line.strip()
        if line.startswith("{"):
            try:
                yield json.loads(line)
            except ValueError:
                continue


def walk(obj):
    """Every dict inside obj."""
    if isinstance(obj, dict):
        yield obj
        for v in obj.values():
            yield from walk(v)
    elif isinstance(obj, list):
        for v in obj:
            yield from walk(v)


def walk_values(obj):
    """Every string inside obj."""
    if isinstance(obj, str):
        yield obj
    elif isinstance(obj, dict):
        for v in obj.values():
            yield from walk_values(v)
    elif isinstance(obj, list):
        for v in obj:
            yield from walk_values(v)


def chosen(harness, output):
    """True when a tool call in the session's output loads persona-judge. The prompt's words never count."""
    for ev in events(output):
        if harness == "claude":
            if ev.get("type") != "assistant":
                continue
            for d in walk(ev.get("message", {})):
                if d.get("type") == "tool_use":
                    args = json.dumps(d.get("input", {}))
                    if d.get("name") == "Skill" and SKILL_NAME in args:
                        return True
                    # A '/persona-judge' request loads the skill's text with no Skill call; the model then reads a
                    # file in the skill's folder, through Read, Bash or another tool.
                    if any(IN_SKILL_FOLDER.search(str(v)) for v in walk_values(d.get("input", {}))):
                        return True
        elif harness == "codex":
            for d in walk(ev):
                if d.get("type") in ("command_execution", "file_read", "tool_call", "mcp_tool_call"):
                    if f"{SKILL_NAME}/SKILL.md" in json.dumps(d):
                        return True
        else:
            if ev.get("type") not in ("tool_use", "tool_call"):
                continue
            name = str(ev.get("tool_name") or ev.get("name") or "")
            args = json.dumps(ev.get("parameters") or ev.get("args") or ev.get("input") or {})
            if "skill" in name.lower() and SKILL_NAME in args:
                return True
            if f"{SKILL_NAME}/SKILL.md" in args:
                return True
    return False


def model_used(harness, output):
    for ev in events(output):
        for d in walk(ev):
            for key in ("model", "model_name", "modelId"):
                if isinstance(d.get(key), str) and d[key]:
                    return d[key]
    return "not recorded in the session's output"


def run_one(harness, prompt, run_dir, label, max_turns, timeout, dry):
    project = run_dir / label
    project.mkdir(parents=True)
    cmd = command(harness, prompt, max_turns)
    if dry:
        shown = " ".join("<request>" if c == prompt else c for c in cmd)
        print(f"  would run in {project.as_posix()}: {shown}")
        return None, ""
    project.chmod(0o500)
    try:
        proc = subprocess.run(cmd, cwd=project, capture_output=True, text=True, timeout=timeout,
                              stdin=subprocess.DEVNULL)
        out = proc.stdout + "\n" + proc.stderr
    except subprocess.TimeoutExpired as exc:
        out = (exc.stdout or b"").decode("utf-8", "replace") if isinstance(exc.stdout, bytes) else (exc.stdout or "")
        out += "\n[timed out]"
    finally:
        project.chmod(0o700)
    (run_dir / f"{label}.out").write_text(out, encoding="utf-8")
    return chosen(harness, out), model_used(harness, out)


def load_triggers(path):
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise ValueError(f"cannot read {path}: {exc}")
    if not isinstance(data, list) or not all(
        isinstance(d, dict) and isinstance(d.get("query"), str) and isinstance(d.get("should_trigger"), bool)
        for d in data
    ):
        raise ValueError(f"{path}: expected a JSON array of {{\"query\": text, \"should_trigger\": true or false}}")
    yes = sum(d["should_trigger"] for d in data)
    if yes != YES_COUNT or len(data) - yes != NO_COUNT:
        raise ValueError(f"{path}: {yes} yes-requests and {len(data) - yes} no-requests; the measure needs 10 of each")
    return data


def main(argv):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--harness", choices=("claude", "codex", "gemini"), required=True)
    ap.add_argument("--triggers", default=str(HERE / "triggers.json"))
    ap.add_argument("--max-turns", type=int, default=DEFAULT_MAX_TURNS)
    ap.add_argument("--timeout", type=int, default=DEFAULT_TIMEOUT)
    ap.add_argument("--probe", action="store_true")
    ap.add_argument("--dry-run", action="store_true")
    try:
        args = ap.parse_args(argv)
    except SystemExit as exc:
        return EXIT_OK_HELP if exc.code == 0 else EXIT_USAGE

    triggers = None
    if not args.probe:
        try:
            triggers = load_triggers(args.triggers)
        except ValueError as exc:
            print(f"run_triggers.py: {exc}", file=sys.stderr)
            return EXIT_USAGE

    if not shutil.which(args.harness):
        print(f"not measured: {args.harness} is not installed")
        return EXIT_NOT_MEASURED
    skills = installed_skills(args.harness)
    others = [s for s in skills if s != SKILL_NAME]
    print(f"skills installed for {args.harness}: {len(skills)} ({len(others)} besides {SKILL_NAME})")
    for s in skills:
        print(f"  {s}")
    if SKILL_NAME not in skills and not args.dry_run:
        print(f"not measured: {SKILL_NAME} is not installed for {args.harness}; run setup.sh first")
        return EXIT_NOT_MEASURED
    if len(others) < OTHERS_NEEDED:
        print(f"note: fewer than {OTHERS_NEEDED} other skills installed; the measure needs at least {OTHERS_NEEDED}")

    stamp = time.strftime("%Y%m%dT%H%M%S")
    run_dir = Path(tempfile.gettempdir()) / "persona-judge-triggers" / f"{args.harness}-{stamp}"
    run_dir.mkdir(parents=True)
    print(f"run folder: {run_dir.as_posix()}")

    print("detector proof:")
    yes, m1 = run_one(args.harness, PROBE_YES[args.harness], run_dir, "probe-named", args.max_turns, args.timeout, args.dry_run)
    no, m2 = run_one(args.harness, PROBE_NO, run_dir, "probe-control", args.max_turns, args.timeout, args.dry_run)
    if args.dry_run:
        if triggers:
            for i, t in enumerate(triggers, 1):
                run_one(args.harness, t["query"], run_dir, f"request-{i:02d}", args.max_turns, args.timeout, True)
        print("Dry run: no session was started.")
        return EXIT_MET
    print(f"  request naming the skill: {'chosen' if yes else 'not chosen'} (model: {m1})")
    print(f"  control: {'chosen' if no else 'not chosen'} (model: {m2})")
    if not (yes and not no):
        print(f"not measured: the detector for {args.harness} was not shown to tell the two apart")
        return EXIT_NOT_MEASURED
    if args.probe:
        print("detector proven")
        return EXIT_MET

    yes_hits = no_hits = 0
    for i, t in enumerate(triggers, 1):
        hit, model = run_one(args.harness, t["query"], run_dir, f"request-{i:02d}", args.max_turns, args.timeout, False)
        kind = "yes-request" if t["should_trigger"] else "no-request"
        print(f"{i:2d} {kind}: {'chosen' if hit else 'not chosen'} (model: {model}) {t['query'][:70]!r}")
        if t["should_trigger"] and hit:
            yes_hits += 1
        if not t["should_trigger"] and hit:
            no_hits += 1
    met_yes = yes_hits >= YES_NEEDED
    met_no = no_hits <= NO_ALLOWED
    print(f"yes-requests that chose {SKILL_NAME}: {yes_hits} of {YES_COUNT}; at least {YES_NEEDED}: {'yes' if met_yes else 'no'}")
    print(f"no-requests that chose {SKILL_NAME}: {no_hits} of {NO_COUNT}; at most {NO_ALLOWED}: {'yes' if met_no else 'no'}")
    return EXIT_MET if met_yes and met_no else EXIT_SHORT


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
