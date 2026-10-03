# Sample review

This file shows the form of every report. Load it when you write a report, and match its order and wording.

Every report opens with the stars, the total and the two subtotals. Each line that lowered the score comes next, with
its file, line, question, note and sources; a script check also names its rule. Then come the checks and ratings by
section, the fit with neighbouring files, which does not count towards the score, and the formula. Source keys refer
to `bibliography.md`.

## Contents

The file holds three sections:

- persona reviewed, the subagent file the example reviews;
- report, the report the script printed for it; and
- edge cases, what a report says when the usual form does not fit.

## Persona reviewed

A subagent file, `.claude/agents/helper.md`, in a project whose `CLAUDE.md` is set aside:

```markdown
---
name: helper
description: Reviews pull requests for style problems.
tools: Read, Grep, Edit
---

You review code for style and report what you find.

Never edit files; report what you find in a list.
Rate each finding high, medium or low.
If the scope is unclear, ask.
```

## Report

`report.py render --summary` printed this from the review record; nothing in it was typed by hand.

```text
Summary: 1 persona reviewed, lowest total first; 1 file set aside
.claude/agents/helper.md   subagent    ★★★☆☆ (3)     55 out of 98
CLAUDE.md                  set aside   project instructions: context for the agent, not a dedicated persona
```

```text
★★★☆☆ (3)
Total: 55 out of 98 (111 possible, less 13 that do not apply)
Persona: 30 out of 54
Instruction writing: 25 out of 44

Review: .claude/agents/helper.md (subagent, Claude Code)
Branches: delegated yes (folder); harness Claude Code; settings tools
Files reviewed:
  .claude/agents/helper.md: the persona's main file
Files left out: none

Do not apply:
  Commands given exactly: no command to run
  Shows an example: no instruction to give output in a particular form
  Its own criteria met: no criterion set for the work

Lines that lowered the score
1. .claude/agents/helper.md, line 4: 'tools: Read, Grep, Edit', against line 9: 'Never edit files; report what you find in a list.'
   Bound parts agree with the prose. The settings allow an edit the prose forbids.
   Rule PJ-003. Sources: AN2, AN3
2. .claude/agents/helper.md, line 9: 'Never edit files; report what you find in a list.'
   Enforceable rules enforced. A tools setting without Edit would enforce this, and Edit is granted instead.
   Sources: AN1, OA1, ST4
3. .claude/agents/helper.md, line 11: 'If the scope is unclear, ask.'
   Directions for when nobody answers. Nothing covers a run with no one to ask.
   Sources: RE1
4. .claude/agents/helper.md, line 4: 'tools: Read, Grep, Edit'
   Tools explained. Three tools are named with no word on when to use them.
   Sources: GO3
5. .claude/agents/helper.md, line 3: 'description: Reviews pull requests for style problems.'
   The description says when to choose it. It names a subject and no task.
   Sources: AN3, GO2, OA3, GO3
6. .claude/agents/helper.md, line 7: 'You review code for style and report what you find.'
   An identity that does the work. It states the work and not where it stops.
   Sources: ST2
7. .claude/agents/helper.md, line 10: 'Rate each finding high, medium or low.'
   Terms defined where they are used. The scale is named and never defined.
   Sources: RE1
8. .claude/agents/helper.md, line 10: 'Rate each finding high, medium or low.'
   Answers defined, edge cases included. Nothing says what to return when nothing is found.
   Sources: none, reading alone
9. .claude/agents/helper.md, line 11: 'If the scope is unclear, ask.'
   Instructions an observer can check. Whether the scope is unclear is not something an observer can see.
   Sources: AN1, GO3
10. .claude/agents/helper.md, line 9: 'Never edit files; report what you find in a list.'
    What to do, not what to avoid. It says what to avoid, not what to do instead.
    Sources: AN5
11. .claude/agents/helper.md, line 9: 'Never edit files; report what you find in a list.'
    Reasons given. The rule gives no reason.
    Sources: AN5

Persona
A dedicated persona                        yes 1
Pointers carry their triggers              yes 1
Bound parts agree with the prose           no  0
Permissions fit the job                    yes 1
Needs no context it is not given           yes 1
Leaves the harness's work to the harness   yes 1
Enforceable rules enforced                 no  0
No procedure for one kind of task          yes 1
No facts the project already holds         yes 1
No pressure from consequences              yes 1
One job                                    yes 1
Declares its tools                         yes 1
States its output                          yes 1
Boundaries in three tiers                  yes 1
Rules held in the persona                  6 of 6   always
Directions for when nobody answers         0 of 6   never
Rules used in every act come first         6 of 6   always
Tools explained                            0 of 6   never
Commands given exactly                     does not apply
The description says when to choose it     2 of 6   fair
An identity that does the work             4 of 6   very good

Instruction writing
No time-sensitive statements               yes 1
Consistent with itself                     yes 3
Nothing said twice                         yes 1
Leaves known things unsaid                 yes 1
Plain emphasis                             yes 1
No placeholders                            yes 1
Shows an example                           does not apply
Terms defined where they are used          0 of 6   never
Answers defined, edge cases included       3 of 6   about half the time
Its own criteria met                       does not apply
Instructions an observer can check         4 of 6   usually
What to do, not what to avoid              4 of 6   usually
Reasons given                              0 of 6   never
Each instruction stands alone              6 of 6   always

Fit with neighbouring files, apart from the score
1. CLAUDE.md, line 6: 'Rate each change as small, medium or large in the pull request.'
   The project rates changes on its own scale, beside the persona's high, medium or low.

Formula: each check counts its weight or 0, and each rating its points; Consistent with itself, Bound parts agree with the prose and Enforceable rules enforced weigh 3, every other check 1; persona 30 out of 54, instruction writing 25 out of 44, total 55 out of 98.
At equal weights: 53 out of 92.
Stars: 55 ÷ 98 × 5 = 2.81, to the nearest half star.
A score does not predict how the agent will behave. The quoted lines are what to act on.
For secrets, hook scripts and server settings, use a configuration or security linter.
```

```text
Set aside: CLAUDE.md (project instructions)
Project instructions: context for the agent, not a dedicated persona.
```

## Edge cases

A report says so plainly when:

- the file is empty, with no stars and no total;
- part of the file cannot be read, with the part skipped and a review of the rest;
- files load with the persona, with each one named under 'Files reviewed:' and its reason;
- nearby files may belong to the persona and nobody can say, with each one named under 'Files left out:' and its
  reason; and
- nothing lowered the score, with the line 'Nothing was found.' in place of the quoted lines.
