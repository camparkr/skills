// OpenCode plugin: hands each `task` call's before and after events to capture_opencode.py, which
// writes the call's dispatch and return records, and each `bash` call's, which the capture records when
// the command makes a model call. It also hands on each web search, web fetch and MCP read: the tools
// subagent-tools.json lists under OpenCode's `outside_tools`, and each tool named `<server>_<tool>` where
// `<server>` is a key of `mcp` in the OpenCode configuration in effect (the opencode.json or
// opencode.jsonc in the plugin's directory, and the global one in OpenCode's configuration folder), read
// once at start, the longest matching server name winning. An MCP tool's events carry the server's name
// as `mcp_server`. The tools it hands on are those subagent-tools.json lists for OpenCode, beside the
// capture; `task` and `bash` where that file cannot be read. It also hands on, from OpenCode's general
// event hook, each `message.part.updated` whose part is one of those tools' parts in state "error":
// OpenCode sends no `after` for a task whose subagent fails, or for a web call that fails, and that event
// is where the failure shows.
//
// Place this file in, or link it from, OpenCode's plugin folder, with SUBAGENT_LEDGER_DIR set to the
// ledger folder in the environment OpenCode starts with. The capture is found through
// SUBAGENT_LEDGER_SCRIPTS, then beside this file's own folder.
//
// The plugin never throws, never prints and never changes the call: it sends a copy of the event to
// the capture, discards the capture's output, and swallows any error after the capture has written
// its own error line.

import { spawnSync } from "child_process";
import { readFileSync } from "fs";
import { homedir } from "os";
import { dirname, join } from "path";
import { fileURLToPath } from "url";

const PYTHON = process.env.SUBAGENT_LEDGER_PYTHON || "python3";
// Searches, fetches and MCP reads are handed on. A test sets this false to show what the plugin handed on before.
const OUTSIDE_ON = true;

function scriptsDir() {
  const named = process.env.SUBAGENT_LEDGER_SCRIPTS;
  if (named) return named;
  return dirname(dirname(fileURLToPath(import.meta.url)));
}

function capturePath() {
  return join(scriptsDir(), "capture_opencode.py");
}

function handedOn() {
  try {
    const entry = JSON.parse(readFileSync(join(scriptsDir(), "subagent-tools.json"), "utf8")).harnesses.opencode;
    const outside = (OUTSIDE_ON && entry.outside_tools) || {};
    return new Set([...(entry.tools || []), ...(entry.shell_tools || []), ...(outside.search || []),
                    ...(outside.fetch || [])]);
  } catch (err) {
    return new Set(["task", "bash"]);
  }
}

const TOOLS = handedOn();

// The keys of `mcp` in one configuration file, JSON or JSON with comments; none where it cannot be read.
function serversIn(path) {
  try {
    let text = readFileSync(path, "utf8");
    text = text.replace(/("(?:[^"\\]|\\.)*")|\/\/[^\n]*|\/\*[\s\S]*?\*\//g, (whole, quoted) => quoted || "");
    text = text.replace(/,(\s*[}\]])/g, "$1");
    const mcp = JSON.parse(text).mcp;
    return mcp && typeof mcp === "object" ? Object.keys(mcp) : [];
  } catch (err) {
    return [];
  }
}

// The MCP servers the configuration in effect names: the plugin's directory's own file and the global one.
function configuredServers(directory) {
  if (!OUTSIDE_ON) return [];
  const global = join(process.env.XDG_CONFIG_HOME || join(homedir(), ".config"), "opencode");
  const found = new Set();
  for (const folder of [directory, global]) {
    if (!folder) continue;
    for (const name of ["opencode.json", "opencode.jsonc"]) {
      for (const server of serversIn(join(folder, name))) found.add(server);
    }
  }
  return [...found].sort((a, b) => b.length - a.length);
}

// The server an MCP tool's name begins with, `<server>_`, the longest match winning; null for any other tool.
function mcpServer(tool, servers) {
  if (typeof tool !== "string" || TOOLS.has(tool)) return null;
  for (const server of servers) {
    if (tool.length > server.length + 1 && tool.startsWith(server + "_")) return server;
  }
  return null;
}

function send(event, input, output, directory, servers) {
  try {
    if (!input) return;
    const server = mcpServer(input.tool, servers);
    if (!TOOLS.has(input.tool) && !server) return;
    const argv = [capturePath(), event];
    if (process.env.SUBAGENT_LEDGER_DIR) argv.push("--ledger", process.env.SUBAGENT_LEDGER_DIR);
    const payload = { input, output, directory };
    if (server) payload.mcp_server = server;
    spawnSync(PYTHON, argv, {
      input: JSON.stringify(payload),
      stdio: ['pipe', 'ignore', 'ignore'],
      env: process.env,
    });
  } /* guard */ catch (err) {}
}

function sendEvent(event, directory, servers) {
  try {
    if (!event || event.type !== "message.part.updated") return;
    const part = event.properties && event.properties.part;
    if (!part || part.type !== "tool") return;
    const server = mcpServer(part.tool, servers);
    const handed = OUTSIDE_ON ? (TOOLS.has(part.tool) && part.tool !== "bash") || server : part.tool === "task";
    if (!handed) return;
    if (!part.state || part.state.status !== "error") return;
    const argv = [capturePath(), "event", event.type];
    if (process.env.SUBAGENT_LEDGER_DIR) argv.push("--ledger", process.env.SUBAGENT_LEDGER_DIR);
    const payload = { event, directory };
    if (server) payload.mcp_server = server;
    spawnSync(PYTHON, argv, {
      input: JSON.stringify(payload),
      stdio: ['pipe', 'ignore', 'ignore'],
      env: process.env,
    });
  } /* event guard */ catch (err) {}
}

export const SubagentLedger = async (context) => {
  const directory = context && context.directory;
  const servers = configuredServers(directory);
  return {
    "tool.execute.before": async (input, output) => send("before", input, output, directory, servers),
    "tool.execute.after": async (input, output) => send("after", input, output, directory, servers),
    "event": async (arg) => sendEvent(arg && arg.event, directory, servers),
  };
};
