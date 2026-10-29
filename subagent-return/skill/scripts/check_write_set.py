#!/usr/bin/env python3
"""Check 4: the member's writes stay inside its write set.

Two sources, each seeing writes the other misses: the worktree's changes against the baseline, committed or not, and
every Write, Edit and NotebookEdit call in the member's transcript whose result is not an error, each tool-use id once
(Write and Edit name their path in `file_path`, NotebookEdit in `notebook_path`). Every path is compared as a
canonical path, links and `..` resolved, so `/tmp/x` and `/private/tmp/x` are one path.

  * A writer passes when every changed path in its worktree is inside its write set, and no write call names a path
    outside the worktree. Each write-set line is a path or folder prefix relative to the repository's root.
  * A read-only member passes when no write call names a path outside the scratch folder.
  * A write to the session's scratch folder never fails the check, for any member. The scratch folder is the
    payload's `scratchpad_dir`, and any folder `return_check.scratch` names (`{session}` replaced by the session id).

A fail names every such path. The check cannot run, and says why, where the transcript holds a write call with no
result yet or one whose result cannot be read as an error or not, where a writer has no dispatch record (so no
baseline), or where git cannot read the worktree against its baseline.

What neither source sees is a shell write outside the worktree, by any member. A read-only member's shell starts in
the shared tree, so a read-only member that used a shell (Bash, Agent or Task) gets `not_checkable (shell writes not
checkable: ...)` when it has no fail. A writer's shell starts in its worktree, where the diff reads its writes; its
shell writes outside the worktree are the accepted residue, so a shell-using writer with no fail passes, and the
result says the residue stands in `residue`.
"""

import os

import call_context as cc

CHECK, NAME = 4, 'write_set'
RESIDUE = 'shell writes outside the worktree are not seen by this check'


def in_set(path, root, entries):
    for entry in entries:
        if entry.lower() == 'none':
            continue
        target = cc.canonical(entry.rstrip('/'), root)
        if cc.inside(path, target):
            return True
    return False


def run(call):
    problem = call.write_problem()
    if problem:
        return cc.result(CHECK, NAME, cc.NOT_CHECKABLE, reason=problem)
    scratch = call.scratch_folders()
    outside = []
    if call.writer:
        changed, problem = call.changes()
        if problem:
            return cc.result(CHECK, NAME, cc.NOT_CHECKABLE, reason=problem)
        entries = call.write_set or []
        for path in changed:
            if not in_set(path, call.root, entries) and not any(cc.inside(path, s) for s in scratch):
                outside.append(path)
        for path in call.written():
            if not cc.inside(path, call.root) and not any(cc.inside(path, s) for s in scratch) \
                    and path not in outside:
                outside.append(path)
    else:
        for path in call.written():
            if not any(cc.inside(path, s) for s in scratch) and path not in outside:
                outside.append(path)
    if outside:
        shown = [os.path.relpath(p, call.root) if call.root and cc.inside(p, call.root) else p for p in outside]
        if call.writer:
            repair = ('Merge none of %s. Discard the worktree, or merge only the paths inside the write set and report '
                      'the rest to the user.' % ', '.join(shown))
        else:
            repair = ('The read-only member wrote %s outside the scratch folder. Look at each, keep or revert it by '
                      'hand, and report them to the user.' % ', '.join(shown))
        return cc.result(CHECK, NAME, cc.FAIL, reason='written outside the write set: %s' % ', '.join(shown),
                         paths=shown, repair=repair)
    if call.shell_using and not call.writer:
        return cc.result(CHECK, NAME, cc.NOT_CHECKABLE, reason='shell writes not checkable: a read-only member used '
                         'a shell, whose writes land in the shared tree unseen')
    found = cc.result(CHECK, NAME, cc.PASS)
    if call.shell_using:
        found['residue'] = RESIDUE
    return found
