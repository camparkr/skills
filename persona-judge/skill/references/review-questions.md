# Review questions

The questions *persona-judge* asks of a persona file and the formula that turns the answers into a score. Load this
file at the start of every review. Each source is cited by its key in `bibliography.md`, which gives its full
reference and the date it was read.

A persona is a dedicated agent: a named specialist with its own instructions, and often its own tools and context,
such as a subagent or a custom agent. It holds instruction, which the model reads and nothing enforces, and it may
hold bound parts: settings the harness applies (the tools the agent may use, its permission mode) and code the file
names to run. A persona can be spread over several files, and the review covers all of them. A project instructions
file, such as `CLAUDE.md`, is context: it can contain a persona's text, but it is not a persona. An output style sets
the main agent's tone and is not a persona either.

## Contents

The file holds six sections:

- a review, not a certification;
- checks and ratings, the two kinds of question and their scales;
- which questions apply, and their weights;
- persona questions, 21 questions on what a persona file must do because it frames every act;
- instruction-writing questions, 14 questions on how any instruction reads; and
- score, the two subtotals, the total, the stars and the order of the report.

## A review, not a certification

The review quotes lines and scores them. It passes nothing, fails nothing and approves nothing: what to do with the
score is the reader's decision. Every question is answered from the file under review alone. Whether the file fits
the other files beside it is reported apart from the score, because a question that needs another file is a
question of fit, not of the file.

## Checks and ratings

Some questions have one right answer that a script or a careful reading settles. Others are judged across every
place in the file they apply to.

**Checks** are met or not. A check is met when nothing in the file contradicts it, and scores its weight, shown as
'yes 1', or 'yes 3' for the three weighted checks; it is not met when anything does, shown as 'no 0'. Checks marked
*script* run in `check.py` from a table, without a model, and give the same answer on every run. Checks marked
*reading* are answered by the reviewer, who quotes the line behind every 0.

**Ratings** are judged on a seven-point scale chosen for the answer the question seeks, from Brown's examples of Likert
scales (SC1). Two are used.

### Frequency scale

*How many places meet the question.* The reviewer lists every place the question applies, quotes each one, counts how
many meet it and rates the share:

| Point | Word | Share of places that meet the question |
|---|---|---|
| 6 | always | all |
| 5 | almost always | over 80%, below 100% |
| 4 | usually | over 60%, up to 80% |
| 3 | about half the time | 40% to 60% |
| 2 | seldom | 20%, below 40% |
| 1 | almost never | more than none, below 20% |
| 0 | never | none |

### Quality scale

*How well the file does something.* The reviewer rates on Brown's seven-point quality scale against the anchors the
question states for each point and quotes the lines behind the rating:

| Point | Word |
|---|---|
| 6 | exceptional |
| 5 | excellent |
| 4 | very good |
| 3 | good |
| 2 | fair |
| 1 | poor |
| 0 | very poor |

The words are Brown's: the quality scale is the seven-point quality scale, and the frequency words come from the
frequency and likelihood lists. The share bands and the anchors are this skill's own choice, and no study fixes them.

**Why a question is a check or a rating.** A check fits where one instance settles the question. Most checks look for a
fault, such as a placeholder, a contradiction or a reference to a conversation the agent never sees: one instance is
the fault, and how many there are adds nothing the quoted lines do not show. The others look for something the persona
must have, such as its tools or its output; it has it or it does not. A rating fits where the question applies across
many places and the degree matters, as for the reasons behind its rules.

## Which questions apply, and their weights

All 35 questions are asked of every file, and 111 points are possible: 60 in the persona section and 51 in instruction
writing. A question that does not apply to a persona leaves the total, and the report names it with its reason, so the
points possible are always 111 less those it names. Which questions apply is decided from the file in this order.

**The root: a dedicated persona.** 'A dedicated persona' is answered first. A file that scores 0 on it is set aside
and answers no other question.

**Three branches, read by the scripts.** `find.py` and `check.py` read each from the file, so every reader gets the
same answer:

| Key | Branch | How it is read | When the answer is no, these do not apply | Reason printed |
|---|---|---|---|---|
| delegated | Is the persona delegated, chosen by another agent for a task? | its folder, or front matter holding both `name` and `description` | One job; States its output; The description says when to choose it | not delegated |
| harness | Does its path name a harness? | its folder, such as `.claude/agents/` or `.github/agents/` | Leaves the harness's work to the harness; Declares its tools | path names no harness |
| settings | Does it hold settings that grant or restrict what the agent can do? | a field `tools`, `disallowedTools`, `permissionMode`, `sandbox_mode`, `hooks` or `mcpServers` in its front matter | Bound parts agree with the prose; Permissions fit the job | holds no settings |

**Questions about what the file holds.** Ten ratings and one check apply only where the file holds their subject.
Each states its test, and the reviewer quotes the line that meets it, or says that no line does:

| Question | Applies when the file holds | Reason printed |
|---|---|---|
| Tools explained | a tool named, in a setting or in the prose | no tool named |
| Commands given exactly | a command the file tells the agent to run | no command to run |
| Directions for when nobody answers | an instruction to ask, wait or confirm | no instruction to ask, wait or confirm |
| Answers defined, edge cases included | a set of answers, a scale or a choice the agent must make | no set of answers, scale or choice |
| Its own criteria met | a criterion the file sets for the agent's work | no criterion set for the work |
| Shows an example | an instruction to give output in a particular form | no instruction to give output in a particular form |
| Rules held in the persona | a rule the agent applies in every act | no rule applied in every act |
| Rules used in every act come first | a rule the agent applies in every act | no rule applied in every act |
| Terms defined where they are used | a scale, a set of answers or a term the rules name | no scale, set of answers or term named |
| What to do, not what to avoid | an instruction about the agent's output | no instruction about the output |
| Reasons given | a rule that limits what the agent does | no rule that limits the agent |

Every other question applies to every dedicated persona.

**A check and the rating that follows it.** Where a rating measures how well the file does what a check finds it does,
the rating applies only when the check scores 1. 'Tools explained' follows 'Declares its tools': a persona that
declares no tools loses that check's point and is not rated on explaining them, so one missing list costs once. Where
'Declares its tools' does not apply, 'Tools explained' applies when the file names a tool. Scoring one fault as both a
check and a rating would count it seven times over.

| Rating | Follows check | Reason printed |
|---|---|---|
| Tools explained | Declares its tools | 'Declares its tools' scored 0 |

**A harness without the field.** Where a harness's files cannot hold what a check looks for, the check does not apply
to them:

| Question | Harness | Reason printed | Source |
|---|---|---|---|
| Declares its tools | Codex | Codex has no tools field | OA2 |

**Weights.** Three checks count 3 points, not 1, because a single instance of each is evidence that the agent may not
do what the file says:

| Check | Why it weighs more | Evidence |
|---|---|---|
| Consistent with itself | the model may follow either of two contradictory statements | vendor rule (AN1, GH1); conflict studies (ST7, ST8) |
| Bound parts agree with the prose | the harness enforces the setting, whatever the prose says | vendor rule (AN2, AN3) |
| Enforceable rules enforced | a rule left to prose binds weakly | study (ST4); vendor rule (AN1) |

Every other check counts 1 and every rating 0 to 6. Weights are value choices: research on scoring finds equal weights
a robust default, and differential weights defensible only where their reason is stated (SC2, SC3). These three rest on
the evidence above. Two other faults that can break an agent, a pointer with no trigger and a reliance on context the
agent never sees, count 1 until a study measures their effect. The report gives the total at equal weights beside the
weighted total, so a reader sees how much the weights move it.

## Persona questions

These follow from what a persona file is: a file loaded to frame every act of an agent, with settings its harness
enforces, beside a harness and other files.

### Checks

**A dedicated persona** (*reading*). The file defines an agent of its own: a named specialist with its own instructions,
and often its own tools and context. It is not project instructions setting the agent's context, nor an output style
setting its tone. Answered first. A file that scores 0 is set aside with that reason and not scored on the other
questions, which assume a persona. *Scores 0 on:* a `CLAUDE.md` of build commands and conventions. Sources: GitHub, a
custom agent is a 'Specialist persona with its own instructions, tool restrictions, and context', and custom
instructions are 'Always-on context' (GH4); Google, 'Each subagent has its own system prompt and persona' (GO2);
Anthropic, an output style 'sets Claude's role, tone, and response format', and has no tools or context of its own
(AN6).

**Pointers carry their triggers** (*script*). Every reference to another file says when to read it and gives its
path. *Scores 0 on:* 'See also `notes.md`.' Evidence: in the record kept while this skill was built, a pointer that
said when to open its file was followed in three runs of three, and an index nothing pointed to was never read.

**Bound parts agree with the prose** (*script*, weight 3). No setting the harness applies permits what the prose forbids
or forbids what the prose requires. *Scores 0 on:* a file told never to edit files whose `tools` include an editing
tool. Applies when the file holds settings ('Which questions apply'). Sources: Anthropic, 'Permission rules are enforced
by Claude Code, not by the model' (AN2); the subagent fields `tools`, `disallowedTools`, `permissionMode` and `hooks`
(AN3).

**Permissions fit the job** (*reading*). Where the persona sets its own permissions, such as Claude Code's
`permissionMode` or Codex's `sandbox_mode`, they allow no more than its job needs. Applies when the file holds settings.
*Scores 0 on:* a reviewer told only to report on a change, whose `permissionMode` is `acceptEdits`. Sources: OpenAI, a
subagent needs 'a tool surface that matches that job' (OA2); Anthropic, 'If you leave it unset, the subagent inherits
the main conversation's permission mode' (AN3). The setting does not always bind: Claude Code ignores it when the main
conversation runs in `bypassPermissions`, `acceptEdits` or auto mode (AN3). So this check reads what the file asks for,
and 'Enforceable rules enforced' asks whether a rule that must hold is enforced.

**Needs no context it is not given** (*reading*). The persona refers to nothing from a conversation it does not see: no
earlier discussion, decision or request that its own files and its brief do not hold. *Scores 0 on:* 'Apply the
approach we agreed earlier.' Sources: Anthropic, 'Each subagent starts with a fresh, isolated context window. It doesn't
see your conversation history, the skills you've already invoked, or the files Claude has already read' (AN3); Google,
'Each subagent runs in its own isolated context loop' (GO2).

**Leaves the harness's work to the harness** (*script*). The file asks for nothing its harness already does, such as
reading a file the harness loads anyway or using tools the agent already has. A table of each harness's defaults drives
the check. *Scores 0 on:* 'Read AGENTS.md before you start', in a file loaded beside it. Sources: Anthropic, 'Only add
context Claude doesn't already have' (AN4); a `CLAUDE.md` that tells Claude in words to read `AGENTS.md` means 'Claude
sees `AGENTS.md` only if it decides to open the file' (AN1).

**Enforceable rules enforced** (*reading*, weight 3). A rule that must hold every time, and that a hook or setting could
enforce, is not left to prose alone. *Scores 0 on:* 'Never push to main', with no setting or hook behind it. Source:
Anthropic, 'If the instruction is something that must run at a specific point … write it as a hook' and 'To block an
action regardless of what Claude decides, use a PreToolUse hook' (AN1). Also: OpenAI, 'reserve formatting and lint
checks for CI' (OA1).

**No procedure for one kind of task** (*reading*). The file holds no multi-step procedure that only one kind of task
needs. *Scores 0 on:* a 12-step release checklist in a project's standing instructions. Source: Anthropic, 'If an
entry is a multi-step procedure or only matters for one part of the codebase, move it to a skill or a path-scoped
rule' (AN1). Also: GitHub, standing instructions 'should be broadly applicable to most requests' (GH1).

**No facts the project already holds** (*reading*). The file does not restate what the agent can read from the project,
such as its directory layout, its dependencies or its architecture. *Scores 0 on:* a copied directory tree. Source:
Anthropic, the `/doctor` trim 'cuts content Claude can derive from the codebase, such as directory layouts, dependency
lists, and architecture overviews' (AN1). GitHub's blog post above recommends listing the file structure; Anthropic's
trim and this question read it the other way.

**No pressure from consequences** (*reading*). The file does not tell the agent what its output will cause for itself
or for others, as a lever on the output. *Scores 0 on:* 'Low scores will get this model retrained.' Source: judges told
what their verdicts would cause 'reliably soften verdicts', with a peak shift of 9.8 percentage points and 'zero
explicit acknowledgment' of the framing in their reasoning (ST6).

**One job** (*reading*). A delegated persona gives the agent one job. Applies to a delegated persona ('Which questions
apply'). *Scores 0 on:* a subagent told to review code, write the tests and update the changelog. Sources: OpenAI, 'The
best custom agents are narrow and opinionated. Give each one clear job' (OA2); Google, 'Limit scope' (GO1).

**Declares its tools** (*script*). A delegated persona names the tools it may use, so it does not inherit every tool by
leaving the list out. Applies to a delegated persona whose path names a harness, since the harness decides what a
missing list gives; not to a Codex custom agent, whose file has no tools field (OA2). *Scores 0 on:* a subagent
definition with no `tools` field. Sources: OpenAI, 'a tool surface that matches that job' (OA2); in Gemini CLI and
GitHub Copilot an agent with no tool list is given every tool (GO2 and GH2).

**States its output** (*reading*). A delegated persona says what the agent returns and in what form. Applies to a
delegated persona. *Scores 0 on:* a subagent told to 'review the change' with no word on what it hands back. Sources:
Google, an agent's instruction covers 'The desired format for its output' (GO3); OpenAI, 'Write imperative steps
with explicit inputs and outputs' (OA3).

**Boundaries in three tiers** (*reading*). The file says what the agent always does, what it asks about first and what
it never does. *Scores 0 on:* a file with rules to follow and nothing on what needs asking first. Source: GitHub, 'Set
clear rules using always do, ask first, never do' (GH3). The post reports one reader's analysis of over 2,500 files, not
a measured comparison.

### Ratings

The first five are rated on the frequency scale and the last two on the quality scale.

**Rules held in the persona** (*frequency*). *Places:* each rule the agent applies in every act. *Meets it:* the rule is
stated in the persona's own files, the ones loaded with it, not only in a file it points to. *Example of a low rating:*
'Rate findings on the scale in `severity.md`', with the scale absent. Evidence: in the same record, a rule moved to
another file and pointed to was applied in one run in three. Source: Anthropic, CLAUDE.md files 'are context, not
enforced configuration' (AN1).

**Directions for when nobody answers** (*frequency*). *Places:* each rule that asks, waits or needs a reply. *Meets it:*
the rule says what the agent does when no one replies, as in a delegated or unattended run. *Example of a low rating:*
'When no level is named, ask', with nothing for a run that has no one to ask. Evidence: a skill review of one persona
file in the same record found that rule 'can stall a pipeline subagent that has no one to ask'; the run that tested it
was inconclusive, so this question rests on the reading.

**Rules used in every act come first** (*frequency*). *Places:* each rule the agent applies in every act. *Meets it:*
the rule stands before any procedure, example or reference material in the file. *Example of a low rating:* the rating
scale a reviewer uses on every finding, set out at the end of a long file after three worked examples. Source:
'earlier-listed instructions' are followed more reliably as instructions accumulate (ST5).

**Tools explained** (*frequency*). Follows 'Declares its tools' ('Which questions apply'). *Places:* each tool the file
names. *Meets it:* the file says when and why the agent uses it. *Example of a low rating:* a list of six tool names and
nothing more. Source: Google, 'Don't just list tools; explain *when* and *why* the agent should use them' (GO3).

**Commands given exactly** (*frequency*). *Places:* each command the file tells the agent to run. *Meets it:* the
command is given as it is run, flags and options included. *Example of a low rating:* 'Run the tests' where `pytest -v
tests/` was meant. Source: GitHub, 'Put relevant executable commands in an early section … Include flags and options,
not just tool names' (GH3).

**The description says when to choose it** (*quality*). Applies to a delegated persona ('Which questions apply'):
nothing chooses a standing one. *Exceptional:* it puts the main use first, names the requests it is for in words a user
would type and says what it is not for. *Excellent:* it names those requests in a user's words and says what it is not
for. *Very good:* it names the requests in a user's words. *Good:* it names the tasks in its own terms. *Fair:* it names
a subject and no task. *Poor:* it names a role and no task, such as 'A helpful reviewer'. *Very poor:* it is empty or
missing. Sources: 'Claude uses each subagent's description to decide when to delegate tasks' (AN3); Gemini CLI's main
agent 'decides whether an agent is a relevant expert based on the agent's description' (GO2). Also: OpenAI, 'Front-load
the key use case and trigger words' and 'Explain exactly when this skill should and should not trigger' (OA3); Google,
'specific enough to differentiate it from peers' (GO3).

**An identity that does the work** (*quality*). Applies to every dedicated persona, which has a role of its own; the
identity is where the file states it, such as 'You are…'. *Exceptional:* it states what the agent does and where its
work stops, with no praise. *Excellent:* it states both, with a word of praise. *Very good:* it states what the agent
does, with no praise. *Good:* it states what the agent does, with praise. *Fair:* it names a role with praise and says
nothing of the work. *Poor:* it is praise alone, such as 'You are a world-class expert'. *Very poor:* it states no
identity, or names a role at odds with the rest of the file. Source: persona cues unrelated to the task cost agents up
to 26.2% of their performance (ST2). GitHub's blog post above opens its examples with 'You are an expert technical
writer'; this question marks the praise down and keeps the role.

## Instruction-writing questions

These hold for any instruction an agent reads, in a persona file or elsewhere.

### Checks

**No time-sensitive statements** (*script*). The file says nothing that goes out of date by itself, such as 'until
August' or 'the new API'. *Scores 0 on:* 'Use the v1 endpoint until the migration finishes.' Source: Anthropic, 'Avoid
time-sensitive information' (AN4).

**Consistent with itself** (*reading*, weight 3). No two statements in the file contradict each other. *Scores 0 on:* a
line leaving the final decision to someone else beside a line telling the agent to make that decision. Source:
Anthropic, 'if two instructions contradict each other, Claude may pick one arbitrarily' (AN1). Also: GitHub, 'Whenever
possible, try to avoid providing conflicting sets of instructions' (GH1).

**Nothing said twice** (*reading*). No sentence restates another sentence or setting in the same file. *Scores 0 on:*
the description's sentence repeated as the first rule. No external source was found; the question rests on the
reading that a second statement can drift from the first.

**Leaves known things unsaid** (*reading*). The file spends no lines on what the model already knows, such as what a
file format is or how a library works. *Scores 0 on:* a paragraph explaining what a pull request is. Source:
Anthropic, 'Claude is already very smart' and 'Does this paragraph justify its token cost?'
(AN4).

**Plain emphasis** (*script*). The file emphasises with plain words, not capitals or alarms such as 'CRITICAL' or 'You
MUST'. *Scores 0 on:* 'CRITICAL: You MUST run the tests.' Source: Anthropic, 'Where you might have said "CRITICAL: You
MUST use this tool when...", you can use more normal prompting like "Use this tool when..."', because such language
makes newer models overtrigger (AN5).

**No placeholders** (*script*). The file holds no unfinished text, such as 'TODO', 'TBD' or a bracketed slot to fill.
*Scores 0 on:* 'Deploy steps: TODO.' Source: a recurring check among the instruction-file linters surveyed while this
skill was built [no primary source quoted].

**Shows an example** (*reading*). Where the file asks for output in a particular form, it shows an example of that form.
Applies when the file asks for output in a particular form. *Scores 0 on:* three paragraphs describing a commit message
style and no example message. Sources: Google, 'Provide Examples (Few-Shot)' (GO3); Anthropic, examples 'convey
the desired style and level of detail to Claude more clearly than descriptions alone'
(AN4).

### Ratings

All seven are rated on the frequency scale.

**Terms defined where they are used** (*frequency*). *Places:* each scale, set of answers or term the file's rules name.
*Meets it:* the file defines it beside the rule. *Example of a low rating:* a rule to rate findings on a named scale
that never says what each step means. Evidence: in the record kept while this skill was built, a persona whose scale was
named and not defined rated findings more harshly than the version that defined it.

**Answers defined, edge cases included** (*frequency*). *Places:* each closed set of answers the agent returns, such as
ratings or recommendations. *Meets it:* the file says what each answer means and what to return when the work is empty,
partial or outside the persona's scope. *Example of a low rating:* three recommendations listed with no word on an empty
input.

**Its own criteria met** (*frequency*). *Places:* each criterion the file sets for the agent's work. *Meets it:* the
file meets that criterion itself. *Example of a low rating:* a rule requiring every claim to cite a source, in a file
whose own claims cite none.

**Instructions an observer can check** (*frequency*). *Places:* each instruction. *Meets it:* someone watching the agent
could tell whether it was followed. *Example of a low rating:* 'Format code properly' where 'Use 2-space indentation'
was meant. Source: Anthropic, 'Write instructions that are concrete enough to verify' (AN1). Also: Google, 'Be Clear and
Specific: Avoid ambiguity. Clearly state the desired actions and outcomes' (GO3).

**What to do, not what to avoid** (*frequency*). *Places:* each instruction about the agent's output. *Meets it:* it
says what to produce rather than only what to leave out. *Example of a low rating:* 'Do not use markdown in your
response.' Source: Anthropic, on steering output format, 'Tell Claude what to do instead of what not to do' (AN5).

**Reasons given** (*frequency*). *Places:* each rule that limits what the agent does. *Meets it:* the rule says why.
*Example of a low rating:* 'NEVER use ellipses', with no word on why. Source: Anthropic, 'Providing context or
motivation behind your instructions, such as explaining to Claude why such behavior is important, can help Claude better
understand your goals' (AN5).

**Each instruction stands alone** (*frequency*). *Places:* each instruction. *Meets it:* it can be understood without
reading another instruction first. *Example of a low rating:* 'Do the same for the other folders', three paragraphs
after the first. Source: GitHub, 'The instructions you add to your custom instruction file(s) should be short,
self-contained statements' (GH1).

## Score

Each check counts its weight or 0, and each rating counts its point, from 0 to 6. Each section has a subtotal, given as
'x out of y', where y is the section's points less those of the questions that do not apply. The two subtotals add to
the total, and the total alone sets the stars: x divided by y, times 5, rounded to the nearest half star, a half
rounding up. They print as five places, ★ for a full star, ½ for a half and ☆ for an empty place, with the number in
brackets: ★★★½☆ (3.5).

The report gives, in this order:

- the stars and the total, as 'x out of y', with the points possible and those that do not apply;
- the two subtotals, persona and instruction writing;
- the questions that do not apply, each with its reason;
- the lines behind every check scoring 0 and every rating below its top point, each quoted with its question and source;
- each check as 'yes' with its weight, or 'no 0', and each rating as its point out of 6 with its word, grouped by
  section;
- the fit with neighbouring files, apart from the score; and
- the formula, with the weights, and the total at equal weights, so anyone can recompute the stars.

The quoted lines matter more than the total, because a total alone does not predict how an agent behaves. In the
record kept while this skill was built, two versions of one persona scored one point apart on a skill rubric, while
blind judges preferred one in every pair. Wording changes behaviour: 'prompt wording can change reasoning and
verification behavior without changing the task' (ST1), and agents given a standing policy document 'report
compliance they did not achieve' (ST4).
