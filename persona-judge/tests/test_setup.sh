#!/usr/bin/env bash
# test_setup.sh: test that setup.sh installs the skill for Claude Code, with HOME set to a scratch folder and
# --harness claude, the reviewer's agent file for Codex and OpenCode, with --harness codex and opencode, and the Gemini
# CLI extension and the policy that limits the reviewer's shell, with --harness gemini.
# A stand-in `gemini` on the PATH does the work of `gemini extensions link` and `gemini extensions uninstall`, so no
# real harness is called.
# The installer runs from a scratch copy of persona-judge/ holding a stand-in SKILL.md and a copy of the policy, so the
# test needs no prose file and writes nothing outside the scratch folders.
# Usage: tests/test_setup.sh. Exit 0 when every case holds, 1 when any does not.

set -u
HERE="$(cd "$(dirname "$0")" && pwd -P)"
SRC="$HERE/../setup.sh"
POLICY_SRC="$HERE/../plugin/harness-agents/gemini/persona-judge.toml"
SCRATCH="$(mktemp -d "${TMPDIR:-/tmp}/persona-judge-setup.XXXXXX")"
trap 'rm -rf "$SCRATCH"' EXIT
FAILURES=0

ok() { echo "ok: $1"; }
bad() { echo "NOT MET: $1"; FAILURES=$((FAILURES + 1)); }

[ -f "$SRC" ] || { echo "NOT MET: setup.sh is missing at $SRC"; exit 1; }

# A scratch copy of the skill folder, so the link target is a scratch folder too.
REPO="$SCRATCH/repo/persona-judge"
mkdir -p "$REPO/skill"
cp "$SRC" "$REPO/setup.sh"
printf -- '---\nname: persona-judge\ndescription: stand-in for the test\n---\n' > "$REPO/skill/SKILL.md"
SKILL_DIR="$(cd "$REPO/skill" && pwd -P)"
# Stand-ins for the generated agent file the installer links for Codex and for the Gemini CLI extension, and a copy of
# the policy.
mkdir -p "$REPO/plugin/harness-agents/codex" "$REPO/plugin/harness-agents/gemini/agents" \
	"$REPO/plugin/harness-agents/gemini/skills"
echo 'name = "persona-judge-reviewer"' > "$REPO/plugin/harness-agents/codex/persona-judge-reviewer.toml"
mkdir -p "$REPO/plugin/harness-agents/opencode"
printf -- '---\nmode: subagent\n---\n' > "$REPO/plugin/harness-agents/opencode/persona-judge-reviewer.md"
OPENCODE_AGENT="$(cd "$REPO/plugin/harness-agents/opencode" && pwd -P)/persona-judge-reviewer.md"
printf -- '---\nname: persona-judge-reviewer\n---\n' > "$REPO/plugin/harness-agents/gemini/agents/persona-judge-reviewer.md"
printf '{"name": "persona-judge", "version": "0.0.0"}\n' > "$REPO/plugin/harness-agents/gemini/gemini-extension.json"
ln -s ../../../../skill "$REPO/plugin/harness-agents/gemini/skills/persona-judge"
cp "$POLICY_SRC" "$REPO/plugin/harness-agents/gemini/persona-judge.toml"
CODEX_AGENT="$(cd "$REPO/plugin/harness-agents/codex" && pwd -P)/persona-judge-reviewer.toml"
GEMINI_EXT="$(cd "$REPO/plugin/harness-agents/gemini" && pwd -P)"

H1="$SCRATCH/home1"
mkdir -p "$H1/.claude"
LINK="$H1/.claude/skills/persona-judge"

# 1. --dry-run changes nothing.
out="$(HOME="$H1" bash "$REPO/setup.sh" --dry-run --harness claude 2>&1)"
if [ ! -e "$LINK" ] && [ ! -L "$LINK" ] && printf '%s' "$out" | grep -q "Dry run: nothing was changed."; then
	ok "--dry-run made no link"
else
	bad "--dry-run: $out"
fi

# 2. Install makes the link, in the scratch HOME only.
out="$(HOME="$H1" bash "$REPO/setup.sh" --harness claude 2>&1)"
if [ -L "$LINK" ] && [ "$(cd "$LINK" && pwd -P)" = "$SKILL_DIR" ]; then
	ok "install linked $LINK to the skill folder"
else
	bad "install: $out"
fi

# 3. A second run leaves the link as is.
before="$(ls -l "$LINK")"
out="$(HOME="$H1" bash "$REPO/setup.sh" --harness claude 2>&1)"
if printf '%s' "$out" | grep -q "already linked, left as is" && [ "$(ls -l "$LINK")" = "$before" ]; then
	ok "second run left the link as is"
else
	bad "second run: $out"
fi

# 4. --uninstall removes the link and leaves the skill folder.
out="$(HOME="$H1" bash "$REPO/setup.sh" --uninstall --harness claude 2>&1)"
if [ ! -e "$LINK" ] && [ ! -L "$LINK" ] && [ -f "$SKILL_DIR/SKILL.md" ]; then
	ok "--uninstall removed the link and kept the skill folder"
else
	bad "--uninstall: $out"
fi

# 5. An occupied path is left alone, on install and on uninstall.
H2="$SCRATCH/home2"
mkdir -p "$H2/.claude/skills/persona-judge"
echo "someone else's" > "$H2/.claude/skills/persona-judge/keep.txt"
out="$(HOME="$H2" bash "$REPO/setup.sh" --harness claude 2>&1)"
out2="$(HOME="$H2" bash "$REPO/setup.sh" --uninstall --harness claude 2>&1)"
if printf '%s' "$out" | grep -q "STOPPED, path occupied" && printf '%s' "$out2" | grep -q "not ours, left alone" \
	&& [ ! -L "$H2/.claude/skills/persona-judge" ] && [ -f "$H2/.claude/skills/persona-judge/keep.txt" ]; then
	ok "an occupied path was left alone"
else
	bad "occupied path: $out / $out2"
fi

# 6. Nothing was written outside the scratch HOMEs: the real HOME has no link from this run.
if [ "$(HOME="$H1" bash "$REPO/setup.sh" --dry-run --harness claude 2>&1 | grep -c "$HOME/.claude")" = "0" ]; then
	ok "no path under the real HOME was named"
else
	bad "a path under the real HOME was named"
fi

# 7. The skill's name is persona-judge throughout the installer.
if grep -q '^NAME="persona-judge"' "$SRC" && ! grep -q 'dry-run' <(grep -v -- '--dry-run\|DRY_RUN\|Dry run\|dry run' "$SRC"); then
	ok "setup.sh names persona-judge and not dry-run"
else
	bad "setup.sh still names another skill"
fi

# 8. Claude Code gets the skill link only: no agent file, since the plugin carries the agent.
H8="$SCRATCH/home8"
mkdir -p "$H8/.claude"
HOME="$H8" bash "$REPO/setup.sh" --harness claude >/dev/null 2>&1
if [ -L "$H8/.claude/skills/persona-judge" ] && [ ! -e "$H8/.claude/agents" ]; then
	ok "Claude Code got the skill link and no agent file"
else
	bad "Claude Code agent: $(ls -R "$H8/.claude")"
fi

# Run setup.sh for one harness with HOME set to $1; CODEX_HOME, GEMINI_CLI_HOME and XDG_CONFIG_HOME are cleared so
# the scratch HOME decides.
run_for() {
	local home="$1"; shift
	env -u CODEX_HOME -u GEMINI_CLI_HOME -u XDG_CONFIG_HOME HOME="$home" PATH="$STUB:$PATH" bash "$REPO/setup.sh" "$@" 2>&1
}

# A stand-in gemini: `extensions link DIR` and `extensions uninstall NAME`, as setup.sh calls them, on the scratch
# HOME. It writes the install record as Gemini CLI 0.46.0 does, and removes it the same way.
STUB="$SCRATCH/bin"
mkdir -p "$STUB"
cat > "$STUB/gemini" <<'STUBEOF'
#!/usr/bin/env bash
dir="$HOME/.gemini/extensions/persona-judge"
case "$1 $2" in
	"extensions link")
		[ -f "$3/gemini-extension.json" ] || { echo "stand-in gemini: no gemini-extension.json in $3" >&2; exit 1; }
		mkdir -p "$dir" && printf '{\n  "source": "%s",\n  "type": "link"\n}\n' "$3" > "$dir/.gemini-extension-install.json" ;;
	"extensions uninstall") [ "$3" = "persona-judge" ] && rm "$dir/.gemini-extension-install.json" && rmdir "$dir" ;;
	*) echo "stand-in gemini: unexpected $*" >&2; exit 1 ;;
esac
STUBEOF
chmod +x "$STUB/gemini"

# 9 to 13, for Codex: the agent link follows the skill link's rules.
agent_cases() {
	local harness="$1" home="$2" link="$3" target="$4" label="$5"
	mkdir -p "$home/.$harness"
	out="$(run_for "$home" --dry-run --harness "$harness")"
	if [ ! -e "$link" ] && [ ! -L "$link" ] && printf '%s' "$out" | grep -q "Dry run: nothing was changed."; then
		ok "$label: --dry-run made no agent link"
	else
		bad "$label --dry-run: $out"
	fi
	out="$(run_for "$home" --harness "$harness")"
	if [ -L "$link" ] && [ "$(readlink "$link")" = "$target" ]; then
		ok "$label: install linked $link to the generated file"
	else
		bad "$label install: $out"
	fi
	before="$(ls -l "$link")"
	out="$(run_for "$home" --harness "$harness")"
	if printf '%s' "$out" | grep -q "$label agent: already linked, left as is" && [ "$(ls -l "$link")" = "$before" ]; then
		ok "$label: second run left the agent link as is"
	else
		bad "$label second run: $out"
	fi
	out="$(run_for "$home" --uninstall --harness "$harness")"
	if [ ! -e "$link" ] && [ ! -L "$link" ] && [ -f "$target" ]; then
		ok "$label: --uninstall removed the agent link and kept the generated file"
	else
		bad "$label --uninstall: $out"
	fi
	# Control: someone else's file at the agent path is left alone, on install and on uninstall.
	mkdir -p "$(dirname "$link")"
	echo "someone else's" > "$link"
	out="$(run_for "$home" --harness "$harness")"
	out2="$(run_for "$home" --uninstall --harness "$harness")"
	if printf '%s' "$out" | grep -q "$label agent: STOPPED, path occupied" \
		&& printf '%s' "$out2" | grep -q "$label agent: not ours, left alone" \
		&& [ ! -L "$link" ] && [ "$(cat "$link")" = "someone else's" ]; then
		ok "$label: an occupied agent path was left alone"
	else
		bad "$label occupied agent path: $out / $out2"
	fi
}

H9="$SCRATCH/home9"
agent_cases codex "$H9" "$H9/.codex/agents/persona-judge-reviewer.toml" "$CODEX_AGENT" "Codex CLI"

# The Gemini CLI extension: linked with `gemini extensions link`, left as is on a second run, removed with `gemini
# extensions uninstall`, and someone else's extension of the same name is never touched.
H10="$SCRATCH/home10"
mkdir -p "$H10/.gemini"
EXT_DIR="$H10/.gemini/extensions/persona-judge"
RECORD="$EXT_DIR/.gemini-extension-install.json"
out="$(run_for "$H10" --dry-run --harness gemini)"
if [ ! -e "$EXT_DIR" ] && printf '%s' "$out" | grep -qF "would run: gemini extensions link $GEMINI_EXT" \
	&& printf '%s' "$out" | grep -q "Gemini CLI extension: would be linked"; then
	ok "Gemini CLI extension: --dry-run named the link command and linked nothing"
else
	bad "Gemini CLI extension --dry-run: $out"
fi
out="$(run_for "$H10" --harness gemini)"
if [ -f "$RECORD" ] && grep -qF "\"source\": \"$GEMINI_EXT\"" "$RECORD" \
	&& printf '%s' "$out" | grep -q "Gemini CLI extension: linked"; then
	ok "Gemini CLI extension: install linked the extension folder"
else
	bad "Gemini CLI extension install: $out"
fi
if [ ! -e "$H10/.gemini/agents" ] && [ ! -e "$H10/.gemini/skills" ]; then
	ok "Gemini CLI extension: no agent or skill link was made beside it"
else
	bad "Gemini CLI extension: $(ls -R "$H10/.gemini")"
fi
before="$(cat "$RECORD")"
out="$(run_for "$H10" --harness gemini)"
if printf '%s' "$out" | grep -q "Gemini CLI extension: already linked, left as is" && [ "$(cat "$RECORD")" = "$before" ]; then
	ok "Gemini CLI extension: second run left it as is"
else
	bad "Gemini CLI extension second run: $out"
fi
out="$(run_for "$H10" --uninstall --harness gemini)"
if [ ! -e "$EXT_DIR" ] && printf '%s' "$out" | grep -q "Gemini CLI extension: uninstalled" \
	&& [ -f "$GEMINI_EXT/agents/persona-judge-reviewer.md" ]; then
	ok "Gemini CLI extension: --uninstall removed it and kept the package's files"
else
	bad "Gemini CLI extension --uninstall: $out"
fi
# Control: another extension named persona-judge is left alone, on install and on uninstall.
mkdir -p "$EXT_DIR"
printf '{\n  "source": "/somewhere/else",\n  "type": "link"\n}\n' > "$RECORD"
out="$(run_for "$H10" --harness gemini)"
out2="$(run_for "$H10" --uninstall --harness gemini)"
if printf '%s' "$out" | grep -q "Gemini CLI extension: STOPPED, path occupied" \
	&& printf '%s' "$out2" | grep -q "Gemini CLI extension: not ours, left alone" \
	&& grep -qF '"source": "/somewhere/else"' "$RECORD"; then
	ok "Gemini CLI extension: someone else's extension was left alone"
else
	bad "Gemini CLI extension occupied path: $out / $out2"
fi

# The links earlier versions made, ~/.gemini/skills/persona-judge and ~/.gemini/agents/persona-judge-reviewer.md, are
# removed when they point into this package, and left alone when they do not.
H11="$SCRATCH/home11"
mkdir -p "$H11/.gemini/skills" "$H11/.gemini/agents"
ln -s "$SKILL_DIR" "$H11/.gemini/skills/persona-judge"
ln -s "$GEMINI_EXT/persona-judge-reviewer.md" "$H11/.gemini/agents/persona-judge-reviewer.md"
out="$(run_for "$H11" --harness gemini)"
if [ ! -L "$H11/.gemini/skills/persona-judge" ] && [ ! -L "$H11/.gemini/agents/persona-judge-reviewer.md" ] \
	&& printf '%s' "$out" | grep -q "Gemini CLI old skill link: removed" \
	&& printf '%s' "$out" | grep -q "Gemini CLI old agent link: removed"; then
	ok "Gemini CLI: the old skill and agent links into this package were removed"
else
	bad "Gemini CLI old links: $out"
fi
H12="$SCRATCH/home12"
mkdir -p "$H12/.gemini/skills" "$H12/.gemini/agents" "$SCRATCH/elsewhere/persona-judge"
ln -s "$SCRATCH/elsewhere/persona-judge" "$H12/.gemini/skills/persona-judge"
ln -s "$SCRATCH/elsewhere/reviewer.md" "$H12/.gemini/agents/persona-judge-reviewer.md"
out="$(run_for "$H12" --harness gemini)"
out2="$(run_for "$H12" --uninstall --harness gemini)"
if [ -L "$H12/.gemini/skills/persona-judge" ] && [ -L "$H12/.gemini/agents/persona-judge-reviewer.md" ] \
	&& [ "$(printf '%s\n%s' "$out" "$out2" | grep -c "Gemini CLI old .* link: not ours, left alone")" = "4" ]; then
	ok "Gemini CLI: links at the old paths that point elsewhere were left alone"
else
	bad "Gemini CLI links elsewhere: $out / $out2"
fi

# OpenCode: the agent link, under ~/.config/opencode/agents/, follows the other agent links' rules, and the skill is
# linked under ~/.config/opencode/skills/ only when neither ~/.claude/skills nor ~/.agents/skills holds it.
H15="$SCRATCH/home15"
mkdir -p "$H15/.config/opencode"
OC_AGENT="$H15/.config/opencode/agents/persona-judge-reviewer.md"
OC_SKILL="$H15/.config/opencode/skills/persona-judge"
out="$(run_for "$H15" --dry-run --harness opencode)"
if [ ! -e "$OC_AGENT" ] && [ ! -e "$OC_SKILL" ] && printf '%s' "$out" | grep -q "Dry run: nothing was changed."; then
	ok "OpenCode: --dry-run made no link"
else
	bad "OpenCode --dry-run: $out"
fi
out="$(run_for "$H15" --harness opencode)"
if [ -L "$OC_AGENT" ] && [ "$(readlink "$OC_AGENT")" = "$OPENCODE_AGENT" ] && [ -L "$OC_SKILL" ] \
	&& [ "$(cd "$OC_SKILL" && pwd -P)" = "$SKILL_DIR" ]; then
	ok "OpenCode: install linked the agent file and the skill folder"
else
	bad "OpenCode install: $out"
fi
out="$(run_for "$H15" --harness opencode)"
if printf '%s' "$out" | grep -q "OpenCode agent: already linked, left as is" \
	&& printf '%s' "$out" | grep -q "OpenCode: already linked, left as is"; then
	ok "OpenCode: second run left both links as is"
else
	bad "OpenCode second run: $out"
fi
out="$(run_for "$H15" --uninstall --harness opencode)"
if [ ! -L "$OC_AGENT" ] && [ ! -L "$OC_SKILL" ] && [ -f "$OPENCODE_AGENT" ] && [ -f "$SKILL_DIR/SKILL.md" ]; then
	ok "OpenCode: --uninstall removed both links and kept the files"
else
	bad "OpenCode --uninstall: $out"
fi
# The skill is not linked for OpenCode when ~/.claude/skills or ~/.agents/skills already holds it.
for other in .claude/skills .agents/skills; do
	H16="$SCRATCH/home16-${other%%/*}"
	mkdir -p "$H16/.config/opencode" "$H16/$other"
	ln -s "$SKILL_DIR" "$H16/$other/persona-judge"
	out="$(run_for "$H16" --harness opencode)"
	if [ ! -e "$H16/.config/opencode/skills/persona-judge" ] && [ -L "$H16/.config/opencode/agents/persona-judge-reviewer.md" ] \
		&& printf '%s' "$out" | grep -qF "OpenCode: not linked, since OpenCode finds the skill at $H16/$other/persona-judge"; then
		ok "OpenCode: no skill link beside the one in ~/$other, and the agent was linked"
	else
		bad "OpenCode with ~/$other: $out"
	fi
done
# XDG_CONFIG_HOME, when set, decides where OpenCode's folder is.
H17="$SCRATCH/home17"
mkdir -p "$H17/xdg/opencode"
out="$(env -u CODEX_HOME -u GEMINI_CLI_HOME HOME="$H17" XDG_CONFIG_HOME="$H17/xdg" PATH="$STUB:$PATH" \
	bash "$REPO/setup.sh" --harness opencode 2>&1)"
if [ -L "$H17/xdg/opencode/agents/persona-judge-reviewer.md" ] && [ ! -e "$H17/.config" ]; then
	ok "OpenCode: XDG_CONFIG_HOME decided where the agent was linked"
else
	bad "OpenCode XDG_CONFIG_HOME: $out"
fi
# Control: someone else's file at the agent path is left alone, on install and on uninstall.
H18="$SCRATCH/home18"
mkdir -p "$H18/.config/opencode/agents"
echo "someone else's" > "$H18/.config/opencode/agents/persona-judge-reviewer.md"
out="$(run_for "$H18" --harness opencode)"
out2="$(run_for "$H18" --uninstall --harness opencode)"
if printf '%s' "$out" | grep -q "OpenCode agent: STOPPED, path occupied" \
	&& printf '%s' "$out2" | grep -q "OpenCode agent: not ours, left alone" \
	&& [ "$(cat "$H18/.config/opencode/agents/persona-judge-reviewer.md")" = "someone else's" ]; then
	ok "OpenCode: an occupied agent path was left alone"
else
	bad "OpenCode occupied agent path: $out / $out2"
fi
# A run with no --harness includes OpenCode.
out="$(run_for "$H18" --dry-run)"
if grep -q "^OpenCode agent:" <<<"$out"; then
	ok "OpenCode: a run with no --harness includes it"
else
	bad "OpenCode is missing from a run with no --harness"
fi

# 14 to 19: the Gemini CLI policy. It is filled with the skill folder's paths, shown and not written by --dry-run,
# left as is on a second run, removed by --uninstall, and someone else's file at its path is never touched.
H14="$SCRATCH/home14"
mkdir -p "$H14/.gemini"
POLICY="$H14/.gemini/policies/persona-judge.toml"
MARK="# Installed by persona-judge's setup.sh; setup.sh --uninstall removes this file."

out="$(run_for "$H14" --dry-run --harness gemini)"
if [ ! -e "$POLICY" ] && printf '%s' "$out" | grep -q "Gemini CLI policy: would be installed" \
	&& printf '%s' "$out" | grep -q "would write:" && printf '%s' "$out" | grep -qF "$MARK"; then
	ok "Gemini CLI policy: --dry-run showed the policy and wrote none"
else
	bad "Gemini CLI policy --dry-run: $out"
fi

out="$(run_for "$H14" --harness gemini)"
linked_re="$(printf '%s' "$GEMINI_EXT/skills/persona-judge" | sed 's/[][\\.^$*+?(){}|]/\\&/g')"
real_re="$(printf '%s' "$SKILL_DIR" | sed 's/[][\\.^$*+?(){}|]/\\&/g')"
if [ -f "$POLICY" ] && [ "$(head -n 1 "$POLICY")" = "$MARK" ] && ! grep -q '@SKILL_DIRS@' "$POLICY" \
	&& [ "$(grep -cF "python3 ($linked_re|$real_re)/scripts/" "$POLICY")" = "3" ]; then
	ok "Gemini CLI policy: install wrote it with the skill folder's paths filled in"
else
	bad "Gemini CLI policy install: $out"
fi

before="$(cat "$POLICY")"
out="$(run_for "$H14" --harness gemini)"
if printf '%s' "$out" | grep -q "Gemini CLI policy: already installed, left as is" && [ "$(cat "$POLICY")" = "$before" ]; then
	ok "Gemini CLI policy: second run left it as is"
else
	bad "Gemini CLI policy second run: $out"
fi

out="$(run_for "$H14" --dry-run --uninstall --harness gemini)"
out2="$(run_for "$H14" --uninstall --harness gemini)"
if printf '%s' "$out" | grep -q "Gemini CLI policy: file would be removed" && [ ! -e "$POLICY" ] \
	&& printf '%s' "$out2" | grep -q "Gemini CLI policy: file removed" && [ -f "$REPO/plugin/harness-agents/gemini/persona-judge.toml" ]; then
	ok "Gemini CLI policy: --uninstall removed it, after --dry-run said it would"
else
	bad "Gemini CLI policy --uninstall: $out / $out2"
fi

# Control: someone else's policy file at the path is left alone, on install and on uninstall.
mkdir -p "$(dirname "$POLICY")"
echo "# someone else's policy" > "$POLICY"
out="$(run_for "$H14" --harness gemini)"
out2="$(run_for "$H14" --uninstall --harness gemini)"
if printf '%s' "$out" | grep -q "Gemini CLI policy: STOPPED, path occupied" \
	&& printf '%s' "$out2" | grep -q "Gemini CLI policy: not ours, left alone" \
	&& [ "$(cat "$POLICY")" = "# someone else's policy" ]; then
	ok "Gemini CLI policy: someone else's file was left alone"
else
	bad "Gemini CLI policy occupied path: $out / $out2"
fi

# Control: a policy this script wrote for another skill folder is refreshed, not left stale.
printf '%s\n%s\n' "$MARK" "# an older policy" > "$POLICY"
out="$(run_for "$H14" --harness gemini)"
if printf '%s' "$out" | grep -q "Gemini CLI policy: refreshed" && ! grep -q "an older policy" "$POLICY"; then
	ok "Gemini CLI policy: an older policy of its own was refreshed"
else
	bad "Gemini CLI policy refresh: $out"
fi

echo "cases not met: $FAILURES"
[ "$FAILURES" -eq 0 ]
