# The brief

Every member gets a brief: one Markdown file, whose absolute path is the first path its prompt names. The ledger's
capture takes the first readable file a prompt names as the brief and reads its front matter. If another file comes
first, the record reads that file instead and says the dispatch was never triaged.

A brief that breaks any rule below is not sent.

## Front matter

| Key | Holds |
|---|---|
| `persona-name` | the persona the brief is for: the recipient, never the author |
| `act_kind` | the kind of act the part asks for, as the act decision read it |
| `task` | the task's id |
| `member` | the member's id, as the plan issues it. Ids are unique within a session |
| `attempt` | the attempt number: `1` for the first dispatch, one more for each re-dispatch |

The keys above are the skill's own names. A project with its own names maps them in the ledger's settings, under
`frontmatter`. A project that keeps its keys under a prefix maps them like this:

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

<!-- BUILD: confirm the default key names for member and attempt with the capture change, which reads them. -->

## Body

The body holds these parts, in this order.

**1. The opening instruction.** The body opens by telling the member to read its persona's file and the memory that
file's folder `index.md` lists, before it does anything else. Name each by its absolute path:

```markdown
Before your first act, read your persona's file, `<absolute path>`, and the memory its folder's `index.md`,
`<absolute path>`, lists.
```

**2. The task.** What the part asks for, its inputs by absolute path, and what done looks like.

**3. Below the line, where it applies.** Where the persona decision found no persona adequate, the body says so in a
sentence of its own, with the adequacy probability and the line:

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

- Every path is relative to its repository's root. Never give the main checkout's absolute path. A writer runs in
  its own worktree, and a relative path lands there.
- All the paths lie in one repository. A part whose writes span two repositories is split into one member for each.
- A folder prefix ends with `/`, and covers everything under it.

**5. The output section instruction.** The instruction in the `subagent-return` skill's
`references/brief-instruction.md`, copied word for word. That file is its one home.

## Paths that do not resolve

Before the brief is sent, every path in it is resolved: the persona's file, its memory index, each input and each
existing write-set file. A path that does not resolve stops the brief, and the parent is told which path failed.

A write-set path may name a file the member is to create. It does not need to exist, but its repository does.

## The worktree

A writer's worktree must hold every write-set file that exists in the main checkout, at the state the parent sent it
against. A worktree branches from a commit and carries no uncommitted or untracked file. So before the dispatch:

- any write-set file the parent has changed and not committed is committed first, by path; and
- the skill compares each write-set file's state in the main checkout with its state at the commit the worktree will
  branch from. Where they differ, the dispatch is refused with the reason, before it is sent.

Inputs other than the write set, such as the persona's file and memory, may be read from the main checkout by
absolute path.
