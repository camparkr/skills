# subagent-ledger

[![Licence: MIT](https://img.shields.io/badge/licence-MIT-blue.svg)](../LICENSE)
![Version](https://img.shields.io/badge/version-0.2.5-green.svg)
![Python](https://img.shields.io/badge/python-3.9%2B-blue.svg)
![OS](https://img.shields.io/badge/OS-macOS%20%7C%20Linux-lightgrey.svg)
![Platforms](https://img.shields.io/badge/platforms-Claude%20Code%20%7C%20Codex%20%7C%20OpenCode%20%7C%20Gemini%20CLI%20%7C%20Cursor-lightgrey.svg)
![Dependencies](https://img.shields.io/badge/dependencies-none%20%28standard%20library%29-blue.svg)
![Install](https://img.shields.io/badge/install-hooks%20%7C%20plugin%20%7C%20call%20script-lightgrey.svg)
![Format](https://img.shields.io/badge/format-Agent%20Skill-green.svg)
![skill-judge](https://img.shields.io/badge/skill--judge-A-brightgreen.svg)

## Problem

An agent that hands work to subagents and other models, or searches and fetches from the web, keeps no dependable record of the calls. It does not keep
what it sent, which model ran, what it cost or whether it worked. Someone rebuilds the answers from transcripts afterwards, or remembers them wrongly.
*Subagent-ledger* writes that record as each call happens: one line when the call goes out and one when it comes back.
The harness's hooks and scripts write it, never the agent.

## Terms

This README uses a few working terms:

- **harness**: the program the agent runs in, such as Claude Code, Codex or OpenCode;
- **capture**: the script a hook runs, which writes the records;
- **dispatch record** and **return record**: the two lines for one call, written as it goes out and as it comes back;
- **absence**: a call the ledger cannot show in full, listed with its reason; and
- **label line**: a line beside a call that marks its conduct against a list of failure modes.

## What it records

For every call the session makes outside itself, the ledger records what was asked, what came back and the true
outcome. A call goes to a subagent, to another model through its command line, or to a web search, a page fetch or an
MCP server.

For a call to a subagent or a model, it also records:

- the brief and the answer, each kept as a file;
- the model asked for, beside the model that ran, read from the call's own transcript;
- the four token counters, read from that transcript, and the cost where the far end reports one;
- the true outcome (served, failed or empty), with the reason, such as not signed in or a usage limit;
- what the run touched outside its own folder; and
- the kind of work the call did and, where the call needed the user's decision, whether the user answered first.

For a search, a fetch or an MCP read, it records the query, the address or the tool's input. It keeps the answer as a
file, with its size or the number of results. A fetch's outcome includes its HTTP status, so a missing page reads as
failed.

A message to another running session is a call of its own. It makes that session answer, and the answer costs tokens.
The record names the receiving session and leaves the tokens to that session's own count, so they are counted once.

The capture also finds a model call inside a loop, a here-document or a script the command runs. A call that slips
past the record shows up as an absence with its reason, such as a call with no return. It does not disappear.

## Why use subagent-ledger

*Subagent-ledger* differs from the delegation tools we surveyed on 10 October 2026 in four ways:

- **One record per call.** It holds the brief, the model asked for, the model that ran, the token counts and the
  outcome. The tools we surveyed either rebuild usage from transcripts afterwards or log harness events without the
  brief and the model together.
- **A check for a person's decision before each call.** Three tests mark a call that needs someone to set its
  objective, accept a risk or approve its result. No developer sets approval flags in advance.
- **Evidence the person answered first.** The record reads that from the session itself and keeps it apart from the
  agent's own account. Tools that store approvals keep them as their own state. None we surveyed reads the transcript
  for the answer.
- **A kind of work for every call, with a test for each kind.** The record carries the kind wherever the harness
  passes the brief in readable form. Routing by kind of work is common; a test for every kind is not.

## Kinds of work

The agent names one kind in the brief, by the test it meets. A call that meets none, or more than one, has no kind,
and its record says so.

| Kind | Test |
|---|---|
| `verdict-or-review` | Does the call return a ruling on whether work may go ahead, or a review of instructions an agent loads, measured against a standard that existed before the work? |
| `deliberation` | Does the call settle or challenge how work still to be done should be shaped, without ruling on whether it may go ahead? |
| `build` | Does the call change what a program or an agent's instructions do, following a design already settled? |
| `inquiry` | Does the call return an account or a catalogue entry with its sources, without ruling on anything? |
| `archiving` | Does the call put a stored record out of use, bring it back or delete it, while it stays where it is stored? |
| `transfer` | Does the call move something from one place or system to another, so that it arrives unchanged? |
| `conversion` | Does the call change the conditions a program runs in, or the form of its input, without changing what the program does? |
| `user-decision` | Does the call need someone with authority over the work to set its objective, accept a risk no standing rule covers, or approve or refuse its result? |

## When the user must decide

A `user-decision` call is one only the user can settle. The skill tells the agent to ask the user before the call goes
out, with the harness's question tool. The record then shows whether an answered question came before the dispatch.

How the record treats it:

- the ledger records the question but never asks it, and never blocks, delays or changes the call;
- the record keeps the question and answer it finds in the transcript apart from what the agent says the user decided;
- only the transcript counts as evidence;
- a question asked in plain chat leaves no question call, so the record reads `not found`; and
- Claude Code is the only harness whose transcript the record reads for this today, and on the others the record says
  so.

## Record fields

Every call record carries a fixed frame: the call's ID, the agent's ID, the session, the time of each side and the
outcome. You switch every other field on or off (see 'Settings'). These fields cover the kind of work, the user's
answer and the label line:

| Field | Holds | Values come from | Filled by |
|---|---|---|---|
| `act_kind` | the kind of work the call does | one of the eight kinds, or `unrecorded (<reason>)` | the capture, from the brief |
| `user_answer` | whether the user answered before a `user-decision` call went out | the caller's transcript: the question call, when it was asked and when it was answered; the agent's own statement kept apart and never counted as the evidence | the capture |
| `triage_kind` | the kind the triage read from the brief, kept beside the brief's own | one of the eight kinds, or `unrecorded (<reason>)`, such as no triage ran | the capture, from the triage |
| `labelled_because` | why the call was labelled | `always: <kind>`, `outcome: <outcome>` or `failure row: <file>:<line>` | the labeller |
| `question_revision` | the revision of the questions the labeller asked | the question file's git blob ID | the labeller |
| `labeller_call_ids` | the IDs of the labeller's requests | the ledger | the labeller |
| `likelihoods` | each failure mode's answer: its expected level, each level's probability and the labeller's confidence | the labeller's requests | the labeller |
| `cutoff` | the lowest level that marks a mode: `2`, with a tie between levels going to the lower | the marking rule | the labeller |
| `failure_modes` | each failure mode marked, with its level and probability | the labeller | the labeller |

A label line sits beside a call in the same file and never rewrites its records. The skill writes and reads label
lines. It does not include a labeller.

## Known limits

The skill has these limits today:

- **Codex** encrypts every brief it passes to a subagent, so a Codex record carries no kind, task, persona or user
  answer from the brief.
- **OpenCode** reports no token counters, sign-in route or effort to a plugin, so its records read `unrecorded` for
  them.
- **A command-line call to another harness's program**, such as `codex exec` run from Claude Code, names no sign-in
  route. The capture does not read that program's sign-in.
- **Cursor** names no session in its own record, so a Cursor call's agent ID reads `unrecorded`.
- **A message to a subagent** is recorded only when the subagent's transcript shows its delivery in a form the skill
  lists. In any other form, no return is written, and the reader lists the message as a call without a return. If
  that happens while the subagent has already started on later work, the reader may show it only once the harness
  ends the hook.
- **A model call made by a script** the capture cannot see goes unrecorded, unless the script writes its own records.
- **A Codex subagent that fails to start** may be joined to the next subagent that does, because Codex's spawn names
  no agent. No such case has been seen yet.
- **A long shell command whose result Codex delivers through a later poll** is not yet read. The reader lists it.
- **A shell command that names a model program but calls none**, such as a loop, a here-document or a script that
  only mentions the program, may be recorded as a call. In tests on one workspace's sessions, about 2% of shell records
  were such commands.
- **Codex's web search** runs on the model service's side and fires no hook, so the capture cannot record it.
- **A Codex MCP read** is recorded. If the read fails, Codex sends no closing event, so the record shows a call with
  no return and the reader lists it as such.
- **A fetch through the shell**, such as `curl`, is not recorded.
- **A Claude Code fetch** keeps the model's summary of the page, not the page itself. That is all the harness returns.
- **A tool the harness refuses before it runs** writes no record.
- **A message received from another session** is listed by the reader, not recorded by the hooks. Its sender is named
  only once the sender's ledger holds a record from version 0.2.2 or later.
- **Messages between sessions** are linked by the desktop app's session ID. Where the app gives none, such as on the
  command line, the link reads `unrecorded`.
- **Ledgers written before version 0.2.5** overstate the tokens and the outside reach of a subagent resumed by a
  message, where the subagent hands its answer back by a tool call. Each such return counts every earlier turn as well
  as its own. From 0.2.5, a return counts its own turn alone.
- **A command in a record's outside list** keeps its first 200 characters, with its full length in `command_chars` and
  its paths listed whole. The subagent's own transcript holds the whole command.
- **Two messages a subagent answers in one turn** each carry that turn's answer and counts, so adding `tokens` across
  records counts that turn twice. Add each turn once.

## Who it is for

*Subagent-ledger* suits:

- anyone who has an agent delegate work and wants to know afterwards what went where, what came back and what it cost;
- teams who route work across several harnesses and models and need one record across them; and
- anyone who wants an agent to stop and ask before work only a person can settle, with evidence of whether it did.

It is not for logging tool calls that do not call a model, or for judging whether a subagent's work was good.

## Requirements

The skill needs:

- Python 3.9 or later and its standard library only (tested on 3.9.6 and 3.14.7);
- macOS or Linux, because the writer locks the ledger file with `fcntl`, which Windows lacks; and
- one of the harnesses tested: Claude Code 2.1.295, Codex 0.162 or OpenCode 1.18.30.

## Install

```bash
./setup.sh --dry-run   # show what would change
./setup.sh             # link the skill into Claude Code, Codex and OpenCode, where installed
```

The script links `skill/` and prints the hook entries for each harness with this folder's paths filled in. It never
writes a harness's settings. Each entry changes how your harness runs, so you add it yourself. Neither the links nor
the entries overwrite anything, and `--uninstall` removes only the links the script made. The entries it prints are
these, with `<skill>` standing for the full path to this folder's `skill/`:

**Claude Code.** Add these under `hooks` in your settings file:

```json
{
  "PreToolUse":         [{"matcher": "Agent|Task|Bash|SendMessage|TaskStop|WebSearch|WebFetch|mcp__.*", "hooks": [{"type": "command", "command": "python3 \"<skill>/scripts/capture_claude_code.py\" PreToolUse"}]}],
  "PostToolUse":        [{"matcher": "Agent|Task|Bash|SendMessage|TaskStop|WebSearch|WebFetch|mcp__.*", "hooks": [{"type": "command", "command": "python3 \"<skill>/scripts/capture_claude_code.py\" PostToolUse"}]}],
  "PostToolUseFailure": [{"matcher": "Agent|Task|Bash|SendMessage|WebSearch|WebFetch|mcp__.*", "hooks": [{"type": "command", "command": "python3 \"<skill>/scripts/capture_claude_code.py\" PostToolUseFailure"}]}],
  "SubagentStart":      [{"hooks": [{"type": "command", "command": "python3 \"<skill>/scripts/capture_claude_code.py\" SubagentStart"}]}],
  "SubagentStop":       [{"hooks": [{"type": "command", "command": "python3 \"<skill>/scripts/capture_claude_code.py\" SubagentStop"}]}]
}
```

`Bash` in the matcher records calls to other models made through their command line, such as `claude -p` or
`codex exec`. `SendMessage` records a message sent to a subagent that is already running. `TaskStop` records a
subagent the agent stops before it finishes. `WebSearch`, `WebFetch` and `mcp__.*` record searches, page fetches and
MCP reads. Without `PostToolUseFailure`, a failed call writes no return.

**Codex.** Add these under `hooks` in `hooks.json` in your Codex folder:

```json
{
  "PreToolUse":    [{"matcher": "Agent|Bash|spawn_agent|exec_command|collaborationspawn_agent|collaborationsend_message|collaborationfollowup_task|mcp__.*", "hooks": [{"type": "command", "command": "python3 \"<skill>/scripts/capture_codex.py\" PreToolUse"}]}],
  "PostToolUse":   [{"matcher": "Agent|Bash|spawn_agent|exec_command|collaborationspawn_agent|collaborationsend_message|collaborationfollowup_task|mcp__.*", "hooks": [{"type": "command", "command": "python3 \"<skill>/scripts/capture_codex.py\" PostToolUse"}]}],
  "SubagentStart": [{"hooks": [{"type": "command", "command": "python3 \"<skill>/scripts/capture_codex.py\" SubagentStart"}]}],
  "SubagentStop":  [{"hooks": [{"type": "command", "command": "python3 \"<skill>/scripts/capture_codex.py\" SubagentStop"}]}]
}
```

Codex names these tools differently across versions, so the matcher lists every name seen. `mcp__.*` records MCP
reads. Codex's own web search fires no hook (see 'Known limits'). Codex runs a hook only
once you have trusted it, and skips an untrusted one without saying so. In the Codex app, open Settings → Hooks and
trust each of the four. In the Codex command-line interface (CLI), type `/hooks` in a session and trust them there.
Then start a fresh session. A changed hook needs trusting again.

**OpenCode.** Link `skill/scripts/opencode-plugin/subagent-ledger.js` into OpenCode's plugin folder, and set
`SUBAGENT_LEDGER_SCRIPTS` to the full path of `skill/scripts`. The plugin also records `websearch`, `webfetch` and
each MCP tool, with nothing more to set.

**Gemini CLI and Cursor.** These need no capture. Make these calls through `<skill>/scripts/call.py`, which writes both
records.

## Use

Records go to `.subagent-ledger/` at the top of your repository, one file per session, unless `SUBAGENT_LEDGER_DIR`
names another folder. Ask your agent which calls this session made, or run
`python3 <skill>/scripts/calls.py --session <id>`.

To read one stretch of the session, such as the time since its last close, add `--since <time>`, and `--until <time>`
if you need an end. The count check and the received messages then cover that stretch alone.

The reader also lists the messages this session received, apart from its calls. It names each sender's session where
the sender's ledger shows it.

## Settings

A `config.json` in the ledger folder chooses the fields. With none, records carry the frame plus the model asked for,
the model that ran, the tokens, the cost and the outcome's reason. `"fields": "all"` turns every field on. A list
names the ones you want, and `"frame"` keeps only the frame. Each record names the fields that were on and those not
chosen, so a missing field is never mistaken for an empty one.

`config.json` also takes these settings:

- `frontmatter`: which keys in a brief's front matter give the kind of work, the user's answer, the persona and the
  task. With none, the capture reads `act_kind`, `user_answer`, `persona-name` and `task`.
- `kind_names`: a file that maps your own names for kinds of work to the eight above.
- `triage_command`: a command the capture runs as each call goes out, to read the kind of work from the brief. The
  command reads the brief and prints the kind it found. The record uses the brief's own kind and keeps the triage's
  reading beside it. With no command, the record says no triage ran.
- `harness_homes`: the configuration folder `call.py` gives Gemini CLI or Cursor.
- `mcp_not_calls`: the MCP servers whose tools act on your machine or the harness, such as a browser or a terminal,
  instead of fetching content. The capture records no call to them, and the count check leaves them out. A name
  ending in `*` covers every server whose name starts with the rest.

## Contents of this folder

The skill itself is in `skill/`, which is what `setup.sh` links. The rest is for people. The `index.md` in each folder
is a generated list of its files. Each file does this:

- `README.md`: this file.
- `setup.sh`: links the skill into Claude Code, Codex and OpenCode, and prints the hook entries for you to add.
- `skill/SKILL.md`: what an agent does before each call, and how it reads the ledger.
- `skill/scripts/ledger.py`: the one writer. Every line in the ledger goes through it. It checks each line against the
  schema and removes anything that looks like a secret. Then it keeps the brief and the answer as files and appends
  the line.
- `skill/scripts/capture_claude_code.py`: Claude Code's hook command. It writes both records for each subagent call,
  each message to a running subagent, each model call made through the command line, and each search, fetch and MCP
  read.
- `skill/scripts/capture_codex.py`: the same for Codex.
- `skill/scripts/capture_opencode.py` and `skill/scripts/opencode-plugin/subagent-ledger.js`: the same for OpenCode,
  through a plugin that hands each event to the capture.
- `skill/scripts/call.py`: makes one call to Gemini CLI or Cursor in a fresh folder and writes both records.
- `skill/scripts/calls.py`: reads the ledger. It lists every call joined from its two records and every absence with
  its reason. Given the transcripts, it also checks that no call was missed.
- `skill/scripts/transcripts.py`: reads a transcript for the model that ran, its four token counters and what the run
  touched.
- `skill/scripts/commands.py`: splits a shell command into its parts, so it finds a model call inside a longer command.
- `skill/scripts/record.schema.json`: the shape of every line the ledger holds.
- `skill/scripts/kinds.json`: the eight kinds of work and their tests.
- `skill/scripts/cli-patterns.json`: which commands count as a call to a model.
- `skill/scripts/reasons.json`: how the skill sorts a failure's message into a reason, such as not signed in.
- `skill/scripts/subagent-tools.json`: which tool starts a subagent in each harness, for the check that no call was
  missed.
- `skill/scripts/*.component.md`: a short record for each script, saying what it runs on, what it reads and what it
  depends on.
- `tests/`: the tests. Run them from this folder with `python3 -m unittest discover -s tests`.
