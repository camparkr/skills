# persona-judge

[![Licence: MIT](https://img.shields.io/badge/licence-MIT-blue.svg)](../LICENSE)
![Version](https://img.shields.io/badge/version-1.0.0-green.svg)
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
  on a skill rubric. Blind judges still preferred the same version in every pair run on Claude Code.
  [`evidence.md`](evidence.md) summarises that record: how it was gathered, what it found and where it falls short.

So *persona-judge* quotes every line that lowered the score: the stars summarise, and the lines show what to act on. The
full sources, with the date each was read, are in `sources.md`.

## How the reviewer scores

*Persona-judge* asks 35 questions of each persona: 21 on what a persona must do, and 14 on how any instruction reads.

**Checks and ratings.** A question is a check or a rating, by what it asks.
- A check scores yes or no, because one instance settles it. Most checks look for a fault: a placeholder, two
  statements that contradict each other, a reference to a conversation the agent never sees. One instance is the
  fault, and how many there are adds nothing the quoted lines do not show. The rest look for something a persona must
  have, such as its list of tools or what it returns: it has it or it does not.
- A rating gives a point from 0 to 6 where a question applies across many places and the degree matters, such as how
  many of a file's rules give their reason.

**Which questions apply.** A question that cannot apply to a persona is left out of its total, and the report names it
with the reason, so the full scale of 111 points is always in view. A persona that is never handed tasks by another
agent is not asked what its description says about when to choose it, for instance. The scripts decide most of this
from the file itself, so two reviews of one file leave out the same questions.

**A check and the rating that follows it.** Where a rating measures how well a persona does what a check finds it does,
the rating applies only when the check is met. A persona that declares no tools loses that check and is not then rated
on explaining them, so one missing list costs once, not twice.

**Weights.** Three checks count 3 points, not 1, because one instance of each is evidence that the agent may not do
what the file says:
- two statements that contradict each other, because the model may follow either;
- a setting that permits what the prose forbids, because the harness enforces the setting; and
- a must-always rule left to prose with no hook or setting behind it, because a rule left to prose binds weakly.

Each weight rests on vendor guidance or a published study, cited in `skill/references/grounding.md`.
Research on scoring finds equal weights a sound default, and different weights defensible only where their reason is
stated, so the report also gives the total at equal weights. Two other faults that can break an agent, a pointer to a
file with no word on when to read it and a reliance on context the agent never sees, count 1 until a study measures
their effect.

**Measured against the vendors' own definitions.** Anthropic, OpenAI, Google and GitHub each describe what a persona
has: its own instructions, tools, permissions and context, a description that decides when it is chosen, and a result
it returns. `vendor-terms.md` maps each of these to the questions that ask about it.

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

The full questions, their scales and the scoring formula are in
`skill/references/questions/`.

## How it differs from other persona checks

Linters for agent instruction files check form: front matter, length, token budget, references to files that do not
exist, duplicated text, contradictory 'always' and 'never' lines, and secrets. AgentLinter, agenteval's lint rules,
cclint and prompt-lint are examples. Claude Code's `/doctor prompt-audit` looks for instructions written for older
models, references to files or commands that do not exist, and files that contradict each other, and proposes edits.

*Persona-judge* checks those faults too, without a model, and then reviews what a linter cannot read:

- where each rule the persona applies in every act sits: in the text the agent loads, or only in a file it points to;
- whether each pointer says when to read its file;
- whether the description tells the harness when to choose the agent;
- whether the settings the harness enforces agree with the prose, such as a persona told never to edit files whose
  tool list includes an editing tool;
- whether the persona's remit fits the other personas beside it, reported apart from the score; and
- the persona as a whole: its main file and every file it loads.

It scores each persona out of the points that apply, by a formula the report states, quotes every line that lowered
the score and names the source behind each question. It runs in its own agent, changes no file and proposes no
wording, so the review stays separate from the next draft. In a survey of public tools made on 30 September 2026, none
checked where a persona's rules sit, and none was a judge of personas rather than a linter of files.

## Other tools

*Persona-judge* reviews the file and leaves it as it is. Other tools cover the rest:

- a skill reviewer such as `skill-judge`, for skills and commands an agent takes up for one task;
- a configuration or security linter, for secrets, hook scripts and server settings;
- the harness's own guidance, for project instructions files such as `CLAUDE.md` and for output styles, which set
  context and tone and are not personas;
- a run of the agent on a real task, for how it behaves; and
- you, for the next draft, since *persona-judge* offers no wording of its own.

`skill/references/persona-boundaries.md` sets out what each term means in a review, and how to tell a
persona from each neighbour. [`definitions.md`](definitions.md), beside this file, sets the terms in an analogy from the
Greek theatre, with the sense of each Greek word.

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

The skill's scripts need Python 3.11 or later, run as `python3`, and nothing beyond its standard library. Check with
`python3 --version`. On Windows, the Microsoft Store's Python provides `python3`; the python.org installer provides
`py` and `python` only, so add `python3` to the path or use the Store's Python.

**Claude Code, as a plugin.** The plugin installs the skill and the reviewer as an agent whose tools Claude Code
enforces, with a hook that lets the reviewer's shell run only the skill's scripts:

```text
/plugin marketplace add camparkr/skills
/plugin install persona-judge@camparkr-skills
```

**Codex and Gemini CLI, or Claude Code without the plugin.** From this folder:

```bash
./setup.sh --dry-run   # show what would change
./setup.sh             # link the skill, and for Codex and Gemini CLI the reviewer agent, where each is installed
```

Codex runs the reviewer agent in a read-only sandbox, unless the session that starts it runs with `--yolo` or a wider
`/permissions` setting, which Codex applies to the agent too. Gemini CLI gives it read, list, search and shell tools and
none that writes a file. For Gemini CLI, `setup.sh` also installs a policy file,
`~/.gemini/policies/persona-judge.toml`, that lets the reviewer agent's shell run only `python3 --version` and the
skill's scripts, and refuses its other commands, in YOLO mode too; Gemini CLI reads policy files only from that folder,
not from a project. The policy refuses `<` and `>` in a command, apart from the opening of the one heredoc that passes a
record, so in Gemini CLI save pasted text that holds them to a file and name the file. On Windows, for Claude Code, run
`powershell -ExecutionPolicy Bypass -File setup.ps1 -DryRun`, then run the command again without `-DryRun`. Neither
script overwrites a file it did not make; `setup.sh` refreshes its own policy file when the skill moves. `--uninstall`
(`-Uninstall` on Windows) removes only the links and the policy file the script made.

## Use

Ask your agent to review its instructions, or type `/persona-judge`. It reviews every persona file in the project. To
review less, name files or folders, or paste instruction text into the session. Each review runs in its own agent:
the installed reviewer where there is one, or a subagent briefed with `skill/reviewer.md`, so your
session's own instructions stay out of it. Only the installed reviewer has a setting that stops it changing a file;
a subagent briefed with `reviewer.md` holds to that rule by its instructions alone, and the skill tells you so.
