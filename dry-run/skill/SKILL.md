---
name: dry-run
description: "Test a planned change before it lands. Use before merging a refactor, renaming or moving files, running a migration or publishing a rewritten prompt, persona, agent instructions, document or spec. It commits its hypotheses to git before checking and shows each check can fail. Triggers: /dry-run, dry-run this, rehearse the change, check this before I merge, what would this change break, blast radius, sanity-check a change. Not for typo fixes, a tool's --dry-run flag, test-driven development or reviewing finished work."
---

# Dry run

A dry run tests a planned change against its intent: its objective, intended outcomes and constraints. Its
check must first be shown able to fail, because a check that cannot fail proves nothing by passing. A control
is the case the check must catch, such as a planted fault, the old code or a should-fail case. A should-fail
case is one the change exists to reject: a rejected alternative or an input an earlier plan got wrong.

The core holds on every route and in every mode. Every dry run has an objective. Every hypothesis is
committed before the check, or, where lighter mode or a fallback allows, sent to the requester before it.
Every hypothesis has a control.

## When no dry run is needed

A fix that cannot change the outcome needs no dry run: a broken link, a typo or a question reworded with
the same answer. Fix it with evidence, and list it in the record or in the commit message. Everything
else starts at 'Find the record'.

## Decision table

| Change | Check | Control that shows the check can fail |
|---|---|---|
| Restructure, rename, migration | a count or diff on a scratch copy | a breakage planted where the check looks is found |
| Code change that alters or adds behaviour | a run on real cases | the old code, run on the same cases, fails where the change should differ, giving a wrong result or none |
| Code change that alters no behaviour, such as a refactor | a run on real cases | a fault planted in a scratch copy of the changed code is caught |
| Redraft | two fresh readers, each given one plain copy, read blind | the planted copy's reader follows or reports each planted instruction |
| Instructions a model runs under, such as a persona or a prompt, where the question is what the model does | real work handed to the model, its outputs read with closed questions | the instructions inverted as a whole, whose outputs the reading tells apart; a version with one line changed is not a control |
| Design, decision, specification | run real cases that read only, or have a fresh reader read them | a should-fail case, written into the hypotheses, fails |

Notes on the table:

- A change that fits no row uses the nearest row and records why.
- Run a check when the change can run on a case. Read only when it cannot, and record why.
- If the control was not run or not caught, a supported finding is inconclusive; a refutation still stands.
- Where the question is what a model does with work, not what a reader takes the instructions to say, use
  the instructions row. Asked what a text tells it to do, a model repeats the text.
- Plant breakages only in a scratch copy, and make each one read naturally. Choose the subtlest plant that
  would still break the intent, such as a sentence that quietly restores a phrase the redraft dropped. The
  check must find what matters, not what is easy to see.

## Before the check

1. **Find the record.** It is `<project>/dry-runs/<YYYY-MM-DD>-<session-id>.md`, where `<project>` is the
   repository's root, unless the project's agent instructions (such as `AGENTS.md` or `CLAUDE.md`) name another
   place. No record at that path: load `references/session-record.md` and create it from its 'Skeleton'
   section. For a missing session id or task id, a public or squash-merging project or a project outside git,
   see 'Records and commits' in `references/when-things-go-wrong.md`.
2. **Find the objective** at source. None written: ask the requester, whoever asked for the work or will rule
   on it. Their answer, quoted and dated, is the objective. No objective, no dry run: the check could only test
   conformance to a record or format. No answer: load `references/when-things-go-wrong.md`.
3. **Cite the intent** at a fixed version. Cite each objective, outcome and constraint as `<path>@<commit>`,
   where its text appears word for word. Cite one given in conversation by its quoted words, speaker and date.
   None written: say so and why. Other cases: 'Citing versions' in `references/session-record.md`.
4. **Ask what the change could break:**
   - **Which intents and constraints could this break?** One is at risk if anything that reads the changed
     thing depends on it. List every such dependent. Name the intents the change cannot touch, and why.
   - **Which failure would surface last?** Start there: the build's own tests are likeliest to miss it. A
     check that silently loses coverage is one, so count its rows before and after.
   - **What would the requester do differently** if it broke? If nothing, it needs no hypothesis.
   - **What must stay unchanged?** At least one hypothesis says what stays, unless the only hypothesis tests
     the intended difference.
5. **Scout, if a model's behaviour is the question.** Is the question what a model does under the changed
   instructions, such as a persona or a prompt? Then load `references/model-output-checks.md` and run its
   scout: the model on real work, read in full. The scout shapes the hypotheses; its outputs are never
   evidence.
6. **Write the hypotheses,** one per intent at risk. Each says what you would see if the intent broke, in
   terms a stranger could observe unaided. 'The new step is clearer' tests nothing. 'A fresh reader asked what
   to do when the fingerprint differs says: stop' can be refuted. Name the observation that would refute each
   one, and the control that shows the check can see it. The 'Skeleton' section of
   `references/session-record.md` has more good and bad pairs.
7. **Choose the route.** The shortest route suits one hypothesis whose check only reads, with no plant and no
   old code. A design, decision or specification against a should-fail case is the usual one. When this
   session runs that check itself, as a count or a script, it skips the three copy steps. They are 'Make the
   scratch copies', 'Check the real tree' and 'Remove the scratch copies'. Keep them when a subagent or another
   session reads, since either could write to the tree. Anything else takes the full route, every step. On the
   shortest route, lighter mode can replace 'Commit the hypotheses': see 'Lighter mode' in
   `references/session-record.md`.
8. **Choose each control** from the decision table above. Load `references/example-dry-runs.md` and read only
   that row's section. On the instructions row, read 'What a good one looks like' in
   `references/model-output-checks.md` instead.
9. **Write any fresh reader's brief,** by 'Briefing a fresh reader' in `references/briefing-others.md`. It
   goes into the hypotheses commit.
10. **Plan item answers,** if the check gives one answer per item, such as each file's new home in a rename.
    Load `references/item-answers.md` and record each answer as it says.
11. **Commit the hypotheses.** This gate comes before any check. Commit the record by name only:

    ```
    git add <record>
    git commit -m 'dry-run <n>: hypotheses' -- <record>
    ```

    `<n>` is the dry run's number in the record: 1 for the first, then 2, and so on. This commit and the
    findings commit are the dry run's evidence. Never run a check before this commit exists, unless lighter
    mode or a fallback has replaced it. A scout is design work, not a check, and runs before it.

    Whether to ask before this commit:

    - the project's instructions require asking: ask;
    - the request was `/dry-run`, or named a dry run or rehearsal: commit without asking; or
    - any other request: ask once.

    If the requester refuses, stop and record why, unless lighter mode applies. Push nothing yourself. For the
    branch, a test index or a project with no push, see 'Committing' in `references/session-record.md`.

## The check

12. **Make the scratch copies.** Skip this step when the check only reads, plants nothing and runs in this
    session. Otherwise load `references/scratch-copies.md`. It says which copy each check needs, and has you
    save a fingerprint of the repository before making one.
13. **Run the check.** If a subagent or a fresh reader runs it, load `references/briefing-others.md` first.
    Cite the commit the check ran at, and name any uncommitted change it included. If the control, the check
    or a commit goes wrong, load `references/when-things-go-wrong.md`.
14. **Check the real tree.** If 'Make the scratch copies' saved a fingerprint, compare it as 'After the check'
    in `references/scratch-copies.md` says. Record any change that has no explanation, and stop. Delete
    nothing, remove no copies and commit no findings until the requester answers.
15. **Remove the scratch copies**, if any were made. Removing a copy deletes what is left in it, so first
    copy into the record the check's output that bears on each hypothesis. Then follow 'Removing the copies'
    in `references/scratch-copies.md`.

## After the check

16. **Commit the findings.** This gate checks each finding sits beside its control's result. Write the
    findings into the record. Mark the dry run 'all supported' if every hypothesis is supported, or 'stopped'
    if any is not. Commit it by name only, with the two commands of 'Commit the hypotheses' and the message
    'dry-run <n>: findings'. In lighter mode, this is the one record commit after the check.
17. **Hand the findings to the requester,** who decides what follows. The findings are evidence, not a
    decision. A supported finding shows the plan is right in principle only. The finished work is still
    checked on its own.
    - All supported: send the findings to the requester. Work they have already asked for goes on as asked.
    - Any refuted or inconclusive: stop. Report each such hypothesis, what was seen and the findings commit to
      the requester, who decides what follows. With no one to report to, write the report into the record,
      commit it and end. A later rerun is a new dry run, with new hypotheses, in the same record.
    - If the work goes next to a review by anyone else, read `references/briefing-others.md` before writing
      its brief.

## Split until each piece can fail

Split a change when one piece's failure could hide another's:

- a change spanning two rows of the table splits by row;
- each piece is its own dry run in the record;
- commit a piece's hypotheses only after the previous piece's finding; and
- a refuted or inconclusive piece stops the pieces after it.

## Never

Never:

- accept a rerun as a control: it shows the check repeats, not that it can fail;
- plant a breakage where the check does not look: the check passes for the wrong reason;
- plant a breakage any reader would flag unread: a crude plant tests the reader's eye, not their reading;
- copy a plant into the real change: the planted fault would ship, and the check has already passed it;
- write hypotheses and results in one pass, or in one commit outside lighter mode: nothing proves
  the order, and hindsight makes any outcome look predicted;
- run a reworded hypothesis or a repaired check before it has its own commit: the old commit does not show
  the new wording came first;
- stage the record's commit with `git add -A` or `git add .`: the change under test enters the hypotheses
  commit;
- delete a file from the real tree after a check: someone else may be working there;
- conclude a file has no readers from a filename search: text also cites by title and in prose;
- gate on a record about the change, such as a status field: it shows what the author wrote, not what the
  change does;
- let the author's own re-reading stand as the check: a model without outside feedback does not reliably
  correct itself; or
- let checkability replace intent: a test chosen for being easy to check measures what it can see, not what
  the change is for.

## Do not load

Each step names when to load a file. Leave each unloaded as follows.

| File | Do not load |
|---|---|
| `references/session-record.md` | again while still in context; once the record exists, read only the section a step names |
| `references/example-dry-runs.md` | again while still in context, or on the instructions row |
| `references/scratch-copies.md` | unless 'Make the scratch copies' makes a copy or saves a fingerprint |
| `references/item-answers.md` | unless the check gives one answer per item |
| `references/when-things-go-wrong.md` | unless a step sends you to it |
| `references/briefing-others.md` | unless a fresh reader's brief is written, a subagent runs the check or an outside review comes next |
| `references/model-output-checks.md` | unless the change is on the instructions row |
