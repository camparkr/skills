---
name: subagent-return
description: "Checks each subagent's report as it comes back, before you act on it. A hook runs four exact checks on every member of a team: that the files it claims are its own, that its Markdown front matter conforms, that its call is on the ledger, and that its writes stayed inside its write set. It records each result and, for a failure, recommends a repair. It refuses, removes and repairs nothing; you decide. Use it when you send work to subagents and must know what came back is what was claimed, and when you read a return to decide whether to merge, re-send or discard. Triggers: /subagent-return, check this subagent's return, did the subagent write what it says, can I merge this worktree, read the return check. Not for judging whether the work is good, for subagent calls with no brief file, or for writing the ledger."
---

# subagent-return

When a member of your team reports back, a hook runs four checks on what it claims and what it wrote. Each result
goes onto the call's return record in the ledger the `subagent-ledger` skill keeps. The check never refuses the
member, never removes or reverts a file, and never discards a worktree. For each failure it recommends a repair. What
happens next is your decision.

The checks are exact. None asks a model whether the work is good.

> **Not settled yet.** How a failure stops you before your next action is still being decided. Until it is, read
> every member's result yourself before you act on its report, as 'Reading the results' says.
<!-- PENDING RULING: how a check failure stops the parent before its next action. Replace this note when settled. -->

## Before you send a member

The checks can only read what the brief sets up. For each member:

1. **Write the brief to a file**, and give its absolute path as the first path in the prompt. The check finds the
   brief by the ledger's own rule: the first readable file the prompt names.
2. **Put the member key and the attempt in its front matter.** A brief without the member key gets check 1
   `not_applicable (no member brief)`, and its output section is never read.
3. **Give it a `## Write set` section**, one path or folder prefix a line, each relative to the repository's root,
   or the single word `none` for a read-only member. A writer runs in its own worktree.
4. **Copy the instruction in [`../references/brief-instruction.md`](../references/brief-instruction.md)** into the
   brief's body, word for word. It tells the member to end its report with an output section.

The `subagent-triage` skill does all four for every brief it writes. If you write a brief by hand, do them yourself.

## The four checks

| Check | Applies to | Passes when |
|---|---|---|
| 1. The claimed output is the member's | the files the report's output section lists ([`../references/output-section.md`](../references/output-section.md)) | every listed file is the member's, as that file's 'Results' section defines it |
| 2. Front matter conforms | every Markdown file of the kinds your settings name that the member wrote, named in its report or not | the front-matter validator your settings name passes it. It is `not_applicable` only where the member wrote no such file |
| 3. The call is on the ledger | every member | a dispatch record carries this agent's id, member and attempt |
| 4. Writes stay in the write set | every member | every path changed in the worktree is inside the write set, and no Write, Edit or NotebookEdit call in the member's transcript names a path outside the worktree. For a read-only member, no such call names a path outside the scratch folder. A write to the session's scratch folder never fails check 4 |

Check 2 and check 4 read what the member wrote, not what its report says. Check 4 reads two sources, the worktree's
changes and the transcript's write calls, because each sees writes the other misses. Paths are compared in full,
after every link and other spelling of a folder is resolved, so `/tmp/x` and `/private/tmp/x` are one path.

## Results

Each check gives one of five results:

| Result | Means |
|---|---|
| `pass` | the check ran and found nothing wrong |
| `fail` | the check ran and found a fault. The result names each path or reason |
| `not_applicable` | nothing to check, such as a report claiming `none`. The reason follows where one is set |
| `not_checkable (<reason>)` | the check could not run, such as `not_checkable (check timed out)` |
| `ledger_absent` | the ledger was not writing for this session, so check 3 cannot tell a missing record from a missing ledger |

A return can also read `unrecorded (no check result when the return was written)` for a check. That means no result
existed in time. It is never a pass.

## When the checks run

The checks run inside the ledger's hooks, before the capture writes:

- **at each hand-back**, before the report reaches you; and
- **at each stop** of the member.

Each run makes all four checks. Its result names the report it read, `hand-back message` or `final message`, with
that text's SHA-256. The call's one return carries every run's result in the order the checks ran.

The return's answer is the report you received: the last delivered hand-back's message where there was one,
otherwise the final message.

## Reading the results

Read the member's results before you act on its report. Use the ledger's reader, as the `subagent-ledger` skill
describes:

```bash
python3 <ledger-skill>/scripts/calls.py --session <session id>
```

<!-- BUILD: name the return-record field that carries the check results, once the capture change fixes it. -->
Find the member's call by its agent id, member and attempt. Read its check results in order. The last result for
each check is the one that stands.

Then decide:

- **Every check `pass` or `not_applicable`:** the return is clean. You may act on the report, and merge a writer's
  worktree as 'Bringing a worktree home' says.
- **Any `fail`:** read the recommended repair below and decide. The check has changed nothing, so the member's work
  and its worktree are as it left them.
- **Any `not_checkable`, `unrecorded` or `ledger_absent`:** this is not a pass. Treat the return as unchecked. Ask
  the user before you merge it.

### Recommended repairs

A recommendation is advice for you, not an instruction. You may choose another repair, and you may choose none.

| Result | Recommended repair |
|---|---|
| check 1 `fail (no output section)` | Send the member back, at a new attempt, with the brief instruction restated. Or read its report yourself and treat it as claiming nothing |
| check 1 `fail (output section malformed)` | As for no output section |
| check 1 `fail` naming a missing file | Ask the member, at a new attempt, to write the file or remove it from the section. Do not act on the claim |
| check 1 `fail` naming a file the member did not change | Do not credit the member with the file. Check the file is not a stale copy before you use it |
| check 1 `fail` for a read-only member | The member wrote where it was told to write nothing. Look for the file it claims, and read check 4's result |
| check 2 `fail` | Run the front-matter validator on each file named and fix the fields it names, or send the member back to fix them |
| check 3 `fail` | The ledger missed this dispatch. Report it to the user. Do not re-send the member to repair the record |
| check 3 `ledger_absent` | The ledger was off. Report it to the user. Every check result for this session is unchecked |
| check 4 `fail` | Merge none of the named paths. Discard the worktree, or merge only the paths inside the write set and report the rest to the user |
| any `not_checkable` | Run the check by hand if you can, or ask the user before you merge |

## Bringing a worktree home

You may merge a writer's worktree into the shared tree, path by path, when every check on its return reads `pass` or
`not_applicable`. Merge a path only where the main checkout's state of it still equals the member's baseline. Where
another session has changed the path since, do not merge it: ask the user.

A merge under this rule covers bringing the paths in and committing them by path. It does not cover a push.

Any other result needs the user's word before you merge. Discard a worktree only once every path in it is merged or
settled with the user. Discarding is your act, never the check's.

## Leave these alone

- Never edit a check result or a return record. Report a wrong result to the user.
- Never read a section from a member's closing text, and never treat a path its report names outside the section as
  a claim.
- A member's shell write outside its worktree is invisible to check 4. A `pass` does not mean no such write happened.
  The skill's README lists what the checks cannot see.
