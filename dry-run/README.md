# dry-run

[![Licence: MIT](https://img.shields.io/badge/licence-MIT-blue.svg)](../LICENSE)
![Version](https://img.shields.io/badge/version-0.1.0-green.svg)
![Platforms](https://img.shields.io/badge/platforms-Claude%20Code%20%7C%20Codex%20%7C%20Gemini%20CLI-lightgrey.svg)
![Format](https://img.shields.io/badge/format-Agent%20Skill-green.svg)
![skill-judge: A](https://img.shields.io/badge/skill--judge-A-brightgreen.svg)

A skill that tests a planned change before the change is merged, published or put to use. *Dry-run* finds
what the change would break while the problem is still small and quick to fix.

*Dry-run* works with artificial intelligence (AI) agents that write code or documents. Before your agent
builds, merges or publishes a change, *dry-run* rehearses the change on a copy, or gives the change to a
separate reader new to the work. *Dry-run* then reports the outcome: what worked and what did not, with the
evidence for each. *Dry-run* decides nothing: the findings go to you. If any check fails or cannot settle its
hypothesis, the agent stops and leaves the decision to you.

## What dry-run guards against

Agents that check their own changes commonly make six mistakes:

- **Predictions made after the fact.** Once the result is in, almost any outcome can be made to look
  expected. *Dry-run* has the agent write down the expected result and commit that record before any check
  runs, so the order is on record.
- **Checks that cannot fail.** An agent runs a test, sees the test pass and reports success. But if the test
  would have passed either way, the pass tells you nothing. *Dry-run* has every check show first that the
  check can fail, by catching a fault planted in a copy or by failing on the old version.
- **Reruns taken as proof.** Running the same check twice shows that the check repeats, not that the check
  can tell a good change from a bad one. *Dry-run* never counts a rerun as proof that a check works.
- **Easy checks standing in for the real question.** A test chosen for being easy to run measures only what
  the test can see, not what the change is for. *Dry-run* starts every prediction from the change's purpose.
- **Agents checking their own work.** A model re-reading its own change tends to agree with itself.
  *Dry-run* gives redrafts, designs and decisions to a separate session or subagent that did not write them
  and does not know which copy holds a planted fault.
- **Effort spent on changes that cannot break anything.** Typos, broken links and rewording that leaves the
  meaning the same need no rehearsal. *Dry-run* tells the agent to fix those and keep its checks for changes
  that could break something.

## Why rehearse a change

The practices behind *dry-run* come from research and from tools you may already use:

- **Write the prediction down first.** Scientists call this *preregistration*. Nosek and colleagues (2018)
  show that people see outcomes as more predictable once they know them, and that fixing the plan before the
  results is the remedy.
- **Make sure the check can fail.** *Mutation testing* plants faults to see whether tests catch them. A
  study at Google found that developers who used mutation testing wrote more tests and improved their test
  suites, and that the planted faults resembled real ones (Petrović et al. 2021).
- **Give the work to a reader other than its author.** Huang and colleagues (2024) found that large language
  models struggle to correct their own reasoning without outside feedback, and sometimes get worse when they
  try.
- **Keep the rehearsal separate from the real test.** Clinical pilot studies test whether a trial can run,
  not whether the treatment works (Leon et al. 2011). Tools such as `terraform plan` and the dry-run mode in
  Kubernetes show a change before the change is applied. *Dry-run* draws the same line: a good rehearsal
  shows the plan is sound, and the finished work is still checked on its own.

Each source has limits, and the skill's sources file sets them out. *Dry-run* makes no claim that late fixes
always cost more; the evidence on that is mixed.

## Why use this skill

*Dry-run* offers five things a general-purpose agent does not do by default:

- **_Dry-run_ starts from what the work is for.** Each prediction begins with the change's purpose and asks
  what the change could break, not whether the paperwork is in order.
- **Each kind of change gets its own check.** A rename gets a count on a copy with a planted breakage. A
  code change runs the old code on the same cases. A redraft goes to two readers, and neither knows which
  copy holds the planted sentence.
- **_Dry-run_ stops the work when a check fails.** A failed or unclear result goes to the person who asked
  for the work, with what was seen.
- **_Dry-run_ leaves your files alone.** Checks that write run in copies outside your repository, and the
  agent confirms that nothing reached your files before finishing.
- **_Dry-run_ was tested on its own wording.** Changes to that wording went through blind comparisons, which
  caught instructions that had changed by accident and that re-reading had missed.

## Who the skill is for

*Dry-run* suits:

- anyone who has an AI agent change code, documents or plans and wants evidence before approving the
  change;
- teams whose agents carry out renames, migrations or refactors, where a quiet breakage shows up late; and
- writers and reviewers who redraft instructions, prompts or policy and need to know the new wording still
  says what they meant.

*Dry-run* is not for a tool's own `--dry-run` option, test-driven development or signing off finished work.

## Install

```bash
./setup.sh --dry-run   # show what would change
./setup.sh             # link into Claude Code, Codex and Gemini, where installed
```

On Windows, for Claude Code, run `powershell -ExecutionPolicy Bypass -File setup.ps1 -DryRun`, then run the
command again without `-DryRun`. Neither script overwrites anything, and `--uninstall` (`-Uninstall` on
Windows) removes only the links the script made. Gemini asks you to confirm each link, so run `setup.sh`
from a terminal.

## Use

Ask your agent to dry-run a change, or type `/dry-run`. Records go in a `dry-runs/` folder in your project,
unless your agent instructions (`AGENTS.md` or `CLAUDE.md`) name another place.

## Contents of this folder

`index.md` lists every file. The skill itself is in `skill/`, which is what the installers link. The rest is
for people: this README, the index and the installers.
