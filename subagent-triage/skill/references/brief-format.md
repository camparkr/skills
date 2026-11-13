# The brief

Every member gets a brief: one Markdown file, whose absolute path is the first path its prompt names. The ledger's
capture takes the first readable file a prompt names as the brief and reads its front matter. If another file comes
first, the record reads that file instead and says the dispatch was never triaged.

The brief writer, `scripts/brief.py`, writes each brief to this format. It refuses a brief that breaks any rule
below, gives the reason and writes nothing.

## Front matter

| Key | Holds |
|---|---|
| `persona-name` | the persona the brief is for: the recipient, never the author |
| `act_kind` | the kind of act the part asks for, as the act decision read it |
| `task` | the task's id |
| `member` | the member's id, as the plan issues it. Ids are unique within a session, and hold only letters, digits, `.`, `_` and `-`, beginning with a letter or digit, so a pending file's name can keep them |
| `attempt` | the attempt number: `1` for the first dispatch, one more for each re-dispatch |

The keys above are the ledger capture's default names, which it reads unless its settings say otherwise. A project
with its own names maps them in the ledger's settings, under `frontmatter`. A project that keeps its keys under a
prefix maps them like this:

```json
{
  "frontmatter": {
    "persona-name": "x-mythos.figure",
    "act_kind": "x-mythos.thiasos",
    "task": "x-mythos.task_id",
    "member": "x-mythos.member",
    "attempt": "x-mythos.attempt"
  }
}
```

The writer writes each value at the key the settings name for it, and refuses where they name no key for `member` or
`attempt`. It writes the kind as the ledger's `kind_names` map spells it, where the settings name one, and refuses a
kind the ledger's list of kinds does not hold.

## Body

The body holds these parts, in this order.

**1. The opening instruction.** The body opens by telling the member to read its persona's file and the memory that
file's folder `index.md` lists, before it does anything else. Name each by its absolute path:

```markdown
Before your first act, read your persona's file, `<absolute path>`, and the memory its folder's `index.md`,
`<absolute path>`, lists.
```

The memory index is the `index.md` in the persona file's own folder.

**2. The task.** What the part asks for, its inputs by absolute path and what done looks like. The writer takes it
from the task file it is given, less any front matter. The task holds no `## Write set` section of its own, since the
capture would read that as the write set.

**3. Below the line, where it applies.** Where the persona decision found no persona adequate, the body says so in a
sentence of its own, with the adequacy probability and the line. The writer fills it from the `below_line` value in
the member's pending triage file:

```markdown
No persona was found adequate for this part. You were the closest, at <probability> against a line of <line>
(definition version <version>). If the part asks for work your role does not cover, say so in your report.
```

**4. The write set.** A section headed `## Write set`, one path or folder prefix a line, or the single word `none`
for a read-only member:

```markdown
## Write set

src/report/
docs/report.md
```

- Every path is relative to its repository's root. Never give the main checkout's absolute path, or a path that
  begins with `~` or leaves the repository. A writer runs in its own worktree, and a relative path lands there.
- All the paths lie in one repository, the top folder of a git working tree. A part whose writes span two
  repositories is split into one member for each.
- A folder prefix ends with `/`, and covers everything under it.

**5. What the work is checked for.** The instruction in the `subagent-return` skill's
`references/brief-instruction.md`, copied word for word, with its two placeholders filled from the return check's
settings as that file says. It tells the member what to write, where, with what front matter and how to end its
report. That file is its one home, and says which check each part of it keeps from failing. The writer refuses a
brief where the settings name no front-matter validator, since the instruction could not be filled.

The writer reads the opening instruction and the below-the-line sentence from the fenced blocks under parts 1 and 3
above, so their wording has one home. Keep each label line and its fenced block together when you change them.

## Which check each field keeps from failing

The `subagent-return` skill checks every member's report as it comes back. The brief's own fields keep failures in three of its
checks from arising:

| Field or rule | Keeps from failing |
|---|---|
| The brief's path is the first path the prompt names | check 3, the call is on the ledger: the check finds the brief by that rule, and a dispatch whose first file is not a brief has no member to match |
| `member` | check 3, which keys the dispatch record by agent id, member and attempt. Without it, check 1 reads `not_applicable (no member brief)` and the report's output section is never read |
| `attempt` | check 3, so a re-dispatch's record is matched to its own attempt and not an earlier one |
| `## Write set`, each path relative to the repository's root | check 4, writes stay in the write set: the check compares every change in the worktree against these paths. A path given from the main checkout would match nothing in the worktree |
| `none` for a read-only member | check 4 and check 1: a read-only member may write only to the scratch folder, and owns no output file |

## Paths that do not resolve

Before the brief is written, its paths are resolved: the persona's file, its memory index and each absolute path the
task names. A path that does not resolve stops the brief, and the parent is told which path failed.

A write-set path may name a file the member is to create. It does not need to exist, but its repository does.

## What else stops a brief

The writer also refuses a brief, writing nothing, where:

- the member id holds a character other than those the front matter table allows, or the attempt is not a whole
  number from 1;
- a file already stands at the brief's path: a brief is never overwritten, so a re-dispatch gets a new one; or
- the member's pending triage file names another persona or another kind than the brief. Record a persona override
  in the pending file first.

Before it writes, it reads the brief back with the ledger capture's own readers: the front matter must give the
member and attempt, and the write-set section the paths given.

## The worktree

A writer's worktree must hold every write-set file that exists in the main checkout, at the state the parent sent it
against. A worktree branches from a commit and carries no uncommitted or untracked file. So before the dispatch:

- any write-set file the parent has changed and not committed is committed first, by path; and
- the worktree check, `scripts/worktree_check.py`, compares each write-set file's state in the main checkout with its
  state at the commit the worktree will branch from: by default `head`, the local `HEAD`, or with `--base remote`
  the remote's default branch (`origin/HEAD`), where the harness branches worktrees from that. Where they differ,
  or a file is on one side only, the dispatch is refused with the reason, naming each file, before it is sent.

The check refuses too a write set whose paths lie in two repositories, one nested in the other. A file the write set
names that exists on neither side is one still to be created, and passes. A read-only member is not checked.

Inputs other than the write set, such as the persona's file and memory, may be read from the main checkout by
absolute path.
