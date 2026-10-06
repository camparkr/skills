# Definitions

This file is for people reading about *persona-judge*. It sets the skill's terms in an analogy from the Greek theatre:
what acts, where and when it acts, the kind of act a review is, and the kinds of thing an agent takes up. The agent
never loads it. What each term means in a review, and how to tell a persona from its neighbours, is in
[`skill/references/persona-boundaries.md`](skill/references/persona-boundaries.md), which the agent loads when it needs to place a file; this
file gives background and does not repeat it. Source keys refer to the sources at the end of this file.

## Contents

The file holds multiple sections:

- the theatre, the analogy the terms are set in;
- a review (*euthynai*), the one kind of act *persona-judge* performs;
- capabilities, the kinds of thing an agent takes up;
- the Greek words, each with its sense;
- where the senses come from; and
- sources.

## The theatre

An actor stands on the stage and wears a mask. The mask fixes the part, but it plays nothing: the actor does. In the
analogy, the work runs as a chain: a project (*praxis*) holds tasks, the festivals (*heortai*), and each task runs as
sessions, the scenes (*epeisodia*) played between the chorus's songs. The chorus-leader (*chorēgos*), the person in
the loop, sets the work and prompts the actor.

| In the theatre | Greek, with its sense | In *persona-judge* |
|---|---|---|
| The mask | *prosōpon* (πρόσωπον), 'face; mask; dramatic part' | the persona: it frames every act and performs none |
| The actor | *hypokritēs* (ὑποκριτής), 'one who answers; actor' | the model: it reads the part and decides how to play it |
| The stage | *skēnē* (σκηνή), 'tent; the stage-building' | the harness: it holds the performance, supplies the props and enforces the stage's limits |
| The doing | *praxis* (πρᾶξις), 'doing, action' | the project: where the work and its capabilities sit |
| The festival | *heortē* (ἑορτή), 'feast, festival' | the task: a named occasion, with a beginning and an end, that several sessions serve |
| The scene | *epeisodion* (ἐπεισόδιον), 'the part between choral odes' | the session: one run from its first prompt to its close; it is when the agent acts, never where anything is kept |
| The chorus-leader | *chorēgos* (χορηγός), 'chorus-leader; sponsor' | the person in the loop: sets the work and prompts the actor |

The analogy holds at its centre, the mask, and loosens at the edges: read it as a picture, not a rule.

It separates what acts from where and when it acts. The model acts; the persona shapes how; the harness and the
project are where the acting happens; the session is when. A review of a persona can judge only the mask, so
*persona-judge* scores the file and claims nothing about how a performance goes. A score does not predict behaviour,
and the report says so.

## A review (*euthynai*)

*Persona-judge* performs one kind of act: a review (*euthynai*, εὔθυναι, 'setting straight, correction', 'calling to
account'). At Athens, *euthynai* was the examination of an official when the term of office ended. A review marks an
instruction text an agent loads against a named standard of how such a text is written, the review questions, and
returns the marks to the text's author. It decides nothing about the text's passage.

That is why the report holds no verdict. A verdict admits or refuses work's passage to its next stage against a named
standard. *Persona-judge* never decides that: the author, or whoever approves the text, decides what the marks allow.

The character of an act (*thiasos*, θίασος, 'troupe, company') differs from behaviour. Behaviour is what an agent does;
the character of an act is what kind of work that doing is, whoever performs it: a review, an inquiry or a making.

## Capabilities

A capability sits somewhere, as code in a folder or prose a harness reads; an act is what happens when something takes
it up. A capability is spatial and an act is temporal. Two questions sort every capability.

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

## The Greek words

Each word pictures one of the skill's terms, as the analogy uses it:

| Greek, with its sense | The term it pictures |
|---|---|
| *prosōpon* (πρόσωπον), 'face; mask; dramatic part', then 'person' | persona |
| *hypokritēs* (ὑποκριτής), 'one who answers; interpreter; actor' | model |
| *skēnē* (σκηνή), 'a covered place, a tent', then 'a wooden stage for actors' | harness |
| *praxis* (πρᾶξις), 'doing, action' | project |
| *heortē* (ἑορτή), 'feast, festival, holiday' | task |
| *epeisodion* (ἐπεισόδιον), 'the portions of dialogue between two choric songs' | session |
| *chorēgos* (χορηγός), 'chorus-leader; sponsor' | the person in the loop |
| *euthynai* (εὔθυναι), 'setting straight, correction', 'calling to account' | review |
| *thiasos* (θίασος), 'troupe, company' | the character of an act |
| *kharaktēr* (χαρακτήρ), 'engraver', 'die, stamp', then a 'distinctive mark … by which it is known from others, characteristic, character' | characteristic: a mark a file leaves on the agent's conduct, as a stamp marks a coin |
| *ēthos* (ἦθος), 'disposition, character', 'as the result of habit'; also a character in a play | disposition: the steady conduct a persona aims to settle in the agent |
| *dynamis* (δύναμις), 'power, capacity' | capability |

## Where the senses come from

The Greek senses come from the Liddell-Scott-Jones *Greek-English Lexicon* in the Perseus TEI edition (LX1), all read at
one pinned revision, so a reader checks each sense against the same text.

## Sources

| Key | Source | Read |
|---|---|---|
| LX1 | Liddell, Scott and Jones, *A Greek-English Lexicon*, Perseus TEI edition, <https://github.com/PerseusDL/lexica>, at commit `56061ca127f4a2844980baffc5f2b6d1332897b3` | at that commit |

`persona-boundaries.md` quotes the vendors' own documents; their keys, such as AN1, are in
[`sources.md`](sources.md).
