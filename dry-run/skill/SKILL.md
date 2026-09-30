---
name: dry-run
description: "Test a planned change before it lands. Use before merging a refactor, renaming or moving files, running a migration, or publishing a rewritten prompt, document or spec; commits its hypotheses before checking and shows each check can fail. Triggers: /dry-run, dry-run this, rehearse the change, check this before I merge, what would this change break, blast radius, sanity-check a change. Not for typo fixes, a tool's --dry-run flag, test-driven development or reviewing finished work (verification-before-completion)."
---

# Dry run

A dry run tests a planned change against its intent: its objective, intended outcomes and constraints.
Its check must first be shown able to fail: a check that cannot fail proves nothing by passing.
A control is the case the check must catch, such as a planted fault, the old code or a should-fail case.
A should-fail case is the case the change exists to reject, a rejected alternative, or an input an earlier
plan got wrong. A fresh reader is a session or subagent with none of the author's context.

The core is fixed. Every dry run has an objective. Every hypothesis is committed before the check, or in
lighter mode sent to the requester before it. Every hypothesis has a control.

## Admin

A fix that cannot change the outcome, such as a broken link, a typo or a question reworded with the same
answer, needs no dry run. Fix it with evidence and list it in the record, or in the commit message when no
dry run is open. Everything else starts with steps 1 to 4, which write the hypotheses; step 4 then chooses
the route.

## Steps

1. **Find the session's record.**
   - It is `<project>/dry-runs/<YYYY-MM-DD>-<session-id>.md`, unless the project's agent instructions
     (such as `AGENTS.md` or `CLAUDE.md`) name another place. Committed there, it shows in the change's
     history and pull request.
   - None there: load `references/session-record.md` and create it from its 'Skeleton' section.
   - No session id, a place needing a task id, a public project, or one that squash-merges: see 'Records
     and commits' in `references/when-things-go-wrong.md`.
2. **Find the objective** at source. None written: ask the requester, whoever asked for the work or will
   rule on it. Their answer, quoted and dated, is the objective. No objective, no dry run: the check could
   only test conformance to a record or format. No answer: load `references/when-things-go-wrong.md`.
3. **Cite the intent** at a fixed version: each objective, outcome and constraint as `<path>@<commit>`
   where its text appears word for word, or, if given in conversation, by its quoted words, speaker and
   date. None written: say so and why. Other cases: 'Citing versions' in `references/session-record.md`.
4. **What could this change break?** Before writing hypotheses, ask:
   - **Which intents and constraints could this break?** One is at risk if anything that reads the changed
     thing depends on it. List every such dependent. Name the intents the change cannot touch, and why. Drop
     any hypothesis whose refutation would not change the decision to go or stop.
   - **Which failure would surface last?** Start there: it costs most to find later, and the build's own
     tests are likeliest to miss it. A check that silently loses coverage is one: count its rows before and
     after.
   - **For a decision: what would the requester do differently** if a hypothesis were refuted? If nothing, it
     tests nothing.
   - **What must stay unchanged?** At least one hypothesis says what stays, unless the only hypothesis
     tests the intended difference.
   - **Could a stranger make the refuting observation unaided?** If not, the hypothesis is not ready.

   Write the hypotheses, one per intent at risk. Each says what you would see if the intent broke; the filled
   examples in the 'Skeleton' section of `references/session-record.md` show good and bad ones. Write any
   fresh reader's brief now, so it goes into the step 7 commit.

   **Then choose the route:**

   | Route | When | Steps |
   |---|---|---|
   | Shortest | one hypothesis, a check that only reads, no plant and no old code; in practice a design, decision or specification against a should-fail case | 5, 7, 9, 12 and 13; if a subagent reads, also 8 and 10 for the fingerprint |
   | Full | anything else | every step |

   **Lighter mode**, on the shortest route only: when the requester is in the conversation and no one else
   will rely on the result, send them the hypothesis and its should-fail case before the check, in place of
   the step 7 commit. After the check, make one record commit that quotes that message with its time and
   marks the dry run 'lighter mode: weaker witness'.
5. **Choose each control** from the decision table below. Load `references/example-dry-runs.md` and read
   only that row's section.
6. If the check gives one answer per item, such as each file's new home in a rename, load
   `references/item-answers.md` and record each answer as it says. Otherwise leave it unloaded.
7. **Gate: is every hypothesis committed before any check?** Commit the record by name only:
   - `git add <record>`
   - `git commit -m 'dry-run <n>: hypotheses' -- <record>`

   A dry run makes local git commits as its evidence: this one and the verdicts commit at step 12, unless
   lighter mode or a fallback in `references/when-things-go-wrong.md` applies.

   `<n>` is the dry run's number in the session's record: 1 for the first, then 2, and so on. Never run a
   check before this commit exists unless lighter mode has replaced it. Whether to ask first: the first row
   that applies decides.

   | When | Before this commit |
   |---|---|
   | the project's instructions require asking before a commit, whatever the request | ask |
   | `/dry-run`, or a request that names a dry run or rehearsal | commit without asking |
   | any other request, such as 'check this before I merge', or the skill loaded unasked | ask once |

   The requester refuses the commit: stop and record why, unless lighter mode applies. Push nothing
   yourself. Which branch, a project that keeps a test index, or a project with no push: see 'Committing'
   in `references/session-record.md`.
8. **Make the scratch copies.** What each kind of check needs:

   | The check | Scratch copy | Fingerprint, step 10 |
   |---|---|---|
   | only reads, with nothing planted | none | only if a subagent runs the check, which could still write; else skip |
   | writes, or needs a fault planted in the changed files | a git copy, made by `scratch-copy.sh` | yes |
   | runs the old code, as a behaviour change's control | a git copy plus an old-code copy, made by `scratch-copy.sh` with the base commit, which is the commit before the change | yes |
   | is a redraft's reading | two plain folders, one planted | yes |

   Where the last column says yes, first, from inside the repository, save in the record the fingerprint that
   `<skill>/scripts/fingerprint.sh <record>` prints (paths from the repository's root); `<skill>` is the
   folder holding this file. The fingerprint leaves out files git ignores, such as build output: if the check
   could write one, also save `git status --short --ignored`. Before making a copy, load
   `references/scratch-copies.md`.

   Copies made by `scratch-copy.sh` share the repository's branches, tags and stash. In such a copy, never
   stash, branch, tag or commit to a named branch.
9. **Run the check.** If a subagent will run it, load `references/briefing-others.md` first. A redraft's
   two fresh readers each get only their own folder's path and the same brief; compare the clean folder's
   reader's answers with the hypotheses. Cite the commit the check ran at, and name any uncommitted change
   it included. If the control, the check or a commit goes wrong, or the project is not in git, load
   `references/when-things-go-wrong.md`.
10. **Did anything reach the real tree?** Skip this step if step 8 saved no fingerprint. Otherwise run
    `fingerprint.sh` again with the same paths, and `git status --short --ignored` if step 8 saved it.
    - The same output: go on.
    - A different one: find what changed with `git status --short`, `git status --short --ignored`,
      `git diff` and `git branch -a` (remote-tracking branches move with any fetch; ignore them).
      - Evidence of another session's change, such as the requester confirming it or the diff matching known
        concurrent work: say so in the record and go on.
      - Anything else is a finding: record it, delete nothing and stop. Remove no copies and commit no
        verdicts until the requester answers.
11. **Remove the scratch copies**, if step 8 made any. Removing them deletes anything left in them, so first
    copy into the record the check's output that bears on each hypothesis. Delete any clone and any redraft
    folders from scratch. Then, from inside the repository, run
    `<skill>/scripts/scratch-copy.sh remove <scratch> <tag>`. It fails if a copy, clone or redraft folder
    remains.
12. **Gate: does each verdict sit beside its control's result?** Write the verdicts into the record, with
    'the work may proceed' if all are supported, or 'stopped' if any is not. Commit it by name only, with
    step 7's two commands and the message 'dry-run <n>: verdicts'. In lighter mode, this is the one
    record commit after the check; include the quoted pre-check message and the weaker-witness mark.
13. **What do the verdicts allow?** A supported verdict shows the plan is right in principle; the finished
    work is still checked on its own.
    - All supported: the record says the work may proceed.
    - Any refuted or inconclusive: stop. Report each such hypothesis, what was seen and the verdict commit
      to the requester, who decides what follows. With no one to report to, write the report into the
      record, commit it and end. A later rerun is a new dry run, with new hypotheses, in the same record.
    - If the work goes next to a review by anyone else, such as someone trying to break the proposal or
      testing the finished work, read `references/briefing-others.md` before writing its brief.

## Decision table

| Change | Check | Control that shows the check can fail |
|---|---|---|
| Restructure, rename, migration | a count or diff on a scratch copy | a breakage planted where the check looks is found |
| Code change that alters or adds behaviour | a run on real cases | the old code, run on the same cases, fails where the change should differ, giving a wrong result or none |
| Code change that alters no behaviour, such as a refactor | a run on real cases | a fault planted in a scratch copy of the changed code is caught |
| Redraft | two fresh readers, each given one plain copy, read blind (step 9) | the planted copy's reader follows or reports each planted instruction |
| Design, decision, specification | run real cases that read only, or have a fresh reader read them | a should-fail case, written into the hypotheses, fails |

- A fresh reader may run on any harness. With no subagents, a new session given only the brief counts.
  Brief each reader the same way: ask what the text tells an agent to do in each situation a hypothesis
  covers, never the hypothesis itself. Say nothing of plants or of a second copy. Record the brief word
  for word in the hypotheses commit. A brief that has worked: 'Read only <path>. Read no other file. <The
  situation.> What does the text tell you to do? Quote the line you rely on, or say that no line covers
  it. Change nothing and run nothing.'
- For a design, decision or specification, present the should-fail case to a fresh reader as one more case
  in the brief. Do not label it as the should-fail case or reveal the hypothesis.
- A change that fits no row uses the nearest row and records why.
- Run a check when the change can run on a case. Read only when it cannot, and record why.
- Without its control, a supported verdict is inconclusive; a refutation still stands.
- Plant breakages only in a scratch copy (step 8), and make each plant read naturally. Choose the subtlest
  plant that would still break the intent: the check must find what matters, not what is easy to see.

## Rules

- **Split until each piece can fail.** Split a change when one piece's failure could hide another's.
  - A change spanning two rows of the table splits by row.
  - Each piece is its own dry run in the record.
  - Commit a piece's hypotheses only after the previous piece's verdict.
  - A refuted or inconclusive piece stops the pieces after it.

**Never** (for why, when someone asks, the recorded incidents are in `references/why-each-never.md`):
- accept a rerun as a control: it shows the check repeats, not that it can fail;
- plant a breakage where the check does not look: the check passes for the wrong reason;
- copy a plant into the real change: the check has already passed it;
- write hypotheses and results in one pass, or in one commit outside the lighter mode: nothing earlier then
  proves the order, and hindsight makes any outcome look predicted;
- stage the record's commit with `git add -A` or `git add .`: the change under test enters the hypotheses
  commit;
- delete a file from the real tree after a check: someone else may be working there;
- conclude a file has no readers from a filename search: text also cites by title and in prose, so
  search those too;
- gate on a record about the change, such as a status field: it shows what the author wrote, not what the
  change does;
- let the author's own re-reading stand as the check: a model without outside feedback does not reliably
  correct itself;
- run a reworded hypothesis or a repaired check before it has its own commit: the old commit does not show
  the new wording came first;
- plant a breakage any reader would flag unread: a crude plant tests the reader's eye, not their reading;
- let checkability replace intent: a test chosen for being easy to check measures what it can see, not
  what the change is for.

## Do not load

Each step names when to load a file. Leave each unloaded as follows.

| File | Do not load |
|---|---|
| `references/session-record.md` | again while still in context, or once the session's record exists unless a step names one of its sections |
| `references/example-dry-runs.md` | again while still in context |
| `references/scratch-copies.md` | unless step 8 makes a scratch copy |
| `references/item-answers.md` | for a check that does not give one answer per item (step 6) |
| `references/when-things-go-wrong.md` | unless a step sends you to it |
| `references/briefing-others.md` | unless a subagent runs the check or an outside review comes next |
| `references/why-each-never.md` | during a dry run; only when asked why a NEVER holds |
| `references/sources.md` | during a dry run; only when asked for a source |
