# persona-judge

[![Licence: MIT](https://img.shields.io/badge/licence-MIT-blue.svg)](../LICENSE)
![Version](https://img.shields.io/badge/version-0.1.0-green.svg)
![Platforms](https://img.shields.io/badge/platforms-Claude%20Code%20%7C%20Codex%20%7C%20Gemini%20CLI-lightgrey.svg)
![Format](https://img.shields.io/badge/format-Agent%20Skill-green.svg)

A skill that reviews dedicated agent personas: the files that define an artificial intelligence (AI) agent of its own,
with its own instructions and often its own tools, such as a subagent or a custom agent.

For each persona, *persona-judge* returns a score out of five stars and quotes every line that lowered it. A summary table
leads when it reviews a whole project. [The sample review](#sample-review) shows what a report holds.

## Reasons to review a persona

An agent does what its instructions lead it to do, and how a file reads tells you little about how the agent will
behave:

- **Wording changes behaviour.** Controlled experiments show 'that prompt wording can change reasoning and
  verification behavior without changing the task' (Weinberger and Hozez 2026).
- **A persona can push an agent off course.** Task-irrelevant persona cues degraded agent performance by up to 26.2%
  (Cao, Sun and Yue 2026).
- **More detail is not always better.** 'Increasing system-prompt constraint specificity does not monotonically
  improve correctness' (Cheng and Mastropaolo 2026).
- **Standing instructions bind weakly.** Under long policy documents, the best agent passed 36.2% of trials. Agents
  also 'report compliance they did not achieve' (Panavas et al. 2026).
- **A total alone predicts little.** While this skill was built, two versions of one persona scored one point apart
  on a skill rubric. Blind judges still preferred the same version in every pair.

So *persona-judge* quotes every line that lowered the score: the stars summarise, and the lines show what to act on. The full sources, with the date each was read, are in
`skill/references/bibliography.md`.

## Scoring well

A persona file holds instruction: prose the model reads and decides whether to follow, with nothing to enforce it. It
may also hold bound parts, which the harness enforces: settings (the tools the agent may use, its permission mode) and
code the file names to run. So a rule counts only if the agent reads it. A setting only if it agrees with the
prose.

A file scores well when:

- every rule the agent needs is written in the file itself;
- each scale, term and set of answers is defined where it is used;
- each pointer to another file says when to open it and gives its path;
- each instruction to ask says what to do when nobody answers;
- each set of answers says what each answer means and what to return for empty or partial work;
- the file meets the criteria it sets for the agent's work;
- its settings agree with its prose;
- it leaves to the harness what the harness already does;
- it spends no lines on what the model already knows;
- a rule that must hold every time sits in a hook or setting, not in prose alone;
- it carries no procedure that only one kind of task needs, and no facts the project already holds;
- it says nothing that goes out of date by itself;
- its opening identity states the work, not praise; and
- a subagent's description names the requests it is for, in words a user would type.

## Losing marks

Every line that works against the agent costs marks. A file loses them for:

- two statements that contradict each other, since the model may follow either;
- the same instruction said twice, where the copies can drift apart;
- a rule kept only in a file the agent is pointed to;
- a named scale or term with no definition, which the agent fills in for itself;
- an instruction to ask, with nothing for a run where nobody answers;
- a setting that permits what the prose forbids, such as an editing tool in a file told never to edit;
- an instruction to do what the harness already does, such as reading a file it loads anyway;
- an explanation of what the model already knows;
- a must-always rule, such as 'Never push to main', left to prose with no hook or setting behind it;
- a procedure for one kind of task, or a copy of the project's directory layout;
- a statement that dates, such as 'until the migration finishes';
- praise in place of an identity, such as 'You are a world-class expert'; and
- a description that names a role and no task, such as 'A helpful reviewer'.

The full questions, their scales and the scoring formula are in `skill/references/review-questions.md`.

## Other tools

*Persona-judge* reviews the file and leaves it as it is. Other tools cover the rest:

- a skill reviewer such as `skill-judge`, for skills and commands an agent takes up for one task;
- a configuration or security linter, for secrets, hook scripts and server settings;
- the harness's own guidance, for project instructions files such as `CLAUDE.md` and for output styles, which set
  context and tone and are not personas;
- a run of the agent on a real task, for how it behaves; and
- you, for the next draft, since *persona-judge* offers no wording of its own.

`skill/references/persona-boundaries.md` sets out each neighbour of a persona and where its review belongs.

## Sample review

Every report leads with the stars and the total, as 'x out of y'. The lines that lowered the score come next, each
quoted with its question. Last come the yes or no for every check and the points for every rating.
`skill/references/sample-review.md` shows a full report.

## Users

*Persona-judge* suits:

- anyone who defines subagents or custom agents and wants to know which lines will not hold;
- teams that keep several agents and want each one's instructions reviewed the same way; and
- anyone working out why an agent ignores a rule it was given.

## Install

```bash
./setup.sh --dry-run   # show what would change
./setup.sh             # link into Claude Code, Codex and Gemini, where installed
```

On Windows, for Claude Code, run `powershell -ExecutionPolicy Bypass -File setup.ps1 -DryRun`, then run the
command again without `-DryRun`. Neither script overwrites anything. `--uninstall` (`-Uninstall` on Windows) removes
only the links the script made.

## Use

Ask your agent to review its instructions, or type `/persona-judge`. It reviews every persona file in the project. To
review less, name files or folders, or paste instruction text into the session. Each review runs in a subagent
briefed with `skill/agents/reviewer.md`, so your session's own instructions stay out of it.
