# Definitions

This file says what each word *persona-judge* relies on means, how to tell it from its neighbours, and where the word
comes from. Load it when a file under review may be something other than a persona, before a finding blames the persona
for what it does not control, or when someone asks what a term means. Source keys refer to `bibliography.md`.

## Contents

The file holds multiple sections:

- the theatre, the picture the terms come from;
- the review itself, the one kind of act *persona-judge* performs;
- terms, each with its root and what it means here;
- capabilities, the kinds of thing an agent takes up;
- placing a file, the questions that decide whether a file is a persona;
- neighbours of a persona, the things a reader may mistake for one;
- bound parts, the settings a persona holds and the harness enforces; and
- where the roots come from.

## The theatre

An actor (*hypokritēs*) stands on the stage building (*skēnē*) and wears a mask (*prosōpon*, the persona). The mask
fixes the part, but it plays nothing: the actor does. The work runs as a chain: a project (*praxis*, a doing) holds
tasks (*heortai*, the festivals), and at each task the plays run as sessions (*epeisodia*), the scenes of dialogue
between the chorus's songs. The chorus-leader (*chorēgos*, the person in the loop) sets the work and prompts the actor.

| In the theatre | Greek, with its sense | In *persona-judge* |
|---|---|---|
| The mask | *prosōpon* (πρόσωπον), 'face; mask; dramatic part' | the persona: it frames every act and performs none |
| The actor | *hypokritēs* (ὑποκριτής), 'one who answers; actor' | the model: it reads the part and decides how to play it |
| The stage | *skēnē* (σκηνή), 'tent; the stage-building' | the harness: it holds the performance, supplies the props and enforces the stage's limits |
| The doing | *praxis* (πρᾶξις), 'doing, action' | the project: where the work and its capabilities sit |
| The festival | *heortē* (ἑορτή), 'feast, festival' | the task: a named occasion, with a beginning and an end, that several sessions serve |
| The scene | *epeisodion* (ἐπεισόδιον), 'the part between choral odes' | the session: one run from its first prompt to its close; it is when the agent acts, never where anything is kept |
| The chorus-leader | *chorēgos* (χορηγός), 'chorus-leader; sponsor' | the person in the loop: sets the work and prompts the actor |

The picture holds at its centre, the mask, and loosens at the edges: read it as a picture, not a rule.

The mask is the point. A persona has no behaviour of its own: the model wearing it behaves, and one model wears several
masks in a single session, one for each subagent it runs. So *persona-judge* scores the file, the mask, and claims
nothing about how a performance goes. A score does not predict behaviour, and the report says so.

## The review itself

*Persona-judge* performs one kind of act: a review. The Greek is *euthynai* (εὔθυναι), 'setting straight, correction',
'calling to account': at Athens, the examination of an official when the term of office ends. A review marks an
instruction text an agent loads against a named standard of how such a text is written, the review questions, and
returns the marks to the text's author. It decides nothing about the text's passage.

That is why the report holds no verdict. A verdict admits or refuses work's passage to its next stage against a named
standard. *Persona-judge* never decides that: the author, or whoever approves the text, decides what the marks allow.

The character of an act differs from behaviour. The Greek is *thiasos* (θίασος), 'troupe, company': the company an act
belongs to by its character, whoever performs it. Behaviour is what an agent does; the character of an act is what kind
of work that doing is, a review, an inquiry or a making.

## Terms

Each term gives its root where the root shows something, then what the word means in *persona-judge*:

| Term | Root and its sense | What it means here |
|---|---|---|
| Persona | Latin *persona*, 'a mask, a false face', then 'a part in a drama'; Greek *prosōpon* | a dedicated agent: a named specialist with its own instructions, and often its own tools, settings and context, such as a subagent or a custom agent; it may span several files |
| Agent | — | the model acting through a harness, wearing a persona or none |
| Project, task, session | Greek *praxis*, *heortē* and *epeisodion*, as 'The theatre' gives them | the chain the work runs in: a project holds tasks, and a task runs over sessions; a session may serve more than one task |
| Model | Greek *hypokritēs* | what reads the persona and reasons; its defaults are what it does with no persona loaded |
| Harness | Old French *harnois*, 'arms, equipment', and the trappings of a horse; by the 1690s, 'to control for use as power'; Greek *skēnē* | the program that holds the session: it loads the persona, supplies the tools and enforces the settings |
| Instruction | — | prose the model reads and decides whether to follow; nothing enforces it |
| Rule | — | an instruction that limits what the agent does, or says what it always does |
| Pointer | — | a path the persona tells the agent to read, with when to read it |
| Setting, or bound part | — | a field the harness applies whatever the prose says, such as `tools` or `permissionMode` |
| Skill | Old Norse *skil*, 'distinction, discernment' | instructions taken up for one kind of task, loaded when chosen; a persona frames every act |
| Project instructions | — | context for every session, such as `CLAUDE.md`, `AGENTS.md` or `GEMINI.md`; it can hold a persona's text, but defines no agent of its own |
| Output style | — | the main agent's tone and response format, with no tools, permissions or context of its own |
| Context | — | what the agent sees when it acts; a subagent starts with its own, and sees no conversation it is not given |
| Behaviour | from *behave*, 'conduct or comport (oneself)' | what the agent does: the model's acts, which a persona shapes and does not perform |
| Characteristic | Greek *kharaktēr* (χαρακτήρ), 'engraver', 'die, stamp', then 'mark engraved, impress, stamp on coins and seals', then a 'distinctive mark … by which it is known from others, characteristic, character' | a mark a file leaves on the agent's conduct, by which that agent is known from others, as a stamp marks a coin |
| Disposition | Greek *ēthos* (ἦθος), 'disposition, character', 'as the result of habit'; also a character in a play | the steady conduct a persona aims to settle in the agent; like *prosōpon*, theatre vocabulary for a part |
| Capability | Latin *capabilis*, 'able to grasp or hold'; Greek *dynamis* (δύναμις), 'power, capacity' | something an agent takes up, or that fires itself, through a way in of its own; 'Capabilities' sets out its kinds |

## Capabilities

A capability sits somewhere, as code in a folder or prose a harness reads; an act is what happens when something takes
it up. Two questions sort every capability, and *persona-judge* uses both.

**What decides its output:**

| Kind | Greek, with its sense | What decides its output | For example |
|---|---|---|---|
| A tool | *ergaleion* (ἐργαλεῖον), 'tool', from *ergon*, work | code | a script, a command; *persona-judge*'s `check.py` |
| A contrivance | *mēchanē* (μηχανή), 'contrivance' | a model's inference | a subagent, a skill; *persona-judge*'s reviewer |
| A compound | *sustēma* (σύστημα), 'a whole of several parts' | a part that passes each call to one of several capabilities, itself a tool or a contrivance | a router |

Repeatable output does not make a contrivance a tool: a model's answer stays a model's answer, even when it repeats.

**What starts it:** something takes it up, or nothing does. A capability that nothing chooses at the moment it runs is
self-acting (*automaton*, αὐτόματον, 'self-acting thing'): a hook, which an event fires, or a scheduled job, which a
clock fires. This is why 'Enforceable rules enforced' looks for a hook or a setting: a self-acting hook holds a rule
whatever the model decides, and prose does not.

**What it relies on.** A runtime, a packaged library or a model a capability calls is not a capability itself: it is one
of the conditions without which the capability does not work (*synaitia*, συναίτια).

## Placing a file

Answer each question yes or no, in order, and follow the line your answer gives:

0. Does the file only bundle other things, with no effect of its own? Yes: it takes no place; place each thing inside
   it by these questions, from question 1. No: go to 1.
1. Does it frame every act of a session or a subagent, rather than being taken up for one task? It frames every act
   when a model reads it whenever the session or subagent acts; a hook, which no model reads, does not. Yes: it is a
   persona, whatever the file is called. Its prose is instruction, which the model reads and nothing enforces. Any
   settings it holds, or code it names to run, are its bound parts: they belong to the persona, and questions 2 to 4
   place each of them on its own. Stop. No: go to 2.
2. Is it built or adopted to be taken up for a task, or to fire itself when something happens, through a way in of
   its own, such as a command, a script or a call? Yes: it is a capability. Stop. No: go to 3.
3. Does it still hold if a different harness runs here? Yes, and it is part of the machine: it is the environment.
   Yes, and it is a service the project uses without owning: it is an outside service. Stop. No: go to 4.
4. The harness applies it, whether the harness enforces it itself or has the operating system do so: it is the
   harness's. Stop.

*Persona-judge* reviews only a file placed at question 1, and sets every other file aside.

## Neighbours of a persona

Each row names something a reader may mistake for a persona, or for the persona's doing:

| Neighbour | What it is | How to tell it apart | Where its review belongs |
|---|---|---|---|
| A project instructions file | Context for every session, such as `CLAUDE.md`, `AGENTS.md` or `GEMINI.md` | It sets context and defines no agent of its own; it can hold a persona's text, but is not a persona | The harness's own guidance |
| An output style | The main agent's tone and response format | It has no tools, permissions or context of its own, and nothing delegates to it | The harness's own guidance |
| The model | What reads the persona and reasons | Its defaults are what it does with no persona loaded | A run of the agent with and without the file |
| A skill or a command | Instructions taken up for one kind of task | It loads when chosen for a task; a persona frames every act of the agent it loads into | A skill reviewer such as `skill-judge` |
| A tool and what it returns | A capability the agent calls | Code decides what it returns; the agent's choice to call it is behaviour, the output is not | The tool's own tests |
| Something that runs by itself | A hook or a scheduled job | An event or a clock fires it, and no act of the agent chooses it | A configuration or security linter |
| The harness | The program holding the session | It loads the persona, supplies the tools and enforces the settings; a refused tool call is the harness acting | The harness's own settings and documents |
| An outside service | A hosted interface or server the agent calls | It runs elsewhere and answers requests | The service's own terms and documents |
| A document nothing loads | A README, design note or reference file | The agent reads it only when a loaded file names it | Its own author |
| A settings file with no prose | Configuration alone | It holds nothing for the model to read | A configuration linter |

## Bound parts

A persona's settings belong to it, but the harness enforces them, not the model. *Persona-judge* checks that they agree
with the prose, and that the permissions they grant fit the job. What a setting points to, such as a hook script or a
server, belongs to the rows above. Sources: 'Permission rules are enforced by Claude Code, not by the model' (AN2);
CLAUDE.md files are 'context, not enforced configuration', and hooks 'apply regardless of what Claude decides to do'
(AN1); a subagent's body 'becomes the system prompt that guides the subagent's behavior' (AN3); 'Subagents are exposed
to the main agent as a tool of the same name' (GO2).

## Where the roots come from

The Greek senses come from the Liddell-Scott-Jones *Greek-English Lexicon* in the Perseus TEI edition (LX1), all read at
one pinned revision, so a reader checks each sense against the same text. The Latin and English roots come from the
*Online Etymology Dictionary* (LX2), read on 4 October 2026. *Persona* and *prosōpon* travel the same road, from mask to
part to person, but no line of descent is proven. Latin *persona* may come from Etruscan *phersu*, 'mask'; the older
link to *personare*, 'to sound through', has a difficulty with the long *o* (LX2). Its sense, 'mask', is not in doubt.
