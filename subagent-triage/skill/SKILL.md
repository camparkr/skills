---
name: subagent-triage
description: "Plans a team of subagents before any is sent, and records why each was sent where it was. For each part of a delegation it reads the kind of act, chooses an eligible persona and assigns an effort level, then writes the brief, the plan and a pending triage file the ledger copies onto the dispatch record. Use it before every dispatch that names a persona, whether the delegation is one part or many, and at the close to mark which hand-overs the parent used. Triggers: /subagent-triage, plan this team, split this delegation, which persona should take this, what effort should this get, close the plan. Not for searches, page fetches or MCP reads, for a message to a running subagent or for checking what a subagent returned (use subagent-return)."
---

# subagent-triage

This skill sits between you and every dispatch that names a persona. It reads what each part of your delegation asks
for, chooses who takes it and at what effort and writes the brief. It records every value in a pending triage file,
and the ledger's capture copies that file onto the member's dispatch record. You never write the ledger.

The three decisions it asks, of each part's kind, persona and effort, are written for Jev, TypeSafe's decision
engine, at model `jev-1.13.0`. Each is a definition in `decisions/`, and
[`references/decisions.md`](references/decisions.md) describes them. The key is read from `JEV_API_KEY`.

In the commands below, `<skill>` is this skill's folder, the one holding this file, and `<ledger>` is the ledger
folder. Each script prints one JSON object. Exit 0 means it did what was asked, 1 that it refused its input, with the
reason, and 2 that it cannot run.

## The order

Run the steps in this order for each delegation:

0. Check the ledger is writing.
1. Read the task's stage.
2. Divide the delegation, with the planner where it divides.
3. Ask each part's three decisions, your own effort first.
4. Override a decision, where you choose otherwise.
5. Write each brief.
6. Write the plan file.
7. Check each writer's worktree.
8. Dispatch.
9. At the end, close the plan.

The order matters at step 3: your own choice of effort is stamped before the skill's is asked. It matters at step 6
too: the plan names each brief, so the briefs come first.

## 0. Check the ledger is writing

Before a team's first dispatch, check that the capture wrote this session's start line:

```bash
python3 <skill>/scripts/witness.py [--ledger <ledger>] [--session <session id>]
```

The script reads the session id from `--session`, or else from `CLAUDE_CODE_SESSION_ID`, and prints it as `session`.
Use that id in every later command. It looks in this session's own ledger file for the line the capture writes at the
session's start. A line from another session does not count.

If it exits 1, stop. Tell the user the ledger is not recording this session, with the reason it printed, and send no
member. A team sent with no record cannot be checked afterwards.

## 1. Read the task's stage

The persona and effort decisions take the task's stage as a fact. Read it once per task, to see what they will be
given:

```bash
python3 <skill>/scripts/stage.py --task <task id> --build-root <folder> --ratified-root <folder>
```

Each `--build-root` and `--ratified-root` names one folder, or a glob pattern naming several, such as
`<project>/*/docs`. Repeat either for more. The script reads each folder to any depth, and reads a file's front matter
for the task's id (`--task-key`, `task_id` by default) and its status (`--status-key`, `status` by default). The
stage is:

- `build specification`, where a file named `*-build-spec.md` under a build folder carries the task's id;
- otherwise `ratified specification`, where a file named `*-surviving-spec.md` or `*-architectural-spec*.md` under a
  ratified folder carries the task's id and the status `ratified`;
- otherwise `unrecorded (no specification found for <task-id>)`.

No other file counts, whatever it carries: a proposal, findings and test criteria are named otherwise. An amendment,
a file whose name matches `*-amendment*`, never counts, even where another pattern matches it, as
`*-architectural-spec*.md` can. A file whose front matter cannot be read is listed under `unreadable`, and a root
that names no folder under `roots.naming_no_folder`. Check both before you go on.

The decisions in step 3 read the stage again, with the same options.

## 2. Divide the delegation

**A delegation of one part.** If you offer the delegation as one part, no planner runs. Go to step 3 with the whole
delegation as the part and one member id, such as `m1`.

**A delegation that divides, or one you want planned.** Dispatch a planner first. Before you do, write the planner's
own pending file:

```bash
python3 <skill>/scripts/plan.py planner --ledger <ledger> --session <session id>
```

It prints `plan_request`, a new id. Name that id in the planner's brief, standing alone, and give the brief no
member key. The dispatch check lets the planner's dispatch through on that id, and its dispatch record says it is the
planner's and names the plan request. Brief the persona you keep for planning.

The planner proposes:

- the parts;
- each part's write set, or `none` for a read-only part;
- which parts run in parallel; and
- who writes the synthesis: you, unless the plan states the stake or volume that calls for a separate member.

You approve the proposal or change it. Record each change against the part it changes, with your reason, in the
proposal's `changes` ([`references/plan-format.md`](references/plan-format.md)). Then give each part a member id and
go on to step 3 for each.

The proposal names no effort. You choose an effort unaided first, at step 3.

## 3. Ask each part's three decisions

For each part, decide first the effort you would give it unaided, before you see the skill's. Then write the part's
text to a file and run:

```bash
python3 <skill>/scripts/decide.py --delegation <part file> --roster <roster file> --ledger <ledger> --session <session id> --member <id> --attempt <n> --effort-unaided <level> --task <task id> --build-root <folder> --ratified-root <folder> --parent-persona <your own persona> [--kind-groups <file>] [--kind-groups-key pairs] [--register <file>] [--register-rows-key rows] [--unit-key unit] [--custodian-key custodian]
```

`--effort-unaided` is one of `low`, `medium`, `high`, `xhigh` or `max`. The script stamps it from the clock before it
asks anything. Then it reads the stage as step 1 does, and asks, in order:

1. **The act decision** (`decisions/d1-act.json`): which kind of act the part asks for. While its lines are
   provisional it reads one kind, or none.
2. **The persona decision** (`decisions/d3-figure.json`), only where the act decision read a kind: which eligible
   persona takes the part, and whether it is adequate.
3. **The effort decision** (`decisions/d4-effort.json`), whatever the other two read: which level the part warrants.

**Eligibility is exact** and comes before the persona decision. A persona is eligible where it is a row of the
roster, its file exists, that file's front matter carries a ratified declaration with a goal and it is not the user.
Name the user's own entries with `--user <name>`. The roster is a YAML or JSON file. Where its rows and fields sit
under other names, say where with `--rows-key` (`rows` by default), `--name-key` (`name`), `--group-key` (`group`),
`--file-key` (`file`), `--goal-key` (`declaration.goal`) and `--ratified-key` (`declaration-ratified`). A dotted name
reads a nested key. `--file-root` is the folder the rows' file paths are read from, by default the roster's own
folder.

**The kind-to-group table** is optional. Name it with `--kind-groups <file>`: a JSON or YAML file whose object at
`--kind-groups-key` (a dotted path, `pairs` by default) maps each kind to its group. Once the act decision reads a
kind, the script reads the group paired with it as `kind_paired_grouping`, a fact for the pending file and never the
record's own grouping. With no table, a table that cannot be read or holds no object at the key, a kind the table
lacks, or no kind read, the value reads `unrecorded (<reason>)` and the triage goes on.

The script writes the member's pending triage file, `<ledger>/.pending/<session id>/triage-<member>-<attempt>.json`,
and prints its path as `pending_file`. Read the output:

- **`act.kind`** is the kind read. Where it is `null`, the act decision read none, or its request failed. A part read
  as none goes back to you as a finding: send it to no persona. Where the request failed, choose the kind yourself.
- **A part read as `user-decision`** is the user's to settle. Ask the user, with the harness's question tool, before
  you write its brief or send anything.
- **`persona.persona`** is the persona chosen. Where `persona.below_line` is `true`, the adequacy answer was below
  its line: the part still goes to the persona ranked first, its brief says no persona was found adequate and its
  record marks the part below the line. Where `persona.answer` reads `none adequate (...)`, no persona was eligible,
  and the part goes back to you. Where it reads `unrecorded (...)`, the request failed: choose the persona yourself.
- **`kind_paired_grouping`** is the group the kind-to-group table pairs with the kind read, or `unrecorded (...)` with
  the reason. It is a fact for the record; it decides nothing.
- **`effort.pass`** is the level to pass. It is the effort decision's level, or your own unaided level where that
  decision returned none.

**Pass the effort decision's level.** Pass `effort.pass` as the Agent tool's `effort` input on every dispatch, from
the first. The tool asks for `effort` only when you are told to give it, and this is that instruction.

Exit 3 means a decision's request to Jev failed. The output and the pending file record the failure and its reason,
and the dispatch still goes out. You choose what to do with it. Every request to Jev is a call of its own, with its
dispatch and return records in the ledger.

## 4. Override a decision

The dispatch goes to the persona decision's persona, at the effort decision's level, unless you override. To
override, record it in the member's pending triage file before the dispatch:

```bash
python3 <skill>/scripts/decide.py override --pending <pending file> --decision d3-figure --persona <name> --parent-persona <your own persona> --reason "<why>"
python3 <skill>/scripts/decide.py override --pending <pending file> --decision d4-effort --level <level> --reason "<why>"
```

**The persona.** Override it before you write the brief: the brief writer refuses a persona the pending file does
not name. The script records the decision's persona and its adequacy probability, your own persona, the persona
chosen instead, your reason and the time. Give `--parent-persona` as the persona you yourself are, so override rates
can be read by parent. It refuses a persona the roster does not list, the decision's own persona and a decision
that chose no persona. It refuses too an empty reason or parent persona.

**The effort.** Override it any time before the dispatch. The script records the decision's level, the level you
pass instead, your reason and the time. Pass the level you recorded.

**No persona.** A dispatch you send with no persona goes out as an override, with your reason. Record it before you
send it; the dispatch check then lets it through.

```bash
python3 <skill>/scripts/decide.py override --decision no-persona --ledger <ledger folder> --session <session id> --member <member id> --attempt <n> --reason "<why>"
python3 <skill>/scripts/decide.py override --decision no-persona --pending <pending triage file> --reason "<why>"
```

Never edit the pending file by hand.

## 5. Write each brief

```bash
python3 <skill>/scripts/brief.py --out <brief path> --member <id> --attempt <n> --persona <name> --persona-file <path> --kind <kind> --task <task id> --body <task file> --write-set <path> [--write-set <path> ...] --pending <pending file> [--repository <folder>] [--ledger <ledger>]
```

Give `--write-set none` for a read-only member. Give each write-set path relative to the repository's root, and
`--repository` where the repository is not the one your shell is in. The `--body` file holds the part's task: what it
asks for, its inputs by absolute path and what done looks like.

The script writes the brief as [`references/brief-format.md`](references/brief-format.md) sets out. Its front
matter names the persona, kind, task, member and attempt. Its body opens with the instruction to read the persona's
file and memory, then holds the task and the write set. It ends with the `subagent-return` skill's instruction on
what the work is checked for. Where the pending file marks the part below the line, the body says so.

A path in the brief that does not resolve stops it, as does a persona or kind the pending file does not name. The
reference lists every rule. A brief is never overwritten: a re-dispatch gets a new one.

Before you send a writer, commit any write-set file you have changed and not committed, by path. A write set lies in
one repository. A part whose writes span two is split into one member for each.

## 6. Write the plan file

Write the plan file before the first dispatch, beside the briefs. Put the approved proposal in a JSON file, with each
member's kind, persona and brief as steps 3 to 5 settled them, and run:

```bash
python3 <skill>/scripts/plan.py write --proposal <proposal file> --out <plan file> [--plan-request <id>] [--history <folder> ...]
```

Give `--plan-request` the planner's id where a planner ran. [`references/plan-format.md`](references/plan-format.md)
gives the proposal's keys and the plan's. The plan holds no effort, decision value, override or check result: those
go on the record.

The script finds the most recent closed plan of the same pattern of act kinds under the `--history` folders, by
default the plan file's own folder. It leaves out each hop that plan marked not cited, lists it as `left_out` and
records it as a change. To keep one, name it in the proposal's `restore` with your reason.

## 7. Check each writer's worktree

A worktree branches from a commit and carries no uncommitted or untracked file. Before each writer's dispatch, check
that its worktree will hold the write set as the main checkout has it:

```bash
python3 <skill>/scripts/worktree_check.py --brief <brief path> [--repository <folder>] [--base head|remote]
```

Give `--base head` where your harness branches worktrees from the local `HEAD`, as Claude Code does with
`worktree.baseRef: "head"`. The default is `head`, and `remote` names the remote's default branch. Exit 1 refuses
the dispatch, naming each file that differs. Commit those files by path and run it again, or split a write set that
spans two repositories. A read-only member is not checked.

## 8. Dispatch

Dispatch each member as the plan's parallel order says:

- the brief's absolute path is the first path in the prompt;
- the `effort` input carries `effort.pass` from step 3, or the level of your effort override;
- the `model` input names the model, as the `subagent-ledger` skill asks; and
- a writer runs in its own worktree (in Claude Code, the Agent tool's `isolation: "worktree"`).

The capture copies the pending triage file onto the member's dispatch record and removes it. If a decision failed,
the pending file records the failure and its reason, and the dispatch still goes out.

**Every dispatch that names a persona goes through these steps,** whether or not you planned to use the skill. Such a
dispatch is an Agent or Task call. A resumption continues an earlier dispatch, and a message to another session names
none, so neither goes through.

Where your harness offers a hook, the dispatch check holds this rule. The ledger's wrapper runs it before each of your
Agent and Task calls, as `config.json`'s `checks.dispatch`:

```json
{"checks": {"dispatch": "python3 \"<skill>/scripts/dispatch_check.py\""}}
```

It refuses, with the reason, a call that has no pending triage file for its member and attempt and is not the
planner's. It never refuses a call whose triage was attempted and failed, and never a member's own dispatch. A check
that errors refuses nothing. The user places the hook in any settings other sessions load.

**Where a check on a return failed,** the `subagent-return` skill's gate refuses these scripts and your dispatches
until you record your decision. Record it first.

## A re-dispatch

A re-dispatch after you reject a member's work is your act, at a level you choose. For the next attempt:

1. where a `fail` stands on the last attempt, record `re-dispatched` with the `subagent-return` skill;
2. run step 3 with `--attempt` one higher, and override the effort where you pass another level;
3. write a new brief with that attempt; and
4. list it in the plan, with your reason:

   ```bash
   python3 <skill>/scripts/plan.py redispatch --plan <plan file> --member <id> --brief <new brief> --reason "<why>" [--persona <name>]
   ```

Then check the worktree and dispatch as before. A closed plan takes no re-dispatch.

## 9. Close the plan

When the team's work is done, run `close`:

```bash
python3 <skill>/scripts/close.py --plan <plan file> --session <session id> [--ledger <ledger>] [--transcript <your transcript>] [--parent <your own persona>]
```

`--transcript` is your own transcript, where the plan's dispatch records do not name it. `--parent` names the persona
you are, so the override rates are read by parent. `close` marks each hop cited or not cited, by the rule in the plan
file's reference, writes the marks and the time into the plan file and reports:

- each pending triage file and planner's file whose dispatch never happened. It removes none of them;
- each dispatch whose member the plan does not list, and each with no persona;
- the parts dispatched below the persona decision's line, with their count;
- the override rates, each a count of a count: the persona decision's overall, by its probability band and by
  parent, and the effort decision's overall; and
- each fault, such as an override missing a value or an effort passed other than the one to pass.

Report all of these to the user. `close` exits 0 when it closed with no fault, 3 when it closed with faults and 1
where the plan is unreadable or already closed, or no transcript is named.

The next plan with the same pattern of act kinds leaves out each hop marked not cited, unless you restore it.

## Leave these alone

- Never write or edit the ledger, a pending triage file, a planner's file or a decision record by hand. The scripts
  and the capture write them.
- Never pass an effort, persona or decision value that the pending triage file does not record.
- Never send a `user-decision` part before the user answers.
- Leave a harness's settings to the user, who places any hook.
