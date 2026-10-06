# Grounding

What each of *persona-judge*'s questions rests on: its sources, the kind of evidence behind it and the words it quotes.
Load this file when a reader asks why a question exists or how strong its support is. Each key's full reference is in
`sources.md`, at the plugin's root.

## Each question's support

The evidence column says what kind of support a question has. A vendor rule is a vendor's published advice. A study is
a paper's measured finding, read in its abstract. The record is what this skill's own test runs found while it was
built. Reading alone means no source was found, and the question rests on the author's reading.

| Question | Section | Kind | Sources | Evidence | Vendors agreeing | Where a source disagrees |
|---|---|---|---|---|---|---|
| A dedicated persona | persona | check, reading; answered first | GH4, GO2, AN6 | vendor rule | GitHub, Google, Anthropic | none |
| Pointers carry their triggers | persona | check, script | RE1 | record | none | none |
| Bound parts agree with the prose | persona | check, script; weight 3 | AN2, AN3 | vendor rule | Anthropic | none |
| Permissions fit the job | persona | check, reading | OA2, AN3 | vendor rule | OpenAI, Anthropic | AN3: the harness ignores the setting in some modes |
| Needs no context it is not given | persona | check, reading | AN3, GO2 | vendor rule | Anthropic, Google | none |
| Leaves the harness's work to the harness | persona | check, script | AN1, AN4 | vendor rule | Anthropic | none |
| Enforceable rules enforced | persona | check, reading; weight 3 | AN1, OA1, ST4 | vendor rule and study | Anthropic, OpenAI | none |
| No procedure for one kind of task | persona | check, reading | AN1, GH1 | vendor rule | Anthropic, GitHub | none |
| No facts the project already holds | persona | check, reading | AN1 | vendor rule | Anthropic | GH3 recommends listing the file structure |
| No pressure from consequences | persona | check, reading | ST6 | study | none | none |
| One job | persona | check, reading | OA2, GO1 | vendor rule | OpenAI, Google | none |
| Declares its tools | persona | check, script | OA2, GO2, GH2 | vendor rule | OpenAI, Google, GitHub | none |
| States its output | persona | check, reading | GO3, OA3 | vendor rule | Google, OpenAI | none |
| Boundaries in three tiers | persona | check, reading | GH3 | vendor rule, Matt Nigh's analysis of 2,500 files | GitHub | none |
| Rules held in the persona | persona | rating, frequency | AN1, RE1 | vendor rule and record | Anthropic | none |
| Directions for when nobody answers | persona | rating, frequency | RE1 | record; the run that tested it was inconclusive | none | none |
| Rules used in every act come first | persona | rating, frequency | ST5 | study | none | none |
| Tools explained | persona | rating, quality; follows 'Declares its tools' | GO3 | vendor rule | Google | none |
| Commands given exactly | persona | rating, frequency | GH3 | vendor rule, Matt Nigh's analysis of 2,500 files | GitHub | none |
| The description says when to choose it | persona | rating, quality | AN3, GO2, OA3, GO3 | vendor rule | Anthropic, Google, OpenAI | none |
| An identity that does the work | persona | rating, quality | ST2 | study | none | GH3 opens its examples with 'You are an expert' |
| No time-sensitive statements | instruction writing | check, script | AN4 | vendor rule | Anthropic | none |
| Consistent with itself | instruction writing | check, reading; weight 3 | AN1, GH1, ST7, ST8 | vendor rule and study | Anthropic, GitHub | ST7 and ST8 measure conflicts between instruction levels, not two statements in one file |
| Nothing said twice | instruction writing | check, reading | none | reading alone | none | none |
| Leaves known things unsaid | instruction writing | check, reading | AN4 | vendor rule | Anthropic | none |
| Plain emphasis | instruction writing | check, script | AN5 | vendor rule | Anthropic | none |
| No placeholders | instruction writing | check, script | RE2 | record of linters surveyed; no primary source | none | none |
| Shows an example | instruction writing | check, reading | GO3, AN4 | vendor rule | Google, Anthropic | none |
| Terms defined where they are used | instruction writing | rating, frequency | RE1 | record | none | none |
| Answers defined, edge cases included | instruction writing | rating, frequency | none | reading alone | none | none |
| Its own criteria met | instruction writing | rating, frequency | none | reading alone | none | none |
| Instructions an observer can check | instruction writing | rating, frequency | AN1, GO3 | vendor rule | Anthropic, Google | none |
| What to do, not what to avoid | instruction writing | rating, frequency | AN5 | vendor rule, on output format | Anthropic | none |
| Reasons given | instruction writing | rating, frequency | AN5 | vendor rule | Anthropic | none |
| Each instruction stands alone | instruction writing | rating, frequency | GH1 | vendor rule | GitHub | none |

The scales come from SC1. The case for reviewing a persona rests on ST1 to ST4 and RE1.

## What each source says, by question

The words each question rests on, quoted from its sources; the questions keep only the keys.

- **A dedicated persona.** Sources: GH4, GO2 and AN6, whose words are in `vendor-terms.md` at the plugin's root, 'Context, not a persona'.
- **Bound parts agree with the prose.** Sources: Anthropic, 'Permission rules are enforced by Claude Code, not by the model' (AN2); the subagent fields `tools`, `disallowedTools`, `permissionMode` and `hooks` (AN3).
- **Permissions fit the job.** Sources: OpenAI, a subagent needs 'a tool surface that matches that job' (OA2); Anthropic, 'If you leave it unset, the subagent inherits the main conversation's permission mode' (AN3).
- **Needs no context it is not given.** Sources: Anthropic, 'Each subagent starts with a fresh, isolated context window. It doesn't see your conversation history, the skills you've already invoked, or the files Claude has already read' (AN3); Google, 'Each subagent runs in its own isolated context loop' (GO2).
- **Leaves the harness's work to the harness.** Sources: Anthropic, 'Only add context Claude doesn't already have' (AN4); a `CLAUDE.md` that tells Claude in words to read `AGENTS.md` means 'Claude sees `AGENTS.md` only if it decides to open the file' (AN1).
- **Enforceable rules enforced.** Source: Anthropic, 'If the instruction is something that must run at a specific point … write it as a hook' and 'To block an action regardless of what Claude decides, use a PreToolUse hook' (AN1). Also: OpenAI, 'reserve formatting and lint checks for CI' (OA1).
- **No procedure for one kind of task.** Source: Anthropic, 'If an entry is a multi-step procedure or only matters for one part of the codebase, move it to a skill or a path-scoped rule' (AN1). Also: GitHub, standing instructions 'should be broadly applicable to most requests' (GH1).
- **No facts the project already holds.** Source: Anthropic, the `/doctor` trim 'cuts content Claude can derive from the codebase, such as directory layouts, dependency lists, and architecture overviews' (AN1).
- **No pressure from consequences.** Source: judges told what their verdicts would cause 'reliably soften verdicts', with a peak shift of 9.8 percentage points and 'zero explicit acknowledgment' of the framing in their reasoning (ST6).
- **One job.** Sources: OpenAI, 'The best custom agents are narrow and opinionated. Give each one clear job' (OA2); Google, 'Limit scope' (GO1).
- **Declares its tools.** Sources: OpenAI, 'a tool surface that matches that job' (OA2); in Gemini CLI and GitHub Copilot an agent with no tool list is given every tool (GO2 and GH2).
- **States its output.** Sources: Google, an agent's instruction covers 'The desired format for its output' (GO3); OpenAI, 'Write imperative steps with explicit inputs and outputs' (OA3).
- **Boundaries in three tiers.** Source: GitHub, 'Set clear rules using always do, ask first, never do' (GH3). The post reports one reader's analysis of over 2,500 files, not a measured comparison.
- **Rules held in the persona.** Source: Anthropic, CLAUDE.md files 'are context, not enforced configuration' (AN1).
- **Rules used in every act come first.** Source: 'earlier-listed instructions' are followed more reliably as instructions accumulate (ST5).
- **Tools explained.** Source: Google, 'Don't just list tools; explain *when* and *why* the agent should use them' (GO3).
- **Commands given exactly.** Source: GitHub, 'Put relevant executable commands in an early section … Include flags and options, not just tool names' (GH3).
- **The description says when to choose it.** Sources: AN3, in `vendor-terms.md` at the plugin's root, 'What the vendors say a persona has'; Gemini CLI's main agent 'decides whether an agent is a relevant expert based on the agent's description' (GO2). Also: OpenAI, 'Front-load the key use case and trigger words' and 'Explain exactly when this skill should and should not trigger' (OA3); Google, 'specific enough to differentiate it from peers' (GO3).
- **An identity that does the work.** Source: persona cues unrelated to the task cost agents up to 26.2% of their performance (ST2).
- **No time-sensitive statements.** Source: Anthropic, 'Avoid time-sensitive information' (AN4).
- **Consistent with itself.** Source: Anthropic, 'if two instructions contradict each other, Claude may pick one arbitrarily' (AN1). Also: GitHub, 'Whenever possible, try to avoid providing conflicting sets of instructions' (GH1).
- **Leaves known things unsaid.** Source: Anthropic, 'Claude is already very smart' and 'Does this paragraph justify its token cost?' (AN4).
- **Plain emphasis.** Source: Anthropic, 'Where you might have said "CRITICAL: You MUST use this tool when...", you can use more normal prompting like "Use this tool when..."', because such language makes newer models overtrigger (AN5).
- **No placeholders.** Source: RE2 [no primary source quoted].
- **Shows an example.** Sources: Google, 'Provide Examples (Few-Shot)' (GO3); Anthropic, examples 'convey the desired style and level of detail to Claude more clearly than descriptions alone' (AN4).
- **Instructions an observer can check.** Source: Anthropic, 'Write instructions that are concrete enough to verify' (AN1). Also: Google, 'Be Clear and Specific: Avoid ambiguity. Clearly state the desired actions and outcomes' (GO3).
- **What to do, not what to avoid.** Source: Anthropic, on steering output format, 'Tell Claude what to do instead of what not to do' (AN5).
- **Reasons given.** Source: Anthropic, 'Providing context or motivation behind your instructions, such as explaining to Claude why such behavior is important, can help Claude better understand your goals' (AN5).
- **Each instruction stands alone.** Source: GitHub, 'The instructions you add to your custom instruction file(s) should be short, self-contained statements' (GH1).
- **Bound parts, in `persona-boundaries.md`.** AN2, as quoted under 'Bound parts agree with the prose'; CLAUDE.md files are 'context, not enforced configuration', and hooks 'apply regardless of what Claude decides to do' (AN1); AN3 on a subagent's body, in [`vendor-terms.md`](vendor-terms.md); 'Subagents are exposed to the main agent as a tool of the same name' (GO2).
- **Pointers carry their triggers, the build's record.** In the record kept while this skill was built, a pointer that said when to open its file was followed in three runs of three, and an index nothing pointed to was never read (RE1).
- **No facts the project already holds, a contrary source.** GitHub's guide (GH3) recommends listing the file structure; this question reads it the other way, as Anthropic's trim does (AN1).
