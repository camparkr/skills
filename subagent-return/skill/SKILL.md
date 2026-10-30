---
name: subagent-return
description: "Checks each subagent's report as it comes back, before you act on it. A hook runs four exact checks on every member of a team: that the files it claims are its own, that its Markdown front matter conforms, that its call is on the ledger and that its writes stayed inside its write set. It records each result and, for a failure, recommends a repair. It refuses, removes and repairs nothing in the member's work. A failure holds your own tool calls until you record what you decided, with one command. Use it when you send work to subagents and must know what came back is what was claimed. Use it also when you read a return to decide whether to merge, re-send or discard, and when a tool call is refused because a check failed. Triggers: /subagent-return, check this subagent's return, did the subagent write what it says, can I merge this worktree, record a disposition, why was my tool call refused. Not for judging whether the work is good, for subagent calls with no brief file or for writing the ledger."
---

# subagent-return

When a member of your team reports back, a hook runs four checks on what it claims and what it wrote. Each result
goes onto the call's records in the ledger the `subagent-ledger` skill keeps. The checks never refuse the member,
never remove or revert a file and never discard a worktree. Each failure carries a recommended repair.

A failure does stop you. Until you record a decision on it, the ledger's hook refuses your own tool calls, save the
few you need to look and to ask. What you decide is yours: the repair is advice.

The checks are exact. None asks a model whether the work is good.

In the commands below, `<skill>` is this skill's folder, the one holding this file, `<ledger-skill>` is the
`subagent-ledger` skill's folder, and `<ledger>` is the ledger folder.

## Before you send a member

The checks can only read what the brief sets up. For each member:

1. **Write the brief to a file**, and give its absolute path as the first path in the prompt. The check finds the
   brief by the ledger's own rule: the first readable file the prompt names.
2. **Put the member key and the attempt in its front matter.** A brief without the member key gets check 1
   `not_applicable (no member brief)`, and its output section is never read.
3. **Give it a `## Write set` section**, one path or folder prefix a line, each relative to the repository's root,
   or the single word `none` for a read-only member. A writer runs in its own worktree.
4. **Copy the instruction in [`references/brief-instruction.md`](references/brief-instruction.md)** into the
   brief's body, word for word, with its two placeholders filled from your settings as that file says. It tells the
   member what each check looks for: where it may write, the front matter its Markdown files need and how to end
   its report.

The `subagent-triage` skill does all four for every brief it writes. If you write a brief by hand, do them yourself.

## The four checks

| Check | Applies to | Passes when |
|---|---|---|
| 1. The claimed output is the member's | the files the report's output section lists ([`references/output-section.md`](references/output-section.md)) | every listed file is the member's, as that file's 'Results' section defines it |
| 2. Front matter conforms | every Markdown file of the kinds your settings name that the member wrote, named in its report or not | the front-matter validator your settings name passes it. It is `not_applicable` only where the member wrote no such file |
| 3. The call is on the ledger | every member | a dispatch record carries this member and attempt, or, for a call with no member brief, this call's id |
| 4. Writes stay in the write set | every member | every path changed in the worktree is inside the write set, and no Write, Edit or NotebookEdit call in the member's transcript names a path outside the worktree. For a read-only member, no such call names a path outside the scratch folder. A write to the session's scratch folder never fails check 4 |

Check 2 and check 4 read what the member wrote, not what its report says. Check 4 reads two sources, the worktree's
changes and the transcript's write calls, because each sees writes the other misses. Paths are compared in full,
after every link and other spelling of a folder is resolved, so `/tmp/x` and `/private/tmp/x` are one path.

## Results

Each check gives one of five results:

| Result | Means |
|---|---|
| `pass` | the check ran and found nothing wrong |
| `fail` | the check ran and found a fault. The result names each path or reason, and carries a recommended repair |
| `not_applicable` | nothing to check, such as a report claiming `none`. The reason follows where one is set |
| `not_checkable (<reason>)` | the check could not run, such as `not_checkable (check timed out)` |
| `ledger_absent` | the ledger was not writing for this session, so check 3 cannot tell a missing record from a missing ledger |

A return can also read `unrecorded (no check result when the return was written)` for a check. That means no result
existed in time. It is never a pass.

Each result carries an id unique in its call, such as `3fa94c1e-2`: the run's own part, then the check's number. A
fault the hand-back's run found and the stop's run finds again, unchanged, keeps the hand-back's id, so one fault is
one `fail`.

Two results say more than their name:

- Check 4 for a read-only member that used a shell reads `not_checkable (shell writes not checkable: ...)` where it
  found no fault, since its shell writes land in the shared tree unseen.
- Check 4 for a writer that used a shell reads `pass` where it found no fault, with a `residue` note: shell writes
  outside the worktree are not seen.

## When the checks run

The checks run inside the ledger's hook wrapper, before the capture writes:

- **at each hand-back**, before the report reaches you; and
- **at each stop** of the member.

Each run makes all four checks. Its result names the report it read, `hand-back message` or `final message`, with
that text's SHA-256. A hand-back's run goes on its witness line in the ledger before its report reaches you. The
call's one return carries every run's result, in the order the checks ran, in its `check_results` field.

The return's answer is the report you received: the last delivered hand-back's message where there was one,
otherwise the final message.

## Reading the results

Read a member's results before you act on its report. They reach you three ways.

- **A foreground call.** When the Agent call returns, its results come with it, as added context: the latest run's
  four results, then each `fail` with its id and its recommended repair, marked as standing or settled. Where a
  `fail` stands, the command that records your decision follows.
- **A background call.** The member's report reaches you as a notification. When that notification names the
  member's agent id, the same summary comes with it, for each agent it names. Where a `fail` stands and no summary
  reached you, the gate's refusal at your next tool call names it.
- **The ledger.** The return record's `check_results` holds every run, and the ledger's reader lists each call with
  its results and its `dispositions`:

  ```bash
  python3 <ledger-skill>/scripts/calls.py --session <session id>
  ```

  While a `fail` stands the gate refuses that Bash call. Read the session's ledger file, `<ledger>/<session id>.jsonl`,
  with your read tool instead.

The latest run shows the member's work as it now stands. A `fail` from any run still holds you until a decision on
the record settles it, whatever later runs found.

Then decide:

- **Every check `pass` or `not_applicable`:** the return is clean. Act on the report, and merge a writer's worktree
  as 'Bringing a worktree home' says.
- **Any `fail`:** the gate holds you. Read the recommended repair, decide and record your decision as 'The gate'
  says. The checks have changed nothing, so the member's work and its worktree are as it left them.
- **Any `not_checkable`, `unrecorded` or `ledger_absent`:** this stops nothing, and it is not a pass. Treat the return
  as unchecked. Ask the user before you merge it.

### Recommended repairs

Each `fail` carries its repair, written from what the check found. A repair is advice for you, not an instruction.
You may choose another, and you may choose none. In outline:

| Result | Recommended repair |
|---|---|
| check 1 `fail (no output section)` | Ask the member, at a new attempt, to end its report with the section. Or read the report yourself and treat it as claiming nothing |
| check 1 `fail (output section malformed)` | As for no output section. The repair names the fault: no non-blank line, or `none` beside a path |
| check 1 `fail (claimed file does not exist: ...)` | Do not act on the claim. Ask the member, at a new attempt, to write the file or take it out of the section |
| check 1 `fail (claimed file not changed since the dispatch: ...)` or `(... not among the worktree's changes: ...)` | Do not credit the member with the file. Check it is not a stale copy before you use it |
| check 1 `fail (a read-only member claims output)` | Credit none of the files to the member. Look for each, and read check 4's result for where it wrote |
| check 2 `fail` | Run the validator on each file named and fix what it names, or send the member back to fix it |
| check 3 `fail` | The ledger missed this dispatch. Report it to the user. Do not send the member back to repair the record |
| check 4 `fail`, a writer | Merge none of the named paths. Discard the worktree, or merge only the paths inside the write set and report the rest to the user |
| check 4 `fail`, a read-only member | Look at each path it wrote, keep or revert it by hand and report them to the user |

Results that stop nothing still need a word:

| Result | What to do |
|---|---|
| check 3 `ledger_absent` | The ledger was off. Report it to the user. Every result for this session is unchecked |
| any `not_checkable` | Run the check by hand if you can, or ask the user before you merge |

## The gate

While a `fail` in this session stands with no decision recorded, the gate refuses each of your tool calls. The
refusal names the call refused and each standing `fail`, with its call, member, attempt, check, id and recommended
repair. It ends with the command that records your decision.

It lets through only:

- Read, Grep and Glob, so you can look at the output;
- TaskStop, so you can stop a member;
- AskUserQuestion, so you can ask the user; and
- the Bash call that runs the disposition command, as below.

Everything else waits: a write, an edit, any other shell command, a message to a member and a new dispatch, the
`subagent-triage` skill's scripts included.

What the gate does not do:

- It never refuses a member's tool call, so a member can always hand back. A `fail` on a member's own dispatch, a
  call one level down, holds you and not the member.
- A `not_checkable`, `unrecorded` or `ledger_absent` result stops nothing.
- A gate that errors or runs out of time refuses nothing. Its result reads `not_checkable` on a witness line.
- A reply with no tool call is not stopped, so a session can end with a `fail` undecided. The ledger's count check
  reports each such `fail` as a fault.

### Recording a decision

The refusal, and the summary that comes with a return, print the command for each call with a standing `fail`:

```bash
python3 "<skill>/scripts/disposition.py" --call <call id> --result <id> --kind <accepted|repaired|sent-back|re-dispatched|discarded> --reason "<why>" --decided-by <parent|user> --ledger "<ledger>"
```

It names each standing result with a `--result` of its own. Run it as printed, in a Bash call of its own, with its
placeholders filled. You may add these flags and no others:

- `--path <path>`, once for each path a `repaired` decision will change;
- `--quote "<the user's words>"`, where the user decided; and
- `--session <session id>`, where your shell does not set `CLAUDE_CODE_SESSION_ID`.

The command holds nothing else. No `;`, `&`, `|`, `<`, `>`, backtick, `$` or line break may appear anywhere in it,
the reason and the quote included, or the gate refuses it and names the fault first. One command settles the results
it names, on the call it names. Where two calls have standing fails, record each.

Choose the kind that says what you will do:

| `--kind` | Means | Then |
|---|---|---|
| `accepted` | the output stands as it is | act on it |
| `repaired` | you change the output yourself | name each path with `--path`, change them and commit the change by path. The count check reports a repaired decision with no later commit changing its paths |
| `sent-back` | you resume the member to fix it | send it your message |
| `re-dispatched` | you send the member's next attempt | brief and dispatch it as a new attempt. Its checks run afresh |
| `discarded` | the output is dropped | leave it unused |

`--decided-by` says who decided:

- `parent`: you did.
- `user`: a standing rule asks the user to decide, and the user did. Quote the user's words with `--quote`. Ask with
  AskUserQuestion, which the gate lets through.

Who decided is your own statement. The record is evidence of the path you took, not a check on it.

The script refuses, writing nothing and exiting 1, where:

- the ledger holds no check result for the call;
- a `--result` is not a result of that call;
- a `repaired` decision names no path;
- a `user` decision gives no quote; or
- the call is a writer with a `fail`, and the decision is `discarded` by `parent`. A failed writer's worktree is
  discarded only once its paths are settled with the user, so record `--decided-by user` with the user's words.

It exits 2 where it cannot run, such as with no session id. On exit 0 it writes a pending file and prints what it
recorded. When the Bash call finishes, the ledger's capture turns that file into a disposition record, and the gate
lifts for the results it settles. For an `accepted` or `repaired` writer with a `fail`, it adds that the merge still
needs the user's word, asked for in chat.

## Bringing a worktree home

You may merge a writer's worktree into the shared tree, path by path, when every check on its return reads `pass` or
`not_applicable`. Merge a path only where the main checkout's state of it still equals the member's baseline. Where
another session has changed the path since, do not merge it: ask the user.

The merge plan reads the ledger and the worktree and lists which paths may come home without asking:

```bash
python3 <skill>/scripts/return_check.py --merge-plan --call <call id> --worktree <worktree folder> [--main <main checkout>] [--session <session id>] [--ledger <ledger>]
```

`--main` is the main checkout, by default the repository your shell is in. The plan prints `merge`, the paths you
may bring in, and `ask`, each other path with the reason to ask. A `fail`,
`not_checkable` or `unrecorded` result, or no return, puts every path under `ask`, whatever disposition you recorded.
The plan changes nothing. It exits 0 with a plan, 1 where the call is no writer or has no dispatch record and 2 where
it cannot run.

A merge under this rule covers bringing the paths in and committing them by path. It does not cover a push.

Any other result needs the user's word before you merge. Discard a worktree only once every path in it is merged or
settled with the user. Discarding is your act, never the check's.

## Settings

The settings sit in the ledger folder's `config.json`. Two parts are this skill's.

**`checks`** names the commands the ledger's wrapper runs, each with the payload on standard input:

| Key | Command | Runs |
|---|---|---|
| `handback` | `python3 "<skill>/scripts/return_check.py"` | at each hand-back, before the report reaches you |
| `stop` | `python3 "<skill>/scripts/return_check.py"` | at each stop of a member |
| `gate` | `python3 "<skill>/scripts/gate.py"` | before each of your own tool calls |
| `context` | `python3 "<skill>/scripts/return_check.py" --context` | after a foreground call returns, and when a notification reaches you |

`check_seconds` bounds each check, 10 seconds by default. A check that runs past it refuses nothing and reads
`not_checkable (check timed out)`. The `subagent-triage` skill's dispatch check takes the `dispatch` key.

**`return_check`** holds the checks' own settings:

| Key | Holds | With none |
|---|---|---|
| `validator` | the front-matter validator check 2 runs, as a command. Each file's path is added as its last argument. Exit 0 passes the file | check 2 reads `not_checkable (no front-matter validator is set)` where the member wrote Markdown |
| `markdown` | glob patterns, read against each path relative to the working root, naming the Markdown files check 2 reads | every file whose name ends `.md` |
| `validator_not_checkable` | regular expressions searched in the validator's output. A non-zero exit whose output matches one reads `not_checkable`, not `fail`, since the validator failed and not the file | a Python traceback |
| `validator_seconds` | how long the validator may take on one file | 5 seconds |
| `scratch` | a folder, or a list, where any member may write. `{session}` is replaced by the session id. The harness's own scratch folder always counts | the harness's scratch folder alone |

For example:

```json
{
  "checks": {
    "handback": "python3 \"/opt/skills/subagent-return/skill/scripts/return_check.py\"",
    "stop": "python3 \"/opt/skills/subagent-return/skill/scripts/return_check.py\"",
    "gate": "python3 \"/opt/skills/subagent-return/skill/scripts/gate.py\"",
    "context": "python3 \"/opt/skills/subagent-return/skill/scripts/return_check.py\" --context"
  },
  "check_seconds": 10,
  "return_check": {
    "validator": "python3 /opt/tools/validate_front_matter.py",
    "markdown": ["docs/*.md", "notes/*.md"]
  }
}
```

The ledger's wrapper prints the hook entries these settings need. The skill's README says how to place them.

## Leave these alone

- Never edit a check result, a return record or a disposition record, and never write a disposition's pending file
  by hand. Report a wrong result to the user.
- Never read a section from a member's closing text, and never treat a path its report names outside the section as
  a claim.
- A member's shell write outside its worktree is invisible to check 4. A `pass` does not mean no such write happened.
  The skill's README lists what the checks cannot see.
- Leave the hook entries to the user, who places them in any settings other sessions load.
