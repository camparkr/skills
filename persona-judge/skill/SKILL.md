---
name: persona-judge
description: "Reviews dedicated agent personas, such as Claude Code and Gemini CLI subagents (.claude/agents/*.md, .gemini/agents/*.md) or Codex and GitHub Copilot custom agents (.codex/agents/*.toml, .github/agents/*.agent.md), and scores each out of five stars, quoting every line that lowered the score. Use when someone asks to review, check, audit or score an agent's instructions, or asks why a subagent ignores its rules, misuses its tools or keeps stopping to ask. Triggers: /persona-judge, review a subagent, check agent instructions, score this custom agent, why does the agent ignore this rule. Changes no file and offers no rewrite. Not for project instructions files such as CLAUDE.md or AGENTS.md, output styles, reviewing a skill (use skill-judge), linting settings or hooks, or writing a new prompt."
---

# persona-judge

The review judges each persona by what its text makes the agent do, not by what its author meant. It runs in its own
agent, the reviewer, so the session that asked for it neither shapes nor softens the score.

## Files

Read only [`reviewer.md`](reviewer.md), and only to brief the reviewer with it. The reviewer loads every other file as
its steps say.

## Steps

1. **Check Python.** Run `python3 --version`. The scripts need Python 3.11 or later and only its standard library.
   When Python is missing or older, tell the user and give no score, because only `scripts/report.py` computes it.
2. **Start the reviewer.** Start the installed reviewer by name: `persona-judge:persona-judge-reviewer` in the Claude
   Code plugin, or `persona-judge-reviewer` in Gemini CLI, Codex or OpenCode. Prefer it, because its harness enforces
   its tools, and the Claude Code plugin's hook runs `scripts/guard.py` to keep its shell to the skill's scripts.
   When the harness has no such agent or refuses it, start a subagent whose brief opens with the whole of
   [`reviewer.md`](reviewer.md), front matter included, and give it only the tools the front matter lists where the
   harness allows. Then tell the user that the rule to change no file rests on the reviewer's instructions alone. In
   this skill's test runs, a reviewer briefed this way held every tool, because the harness could not limit them for
   one call, and its reasoning effort could not be set.
   Where the harness lets you set the reasoning effort, set it high, because the review weighs every line.
3. **Brief it.** Give the reviewer four things and nothing more:
   - this folder's path as the harness reports it, the link path, not a resolved real path, because the reviewer's
     limits name the skill by that path;
   - the project's folder: the root of the repository that holds what the user named, or your current folder for
     pasted text or nothing named, because the reviewer runs its commands from there; when the named files sit in
     several projects, run one review for each;
   - what the user named: files, folders or pasted text, or nothing, which means the whole project; and
   - whether the user is there to answer a question, with any answer they have given.

   Any other instruction you add enters the review as one the persona never held.
4. **Report a reviewer that cannot start.** Tell the user why, and give no score, because a score from your own
   session would carry its instructions into the review.
5. **Pass on what it returns.** Give the user the reviewer's output whole, with nothing added or summarised, because
   the quoted lines are what the author acts on. When the output is a line starting 'Question:', ask the user once,
   then start the reviewer again with the same brief and the answer. When the user does not answer, or the reviewer
   asks again, start it with a brief that says nobody is there to answer, so the review ends.
