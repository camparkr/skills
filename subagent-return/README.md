# subagent-return

[![Licence: MIT](https://img.shields.io/badge/licence-MIT-blue.svg)](../LICENSE)
![Version](https://img.shields.io/badge/version-0.1.0%20(pre--release)-lightgrey.svg)
![Python](https://img.shields.io/badge/python-3.9%2B-blue.svg)
![Platforms](https://img.shields.io/badge/platforms-Claude%20Code-lightgrey.svg)
![Format](https://img.shields.io/badge/format-Agent%20Skill-green.svg)

> **Pre-release.** The checks, the gate and the disposition script are built and pass their tests. Try the skill in
> a session whose settings no other session loads before you rely on it.

## Problem

An agent that sends work to a team of subagents acts on what each one reports. A report can claim a file the member
never wrote, or one that does not exist. A member can write outside the files it was given, or write a document whose
front matter breaks the project's rules. The agent rarely checks, and when it does it reads the report, which is the
thing in doubt.

*Subagent-return* checks each report as it comes back, against what the member actually wrote. It records the result
on the call's records and recommends a repair for each failure. It refuses and repairs nothing in the member's work.
A failure stops the agent that sent the work instead: its next tool calls wait until it records what it decided.

## Terms

This README uses a few working terms:

- **parent**: the agent that sends the work;
- **member**: one subagent in the parent's team, sent with a brief;
- **brief**: the file that tells a member what to do, named first in its prompt;
- **write set**: the paths a member may write, listed in its brief, or `none` for a read-only member;
- **output section**: the end of a member's report, listing the files it claims as output;
- **hand-back**: a report a member hands to its parent by a tool, before it stops;
- **return record**: the ledger line written when a call comes back, as the `subagent-ledger` skill keeps it;
- **gate**: the check that holds the parent's tool calls while a failure stands undecided; and
- **disposition**: the parent's recorded decision on a failure, which lifts the gate for it.

## What it checks

| Check | Passes when |
|---|---|
| 1. The claimed output is the member's | every file the output section lists exists, changed after the member was sent and is among its worktree's changes |
| 2. Front matter conforms | every Markdown file of the configured kinds the member wrote passes the configured validator |
| 3. The call is on the ledger | a dispatch record carries the member and its attempt |
| 4. Writes stay in the write set | every write the worktree's changes or the transcript show is inside the write set |

Each result is one of `pass`, `fail`, `not_applicable`, `not_checkable (<reason>)` or `ledger_absent`. A missing
result reads `unrecorded`, never `pass`. Each `fail` carries a recommended repair. The skill's `SKILL.md` gives the
rules in full.

## Why use subagent-return

- **It reads the work, not the account.** Checks 2 and 4 read the member's worktree and transcript. A report that
  leaves out a write does not hide it.
- **A claim has one place.** Only the output section is a claim. A path mentioned as evidence is not, so a reviewer
  citing its inputs does not fail.
- **It checks the report the parent receives.** At a hand-back it reads the handed-back message, not the closing text
  the member writes after it.
- **A failure cannot slip past.** The parent's tool calls wait while a failure stands, save reading, asking the user
  and recording a decision. The member is never stopped, so it can always hand back.
- **Every decision is on the record.** One command records what the parent chose: accept, repair, send back, send a
  new attempt or discard. Each check result sits on the ledger with the SHA-256 of the text it read, beside the
  decisions that settled it.

## Known limits

- **A shell write outside the member's worktree is not seen.** Check 4 reads the worktree's changes and the
  transcript's Write, Edit and NotebookEdit calls. A shell command that writes outside the worktree shows in neither.
  A read-only member has no worktree, so a relative shell write lands in the shared tree unseen.
- **A write by an MCP tool is not seen.**
- **Check 2 judges form, not content.** It runs the validator your settings name and nothing else.
- **The gate holds tool calls, not replies.** A parent that answers in plain text with no tool call is not stopped,
  so a session can end with a failure undecided. The ledger's count check reports each one.
- **The decision command takes one closed form.** It holds the script's path and its flags only. No `;`, `&`, `|`,
  `<`, `>`, backtick, `$` or line break may appear anywhere in it, the reason included.
- **Claude Code only.** Other harnesses wait on probes of what their hooks carry.

## Who it is for

*Subagent-return* suits anyone whose agent sends work to several subagents at once and merges what comes back. It is
not for judging whether a member's work is good, or for calls with no brief file.

## Requirements

- Python 3.9 or later, standard library only (the suite was last run on 3.14.7).
- The `subagent-ledger` skill, from the same checkout of this repository. Its hook wrapper runs the checks and the
  gate, and its capture writes the results.
- Claude Code, with subagents run in worktrees for any member with a write set, and worktrees branched from the
  local `HEAD` (`worktree.baseRef: "head"`), since the checks read a writer's changes against the commit `HEAD` was
  at when it was sent.

## Install

1. Keep this folder beside `subagent-ledger` in one checkout of the repository. The scripts find the ledger's scripts
   there, and the decision command the gate prints names this checkout's path.
2. Link `skill/` into your harness's skills folder, for Claude Code `~/.claude/skills/subagent-return`. Link it
   rather than copy it, so the scripts still find the ledger's.
3. Add this skill's commands to the ledger folder's `config.json`, as 'Settings' below shows.
4. Print the hook entries those settings need:

   ```bash
   python3 <ledger-skill>/scripts/wrapper.py --hook-entries --ledger <ledger folder>
   ```

   `<ledger-skill>` is the full path to `subagent-ledger/skill`. The wrapper runs each check and then the capture,
   in one process, so its entries take the place of the capture's own entries on every event they name. The
   PreToolUse entry matches every tool, because the gate runs before each of the parent's calls. Each entry's time
   limit is set above the capture's longest wait, so `background_wait_seconds` must be set in `config.json`.
5. Place the entries under `hooks` in your settings yourself. Each changes how your harness runs. Try them first in
   a session whose settings no other session loads.

## Use

The parent writes each brief with the member key, the attempt, a write set and the instruction in
`skill/references/brief-instruction.md`. The hooks do the rest. Each member's results reach the parent with its
return, or with the notification of a background member's report. Where a check fails, the parent records its
decision with the command the gate prints, then goes on. `skill/SKILL.md` says how.

## Settings

The settings sit in the ledger folder's `config.json`, beside the ledger's own.

- `checks`: the commands the ledger's wrapper runs. This skill uses four keys: `handback` and `stop`, each running
  `skill/scripts/return_check.py`; `gate`, running `skill/scripts/gate.py`; and `context`, running
  `skill/scripts/return_check.py --context`.
- `check_seconds`: how long each check may run, 10 seconds by default. A check past it refuses nothing and reads
  `not_checkable (check timed out)`.
- `return_check`: the checks' own settings.
  - `validator`: the command check 2 runs on each Markdown file, with the file's path added last. Exit 0 passes it.
  - `markdown`: glob patterns naming the Markdown files check 2 reads. With none, every `.md` file.
  - `validator_not_checkable`: regular expressions that mark the validator's own failure in its output, so the file
    reads `not_checkable`, not `fail`. With none, a Python traceback.
  - `validator_seconds`: how long the validator may take on one file, 5 seconds by default.
  - `scratch`: a folder, or a list, where any member may write, with `{session}` standing for the session id. The
    harness's own scratch folder always counts.

```json
{
  "background_wait_seconds": 600,
  "checks": {
    "handback": "python3 \"<skill>/scripts/return_check.py\"",
    "stop": "python3 \"<skill>/scripts/return_check.py\"",
    "gate": "python3 \"<skill>/scripts/gate.py\"",
    "context": "python3 \"<skill>/scripts/return_check.py\" --context"
  },
  "check_seconds": 10,
  "return_check": {
    "validator": "python3 /opt/tools/validate_front_matter.py",
    "markdown": ["docs/*.md"]
  }
}
```

`<skill>` stands for the full path to this folder's `skill/`.

## Contents of this folder

- `README.md`: this file.
- `skill/SKILL.md`: what the parent does before sending a member, how it reads the results and how it records a
  decision.
- `skill/references/output-section.md`: the grammar of a report's output section, which the parser applies.
- `skill/references/brief-instruction.md`: the instruction every member's brief carries, telling the member what each
  check looks for.
- `skill/scripts/return_check.py`: runs the four checks at each hand-back and stop, hands the parent its results, and
  prints the merge plan.
- `skill/scripts/call_context.py`: reads, once a run, what the checks need about a member's call.
- `skill/scripts/check_authorship.py`, `check_frontmatter.py`, `check_ledger.py` and `check_write_set.py`: the four
  checks, one each.
- `skill/scripts/output_section.py`: the output section's parser.
- `skill/scripts/gate.py`: the gate on the parent's tool calls.
- `skill/scripts/disposition.py`: records the parent's decision on a failure.
- `skill/scripts/results.py`: reads the results and decisions a session's ledger holds.
- `tests/`: the tests. Run them from this folder with `python3 -m unittest discover -s tests`.
- `index.md`: a generated list of this folder's files.
