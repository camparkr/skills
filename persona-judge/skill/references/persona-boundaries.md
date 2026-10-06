# Persona boundaries

This file says what a persona is, what it is not, and what the persona controls, for the reviewer to load when
`../steps/answer.md` says. Source keys refer to [`sources.md`](sources.md), which you open only when someone asks for a
source.

## Terms

A persona is defined in `questions/scales.md`. The words around it mean this:

| Term | What it means in a review |
|---|---|
| Rule | an instruction that limits what the agent does, or says what it always does |
| Pointer | a path the persona tells the agent to read, with when to read it |
| Behaviour | what the agent does: the model's acts, which a persona shapes and does not perform |

## Placing a file

Answer each question yes or no, in order, and follow the line your answer gives:

0. Does the file only bundle other things, with no effect of its own? Yes: place each thing inside it by these
   questions, from question 1. No: go to 1.
1. Does it define an agent of its own, as `questions/scales.md` defines a persona, whose text frames every act of
   that agent, rather than being taken up for one task? Yes: it is a persona, whatever the file is called. Stop. No: go
   to 2.
2. It is not a persona: set it aside, with the reason the neighbours below give.

## Neighbours of a persona

Each row names something a reader may mistake for a persona, or for the persona's doing:

| Neighbour | What it is | How to tell it apart |
|---|---|---|
| A project instructions file | Context for every session, such as `CLAUDE.md`, `AGENTS.md` or `GEMINI.md` | It sets context and defines no agent of its own; it can hold a persona's text, but is not a persona |
| An output style | The main agent's tone and response format | It has no tools, permissions or context of its own, and nothing delegates to it |
| The model | What reads the persona and reasons | Its defaults are what it does with no persona loaded |
| A skill or a command | Instructions taken up for one kind of task | It loads when chosen for a task; a persona frames every act of the agent it loads into |
| A tool and what it returns | Code the agent calls | Code decides what it returns; the agent's choice to call it is behaviour, the output is not |
| Something that runs by itself | A hook or a scheduled job | An event or a clock fires it, and no act of the agent chooses it |
| The harness | The program holding the session | It loads the persona, supplies the tools and enforces the settings; a refused tool call is the harness acting |
| An outside service | A hosted interface or server the agent calls | It runs elsewhere and answers requests |
| A document nothing loads | A README, design note or reference file | The agent reads it only when a loaded file names it |
| A settings file with no prose | Configuration alone | It holds nothing for the model to read |

## Bound parts

A persona's settings belong to it, but the harness enforces them, not the model. What a setting points to, such as a
hook script or a server, is not part of the review. Sources: AN1, AN2, AN3, GO2.
