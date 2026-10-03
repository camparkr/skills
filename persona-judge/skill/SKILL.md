---
name: persona-judge
description: "Reviews dedicated agent personas, such as Claude Code and Gemini CLI subagents or Codex and GitHub Copilot custom agents, and scores each out of five stars, quoting every line that lowered the score. Use when someone asks to review, check, audit or score an agent's instructions, or asks why a subagent ignores its rules, misuses its tools or keeps stopping to ask. Triggers: /persona-judge, review a subagent, check agent instructions, score this custom agent, why does the agent ignore this rule. Changes no file and offers no rewrite. Not for project instructions files such as CLAUDE.md or AGENTS.md, output styles, reviewing a skill (use skill-judge), linting settings or hooks, or writing a new prompt."
---

# persona-judge

A review of each dedicated agent persona in a project: a subagent or custom agent with its own instructions, and
often its own tools. *Persona-judge* answers 33 questions about each one, scores it out of five stars and quotes every
line that lowered the score. It changes no file.

## Contents

The file holds seven sections:

- terms, the words the review uses in one sense each;
- requirement, the Python version the scripts need;
- steps for the agent the user asked;
- steps for the subagent, with its checklist;
- judgement calls, for answers that turn on judgement;
- scripts, with each one's command line and output; and
- rules for every review.

## Terms

The review uses these words in one sense each:

- a **persona** is a dedicated agent, as `references/review-questions.md` defines it, and it may span several
  files;
- a file is **set aside** when it is not reviewed, with the reason printed: project instructions, an output style, a
  README, a skill, or a file scoring 0 on 'A dedicated persona';
- a **question** is one of the 33 in `references/review-questions.md`, in two **sections**, persona and instruction
  writing;
- a **check** scores 1 or 0, and a **rating** gives a point from 0 to 6 on a seven-point scale;
- a **place** is a spot in the file that a rating applies to;
- a **finding** is one quoted **line** that lowers a score, with its question and sources;
- a **subtotal** is a section's points given out of points possible, and the **total** adds the two; and
- the **stars** are the total divided by the points possible, times 5, to the nearest half star.

## Requirement

The scripts need Python 3.11 or later and nothing beyond its standard library. Before a review, run
`python3 --version`. When Python is missing or older, tell the user the requirement and how to check it, give no
score and stop: the score comes only from `scripts/report.py`.

## Steps for the agent the user asked

1. Check the requirement above.
2. Start a subagent briefed with [`agents/reviewer.md`](agents/reviewer.md). That agent orchestrates the review:
   it runs the scripts, answers the questions and composes the report, apart from your session. Give it what the
   user named: files, folders or pasted text. With nothing named, it reviews the whole project.
3. Pass the subagent's output to the user as it is, with nothing added.

## Steps for the subagent

Copy this checklist into your working notes and tick each step as you finish it:

```text
- [ ] 1. Read references/review-questions.md in full
- [ ] 2. Find the personas with find.py
- [ ] 3. Settle the files each persona loads
- [ ] 4. Run check.py
- [ ] 5. Answer every question for each persona
- [ ] 6. Write the review record
- [ ] 7. Validate the record until it exits 0
- [ ] 8. Render the report, delete the record and return the report
```

1. Read [`references/review-questions.md`](references/review-questions.md) in full.
2. Run `find.py` from the project's folder, with any paths the user named, or `-` for pasted text. It lists each
   persona with its kind and each file it sets aside with the reason. Exit 3 means no persona was found: return that
   result and the files set aside, and stop. Exit 2 means a path or the project's list could not be read: say which,
   and stop.
3. Settle the files each persona loads, in this order:
   1. Take the files its own text tells the agent to read, from the candidates `find.py` lists; decide which the
      persona loads.
   2. Take the files the project's `personas.txt`, or the file `--list` names, lists with it.
   3. Where nearby files may belong to it and nobody can say, ask the user one question, if someone is there to
      answer.
   4. With nobody to answer, review the persona file alone and name each nearby file as left out, with the reason.
4. Run `check.py` on the same paths. Its rows set every check the review questions mark *script*. Exit 1 is the
   usual result: it means a check scored 0, which the report then shows. Exit 2 is a fault in a file or the table:
   say which, and stop.
5. Answer every other question for each persona, reading every file it loads. Answer 'A dedicated persona' first; a
   file scoring 0 on it answers nothing else. For a rating, quote every place it applies to. Load
   [`references/persona-boundaries.md`](references/persona-boundaries.md) when a file may be something other than a
   persona.
6. Run `report.py schema` and write the review record it describes, as one JSON file in the system's temporary
   folder. Load [`references/sample-review.md`](references/sample-review.md) for the form the report takes.
7. Run `report.py validate` on the record. Fix each fault it lists and run it again until it exits 0, at most three
   reruns. Past that the fault is in the review, not the record: return the last messages and no report.
8. Run `report.py render` on the record, adding `--summary` when there is more than one persona. Delete the record
   and return the report as printed, and nothing else. Exit 3 means no persona got a total, because each was empty,
   set aside or had no question apply: return what it printed.

Load [`references/bibliography.md`](references/bibliography.md) only when someone asks for the source behind a
question.

## Judgement calls

Some answers turn on judgement. Settle them this way:

- count a place once, at the line that states it; a rule stated twice is two places, and 'Nothing said twice' also
  scores it;
- count a place that half meets a question as not meeting it, and quote it, so the author sees what is missing;
- when two quality anchors both fit, give the lower point and quote the line that keeps it from the higher one,
  because a point no quoted line supports cannot be checked;
- give 'not rated' only when the file has no place the question applies to, and say why; and
- score 'Bound parts agree with the prose' 0 when a setting and the prose disagree, even where the prose is right,
  because the harness enforces the setting and not the prose.

## Scripts

Run each script with its path in this skill's `scripts/` folder, and read none of them into the session: their
output is the evidence, and reading their code spends context and settles nothing. Each prints its usage with
`--help` and changes no file. `personafile.py` is imported by the others and is never run on its own.
`references/failures.tsv`, the table of checks, and `references/harness-defaults.tsv`, what each harness already does,
are read by `check.py`, not by you. `check.py --exit-zero` turns its exit 1 into 0, for a hook that should not block
a commit; a review does not need it.

| Script | Command | Output |
|---|---|---|
| `find.py` | `python3 scripts/find.py [PATH ...] [--list FILE] --format json` | each persona's path, kind, harness, candidates and listed files; each file set aside, with its reason |
| `check.py` | `python3 scripts/check.py [PATH ...] --format json` | one row per check and file: the row's ID, the score, the place, the quoted line and the message |
| `report.py` | `python3 scripts/report.py schema`, then `validate RECORD.json`, then `render [--summary] RECORD.json` | the record's shape; the faults, one per line; the report in a fenced text block |

## Rules for every review

Five rules hold in every act of a review:

- leave every file in the project as it is;
- quote and score, and leave the wording of any change to the author;
- review the version in front of you alone;
- describe with scores and quotes, with no verdict words or severity grades; and
- use neighbouring files only for the fit section.

[`agents/reviewer.md`](agents/reviewer.md) gives the reason for each, and lists the ways a review goes wrong, under
'How a review goes wrong'.
