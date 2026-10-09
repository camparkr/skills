// OpenCode plugin: hands each `task` call's before and after events to capture_opencode.py, which
// writes the call's dispatch and return records. It also hands on, from OpenCode's general event
// hook, each `message.part.updated` whose part is a `task` tool part in state "error": OpenCode sends
// no `after` for a task whose subagent fails, and that event is where the failure shows.
//
// Place this file in, or link it from, OpenCode's plugin folder, with SUBAGENT_LEDGER_DIR set to the
// ledger folder in the environment OpenCode starts with. The capture is found through
// SUBAGENT_LEDGER_SCRIPTS, then beside this file's own folder.
//
// The plugin never throws, never prints and never changes the call: it sends a copy of the event to
// the capture, discards the capture's output, and swallows any error after the capture has written
// its own error line.

import { spawnSync } from "child_process";
import { dirname, join } from "path";
import { fileURLToPath } from "url";

const PYTHON = process.env.SUBAGENT_LEDGER_PYTHON || "python3";

function capturePath() {
  const named = process.env.SUBAGENT_LEDGER_SCRIPTS;
  if (named) return join(named, "capture_opencode.py");
  return join(dirname(dirname(fileURLToPath(import.meta.url))), "capture_opencode.py");
}

function send(event, input, output, directory) {
  try {
    if (!input || input.tool !== "task") return;
    const argv = [capturePath(), event];
    if (process.env.SUBAGENT_LEDGER_DIR) argv.push("--ledger", process.env.SUBAGENT_LEDGER_DIR);
    spawnSync(PYTHON, argv, {
      input: JSON.stringify({ input, output, directory }),
      stdio: ['pipe', 'ignore', 'ignore'],
      env: process.env,
    });
  } /* guard */ catch (err) {}
}

function sendEvent(event, directory) {
  try {
    if (!event || event.type !== "message.part.updated") return;
    const part = event.properties && event.properties.part;
    if (!part || part.type !== "tool" || part.tool !== "task") return;
    if (!part.state || part.state.status !== "error") return;
    const argv = [capturePath(), "event", event.type];
    if (process.env.SUBAGENT_LEDGER_DIR) argv.push("--ledger", process.env.SUBAGENT_LEDGER_DIR);
    spawnSync(PYTHON, argv, {
      input: JSON.stringify({ event, directory }),
      stdio: ['pipe', 'ignore', 'ignore'],
      env: process.env,
    });
  } /* event guard */ catch (err) {}
}

export const SubagentLedger = async (context) => {
  const directory = context && context.directory;
  return {
    "tool.execute.before": async (input, output) => send("before", input, output, directory),
    "tool.execute.after": async (input, output) => send("after", input, output, directory),
    "event": async (arg) => sendEvent(arg && arg.event, directory),
  };
};
