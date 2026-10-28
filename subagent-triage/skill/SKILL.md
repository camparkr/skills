---
name: subagent-triage
description: "Plans a team of subagents before any is sent, and records why each was sent where it was. For each part of a delegation it reads the kind of act, chooses an eligible persona and assigns an effort level, then writes the brief, the plan and a pending triage file the ledger copies onto the dispatch record. Use it before every dispatch that names a persona, whether the delegation is one part or many, and at the close to mark which hand-overs the parent used. Triggers: /subagent-triage, plan this team, split this delegation, which persona should take this, what effort should this get, close the plan. Not for searches, page fetches or MCP reads, for a message to a running subagent, or for checking what a subagent returned (use subagent-return)."
---

# subagent-triage

This skill sits between you and every dispatch that names a persona. It reads what each part of your delegation asks
for, chooses who takes it and at what effort, and writes the brief. It records every value in a pending triage file,
and the ledger's capture copies that file onto the member's dispatch record. You never write the ledger.

In the commands below, `<skill>` is this skill's folder.

> **Scaffold.** The scripts are not built yet. Each step names what its script does. The commands are placeholders.
<!-- BUILD: replace each placeholder command with the built script's command line. -->

## The order

Run the steps in this order for each delegation:

0. Check the ledger is writing.
1. Plan the team.
2. Choose each part's persona, and read the task's stage.
3. Write each brief.
4. Write the plan file.
5. Set each member's effort.
6. Write each pending triage file, then dispatch.
7. At the end, close the plan.

The order matters at step 5: your own choice of effort is stamped before you see the skill's.

## 0. Check the ledger is writing

Before a team's first dispatch, the script looks in this session's ledger file for the line the capture writes at
the session's start.

<!-- BUILD: witness check command, with how the script finds this session's id. -->

If the line is missing, stop. Tell the user the ledger is not recording this session, and send no member. A team sent
with no record cannot be checked afterwards.

## 1. Plan the team

**A delegation of one part.** If you offer the delegation as one part, the script asks the act decision
(`decisions/d1-act.json`). Where it reads one kind, go on to step 2 for that one member. No planning subagent runs.

**A delegation that divides, or one you want planned.** Dispatch the planning subagent. Before you do, the script
writes the planner's own pending file and gives you a plan request id. Name that id in the planner's brief. The
planner's brief carries no member key, and its dispatch record says it is the planner's.

<!-- BUILD: planner pending-file command, and the planner's persona from the settings. -->

The planner proposes:

- the parts;
- each part's write set, or `none` for a read-only part;
- which parts run in parallel; and
- who writes the synthesis: you, unless the plan states the stake or volume that calls for a separate member.

A part whose act decision reads two kinds is split into two parts, one kind each. A part that reads none comes back
to you as a finding, with no persona. A part that reads `user-decision` comes back to you to ask the user before
anything is sent.

You approve the plan or change it. Record each change against the part it changes, with your reason. A change to a
member's persona or effort is recorded on that member's dispatch record, through its pending triage file.

The plan shown to you names no effort. You choose an effort unaided first, at step 5.

## 2. Choose each part's persona, and read the stage

**The persona.** The script asks the persona decision (`decisions/d3-figure.json`). Eligibility is exact and comes
first: a persona must be on the roster your settings name, and its file must carry a ratified declaration. It must
not be the user. Where the part names a capability, the persona must be recorded against it. An unknown persona name
is refused, never matched to a near one.

The dispatch goes to the decision's persona unless you override it. To override, give the persona you choose and a
reason. The script records the decision's persona and its probability, the persona you would have chosen, the one
you chose and the time.

**Below the line.** Where the decision's adequacy answer is below its line, the part still goes to the persona the
decision ranked first. Its brief says no persona was found adequate. Its record marks the part below the line. You
may override as above. Report these parts at the close; the script counts them.

**The stage.** The script reads the task's stage exactly, from the files your settings name. Where it finds none, the
stage reads `unrecorded (no specification found for <task-id>)`.

<!-- BUILD: persona decision and stage read commands. -->

## 3. Write each brief

Write each member's brief as [`../references/brief-format.md`](../references/brief-format.md) sets out. In short,
the front matter names the persona, kind, task, member and attempt. The body opens with the instruction to read the
persona's file and memory, holds the task and the write set, and ends with the output section instruction.

A path in the brief that does not resolve stops it. A write set lies in one repository. Before you send a writer,
commit any write-set file you have changed and not committed, by path. The script refuses a writer whose worktree
would not hold its write set as you have it.

<!-- BUILD: brief check and worktree check commands. -->

## 4. Write the plan file

Write the plan file before the first dispatch, beside the briefs, as
[`../references/plan-format.md`](../references/plan-format.md) sets out. List every member, its persona, part, brief,
write set and attempt, the parallel order, the synthesiser and each hop. A re-dispatch is a new entry under its
member, with the next attempt number and your reason.

<!-- BUILD: plan file command. -->

## 5. Set each member's effort

For each member, in this order:

1. **Choose your own level first, unaided.** Decide the effort you would give this member before you see the skill's.
   The script stamps it from the clock.
2. **Then the skill's level.** The script asks the effort decision (`decisions/d4-effort.json`) and stamps its level
   after yours.
3. **Pass the skill's level.** Pass the effort decision's level as the Agent tool's `effort` input on every dispatch,
   from the first. The tool asks for `effort` only when you are told to give it, and this is that instruction.

You may override the skill's level. Give the level you pass instead and a reason; the script records both, with the
skill's level and the time. Where the effort decision returns no level, pass your own unaided level. The record says
why.

A re-dispatch after you reject a member's work is your act, at a level you choose. Record your reason and the attempt.

<!-- BUILD: unaided-effort stamp and effort decision commands. -->

## 6. Write each pending triage file, then dispatch

The script writes one pending triage file per member and attempt, before you dispatch. Each value is stamped from the
clock as it is written: your unaided effort, the three decision records, the persona and its facts, the group the
part's kind is paired with, who chose, and any override. The capture copies the file onto the member's dispatch
record and then removes it.

<!-- BUILD: pending writer command. -->

Then dispatch:

- the brief's absolute path is the first path in the prompt;
- the `effort` input carries the level from step 5;
- the `model` input names the model, as the `subagent-ledger` skill asks; and
- a writer runs in its own worktree.

If a decision failed, the pending file records the failure and its reason, and the dispatch still goes out. You
choose what to do with it.

## 7. Every dispatch goes through this skill

Every dispatch that names a persona goes through these steps, whether or not you planned to use the skill. A
dispatch that names a persona is an Agent or Task call. A resumption continues an earlier dispatch, and a message to
another session names none, so neither goes through.

Where your harness offers a hook, the hook refuses an Agent or Task call that has no pending triage file and is not
the planner's, and gives the reason. It never refuses a call whose triage was attempted and failed. A dispatch you
send with no persona goes out as an override, with your reason.

<!-- BUILD: the hook entry, once it runs inside the ledger's wrapper. It is placed in settings other sessions load
only by the user. -->

## Closing the plan

When the team's work is done, run `close`:

<!-- BUILD: close command. -->

`close` marks each hop cited or not cited, by the rule in the plan file's reference, and reports:

- each pending triage file whose dispatch never happened. It removes none of them;
- each dispatch whose member the plan does not list;
- the parts dispatched below the persona decision's line; and
- the override rates, by the persona decision's probability band and by parent.

Report all four to the user.

The next plan with the same pattern of act kinds leaves out each hop marked not cited, unless you restore it.

## Leave these alone

- Never write or edit the ledger, a pending triage file or a decision record by hand. The scripts and the capture
  write them.
- Never pass an effort, persona or decision value that the pending triage file does not record.
- Never send a `user-decision` part before the user answers.
- Leave a harness's settings to the user, who places any hook.
