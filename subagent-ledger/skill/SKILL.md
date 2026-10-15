---
name: subagent-ledger
description: "Keeps a record of every call a session makes outside itself. That means a call to a subagent, to another model through its command line, or to a web search, a page fetch or an MCP server. Hooks and scripts write it, not the agent. Use it before you hand work to a subagent or another model, and when a session closes. Use it also when the user asks what was delegated, searched or fetched, what it cost or what came back. Triggers: /subagent-ledger, record subagent calls, what did the subagents cost, list this session's calls, delegate this to Gemini or Cursor. Not for tool calls that stay inside the session, such as reading or editing files, or for judging a subagent's work."
---

# subagent-ledger

Hooks in the harness write a dispatch record when a call goes out and a return record when it comes back. The hook's
script that writes them is the capture. You do not write either record, and you never edit the ledger. What you do
before the call decides whether the records are correct.

In the commands below, `<skill>` is this skill's folder, the one holding this file.

## Before each call

Do these four things before every call:

1. **Name the kind of work.** Read the tests in [`scripts/kinds.json`](scripts/kinds.json). Put the one kind whose
   test the call meets in the brief's front matter as `act_kind:`. If the call meets none, or more than one, split it
   or leave the kind out. Never guess a kind.
2. **If the kind is `user-decision`, ask the user before anything else.** Only the user can settle such a call. Ask
   with the harness's question tool, such as `AskUserQuestion` in Claude Code, because a question asked in plain chat
   leaves nothing the record can find. Put what the user said in the brief's front matter as `user_answer:`. The
   ledger does not stop the call, so you must ask. Never send a `user-decision` call before the user answers. Where
   the harness has no question tool, ask in chat and expect the record to read `not found`. If you are a
   subagent, do not send the call: return the question to your caller.
3. **Write the brief to a file and give its absolute path as the first path in the prompt.** The capture takes the
   first readable file the prompt names as the brief. If another file comes first, such as the file under review, the
   capture records that file as the brief and reads its front matter instead.
4. **Name the model in the dispatch tool's own `model` setting** (the Agent tool's `model` in Claude Code), even when
   it is the default. The capture does not record a model named only in the brief.

A model called through the shell, such as `claude -p` or `codex exec`, is recorded with the command as its brief and
no kind. Codex encrypts the brief it passes to a subagent, so a Codex record carries no kind or user answer from the
brief. The call script covers only Gemini CLI and Cursor. For a Claude or Codex call that needs a brief and a kind,
send it as a subagent instead.

Searches, page fetches and MCP reads are recorded by the same hooks. You do nothing before them. A server named in
`config.json`'s `mcp_not_calls` is left out.

## Calls to Gemini CLI or Cursor

These have no hook, so make the call through the call script, which writes both records:

```bash
python3 <skill>/scripts/call.py --harness gemini-cli --brief <absolute path> --model <model>
python3 <skill>/scripts/call.py --harness cursor --brief <absolute path> --model <model>
```

It runs the call in a fresh folder and prints the answer. It ends with one of these exit codes:

- 0: the call served or came back empty, so check the answer is not empty;
- 1: the call failed; or
- 2: the command was wrong.

It finds your session from `CLAUDE_CODE_SESSION_ID` or `CODEX_THREAD_ID`. If neither is set, pass `--session <id>`.
It writes to the same ledger as the hooks; pass `--ledger <folder>` to name another.

## Reading the ledger

Run `calls.py` from the repository the session works in, or pass `--ledger <folder>`. If your hooks name a folder with
`--ledger`, pass the same folder here. Take the session ID from
`CLAUDE_CODE_SESSION_ID` in Claude Code or `CODEX_THREAD_ID` in Codex:

```bash
python3 <skill>/scripts/calls.py --session <session id>
```

To read one stretch of the session, such as the time since its last close, add `--since <time>`, and `--until <time>`
if you need an end. The count check and the received messages then cover that stretch alone.

It prints one JSON object with these top-level keys:

- `calls`: each call, joined from its two records, with its models, tokens, cost where reported and outcome;
- `peer_sessions`: each message sent to another running session, in the same shape as `calls`;
- `absences`: each call the ledger cannot show, with its reason;
- `received_messages`: each message another session sent this one, with its sender's session where the ledger shows
  it, present only with `--count-check`; and
- `count_check`: the result of the check below, present only with `--count-check`.

It makes no model call and changes nothing. It ends with one of these exit codes:

- 0: it listed the calls;
- 1: it refused the input;
- 2: it could not run;
- 3: it found no ledger for the session, or the count check could not read a transcript; or
- 4: the count check found the counts differ.

To check that no call escaped the record, give `--transcript` once for each transcript of the session: the parent's
and each subagent's. `--harness` takes `claude-code` or `codex`. The files are:

- Claude Code: `~/.claude/projects/<project>/<session id>.jsonl` for the parent, and each
  `~/.claude/projects/<project>/<session id>/subagents/agent-<id>.jsonl` for its subagents; and
- Codex: each `~/.codex/sessions/<year>/<month>/<day>/rollout-*-<id>*.jsonl` for the session and its subagents. The
  pattern also takes the files a long session continues into. Each subagent's ID is in the ledger's `agent_id`.

The command:

```bash
python3 <skill>/scripts/calls.py --session <id> --count-check --harness claude-code --transcript <path>
```

If the counts differ (exit 4), report the difference to the user. Exit 3 here usually means a transcript path was
wrong.

## At session close

Run the reader with the count check, as above. Report to the user the calls, every absence with its reason, and any
difference the count check found. Repair nothing.

## Leave these alone

Keep to these limits:

- Report a difference in the ledger. Never edit or repair the ledger by hand.
- Leave a harness's settings to the user, who adds the hooks.
- Use `calls.py`'s output as the interface. You need not read the capture scripts or `record.schema.json`.

## When no records appear

Check these, in order:

1. The session ID is right. A wrong ID gives exit 3, which does not mean no calls were made. Exit 2 means the
   ledger folder or the skill's scripts could not be found.
2. You ran `calls.py` from the session's repository, or passed the right `--ledger` (or `SUBAGENT_LEDGER_DIR`).
3. The hooks are in the harness's settings. If not, point the user to the 'Install' section of the skill's README.
   Follow this skill's folder link to its source; the README sits beside it.
4. In Codex, the hooks are trusted. Codex skips an untrusted hook without saying so. The user trusts them in the Codex
   app's Settings → Hooks, or with `/hooks` in the Codex command-line interface (CLI), then starts a fresh session.
