# Scratch copies

Load at step 8 ('Make the scratch copies') before making one. Scratch copies are throwaway copies of the
project, or of the changed files, kept outside the repository so the check never touches the real files.

- `<scratch>` is the session's scratch or temporary folder, outside the repository. `<tag>` is a short tag
  for the session ending in the dry run's number, such as the session id's first eight characters and
  `3`: `a1b2c3d4-3`, so no two sessions share a copy.
- **A git copy:** from inside the repository, `<skill>/scripts/scratch-copy.sh make <scratch> <tag>
  [<base-commit>]`. A base commit adds a second copy with the old code, for a code change's control. Where
  git has no identity set, `scratch-copy.sh` signs its throwaway snapshot commit with the placeholder 'Lorem
  Ipsum'.
- **What a git copy leaves in the real repository.** `make` leaves the working tree and index alone, but
  adds to the real `.git` a worktree entry per copy and one snapshot commit. `remove` deletes the entries;
  git's routine garbage collection later deletes the commit.
- **A redraft's two plain folders:** `cp -R` the redrafted files into `<scratch>/<tag>a` and
  `<scratch>/<tag>b`, with any file they link to that a reader needs; plant one sentence per hypothesis
  in one only. Plain folders, not git copies, so `git status` cannot show a reader which is planted.
- A check that must stash, branch, tag or commit to a named branch runs in
  `git clone --local <copy> <scratch>/<tag>-clone`.

**A redraft, start to finish.** Write the brief at step 4, never naming a plant or a second copy. Copy the
redrafted files into `<tag>a` and `<tag>b`; plant one natural sentence per hypothesis in one of them, and
note which in the record. Give each fresh reader only its own folder's path and the brief. Compare the
clean reader's answers with the hypotheses; the control is caught when the planted reader follows or
reports each plant. Delete both folders at step 11.
