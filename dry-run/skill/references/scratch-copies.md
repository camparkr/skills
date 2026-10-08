# Scratch copies

Load at 'Make the scratch copies', before making a copy or saving a fingerprint. 'Check the real tree' and
'Remove the scratch copies' come back to it.

## Which copy each check needs

| The check | Scratch copy | Fingerprint |
|---|---|---|
| only reads, with nothing planted, run by a subagent | none | yes, since a subagent could still write |
| writes, or needs a fault planted in the changed files | a git copy | yes |
| runs the old code, as a behaviour change's control | a git copy plus an old-code copy, made with the base commit (the commit before the change) | yes |
| is a redraft's reading | two plain folders, one planted | yes |
| hands a model work, as the instructions row does | a folder per run outside the repository, holding only what the run needs (`model-output-checks.md`) | yes |

## The fingerprint, before the copy

The fingerprint is one hash of the repository's commit, branches, tags, stash, uncommitted changes and new
untracked files. Save it in the record before making any copy. From inside the repository, run:

```
<skill>/scripts/fingerprint.sh <record> [<test-index>]
```

Give each path from the repository's root. Pass the test index only where the project keeps one. `<skill>` is
the folder holding `SKILL.md`. The fingerprint leaves out files git ignores, such as build output. If the check
could write such a file, also save `git status --short --ignored`.

## Making the copies

These names and commands make each copy:

- `<scratch>` is the session's scratch or temporary folder, outside the repository. `<tag>` is a short tag for
  the session ending in the dry run's number, such as the session id's first eight characters and `3`:
  `a1b2c3d4-3`. No two sessions then share a copy.
- **A git copy:** from inside the repository, run `<skill>/scripts/scratch-copy.sh make <scratch> <tag>`, adding
  `<base-commit>` for a second copy with the old code.
- **What a git copy leaves in the real repository:** the script's header says, and `remove` clears it.
- **Never stash, branch, tag or commit to a named branch in a git copy.** A git copy shares its branches,
  tags and stash with the real repository. A check that must do one of them runs in
  `git clone --local <copy> <scratch>/<tag>-clone`.

**A redraft, start to finish.** The brief was written at 'Write any fresh reader's brief', naming no plant and
no second copy. Copy the redrafted files with `cp -R` into `<scratch>/<tag>a` and `<scratch>/<tag>b`, with any
file they link to that a reader needs. Use plain folders, not git copies, so `git status` cannot show a reader
which is planted. Plant one natural sentence per hypothesis in one of them, and note which in the record. Give
each fresh reader only its own folder's path and the brief. Compare the clean reader's answers with the
hypotheses. The control is caught when the planted reader follows or reports each plant. Delete both folders at
'Remove the scratch copies'.

## After the check

At 'Check the real tree', run `fingerprint.sh` again with the same arguments, and `git status --short --ignored`
if it was saved. Then act on what it shows:

- **The same output:** go on.
- **A different one:** find what changed with `git status --short`, `git status --short --ignored`, `git diff`
  and `git branch -a`. Remote-tracking branches move with any fetch, so ignore them.
- **Evidence of another session's change,** such as the requester confirming it or the diff matching known
  concurrent work: say so in the record and go on.
- **Anything else:** record it, delete nothing and stop. Remove no copies and commit no findings until the
  requester answers.

## Removing the copies

At 'Remove the scratch copies', once the record holds the check's output, delete any clone and any redraft
folders from scratch. Then, from inside the repository, run
`<skill>/scripts/scratch-copy.sh remove <scratch> <tag>`. It removes the registered copies itself. It fails if a
clone, a redraft folder or an unregistered copy remains.
