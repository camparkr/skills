# Session record

Paths are placeholders; a real one appears only under a marked example.

## The record

- One record holds all of a session's dry runs and their item answers, whatever their size.
- It lives at `<project>/dry-runs/<YYYY-MM-DD>-<session-id>.md` (the session id is the one the harness
  shows for the session or its transcript), in the project's own repository, unless the
  project's agent instructions (such as `AGENTS.md` or `CLAUDE.md`) name another place. Then use that place,
  filling any part it names, such as a task id, from the session.
- The first dry run is the one that finds no record at that path.
- No session id, a place needing a task id the session lacks, or a public project: see 'Records and
  commits' in `when-things-go-wrong.md`.

## The test index (optional)

Keep one only where the project's agent instructions ask for it or one already exists. Follow the form
those instructions or the existing index give; with neither, add one line per record to `index.md` beside
the records, in the commit that first holds the record's hypotheses.

## Committing

- Commit in the repository that holds the record, on the branch where the change is being made. A protected
  branch that refuses the commit is a refused commit (`when-things-go-wrong.md`). The records then travel
  with the change into its history; a project that wants them elsewhere names the place in its agent
  instructions, and a public project keeps them out of its public history ('Records and commits' in
  `when-things-go-wrong.md`). The records then show in the change's pull request, and a squash merge keeps
  only their final text, not the commit that proves the hypotheses came first; a project that squash-merges
  names another place for them.
- Commit only the record, and the test index if the project keeps one, by name, with the commands in
  the two gate steps of `SKILL.md`. The verdicts commit's ancestor holds the hypotheses.
- The local commit is the witness that hypotheses came first. A local commit can be rewritten until it is
  pushed, so the project's normal push is what takes it outside the author.
- **A project with no push:** send the hypotheses commit id to the requester before the check.
- A refused commit, a project outside git, or a session ending before the check: see 'Records and commits'
  in `when-things-go-wrong.md`.

## Citing versions

- Cite each objective, intended outcome and constraint as `<path>@<commit>`, where the cited text appears word
  for word. Outside git, cite a dated copy or version number. An objective given in conversation is cited
  by its quoted words, who said them and the date; the record's hypotheses commit then holds it.
- Cite each commit in the repository that holds it. Name that repository when it is not the record's own.
- If the change is not yet committed, record its base commit and the diff under test.

## Skeleton

*A guide to what a reader needs. It gates nothing.*

```markdown
## Dry run <n>: <the change, in a few words>

**Intent.** <objective>, <intended outcomes>, <constraints>, each at `<path>@<commit>`.

| # | Hypothesis | Tests (objective, intended outcome or constraint) | Refuted by | Control or refuting passage |
|---|---|---|---|---|
| H1 | ... | ... | ... | ... |

**Hypotheses committed:** <commit> (filled in the verdict commit; never amend the hypotheses commit).

**Check.** <command or reader>, run at <commit>, on <copy or live tree>.
<raw output>

| # | Control result | Verdict | Reason |
|---|---|---|---|
| H1 | caught, missed or none | supported, refuted or inconclusive | ... |

**What follows.** <'the work may proceed', or the stop and what was reported to the requester>.

**Admin fixed.** <each fix, with its diff or count>.

**Item answers.** <one per item, where the dry run answered one question for each>.
```

*Filled example, from the code change in `example-dry-runs.md`:*

| # | Hypothesis | Tests (objective, intended outcome or constraint) | Refuted by | Control or refuting passage |
|---|---|---|---|---|
| H1 | The changed loader reads each of ten timestamps as written | constraint: approval times are judged as written | a case read with a conversion applied | control: the stock loader converts all ten |

| # | Control result | Verdict | Reason |
|---|---|---|---|
| H1 | caught: the stock loader converted all ten | supported | the changed loader read all ten as written; right in principle only |

*A redraft's hypothesis, weak and then fixed, from a reworded step 10 in this skill:*

| | Hypothesis | Refuted by | Control |
|---|---|---|---|
| Weak | The new step 10 is clearer | nothing a stranger could observe | none |
| Fixed | A fresh reader asked what to do when the fingerprint differs says: stop, remove no copies, commit no verdicts | the reader goes on to remove the copies | the planted copy says 'go on to step 11 while waiting', and its reader follows it |
