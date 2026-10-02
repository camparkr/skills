# Bibliography

Where each of *persona-judge*'s questions comes from, and every source the skill cites. Load this file when a reader
asks what a question rests on.

## Contents

The file holds three sections:

- grounding, a table of every question with its sources and the kind of evidence behind it;
- vendor terms, what each vendor calls a project instructions file and a defined agent, and how an output style differs from a persona; and
- sources, every source by its key, with where to read it and when it was read.

## Grounding

The evidence column says what kind of support a question has. A vendor rule is a vendor's published advice. A study is
a paper's measured finding, read in its abstract. The record is what this skill's own test runs found while it was
built. Reading alone means no source was found, and the question rests on the author's reading.

| Question | Section | Kind | Sources | Evidence | Vendors agreeing | Where a source disagrees |
|---|---|---|---|---|---|---|
| A dedicated persona | persona | check, reading; answered first | GH4, GO2, AN6 | vendor rule | GitHub, Google, Anthropic | none |
| Pointers carry their triggers | persona | check, script | RE1 | record | none | none |
| Bound parts agree with the prose | persona | check, script | AN2, AN3 | vendor rule | Anthropic | none |
| Leaves the harness's work to the harness | persona | check, script | AN1, AN4 | vendor rule | Anthropic | none |
| Enforceable rules enforced | persona | check, reading | AN1, OA1 | vendor rule | Anthropic, OpenAI | none |
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
| Tools explained | persona | rating, frequency | GO3 | vendor rule | Google | none |
| Commands given exactly | persona | rating, frequency | GH3 | vendor rule, Matt Nigh's analysis of 2,500 files | GitHub | none |
| The description says when to choose it | persona | rating, quality | AN3, GO2, OA3, GO3 | vendor rule | Anthropic, Google, OpenAI | none |
| An identity that does the work | persona | rating, quality | ST2 | study | none | GH3 opens its examples with 'You are an expert' |
| No time-sensitive statements | instruction writing | check, script | AN4 | vendor rule | Anthropic | none |
| Consistent with itself | instruction writing | check, reading | AN1, GH1 | vendor rule | Anthropic, GitHub | none |
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

The scales come from SC1. The README's case for reviewing a persona rests on ST1 to ST4 and RE1.

## Vendor terms

A project instructions file, such as `CLAUDE.md`, `AGENTS.md` or `GEMINI.md`, is context. It can contain a persona's
text, but it is not a persona. The vendors' own words draw the same line.

Vendors call project instructions files context or guidance:

- Anthropic: `CLAUDE.md` files are 'instructions you write to give Claude persistent context', and 'Claude treats them
  as context, not enforced configuration' (AN1).
- OpenAI: '`AGENTS.md` gives Codex durable project guidance that travels with your repository and applies before the
  agent starts work' (OA4).
- Google: 'Context files, which use the default name `GEMINI.md`, are a powerful feature for providing instructional
  context to the Gemini model' (GO4).
- GitHub: custom instructions are 'Always-on context that automatically applies to every interaction within its
  defined scope' (GH4).

Vendors call defined agents personas:

- GitHub: a custom agent is a 'Specialist persona with its own instructions, tool restrictions, and context' (GH4).
- GitHub's blog: 'Each agents.md file acts as an agent persona, which you define with frontmatter and custom
  instructions' (GH3). The files it means are Copilot's custom-agent files under `.github/agents/`, not a project's
  `AGENTS.md`.
- Google: 'Each subagent has its own system prompt and persona' (GO2).
- Anthropic: a subagent's body 'becomes the system prompt that guides the subagent's behavior' (AN3).

One passage joins the two. Google gives `system.md` the 'Non‑negotiable operational rules' and `GEMINI.md` the
'Persona, goals, methodologies, and project/domain context' (GO5). There, 'Persona' names one part of what the file
holds, beside goals, methods and project context. The file as a whole is still context.

An output style is not a persona either. It sets how the main agent responds, and a persona defines an agent of its
own. Anthropic's pages show the difference:

| | Output style | Subagent, a dedicated persona |
|---|---|---|
| What it sets | 'Claude's role, tone, and response format for every response in a session' (AN6) | 'The body becomes the system prompt that guides the subagent's behavior' (AN3) |
| Its own tools | None. Its fields are `name`, `description`, `keep-coding-instructions` and `force-for-plugin` (AN6) | `tools`, `disallowedTools`, `permissionMode`, `hooks`, `mcpServers` and more (AN3) |
| Its own permissions | None: 'Switching to the Proactive style doesn't change your permission mode' (AN6) | Its own, through `permissionMode` (AN3) |
| Its own context | None. It applies to the main conversation, and 'Other subagents run their own system prompt, so styles don't change how they respond' (AN6) | 'It runs in a separate context with its own system prompt and returns a summary to your conversation' (AN6) |
| How it is chosen | Switched on for the whole session with `/output-style` (AN6) | 'Claude uses each subagent's description to decide when to delegate tasks' (AN3) |
| What it returns | Nothing of its own: it shapes the main agent's replies | 'a summary to your conversation' (AN6) |

## Sources

### Vendor documentation

| Key | Source | Read |
|---|---|---|
| AN1 | Anthropic, 'How Claude remembers your project', <https://code.claude.com/docs/en/memory> | 1 October 2026 |
| AN2 | Anthropic, 'Configure permissions', <https://code.claude.com/docs/en/permissions> | 1 October 2026 |
| AN3 | Anthropic, 'Subagents', <https://code.claude.com/docs/en/sub-agents> | 1 October 2026 |
| AN4 | Anthropic, 'Skill authoring best practices', <https://platform.claude.com/docs/en/agents-and-tools/agent-skills/best-practices> | 2 October 2026 |
| AN5 | Anthropic, 'Prompting best practices', <https://platform.claude.com/docs/en/build-with-claude/prompt-engineering/claude-prompting-best-practices> | 2 October 2026 |
| AN6 | Anthropic, 'Output styles', <https://code.claude.com/docs/en/output-styles> | 1 October 2026 |
| OA1 | OpenAI, 'Custom instructions with AGENTS.md', <https://learn.chatgpt.com/docs/agent-configuration/agents-md> | 2 October 2026 |
| OA2 | OpenAI, 'Subagents', <https://learn.chatgpt.com/docs/agent-configuration/subagents> | 2 October 2026 |
| OA3 | OpenAI, 'Build skills', <https://learn.chatgpt.com/docs/build-skills> | 2 October 2026 |
| OA4 | OpenAI, Codex customisation overview, <https://learn.chatgpt.com/docs/customization/overview> | 1 October 2026 |
| GO1 | Google, 'Agent Skill best practices', <https://geminicli.com/docs/cli/skills-best-practices/> | 2 October 2026 |
| GO2 | Google, Gemini CLI subagents, <https://geminicli.com/docs/core/subagents/>, source at <https://github.com/google-gemini/gemini-cli/blob/main/docs/core/subagents.md> | 1 October 2026 |
| GO3 | Google, Agent Development Kit, 'LLM Agent', <https://google.github.io/adk-docs/agents/llm-agents/> | 2 October 2026 |
| GO4 | Google, 'GEMINI.md', <https://geminicli.com/docs/cli/gemini-md/> | 1 October 2026 |
| GO5 | Google, 'System Prompt Override (GEMINI_SYSTEM_MD)', <https://geminicli.com/docs/cli/system-prompt/> | 1 October 2026 |
| GH1 | GitHub, 'About customizing GitHub Copilot responses', <https://docs.github.com/en/copilot/concepts/prompting/response-customization> | 2 October 2026 |
| GH2 | GitHub, 'Custom agents configuration', <https://docs.github.com/en/copilot/reference/custom-agents-configuration> | 2 October 2026 |
| GH3 | Matt Nigh, 'How to write a great agents.md: Lessons from over 2,500 repositories', GitHub Blog, 19 November 2025, <https://github.blog/ai-and-ml/github-copilot/how-to-write-a-great-agents-md-lessons-from-over-2500-repositories/> | 2 October 2026 |
| GH4 | GitHub, customisation cheat sheet, <https://docs.github.com/en/copilot/reference/customization-cheat-sheet> | 1 October 2026 |

### Studies

Each entry rests on its abstract. The arXiv identifier pins the version.

| Key | Source | Read |
|---|---|---|
| ST1 | Weinberger and Hozez, 'Prompt-Induced Waste in Coding Agents: Reasoning, Effort, Harness Design, and End-to-End Cost', 2026, <https://arxiv.org/abs/2608.01347> | 1 October 2026 |
| ST2 | Cao, Sun and Yue, 'From Biased Chatbots to Biased Agents: Examining Role Assignment Effects on LLM Agent Robustness', 2026, <https://arxiv.org/abs/2602.12285> | 1 October 2026 |
| ST3 | Cheng and Mastropaolo, 'An Empirical Study on the Effects of System Prompts in Instruction-Tuned Models for Code Generation', 2026, <https://arxiv.org/abs/2602.15228> | 1 October 2026 |
| ST4 | Panavas, Minus, Monton, Ray, Garre, Mehta and Chen, 'HANDBOOK.md: A Benchmark for Long-Context Agentic Instruction Following', 2026, <https://arxiv.org/abs/2607.25398> | 1 October 2026 |
| ST5 | Jaroslawicz, Whiting, Shah and Maamari, 'How Many Instructions Can LLMs Follow at Once?', 2025, <https://arxiv.org/abs/2507.11538> | 30 September 2026 |
| ST6 | Gupta, Nair, Wang and Kumar, 'Context Over Content: Exposing Evaluation Faking in Automated Judges', 2026, <https://arxiv.org/abs/2604.15224> | 30 September 2026 |

### Scale

| Key | Source | Read |
|---|---|---|
| SC1 | Sorrel Brown, 'Likert Scale Examples for Surveys', Iowa State University Extension, December 2010, <https://www.extension.iastate.edu/documents/anr/likertscaleexamplesforsurveys.pdf> | 1 October 2026 |

### Record of this build

| Key | Source |
|---|---|
| RE1 | The record kept while this skill was built: 12 dry runs on one persona file and two rewrites of it, run on two harnesses and judged blind, and a skill review of three versions of the file |
| RE2 | The instruction-file linters surveyed while this skill was built, which check for placeholders; no primary source is quoted |
