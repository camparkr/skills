---
name: persona-judge
description: "Reviews dedicated agent personas, such as Claude Code and Gemini CLI subagents or Codex and GitHub Copilot custom agents, and scores each out of five stars, quoting every line that lowered the score. Use when someone asks to review, check, audit or score an agent's instructions, or asks why a subagent ignores its rules, misuses its tools or keeps stopping to ask. Triggers: /persona-judge, review a subagent, check agent instructions, score this custom agent, why does the agent ignore this rule. Changes no file and offers no rewrite. Not for project instructions files such as CLAUDE.md or AGENTS.md, output styles, reviewing a skill (use skill-judge), linting settings or hooks, or writing a new prompt."
---

# persona-judge

A review of each dedicated agent persona in a project: a subagent or custom agent with its own instructions, and
often its own tools. *Persona-judge* answers the questions in `references/review-questions.md` for each one, scores it
out of five stars and quotes every line that lowered the score. Each persona is judged by what its text makes the
agent do: a line counts for what it tells the agent, not for what its author meant.

## Terms

The review uses these words in one sense each:

- a **persona** is a dedicated agent, as `references/review-questions.md` defines it, and it may span several
  files;
- a file is **set aside** when it is not reviewed, with the reason printed: project instructions, an output style, a
  README, a skill, or a file scoring 0 on 'A dedicated persona';
- a **question** is a **check**, met or not, or a **rating**, a point on a seven-point scale; `review-questions.md`
  defines each kind, its scales and its weights;
- a **place** is a spot in the file that a rating applies to;
- a question **does not apply** when a branch or a content test in 'Which questions apply' removes it, with the
  reason printed;
- a **finding** is one quoted **line** that lowers a score, with its question and sources; and
- the **total** is the points given out of the points possible, less those that do not apply, and sets the **stars**.

## The reviewer's rules

The rules that hold in every act of a review, what the reviewer returns, what it never does and the errors it checks
before returning are in [`agents/reviewer.md`](agents/reviewer.md), the persona the review runs as.

## Judgement calls

Some answers turn on judgement. Settle them this way:

- count a place once, at the line that states it, so that a repeated rule shows as two places and 'Nothing said twice'
  can find it;
- count a place that half meets a question as not meeting it, and quote it, so the author sees what is missing;
- when two quality anchors both fit, give the lower point and quote the line that keeps it from the higher one,
  because a point no quoted line supports cannot be checked;
- mark a question as not applying only for a reason its table in 'Which questions apply' gives, and quote the line
  that holds the subject or say that no line does, so two reviews of one file leave out the same questions; and
- score 'Bound parts agree with the prose' 0 when a setting and the prose disagree, even where the prose is right,
  because the harness enforces the setting and not the prose.

## Requirement

The scripts need Python 3.11 or later and nothing beyond its standard library. Before a review, run
`python3 --version`. When Python is missing or older, tell the user the requirement and how to check it, give no
score and stop, because the score comes only from `scripts/report.py`.

## Steps for the agent the user asked

1. Run `python3 --version` and stop as 'Requirement' says if Python is older than 3.11.
2. Start a subagent briefed with [`agents/reviewer.md`](agents/reviewer.md). That agent orchestrates the review: it
   runs the scripts, answers the questions and composes the report, apart from your session. Give it what the user
   named: files, folders or pasted text. With nothing named, it reviews the whole project.
3. When the subagent cannot be started, or returns no report, tell the user that and why, and give no score, because
   the review runs apart from your session and you do not run it yourself.
4. Pass the subagent's output to the user as it is, with nothing added, because anything you add would read as part
   of the review.

## Steps for the subagent

`<skill>` below is the folder this file is in. Run every command from the project's folder.

Copy this checklist into your working notes and tick each step as you finish it:

```text
- [ ] 1. Read references/review-questions.md in full
- [ ] 2. Find the personas and their branches
- [ ] 3. Settle the files each persona loads
- [ ] 4. Run the script checks
- [ ] 5. Answer every other question for each persona
- [ ] 6. Write the review record
- [ ] 7. Validate the record until it exits 0
- [ ] 8. Render the report, delete the record and return the report
```

1. Read [`references/review-questions.md`](references/review-questions.md) in full.
2. Run `python3 <skill>/scripts/find.py [PATH ...] --format json`, with the paths the user named, or with `-` and the
   pasted text on standard input. It lists each persona with its kind and its branches, and each file it sets aside
   with the reason. Exit 3 means no persona was found: return that result and the files set aside, and stop. Exit 2
   means a path or the project's list could not be read: say which, and stop, because a review of part of the input
   would read as a review of all of it.
3. Settle the files each persona loads, in this order:
   1. Take the files its own text tells the agent to read, from the candidates `find.py` lists; a candidate loads
      when the persona's text tells the agent to read it in every review, and not when it is named only as an
      example or a source.
   2. Take the files the project's `personas.txt`, or the file `--list` names, lists with it.
   3. Where nearby files may belong to it and nobody can say, ask or leave them out as the reviewer's 'Ask first'
      section says.
4. Run `python3 <skill>/scripts/check.py [PATH ...] --format json` on the paths you gave `find.py`. Its rows set every
   check the review questions mark *script*. Exit 1 is the usual result: it means a check was not met, which the
   report then shows. Exit 3 means nothing was found to check: return that result and stop. Exit 2 is a fault in a
   file or the table: say which, and stop, because the checks it skipped would be missing from the score.
5. Answer every other question for each persona, reading every file it loads. Answer 'A dedicated persona' first; a
   file scoring 0 on it answers nothing else. When a file is empty, say so and give it no score; when part of a file
   cannot be read, review the rest and name the part skipped. Load
   [`references/persona-boundaries.md`](references/persona-boundaries.md) when a file may be something other than a
   persona, or before a finding blames the persona for the model, the harness or a hook, which the persona does not
   control. Leave it unloaded otherwise, because no other answer depends on it.
6. Run `python3 <skill>/scripts/report.py schema` and write the review record it describes, as one JSON file in the
   system's temporary folder, copying each persona's branches from `find.py`. Load
   [`references/sample-review.md`](references/sample-review.md) now, for the form the report takes; no earlier step
   needs it.
7. Run `python3 <skill>/scripts/report.py validate RECORD.json`. Fix each fault it lists and run it again until it
   exits 0, at most three reruns. Past that the fault is in the review, not the record: return the last messages and
   no report.
8. Run `python3 <skill>/scripts/report.py render RECORD.json`, adding `--summary` when there is more than one persona.
   Delete the record and return the report as the reviewer's 'What you return' section says. Exit 3 means no persona got
   a total, because each was empty, set aside or had no question apply: return what it printed.

Leave [`references/bibliography.md`](references/bibliography.md) unloaded during a review, because no score depends
on it. Load it only when someone asks for the source behind a question.

## Scripts

Run each script and read none of them into the session, because their output is the evidence, and reading their code
spends context and settles nothing. Each prints its usage with `--help` and changes no file.

- `find.py` finds the personas, their kinds and branches, and the files set aside.
- `check.py` runs the checks marked *script* from `references/failures.tsv`, using `references/harness-defaults.tsv`
  for what each harness already does. `check.py --exit-zero` turns its exit 1 into 0, for a hook that should not block
  a commit; a review does not need it.
- `report.py` validates the record, renders the report and recomputes a report's totals with `verify`.
- `questions.py` reads the review questions for the other three, and `personafile.py` reads persona files for them;
  neither is run on its own.
