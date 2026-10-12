# Skills

A collection of agent skills for Claude Code, Codex and Gemini CLI, by Cam Parker. Each skill sits in its
own folder with its own README and installers, so you can take only the one you want.

The collection holds three skills so far:

| Skill | What the skill does |
|---|---|
| [*dry-run*](dry-run/) | Tests a planned change before the change is merged, published or put to use, to find what the change would break. Every check must first show that the check can fail, and the agent commits its predictions before looking. |
| [*persona-judge*](persona-judge/) | Reviews dedicated agent personas, such as subagents and custom agents, and scores each out of five stars. Every line that lowered the score is quoted, and no file is changed. |
| [*subagent-ledger*](subagent-ledger/) | Keeps a record of every call a session makes to a subagent or another model. Hooks write a record when each call goes out and when it comes back, so the agent never writes its own. |

## Install a skill

Clone this repository, then run the installer inside the skill's folder:

```bash
git clone https://github.com/camparkr/skills.git
cd skills/dry-run
./setup.sh --dry-run   # show what would change
./setup.sh             # link the skill into Claude Code, Codex and Gemini, where installed
```

In Claude Code, *persona-judge* also installs as a plugin from this repository's marketplace:

```text
/plugin marketplace add camparkr/skills
/plugin install persona-judge@camparkr-skills
```

Each skill's README covers the skill's purpose, its audience and its use.

## Layout

Each skill folder holds the skill itself in `skill/`, which is
what the installers link, beside a README, an index and the installers. `.claude-plugin/marketplace.json` lists the
skills that also install as Claude Code plugins. The `index.md` file here lists every skill.

## Licence

MIT. See `LICENSE`.
