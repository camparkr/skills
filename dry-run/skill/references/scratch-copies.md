# Scratch copies

Load at 'Make the scratch copies', before making a copy or saving a fingerprint. 'Check the real tree' and
'Remove the scratch copies' come back to it.

## Sizing the check

A check uses the smallest input that can fail. A larger one costs time and disk and finds nothing more.

- **What the check reads:** the changed files, the readers a search finds and the tests that read the changed
  paths. Find those tests by searching the test files for each changed path and name, as for any other reader.
- **One git copy, not a clone.** A scratch copy is the script's git copy, made as 'Making the copies' says.
  Clone only where this file names a clone: a check that must stash, branch, tag or commit. Never clone the
  repository to get a copy, and make a second copy only for the old code a behaviour change's control runs.
- **A full test suite** runs only when its result decides a finding, such as a hypothesis that the change
  breaks nothing a search can find. Otherwise run the tests that read the changed paths, and name them in the
  hypothesis before the commit.
- **Free disk, before any copy.** Check the free space where the copy will go, such as with `df -h <scratch>`.
  If the copy and what the check writes would not fit with room to spare, stop and tell the requester.
- **Removal, as soon as a copy exists.** Write the command that removes it into the record straight away,
  before the check runs. Where the check runs as a script, have the script remove what it makes when it exits,
  such as with a shell `trap`, and list any folder the check itself makes, such as a test run's temporary
  copies. A check that fails partway then leaves nothing behind: 'Remove the scratch copies' runs the
  recorded commands whatever the check did.

## Which copy each check needs

| The check | Scratch copy | Fingerprint |
|---|---|---|
| only reads, with nothing planted, run by a subagent or another session | none | yes, since either could still write |
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
- **What a git copy leaves in the real repository:** the script's header says. `remove` deletes the worktree
  entries, and git's routine garbage collection later deletes the commit and its objects.
- **Never stash, branch, tag or commit to a named branch in a git copy.** A git copy shares its branches,
  tags and stash with the real repository. A check that must do one of them runs in
  `git clone --local <copy> <scratch>/<tag>-clone`.

**A redraft, start to finish.** 'Write any fresh reader's brief' has already written the brief, naming no plant
and no second copy. Copy the redrafted files with `cp -R` into `<scratch>/<tag>a` and `<scratch>/<tag>b`, with
any file they link to that a reader needs. Use plain folders, not git copies, so `git status` cannot show a
reader which is planted. Plant one natural sentence per hypothesis in one of them, and note which in the record.
Give each fresh reader only its own folder's path and the brief. Compare the clean reader's answers with the
hypotheses. The control is caught when the planted reader follows or reports each plant. Delete both folders at
'Remove the scratch copies'.

## After the check

At 'Check the real tree', run `fingerprint.sh` again with the same arguments, and `git status --short --ignored`
if it was saved. Then act on what it shows:

- **The same output:** go on.
- **A different one:** find what changed. Run `git status --short`, `git status --short --ignored`, `git diff`
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
