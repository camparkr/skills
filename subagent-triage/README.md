# subagent-triage

[![Licence: MIT](https://img.shields.io/badge/licence-MIT-blue.svg)](../LICENSE)
![Version](https://img.shields.io/badge/version-0.0.1%20(scaffold)-lightgrey.svg)
![Python](https://img.shields.io/badge/python-3.9%2B-blue.svg)
![Platforms](https://img.shields.io/badge/platforms-Claude%20Code-lightgrey.svg)
![Jev](https://img.shields.io/badge/Jev-1.13.0-blue.svg)
![Format](https://img.shields.io/badge/format-Agent%20Skill-green.svg)

> **Scaffold.** The instructions, references and decision definitions are drafted. The scripts are not built, the
> decision lines are provisional, and no command below runs. Do not install it.

## Problem

An agent that sends work to subagents chooses, each time, who gets the work, at what effort and with what brief. It
makes those choices quickly and records none of them. Afterwards no one can say why a part went where it did, whether
a better-suited persona was passed over, or whether the effort matched the work.

*Subagent-triage* makes the choices in a fixed order and records each one where the call's own record will carry it.
It reads the kind of act each part asks for, chooses an eligible persona, and assigns an effort. It writes the brief
and a plan. Every value lands on the call's dispatch record in the ledger the `subagent-ledger` skill keeps.

## Terms

This README uses a few working terms:

- **parent**: the agent sending the work;
- **part**: one piece of a delegation, sent to one member;
- **member**: one subagent in the parent's team, with an id and an attempt number;
- **persona**: the role a member is briefed to take, with its own file and memory;
- **group**: the standing home a persona belongs to;
- **planner**: the subagent that proposes how a delegation divides, run only when it divides or the parent asks;
- **pending triage file**: the file the skill writes before a dispatch, which the ledger's capture copies onto the
  dispatch record and removes; and
- **hop**: a hand-over of output from a member to the parent or to another member.

This skill's triage is not the ledger's own `triage_command`, which reads a brief's kind after the fact.

## What it records

For each member, the dispatch record carries:

- the kind of act its part asks for, and how sure the reading was;
- the persona chosen, the facts the choice rested on, whether it was found adequate, and any override with its reason;
- the parent's own effort level, chosen before it saw the skill's, then the skill's level, and any override; and
- the member id and attempt, so a re-dispatch counts against the member it repeats.

The three readings are decision definitions in `skill/decisions/`, written for Jev at model `jev-1.13.0`. Each answer is a decision record with its
probability, line, version and lane, so results from different versions are never pooled.

## Why use subagent-triage

- **The parent's own choice is kept.** The parent's unaided effort is stamped before the skill's is shown, so the two
  can be compared honestly.
- **Eligibility is exact.** Only personas the roster lists, with a ratified declaration, are candidates. An unknown
  name is refused, never matched.
- **A weak match is marked, not hidden.** A part no persona is adequate for still goes to the closest one, and its
  brief and record both say so.
- **Unused hand-overs are dropped.** At the close, a hop whose output the parent never used is marked, and the next
  plan of the same pattern leaves it out.
- **It never stops work it could not triage.** A failed decision is recorded, and the dispatch goes out.

## Known limits

- **The lines are provisional.** The act decision reads one kind with a provisional Choice until its eight lines are
  set. The adequacy line is 0.5, with no measured basis. The effort decision is uncalibrated.
- **The citation rule is a starting value.** A hop counts as cited on a path, a call id or 20 consecutive words
  quoted. A parent that acts on a hop's output in its own words is marked not cited.
- **Claude Code only.** Other harnesses wait on probes of whether they take a per-call effort and carry a brief's
  front matter to the record.
- **Jev is required** for the three decisions, which are written for model `jev-1.13.0`. Without it, every decision
  records its failure and the parent chooses.

## Who it is for

*Subagent-triage* suits anyone whose agent sends work to a roster of personas and wants each choice recorded and
measurable. It is not for searches, page fetches, MCP reads, or checking what came back (use `subagent-return`).

## Requirements

- Python 3.9 or later, standard library only.
- The `subagent-ledger` skill, whose capture copies the pending triage file onto the dispatch record.
- The `subagent-return` skill, whose output section instruction every brief carries.
- Jev, TypeSafe's decision engine, at model `jev-1.13.0`, and a key for it.

## Install

<!-- BUILD: install steps, once the scripts exist. -->
Not yet.

## Use

Invoke the skill before every dispatch that names a persona, and run `close` at the end. `skill/SKILL.md` gives the
steps.

## Settings

<!-- BUILD: the settings keys, once the scripts fix them. -->
The settings will name the roster, the capability register, the group paired with each kind of act, the files the
stage read looks in, the planner's persona, and the environment variable that holds the Jev key.

## Contents of this folder

- `README.md`: this file.
- `skill/SKILL.md`: the steps, from checking the ledger to closing the plan.
- `skill/decisions/d1-act.json`: the act decision.
- `skill/decisions/d3-figure.json`: the persona decision.
- `skill/decisions/d4-effort.json`: the effort decision.
- `skill/references/decisions.md`: what a decision definition holds, the lanes and the decision record.
- `skill/references/brief-format.md`: the brief every member gets.
- `skill/references/plan-format.md`: the plan file, and how `close` marks a hop cited.
- `index.md`: a generated list of this folder's files.
