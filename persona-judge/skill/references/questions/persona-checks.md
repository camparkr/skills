## Persona questions

### Checks

**A dedicated persona** (*reading*). The file defines an agent of its own, a persona as `scales.md` defines it. It is
not project instructions setting the agent's context, nor an output style setting its tone. It is answered first, as
'Which questions apply' sets out. *Scores 0 on:* a `CLAUDE.md` of build commands and conventions. Sources: GH4, GO2,
AN6.

**Pointers carry their triggers** (*script*). Every reference to another file says when to read it and gives its
path. *Scores 0 on:* 'See also `notes.md`.' Sources: RE1.

**Bound parts agree with the prose** (*script*, weight 3). No setting the harness applies permits what the prose forbids
or forbids what the prose requires. *Scores 0 on:* a file told never to edit files whose `tools` include an editing
tool. Applies when the file holds settings ('Which questions apply'). Sources: AN2, AN3.

**Permissions fit the job** (*reading*). Where the persona sets its own permissions, such as Claude Code's
`permissionMode` or Codex's `sandbox_mode`, they allow no more than its job needs. Applies when the file holds settings.
*Scores 0 on:* a reviewer told only to report on a change, whose `permissionMode` is `acceptEdits`. Sources: OA2, AN3.
The setting does not always bind: Claude Code ignores it when the main conversation runs in `bypassPermissions`,
`acceptEdits` or auto mode (AN3). So this check reads what the file asks for, and 'Enforceable rules enforced' asks
whether a rule that must hold is enforced.

**Needs no context it is not given** (*reading*). The persona refers to nothing from a conversation it does not see: no
earlier discussion, decision or request that its own files and its brief do not hold. *Scores 0 on:* 'Apply the approach
we agreed earlier.' Sources: AN3, GO2.

**Leaves the harness's work to the harness** (*script*). The file asks for nothing its harness already does, such as
reading a file the harness loads anyway or using tools the agent already has. A table of each harness's defaults drives
the check. *Scores 0 on:* 'Read AGENTS.md before you start', in a file loaded beside it. Sources: AN4, AN1.

**Enforceable rules enforced** (*reading*, weight 3). A rule that must hold every time, and that a hook or setting could
enforce, is not left to prose alone. To decide, ask two questions of each rule. Must it hold every time: does the file
state it without exception, and would one breach leave something the agent cannot take back, such as a changed file, a
push or a deletion? Could it be enforced: does the persona's harness offer a setting or hook that stops the act, such as
leaving a tool out of `tools` or a hook that refuses the command? When both answers are yes and nothing in the persona's
files enforces the rule, the check scores 0. A rule about judgement, such as how to rate a finding, has no setting that
could enforce it, so this check leaves it alone. *Scores 0 on:* 'Never push to main', with no setting or hook behind it.
A setting that closes some routes and leaves another open leaves the rule to prose: a tools list without Edit or Write
that still grants Bash scores 0 on 'Never change code'; in this skill's test runs, one review in four gave such a
persona full marks. Sources: AN1, OA1.

**No procedure for one kind of task** (*reading*). The file holds no multi-step procedure that only one kind of task
needs. *Scores 0 on:* a 12-step release checklist in a project's standing instructions. Sources: AN1, GH1.

**No facts the project already holds** (*reading*). The file does not restate what the agent can read from the project,
such as its directory layout, its dependencies or its architecture. *Scores 0 on:* a copied directory tree. Sources:
AN1.

**No pressure from consequences** (*reading*). The file does not tell the agent what its output will cause for itself or
for others, as a lever on the output. *Scores 0 on:* 'Low scores will get this model retrained.' Sources: ST6.

**One job** (*reading*). A delegated persona gives the agent one job. Applies to a delegated persona ('Which questions
apply'). *Scores 0 on:* a subagent told to review code, write the tests and update the changelog. Sources: OA2, GO1.

**Declares its tools** (*script*). A delegated persona names the tools it may use, so it does not inherit every tool by
leaving the list out. Applies to a delegated persona whose path names a harness, since the harness decides what a
missing list gives; not to a Codex custom agent, whose file has no tools field (OA2). *Scores 0 on:* a subagent
definition with no `tools` field. Sources: OA2, GO2, GH2.

**States its output** (*reading*). A delegated persona says what the agent returns and in what form. Applies to a
delegated persona. *Scores 0 on:* a subagent told to 'review the change' with no word on what it hands back. Sources:
GO3, OA3.

**Boundaries in three tiers** (*reading*). The file says what the agent always does, what it asks about first and what
it never does. *Scores 0 on:* a file with rules to follow and nothing on what needs asking first. Sources: GH3.
