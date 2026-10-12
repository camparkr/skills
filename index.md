---
type: index
title: Skills
description: One line per skill in this repository, saying what each skill does.
tags: [index, skill]
---

# Skills

The repository holds three skills:

- `dry-run/`, which tests a planned change before the change is merged, published or put to use, to find
  what the change would break, with the skill's files listed in `dry-run/index.md`;
- `persona-judge/`, which reviews dedicated agent personas and scores each out of five stars, quoting every
  line that lowered the score, with the skill's files listed in `persona-judge/index.md`; and
- `subagent-ledger/`, which keeps a record of every call a session makes to a subagent or another model, written by
  hooks rather than the agent, with the skill's files listed in `subagent-ledger/index.md`.

`.claude-plugin/marketplace.json` lists the skills that also install as Claude Code plugins: `persona-judge`.
