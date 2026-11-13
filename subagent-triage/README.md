# subagent-triage

[![Licence: MIT](https://img.shields.io/badge/licence-MIT-blue.svg)](../LICENSE)
![Version](https://img.shields.io/badge/version-0.1.0%20(pre--release)-lightgrey.svg)
![Python](https://img.shields.io/badge/python-3.9%2B-blue.svg)
![Platforms](https://img.shields.io/badge/platforms-Claude%20Code-lightgrey.svg)
![Jev](https://img.shields.io/badge/Jev-1.13.0-blue.svg)
![Format](https://img.shields.io/badge/format-Agent%20Skill-green.svg)

> **Pre-release.** The scripts are built and pass their tests. The decision lines are provisional and uncalibrated.
> Try the skill in a session whose settings no other session loads before you rely on it.

## Problem

An agent that sends work to subagents chooses, each time, who gets the work, at what effort and with what brief. It
makes those choices quickly and records none of them. Afterwards no one can say why a part went where it did, whether
a better-suited persona was passed over or whether the effort matched the work.

*Subagent-triage* makes the choices in a fixed order and records each one where the call's own record will carry it.
It reads the kind of act each part asks for, chooses an eligible persona and assigns a harness, a model and an
effort. It writes the brief and a plan. Every value lands on the call's dispatch record in the ledger the
`subagent-ledger` skill keeps.

## Terms

This README uses a few working terms:

- **parent**: the agent sending the work;
- **part**: one piece of a delegation, sent to one member;
- **member**: one subagent in the parent's team, with an id and an attempt number;
- **persona**: the role a member is briefed to take, with its own file and memory;
- **group**: the standing home a persona belongs to;
- **roster**: the file listing the personas a parent may send work to;
- **planner**: the subagent that proposes how a delegation divides, run only when it divides or the parent asks;
- **pending triage file**: the file the skill writes before a dispatch, which the ledger's capture copies onto the
  dispatch record and removes; and
- **hop**: a hand-over of output from a member to the parent or to another member.

This skill's triage is not the ledger's own `triage_command`, which reads a brief's kind after the fact.

## What it records

For each member, the dispatch record carries:

- the kind of act its part asks for, and how sure the reading was;
- for a build part, whether code or a model's inference decides the output of what it builds, which names its builder;
- the persona chosen, the facts the choice rested on, whether it was found adequate and any override with its reason;
- who sent the part (`sender`), recorded only: no decision reads it;
- the harness and model assigned, each with any override, and the harness to pass (`harness_assigned`);
- the parent's own effort level, chosen before it saw the skill's, then the skill's level and any override; and
- the member id and attempt, so a re-dispatch counts against the member it repeats.

The readings are decision definitions in `skill/decisions/`, written for Jev at model `jev-1.13.0`. Each answer is a
decision record with its probability, line, version and lane, so results from different versions are never pooled.

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
- **A brief cannot point at nothing.** A persona file, memory index or input that does not resolve stops the brief,
  and a writer whose worktree would not hold its write set is refused before it is sent.

## Known limits

- **The lines are provisional.** The act decision reads one kind, none or two or more with a provisional Choice until
  its nine lines are set. The adequacy and form lines are 0.5, with no measured basis. The harness, model and effort
  decisions are uncalibrated.
- **The citation rule is a starting value.** A hop counts as cited on a path, a call id or 20 consecutive words
  quoted. A parent that acts on a hop's output in its own words is marked not cited.
- **Eligibility trusts its sources.** A persona's standing comes from its file's ratified declaration, and the skill
  checks only that the mark is there. A register of capabilities narrows the set only where the parent names one.
- **The dispatch check is evidence, not a lock.** It finds a pending triage file for the member and attempt. A parent
  that writes one by hand gets past it.
- **Claude Code only.** Other harnesses wait on probes of whether they take a per-call effort and carry a brief's
  front matter to the record.
- **Jev is required** for the six decisions, which are written for model `jev-1.13.0`. Without it, every decision
  records its failure and the parent chooses.

## Who it is for

*Subagent-triage* suits anyone whose agent sends work to a roster of personas and wants each choice recorded and
measurable. It is not for searches, page fetches, MCP reads or checking what came back (use `subagent-return`).

## Requirements

- Python 3.9 or later, with PyYAML to read front matter and a YAML roster (the suite was last run on Python 3.14.7 with
  PyYAML 6.0.3).
- The `subagent-ledger` skill, whose capture copies the pending triage file onto the dispatch record.
- The `subagent-return` skill, whose output section instruction every brief carries.
- Jev, TypeSafe's decision engine, at model `jev-1.13.0`, and a key for it.
- git, for the brief's repository, the worktree check and each part file's commit.

## Install

1. Keep this folder beside `subagent-ledger` and `subagent-return` in one checkout of the repository. The scripts
   find theirs there.
2. Link `skill/` into your harness's skills folder, for Claude Code `~/.claude/skills/subagent-triage`. Link it
   rather than copy it. Where the other skills sit elsewhere, set `SUBAGENT_LEDGER_SCRIPTS` and
   `SUBAGENT_RETURN_SCRIPTS` to their `scripts` folders.
3. Set `JEV_API_KEY` in the environment the scripts run in.
4. Set the return check's `validator` in the ledger folder's `config.json`, as the `subagent-return` skill's README
   says. The brief writer needs it to fill the brief's instruction.
5. For the dispatch check, add `checks.dispatch` to the ledger folder's `config.json` and print the hook entries with
   the ledger's wrapper:

   ```bash
   python3 <ledger-skill>/scripts/wrapper.py --hook-entries --ledger <ledger folder>
   ```

   `<ledger-skill>` is the full path to `subagent-ledger/skill`. Place the entries in your settings yourself. They
   take the place of the capture's own entries, and they change how your harness runs. Try them first in a session
   whose settings no other session loads.

## Use

Invoke the skill before every dispatch that names a persona, and run `close` at the end. `skill/SKILL.md` gives the
steps: check the ledger is writing, read the task's stage, divide the delegation, ask each part's decisions with the
parent's own effort first, write the briefs and the plan, check each writer's worktree, dispatch and close.

## Settings

The scripts take most settings as options, so they read any project without knowing its layout.

**The roster** (`decide.py`). A YAML or JSON file. Each row names a persona, its group and its file:

```yaml
rows:
- name: builder
  group: workshop
  file: personas/builder.md
- name: reviewer
  group: review
  file: personas/reviewer.md
```

A persona's file carries its declared goal, what it declares it does and a ratified mark in its front matter:

```yaml
declaration:
  goal: Builds what a settled design specifies, with tests.
  does: Writes scripts and their tests from a build specification.
declaration-ratified:
  by: the owner
  at: '2026-01-01T00:00:00Z'
```

Where your roster or files use other names, say where they are:

| Option | Default | Names |
|---|---|---|
| `--rows-key` | `rows` | where the rows sit in the roster |
| `--name-key` | `name` | each row's persona name |
| `--group-key` | `group` | each row's group |
| `--file-key` | `file` | each row's file, relative to `--file-root` |
| `--file-root` | the roster's folder | where the rows' files are read from |
| `--goal-key` | `declaration.goal` | the declared goal, in the persona file's front matter |
| `--does-key` | `declaration.does` | what the persona declares it does, in the persona file's front matter |
| `--ratified-key` | `declaration-ratified` | the ratified mark, in the persona file's front matter |
| `--user` | none | a row that is the user, never a candidate. Repeat for more |

A dotted name reads a nested key.

**The stage** (`stage.py`, and `decide.py` with the same options). `--build-root` and `--ratified-root` name the
folders the stage read looks in, each a folder or a glob pattern, repeated for more. `--task-key` (`task_id`) and
`--status-key` (`status`) name the front-matter keys it reads.

**The forms map** (`decide.py`, `--forms`). A JSON or YAML file whose object at `--forms-key` (`builders`) names the
persona that builds each form: `code` and `model`. The skill names no builder itself.

**The reachable list** (`decide.py`, `--reachable`). A JSON or YAML file whose list at `--reachable-key`
(`harnesses`) holds each harness the parent can reach, with its `name`, a `description` and its `models`, each with a
`name`, a `description` and the effort `levels` it is offered on that harness. Where the list names none,
`--parent-harness` and `--parent-model`, the parent's own, are passed.

**The parent and the work** (`decide.py`). `--parent-persona` names who sends the part, recorded as `sender`.
`--work-call` names the call id of the work a review part calls to account.

**The environment.**

| Variable | Holds |
|---|---|
| `JEV_API_KEY` | the key for Jev. `decide.py --key-from-zsh` fills it, where it is not set, from what zsh sets it to on starting |
| `SUBAGENT_TRIAGE_JEV_URL` | another endpoint for Jev, such as a stand-in for tests |
| `SUBAGENT_TRIAGE_RETRY_WAIT` | the seconds to wait before a retry, raised with each try; 2 by default |
| `SUBAGENT_LEDGER_SCRIPTS` | the ledger skill's `scripts` folder, where it is not beside this one |
| `SUBAGENT_RETURN_SCRIPTS` | the return skill's `scripts` folder, where it is not beside this one |
| `SUBAGENT_LEDGER_DIR` | the ledger folder, where `--ledger` is not given |
| `CLAUDE_CODE_SESSION_ID` | the session id, where `--session` is not given to `witness.py` |

**The ledger's `config.json`.** The brief writer reads the ledger's `frontmatter` map for the keys it writes, its
`kind_names` map for how it spells each kind and the return check's `validator` and `markdown` for the brief's
instruction. The dispatch check runs as `checks.dispatch`.

## Contents of this folder

- `README.md`: this file.
- `skill/SKILL.md`: the steps, from checking the ledger to closing the plan.
- `skill/decisions/d1-act.json`: the act decision.
- `skill/decisions/d3-figure.json`: the persona decision.
- `skill/decisions/d4-effort.json`: the effort decision.
- `skill/decisions/d5-form.json`: the form decision.
- `skill/decisions/d6-harness.json`: the harness decision.
- `skill/decisions/d7-model.json`: the model decision.
- `skill/references/decisions.md`: what a decision definition holds, the lanes and the decision record.
- `skill/references/brief-format.md`: the brief every member gets.
- `skill/references/plan-format.md`: the plan file, its proposal and how `close` marks a hop cited.
- `skill/scripts/witness.py`: checks the ledger is writing for this session.
- `skill/scripts/stage.py`: reads a task's stage from named files.
- `skill/scripts/decide.py`: asks the six decisions for one part, writes its pending triage file and records an
  override.
- `skill/scripts/plan.py`: writes the planner's own pending file and the plan file, and lists a re-dispatch.
- `skill/scripts/brief.py`: writes one member's brief.
- `skill/scripts/worktree_check.py`: refuses a writer whose worktree would not hold its write set.
- `skill/scripts/dispatch_check.py`: the hook's check, refusing a dispatch no triage reached.
- `skill/scripts/close.py`: closes a plan, marking each hop, and reports what the team's records show.
- `tests/`: the tests. Run them from this folder with `python3 -m unittest discover -s tests`.
- `index.md`: a generated list of this folder's files.
