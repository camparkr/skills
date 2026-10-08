---
type: index
title: Dry-run skill repository
description: One line per file in the dry-run skill's repository, saying what each file holds.
tags: [index, skill, dry-run]
---

# Dry-run skill repository

The folder holds these files:

- `README.md`: what the skill does and how to install the skill;
- `setup.sh`: the installer for macOS and Linux, which links the skill into Claude Code, Codex and Gemini
  CLI and has a switch that shows what would change;
- `setup.ps1`: the installer for Windows, which links the skill into Claude Code and has the same switch;
- `skill/SKILL.md`: the skill's entry point, which names when each reference loads;
- `skill/references/session-record.md`: where the session's record lives, the optional test index,
  committing, lighter mode, citing versions, the record's template and filled example hypotheses;
- `skill/references/example-dry-runs.md`: one recorded dry run per kind of change;
- `skill/references/scratch-copies.md`: which copy each check needs, the fingerprint, making and removing
  the copies, and checking that nothing reached the real tree;
- `skill/references/item-answers.md`: how to record one answer per item, and the fields to use;
- `skill/references/when-things-go-wrong.md`: what to do when the objective, a control, a check or a
  commit goes wrong;
- `skill/references/briefing-others.md`: briefing a fresh reader or a subagent that runs the check, and the
  line a brief for an outside review carries;
- `skill/references/model-output-checks.md`: for checks that read a model's output, how to ask, the scout,
  reading with a classifier, isolation, the Nevers for that row and what each rule rests on;
- `skill/scripts/scratch-copy.sh`: makes and removes the scratch copies a dry run checks in;
- `skill/scripts/fingerprint.sh`: prints a fingerprint of the real repository's state, to catch leaks;
- `docs/why-each-never.md`: the recorded incidents and examples behind the Nevers, for maintainers; and
- `docs/sources.md`: each kind of test's source and its limit, and what rests on internal record only, for
  maintainers.
