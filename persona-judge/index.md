---
type: index
title: Persona-judge skill repository
description: One line per file in the persona-judge skill's repository, saying what each file holds.
tags: [index, skill, persona-judge]
---

# Persona-judge skill repository

The folder holds these files:

- `README.md`: what the skill does and how to install the skill;
- `evidence.md`: a summary of the record kept while the skill was built: how it was gathered, what it found and where
  it falls short;
- `.claude-plugin/plugin.json`: the manifest that makes this folder a Claude Code plugin;
- `plugin/agents/persona-judge-reviewer.md`: the reviewer as a Claude Code plugin agent, generated from `reviewer.md`;
- `plugin/hooks/hooks.json`: the plugin hook that lets the reviewer's shell run only the skill's scripts;
- `plugin/harness-agents/gemini/persona-judge-reviewer.md` and
  `plugin/harness-agents/codex/persona-judge-reviewer.toml`: the reviewer as a Gemini CLI agent and a Codex agent,
  generated from `reviewer.md`, which `setup.sh` links;
- `plugin/harness-agents/gemini/persona-judge.toml`: the Gemini CLI policy that lets the reviewer agent's shell run
  only `python3`, which `setup.sh` installs;
- `tools/make_agents.py`: writes the three agent files from `reviewer.md`;
- `definitions.md`: for people, the analogy from the Greek theatre the terms are set in, a review (*euthynai*), the
  kinds of capability and the sense of each Greek word; the agent never loads it;
- `setup.sh`: the installer for macOS and Linux, which links the skill into Claude Code, Codex and Gemini CLI, links
  the reviewer agent into Codex and Gemini CLI, and has a switch that shows what would change;
- `setup.ps1`: the installer for Windows, which links the skill into Claude Code and has the same switch;
- `skill/SKILL.md`: the skill's entry point, with the steps for the agent that starts the reviewer;
- `skill/reviewer.md`: the persona of the agent that runs a review and composes its report, with its
  rules and steps;
- `skill/steps/`: the detail of the reviewer's steps, one file for each step that needs one, read at that step;
- `skill/references/questions/`: the questions, their scales and weights, and the scoring formula, each file read at
  the step that uses it;
- `skill/references/sample-review.md`: the form every report takes, shown on one persona;
- `skill/references/persona-boundaries.md`: what each term means in a review, and what a persona is not;
- `skill/references/grounding.md`: what each question rests on, and the words its sources say;
- `skill/references/vendor-terms.md`: what each vendor calls a persona and what it says a persona has;
- `skill/references/sources.md`: every source by its key, with the date each was read;
- `skill/references/failures.tsv`: the table of checks `check.py` runs without a model;
- `skill/references/harness-defaults.tsv`: what each harness already does, which a persona need not ask
  for;
- `skill/scripts/guard.py`: the hook's check, which refuses any shell command of the reviewer's but the
  skill's scripts;
- `skill/scripts/find.py`: finds the personas in a project and sets aside the files that are not
  personas;
- `skill/scripts/check.py`: runs the table of checks against persona files;
- `skill/scripts/report.py`: checks a review record, renders the report and recomputes its totals;
- `skill/scripts/questions.py`: reads the review questions, their weights and what applies, for the other
  scripts;
- `skill/scripts/personafile.py`: reads a persona file for the other scripts;
- `tests/`: the scripts' tests, their fixtures, the evaluation cases and the trigger requests in
  `tests/triggers.json`.
