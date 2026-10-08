# When things go wrong

## Objective, control and check

- **No answer to the objective question this session.** Write the question into the record, uncommitted:
  with no objective there is no hypothesis to commit. Check nothing and end.
- **The control gives the wrong result.** The check is broken, not the change. Fix the check and run the
  control again before any finding. Record the repaired check and its control as a new row in the same dry
  run, committed before it runs. After a reported stop, a rerun is a new dry run ('Who decides what
  follows?' in `SKILL.md`).
- **The control is caught only some of the time.** The check is flaky: mark each hypothesis it bears on
  inconclusive, and report it ('Who decides what follows?' in `SKILL.md`).
- **A hypothesis partly supported.** Split it into the part that held and the part that did not, each with
  its own finding, or mark the whole inconclusive. Never round it up to supported.
- **No fresh reader or no planted copy for a redraft.** The finding is inconclusive; report it ('Who decides what
  follows?' in `SKILL.md`).
- **The repository has submodules or Git LFS files.** A `scratch-copy.sh` copy does not fetch them. Run
  `git submodule update --init` or `git lfs pull` inside the copy before the check, and record that step.
- **The check needs ignored files**, such as installed dependencies. `scratch-copy.sh` leaves them out. Install
  them into the copy, or copy them in, and record that step. Never link them: a check could write
  through the link into the real tree.
- **Windows.** Run `scratch-copy.sh` in Git Bash, which comes with Git for Windows.
- **No copy possible**, as with a live service. Check by reading, or mark the hypothesis inconclusive. A
  write to the live system is the change itself, not a rehearsal of it.
- **No check can settle a hypothesis.** Mark it inconclusive, stop and report it ('Who decides what
  follows?' in `SKILL.md`).
- **A check too costly to run in full**, such as a slow suite. Sample the cases, name the sample in the
  hypothesis before the commit, and mark the unsampled scope inconclusive.
- **Output too long to keep whole.** Keep the command, the version it ran at and the lines that bear on each
  hypothesis, so another reader can run it again.

## Records and commits

- **No session id.** Name the record `<YYYY-MM-DD>-<HHMM>.md` from the time of the session's first dry run,
  and reuse that name all session.
- **The project's place needs a task id the session lacks.** Take it from the session's name. With none,
  ask the requester once per session, and until the answer comes use
  `untitled-<YYYY-MM-DD>` as the task id. The record may stay there; add the task id to it when it arrives.
- **A project that squash-merges** loses the commit that proves the hypotheses came first. Name another
  place for the records before the first dry run.
- **A public project** keeps its records wherever it keeps working notes it does not publish. With none,
  stop and ask where they go. In a repository someone else owns, ask before adding a `dry-runs/` folder to
  it.
- **The record lives in another repository** than the change. Run the gate commits in the record's
  repository and `fingerprint.sh` in the change's, giving the record's absolute path, which it skips.
- **A commit refused** by a hook, a sandbox or a permission. Stop, record the refusal as it came, run
  nothing and report it to the requester.
- **`scratch-copy.sh` cannot write to `.git`**, as in a sandbox or a read-only repository. Copy the project
  folder to scratch outside it by hand, as for a project outside git, and record that step.
- **A project outside git.** Make the copy by copying the project folder to scratch outside it. Send
  the hypotheses to the requester before the run, and cite that message in the record. For step 10, save
  a checksum list of the project folder before the check, such as `find . -type f -exec cksum {} +`, and
  compare it after.
- **The session ends while step 10 waits for the requester.** Commit the record with what step 10 found
  and no findings, and name the copies still in scratch. The next session resumes at step 10 with the answer.
- **The session ends before the check runs.** The next session appends the result to the original record,
  under the same dry run, citing the hypotheses' commit. It opens its own record only for new dry runs.
