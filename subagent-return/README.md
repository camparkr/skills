# subagent-return

[![Licence: MIT](https://img.shields.io/badge/licence-MIT-blue.svg)](../LICENSE)
![Version](https://img.shields.io/badge/version-0.0.1%20(scaffold)-lightgrey.svg)
![Python](https://img.shields.io/badge/python-3.9%2B-blue.svg)
![Platforms](https://img.shields.io/badge/platforms-Claude%20Code-lightgrey.svg)
![Format](https://img.shields.io/badge/format-Agent%20Skill-green.svg)

> **Scaffold.** The instructions and references are drafted. The checks, the parser and the hook are not built yet,
> and no command below runs. Do not install it.

## Problem

An agent that sends work to a team of subagents acts on what each one reports. A report can claim a file the member
never wrote, or one that does not exist. A member can write outside the files it was given, or write a document whose
front matter breaks the project's rules. The agent rarely checks, and when it does it reads the report, which is the
thing in doubt.

*Subagent-return* checks each report as it comes back, against what the member actually wrote. It records the result
on the call's return record and recommends a repair for each failure. It refuses nothing and repairs nothing. The
agent that sent the work decides.

## Terms

This README uses a few working terms:

- **parent**: the agent that sends the work;
- **member**: one subagent in the parent's team, sent with a brief;
- **brief**: the file that tells a member what to do, named first in its prompt;
- **write set**: the paths a member may write, listed in its brief, or `none` for a read-only member;
- **output section**: the end of a member's report, listing the files it claims as output;
- **hand-back**: a report a member hands to its parent by a tool, before it stops; and
- **return record**: the ledger line written when a call comes back, as the `subagent-ledger` skill keeps it.

## What it checks

| Check | Passes when |
|---|---|
| 1. The claimed output is the member's | every file the output section lists exists, changed after the member was sent, and is among its worktree's changes |
| 2. Front matter conforms | every Markdown file of the configured kinds the member wrote passes the configured validator |
| 3. The call is on the ledger | a dispatch record carries the member and its attempt |
| 4. Writes stay in the write set | every write the worktree's changes or the transcript show is inside the write set |

Each result is one of `pass`, `fail`, `not_applicable`, `not_checkable (<reason>)` or `ledger_absent`. A missing
result reads `unrecorded`, never `pass`. The skill's `SKILL.md` gives the rules in full.

## Why use subagent-return

- **It reads the work, not the account.** Checks 2 and 4 read the member's worktree and transcript. A report that
  leaves out a write does not hide it.
- **A claim has one place.** Only the output section is a claim. A path mentioned as evidence is not, so a reviewer
  citing its inputs does not fail.
- **It checks the report the parent receives.** At a hand-back it reads the handed-back message, not the closing text
  the member writes after it.
- **It records, then advises.** Every result sits on the ledger's return record, in order, with the SHA-256 of the
  text it read. The parent decides what to do, with a recommended repair beside each failure.

## Known limits

- **A shell write outside the member's worktree is not seen.** Check 4 reads the worktree's changes and the
  transcript's Write, Edit and NotebookEdit calls. A shell command that writes outside the worktree shows in neither.
  A read-only member has no worktree, so a relative shell write lands in the shared tree unseen.
- **A write by an MCP tool is not seen.**
- **Check 2 judges form, not content.** It runs the validator your settings name and nothing else.
- **Claude Code only.** Other harnesses wait on probes of what their hooks carry.

## Who it is for

*Subagent-return* suits anyone whose agent sends work to several subagents at once and merges what comes back. It is
not for judging whether a member's work is good, or for calls with no brief file.

## Requirements

- Python 3.9 or later, standard library only.
- The `subagent-ledger` skill, whose hooks run the checks and write the results.
- Claude Code, with subagents run in worktrees for any member with a write set.

## Install

<!-- BUILD: install steps, once the hook entry in the ledger's wrapper exists. -->
Not yet. The checks run inside the ledger's hook wrapper, which is not built.

## Use

The parent writes each brief with the member key, the attempt, a write set and the instruction in
`skill/references/brief-instruction.md`. The hooks do the rest. The parent reads each member's results through the ledger's
reader before acting on its report. `skill/SKILL.md` says how.

## Settings

<!-- BUILD: the settings keys, once the wrapper's configuration is fixed. -->
The settings will name the front-matter validator, the kinds of Markdown file check 2 reads and the front-matter keys
that carry the member and the attempt.

## Contents of this folder

- `README.md`: this file.
- `skill/SKILL.md`: what the parent does before sending a member, and how it reads the results.
- `skill/references/output-section.md`: the grammar of a report's output section, which the parser applies.
- `skill/references/brief-instruction.md`: the instruction every member's brief carries, telling the member what each
  check looks for.
- `index.md`: a generated list of this folder's files.
