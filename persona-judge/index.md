---
type: index
title: Persona-judge skill repository
description: One line per file in the persona-judge skill's repository, saying what each file holds.
tags: [index, skill, persona-judge]
---

# Persona-judge skill repository

The folder holds these files:

- `README.md`: what the skill does and how to install the skill;
- `setup.sh`: the installer for macOS and Linux, which links the skill into Claude Code, Codex and Gemini
  CLI and has a switch that shows what would change;
- `setup.ps1`: the installer for Windows, which links the skill into Claude Code and has the same switch;
- `skill/SKILL.md`: the skill's entry point, with the steps of a review and when each file loads;
- `skill/agents/reviewer.md`: the persona of the agent that runs a review and composes its report;
- `skill/references/review-questions.md`: the 33 questions, their scales and the scoring formula;
- `skill/references/sample-review.md`: the form every report takes, shown on one persona;
- `skill/references/persona-boundaries.md`: what a persona is not, and where each neighbour's review belongs;
- `skill/references/bibliography.md`: the source behind each question, with the date each was read;
- `skill/references/failures.tsv`: the table of checks `check.py` runs without a model;
- `skill/references/harness-defaults.tsv`: what each harness already does, which a persona need not ask for;
- `skill/scripts/find.py`: finds the personas in a project and sets aside the files that are not personas;
- `skill/scripts/check.py`: runs the table of checks against persona files;
- `skill/scripts/report.py`: checks a review record, renders the report and recomputes its totals;
- `skill/scripts/personafile.py`: reads a persona file for the other scripts;
- `tests/`: the scripts' tests, their fixtures, the evaluation cases and the trigger requests in
  `tests/triggers.json`.
