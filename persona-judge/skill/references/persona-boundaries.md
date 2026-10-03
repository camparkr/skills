# Persona boundaries

Much besides a persona shapes what an agent does; `review-questions.md` defines a persona. Load this file when a file
under review may be something other than a persona, or before a finding blames the persona for what it does not
control.

A persona file holds instruction, which the model reads, and may hold bound parts: settings the harness enforces and
code the file names to run. So a persona has no behaviour of its own: it shapes the agent's acts by being read, and
limits them through its settings.

## Neighbours of a persona

Each row names something a reader may mistake for a persona, or for the persona's doing:

| Neighbour | What it is | How to tell it apart | Where its review belongs |
|---|---|---|---|
| A project instructions file | Context for every session, such as `CLAUDE.md`, `AGENTS.md` or `GEMINI.md` | It sets context and defines no agent of its own; it can contain a persona's text, but is not a persona | The harness's own guidance |
| An output style | The main agent's tone and response format | It has no tools, permissions or context of its own, and nothing delegates to it | The harness's own guidance |
| The model | What reads the persona and reasons | Its defaults are what it does with no persona loaded | A run of the agent with and without the file |
| A skill or a command | Instructions taken up for one kind of task | It loads when chosen for a task; a persona frames every act of the agent it loads into | A skill reviewer such as `skill-judge` |
| A tool and what it returns | A capability the agent calls | Code decides what it returns; the agent's choice to call it is behaviour, the output is not | The tool's own tests |
| Something that runs by itself | A hook or a scheduled job | It fires on an event or a clock, and no act of the agent chose it | A configuration or security linter |
| The harness | The program holding the session | It loads the persona, supplies the tools and enforces the settings; a refused tool call is the harness acting | The harness's own settings and documents |
| An outside service | A hosted interface or server the agent calls | It runs elsewhere and answers requests | The service's own terms and documents |
| A document nothing loads | A README, design note or reference file | The agent reads it only when a loaded file names it | Its own author |
| A settings file with no prose | Configuration alone | There is nothing for the model to read | A configuration linter |

## Bound parts

A persona's settings belong to it, but the harness enforces them, not the model. *Persona-judge* checks only that
they agree with the prose. What a setting points to, such as a hook script or a server, belongs to the rows above.

## Sources

Read 1 October 2026:

- Anthropic, 'How Claude remembers your project': CLAUDE.md files are 'context, not enforced configuration', and
  hooks 'apply regardless of what Claude decides to do' (<https://code.claude.com/docs/en/memory>);
- Anthropic, 'Configure permissions': 'Permission rules are enforced by Claude Code, not by the model'
  (<https://code.claude.com/docs/en/permissions>);
- Anthropic, 'Subagents': a subagent's body 'becomes the system prompt that guides the subagent's behavior'
  (<https://code.claude.com/docs/en/sub-agents>); and
- Google, Gemini CLI subagents: 'Subagents are exposed to the main agent as a tool of the same name'
  (<https://github.com/google-gemini/gemini-cli/blob/main/docs/core/subagents.md>).
