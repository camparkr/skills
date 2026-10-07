"""Tests for the Claude Code plugin manifest and the repository's marketplace file.

`.claude-plugin/plugin.json` sits at the plugin root, persona-judge/, and names the plugin persona-judge, with a
description from SKILL.md's and the author camparkr. It declares the skill folder, skill/, the reviewer agent under
plugin/agents/ and the hook file under plugin/hooks/. `.claude-plugin/marketplace.json` sits at the repository root,
names the marketplace camparkr-skills and lists persona-judge with source ./persona-judge. Every path either file
names starts with ./ and exists inside the plugin root.

The hook file runs guard.py on every Bash call, at a path that exists, so the reviewer's rule to change no file is
enforced by the harness; a control plants a hook that misses Bash calls and one whose path does not exist.
"""

import json
import os
import shutil
import subprocess
import unittest
from pathlib import Path

from support import PLUGIN, ROOT, SKILL, ScratchCase

PLUGIN_JSON = ROOT / ".claude-plugin" / "plugin.json"
# What plugin.json declares, each path relative to the plugin root.
DECLARED = {
    "skills": ["./skill"],
    "agents": ["./plugin/agents/persona-judge-reviewer.md"],
    "hooks": "./plugin/hooks/hooks.json",
}
# The hook's command, and the file it runs relative to the plugin root.
HOOK_COMMAND = 'python3 "${CLAUDE_PLUGIN_ROOT}/skill/scripts/guard.py"'
PLUGIN_ROOT_VARIABLE = "${CLAUDE_PLUGIN_ROOT}"
MARKETPLACE_JSON = ROOT.parent / ".claude-plugin" / "marketplace.json"


def skill_description(skill_md):
    """The description from SKILL.md's front matter, with its surrounding quotes removed."""
    for line in Path(skill_md).read_text(encoding="utf-8").splitlines()[1:]:
        if line.startswith("description:"):
            return line.split(":", 1)[1].strip().strip('"')
        if line == "---":
            break
    raise AssertionError("SKILL.md has no description")


def path_faults(paths, plugin_root):
    """Faults in the paths a manifest names: each must start with ./ and exist inside the plugin root."""
    root = Path(plugin_root).resolve()
    faults = []
    for path in paths:
        if not path.startswith("./"):
            faults.append(f"{path} does not start with ./")
            continue
        target = (root / path).resolve()
        if root != target and root not in target.parents:
            faults.append(f"{path} leaves the plugin root")
        elif not target.exists():
            faults.append(f"{path} does not exist")
    return faults


def plugin_faults(plugin_root, skill_md):
    """Faults in plugin.json; empty when every rule holds."""
    path = Path(plugin_root) / ".claude-plugin" / "plugin.json"
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as err:
        return [f"plugin.json unreadable: {err}"]
    faults = []
    if data.get("name") != "persona-judge":
        faults.append(f"name is {data.get('name')!r}")
    if data.get("description") != skill_description(skill_md):
        faults.append("description differs from SKILL.md's")
    author = data.get("author")
    if not isinstance(author, dict) or author.get("name") != "camparkr":
        faults.append(f"author is {author!r}")
    named = []
    for key in ("skills", "agents", "hooks", "commands"):
        value = data.get(key)
        named += [value] if isinstance(value, str) else [v for v in value or [] if isinstance(v, str)]
    for key, want in DECLARED.items():
        if data.get(key) != want:
            faults.append(f"{key} is {data.get(key)!r}, not {want!r}")
    return faults + path_faults(named, plugin_root)


def hook_faults(plugin_root):
    """Faults in the hook plugin.json declares: it must run guard.py on every Bash call, before the call, at a path
    that exists in the plugin. Empty when every rule holds."""
    root = Path(plugin_root)
    try:
        manifest = json.loads((root / ".claude-plugin" / "plugin.json").read_text(encoding="utf-8"))
        data = json.loads((root / manifest["hooks"]).read_text(encoding="utf-8"))
    except (OSError, ValueError, KeyError, TypeError) as err:
        return [f"the hook file is unreadable: {err}"]
    groups = data.get("hooks", {}).get("PreToolUse", [])
    # A matcher of exactly Bash, with no condition beside it, catches every Bash call.
    commands = [h.get("command") for g in groups if g.get("matcher") == "Bash" and set(g) == {"matcher", "hooks"}
                for h in g.get("hooks", []) if h.get("type") == "command"]
    faults = []
    if commands != [HOOK_COMMAND]:
        faults.append(f"PreToolUse on every Bash call runs {commands!r}, not [{HOOK_COMMAND!r}]")
    for command in commands:
        path = command.split('"')[1] if command.count('"') == 2 else ""
        if not path.startswith(PLUGIN_ROOT_VARIABLE + "/"):
            faults.append(f"{command!r} names no path inside the plugin")
        elif not (root / path[len(PLUGIN_ROOT_VARIABLE) + 1 :]).is_file():
            faults.append(f"{path} does not exist")
    return faults


def marketplace_faults(repo_root):
    """Faults in marketplace.json; empty when every rule holds."""
    path = Path(repo_root) / ".claude-plugin" / "marketplace.json"
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as err:
        return [f"marketplace.json unreadable: {err}"]
    faults = []
    if data.get("name") != "camparkr-skills":
        faults.append(f"name is {data.get('name')!r}")
    owner = data.get("owner")
    if not isinstance(owner, dict) or not owner.get("name"):
        faults.append("owner.name is missing")
    plugins = data.get("plugins")
    entries = [p for p in plugins if isinstance(p, dict)] if isinstance(plugins, list) else []
    mine = [p for p in entries if p.get("name") == "persona-judge"]
    if len(mine) != 1:
        return faults + ["plugins does not list persona-judge once"]
    if mine[0].get("source") != "./persona-judge":
        faults.append(f"source is {mine[0].get('source')!r}")
    return faults + path_faults([str(mine[0].get("source"))], repo_root)


class TestPlugin(ScratchCase):
    def test_plugin_json(self):
        self.assertEqual(plugin_faults(ROOT, SKILL / "SKILL.md"), [])

    def test_marketplace_json(self):
        self.assertEqual(marketplace_faults(ROOT.parent), [])

    def test_hooks_json(self):
        """plugin/hooks/hooks.json runs guard.py on every Bash call, and the path it names exists in the plugin."""
        self.assertEqual(hook_faults(ROOT), [])
        self.assertTrue((PLUGIN / "hooks" / "hooks.json").is_file())

    def test_control_hook(self):
        """A hook that misses some Bash calls, or runs a guard that does not exist, is a fault."""
        repo, plugin = self.scratch()
        self.assertEqual(hook_faults(plugin), [])
        hooks = plugin / "plugin" / "hooks" / "hooks.json"
        data = json.loads(hooks.read_text(encoding="utf-8"))
        data["hooks"]["PreToolUse"][0]["matcher"] = "Read"
        hooks.write_text(json.dumps(data), encoding="utf-8")
        self.assertEqual(hook_faults(plugin), [f"PreToolUse on every Bash call runs [], not [{HOOK_COMMAND!r}]"])
        data["hooks"]["PreToolUse"][0]["matcher"] = "Bash"
        hooks.write_text(json.dumps(data), encoding="utf-8")
        (plugin / "skill" / "scripts" / "guard.py").unlink()
        self.assertEqual(hook_faults(plugin), ["${CLAUDE_PLUGIN_ROOT}/skill/scripts/guard.py does not exist"])

    def scratch(self):
        """A scratch repository holding copies of the two manifests, SKILL.md, the agent, the hook file and guard.py."""
        repo = self.tmp / "repo"
        plugin = repo / "persona-judge"
        (plugin / ".claude-plugin").mkdir(parents=True)
        (repo / ".claude-plugin").mkdir()
        (plugin / "skill" / "scripts").mkdir(parents=True)
        (plugin / "plugin" / "agents").mkdir(parents=True)
        (plugin / "plugin" / "hooks").mkdir(parents=True)
        shutil.copy(PLUGIN_JSON, plugin / ".claude-plugin" / "plugin.json")
        shutil.copy(MARKETPLACE_JSON, repo / ".claude-plugin" / "marketplace.json")
        shutil.copy(SKILL / "SKILL.md", plugin / "skill" / "SKILL.md")
        shutil.copy(SKILL / "scripts" / "guard.py", plugin / "skill" / "scripts" / "guard.py")
        shutil.copy(PLUGIN / "agents" / "persona-judge-reviewer.md", plugin / "plugin" / "agents")
        shutil.copy(PLUGIN / "hooks" / "hooks.json", plugin / "plugin" / "hooks")
        return repo, plugin

    def test_control_plugin(self):
        repo, plugin = self.scratch()
        self.assertEqual(plugin_faults(plugin, plugin / "skill" / "SKILL.md"), [])
        data = json.loads((plugin / ".claude-plugin" / "plugin.json").read_text())
        data.update(name="judge", author="camparkr", agents=["../elsewhere/agents/reviewer.md"])
        (plugin / ".claude-plugin" / "plugin.json").write_text(json.dumps(data))
        self.assertEqual(
            plugin_faults(plugin, plugin / "skill" / "SKILL.md"),
            ["name is 'judge'", "author is 'camparkr'",
             "agents is ['../elsewhere/agents/reviewer.md'], not ['./plugin/agents/persona-judge-reviewer.md']",
             "../elsewhere/agents/reviewer.md does not start with ./"],
        )
        (plugin / ".claude-plugin" / "plugin.json").write_text("{not json")
        self.assertEqual(len(plugin_faults(plugin, plugin / "skill" / "SKILL.md")), 1)

    def test_control_marketplace(self):
        repo, plugin = self.scratch()
        self.assertEqual(marketplace_faults(repo), [])
        data = json.loads((repo / ".claude-plugin" / "marketplace.json").read_text())
        data["name"] = "skills"
        data["plugins"][0]["source"] = "./persona-judges"
        (repo / ".claude-plugin" / "marketplace.json").write_text(json.dumps(data))
        self.assertEqual(
            marketplace_faults(repo),
            ["name is 'skills'", "source is './persona-judges'", "./persona-judges does not exist"],
        )


# The Gemini CLI extension: its manifest, the reviewer's agent file and a link to the skill folder.
GEMINI_EXT = PLUGIN / "harness-agents" / "gemini"
GEMINI_EXT_AGENT = GEMINI_EXT / "agents" / "persona-judge-reviewer.md"
GEMINI_EXT_SKILL = GEMINI_EXT / "skills" / "persona-judge"
# Calls Gemini CLI's own loadAgentsFromDirectory, from the bundle file argv[1], on the folder argv[2], and prints the
# names of the agents it loads as JSON.
LOAD_AGENTS_JS = """
const m = await import(process.argv[1]);
const r = await m.loadAgentsFromDirectory(process.argv[2]);
console.log(JSON.stringify(r.agents.map((a) => a.name)));
process.exit(0);
"""


def gemini_bundle_files():
    """The files of the installed Gemini CLI's bundle that define loadAgentsFromDirectory; empty when there are none."""
    gemini = shutil.which("gemini")
    if not gemini:
        return []
    bundle = Path(os.path.realpath(gemini)).parent
    return sorted(p for p in bundle.glob("*.js")
                  if "async function loadAgentsFromDirectory(" in p.read_text(encoding="utf-8", errors="replace"))


def gemini_agents(bundle_file, folder):
    """The names Gemini CLI's loadAgentsFromDirectory, in bundle_file, loads from folder."""
    proc = subprocess.run(["node", "--input-type=module", "-e", LOAD_AGENTS_JS, bundle_file.as_uri(), str(folder)],
                          capture_output=True, text=True, timeout=120)
    if proc.returncode != 0:
        raise AssertionError(f"node failed on {bundle_file.name}: {proc.stderr}")
    return json.loads(proc.stdout.strip().splitlines()[-1])


class TestGeminiExtension(ScratchCase):
    """plugin/harness-agents/gemini/ is a Gemini CLI extension. Gemini CLI keeps only an agents/ entry that is a file,
    and a symlink is not, so the agent file is a real file; the skill is a relative link to skill/, so one copy of
    the skill exists. The policy stays out of a policies/ folder, since Gemini CLI drops an extension policy's allow
    rules."""

    def test_manifest(self):
        data = json.loads((GEMINI_EXT / "gemini-extension.json").read_text(encoding="utf-8"))
        self.assertEqual(data.get("name"), "persona-judge")
        self.assertTrue(data.get("version"))

    def test_agent_is_a_regular_file(self):
        self.assertTrue(GEMINI_EXT_AGENT.is_file(), GEMINI_EXT_AGENT)
        self.assertFalse(GEMINI_EXT_AGENT.is_symlink(), f"{GEMINI_EXT_AGENT} is a symlink, which Gemini CLI skips")

    def test_skill_resolves_to_the_one_skill_folder(self):
        self.assertTrue(GEMINI_EXT_SKILL.is_symlink())
        self.assertFalse(os.path.isabs(os.readlink(GEMINI_EXT_SKILL)), "the skill link must be relative")
        self.assertEqual((GEMINI_EXT_SKILL / "SKILL.md").resolve(), (SKILL / "SKILL.md").resolve())

    def test_no_policies_folder(self):
        self.assertFalse((GEMINI_EXT / "policies").exists())

    def test_real_gemini_loads_the_reviewer(self):
        """Linked into a scratch GEMINI_CLI_HOME, the extension's agents/ folder gives Gemini CLI's own loader the
        reviewer; a control shows the same loader skipping a symlink to the same file."""
        if not shutil.which("gemini") or not shutil.which("node"):
            self.skipTest("gemini or node is not installed")
        bundle_files = gemini_bundle_files()
        if not bundle_files:
            self.skipTest("this Gemini CLI's bundle defines no loadAgentsFromDirectory")
        home = self.tmp / "gemini-home"
        home.mkdir()
        proc = subprocess.run(["gemini", "extensions", "link", "--consent", str(GEMINI_EXT)], cwd=self.tmp,
                              env=dict(os.environ, GEMINI_CLI_HOME=str(home)), capture_output=True, text=True,
                              timeout=180)
        self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
        record = json.loads((home / ".gemini" / "extensions" / "persona-judge" / ".gemini-extension-install.json")
                            .read_text(encoding="utf-8"))
        self.assertEqual(record, {"source": str(GEMINI_EXT), "type": "link"})
        linked = Path(record["source"]) / "agents"
        symlinked = self.tmp / "symlinked"
        symlinked.mkdir()
        (symlinked / GEMINI_EXT_AGENT.name).symlink_to(GEMINI_EXT_AGENT)
        for bundle_file in bundle_files:
            self.assertEqual(gemini_agents(bundle_file, linked), ["persona-judge-reviewer"], bundle_file.name)
            self.assertEqual(gemini_agents(bundle_file, symlinked), [], bundle_file.name)


if __name__ == "__main__":
    unittest.main()
