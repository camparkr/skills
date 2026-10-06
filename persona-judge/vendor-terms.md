# Vendor terms

What each vendor calls a project instructions file and a defined agent, how an output style differs from a persona,
and what the vendors say a persona has. Load this file when a reader asks what a term means to a vendor. Each key's full
reference is in [`sources.md`](sources.md).

## Context, not a persona

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

## What the vendors say a persona has

Each row names a property the vendors give a persona, in their words, and the questions that ask about it:

| What a persona has | Vendor wording | Questions |
|---|---|---|
| Its own instructions | a 'Specialist persona with its own instructions' (GH4); 'its own system prompt and persona' (GO2); the body 'becomes the system prompt' (AN3) | Rules held in the persona; An identity that does the work; One job; Rules used in every act come first |
| Its own tools | 'tool restrictions' (GH4); `tools` and `disallowedTools` (AN3); a list left out gives every tool (GO2, GH2) | Declares its tools; Tools explained; Bound parts agree with the prose |
| Its own permissions | `permissionMode` (AN3); `sandbox_mode` (OA2) | Permissions fit the job; Bound parts agree with the prose; Enforceable rules enforced |
| Its own context | 'a fresh, isolated context window' (AN3); 'its own isolated context loop' (GO2) | Needs no context it is not given; Each instruction stands alone |
| Chosen by its description | 'Claude uses each subagent's description to decide when to delegate tasks' (AN3) | The description says when to choose it |
| Returns its result to the caller | 'returns a summary to your conversation' (AN6) | States its output; Shows an example |
| Its own model | `model` in all four (AN3, OA2, GO2, GH2) | Not scored, see below |

**Its own model, recorded and not scored.** All four vendors let a persona set its model, and all four fall back to a
default when it is left out: the main session's model, or the harness's default (AN3, OA2, GO2, GH2). GitHub honours the
field in its IDE agents, not in its cloud agent (GH5). Two vendors advise a faster, lower-cost model for light work:
OpenAI, 'for lighter subagent work' (OA2), and Anthropic, 'For simple subagent tasks, specify `model: haiku` in your
subagent configuration' (AN7). They give that advice to save cost and time. *Persona-judge* scores how a file shapes what
the agent does, and leaving the model to its default is no vendor's error, so no question scores it.
