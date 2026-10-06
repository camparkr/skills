#!/usr/bin/env bash
# test_setup.sh: test that setup.sh installs the skill for Claude Code, with HOME set to a scratch folder and
# --harness claude, the reviewer's agent file for Codex and Gemini CLI, with --harness codex and gemini, and the Gemini
# CLI policy that limits the reviewer's shell, with --harness gemini.
# A stand-in `gemini` on the PATH does the work of `gemini skills link`, so no real harness is called.
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
# Stand-ins for the generated agent files the installer links for Codex and Gemini CLI, and a copy of the policy.
mkdir -p "$REPO/plugin/harness-agents/codex" "$REPO/plugin/harness-agents/gemini"
echo 'name = "persona-judge-reviewer"' > "$REPO/plugin/harness-agents/codex/persona-judge-reviewer.toml"
printf -- '---\nname: persona-judge-reviewer\n---\n' > "$REPO/plugin/harness-agents/gemini/persona-judge-reviewer.md"
cp "$POLICY_SRC" "$REPO/plugin/harness-agents/gemini/persona-judge.toml"
CODEX_AGENT="$(cd "$REPO/plugin/harness-agents/codex" && pwd -P)/persona-judge-reviewer.toml"
GEMINI_AGENT="$(cd "$REPO/plugin/harness-agents/gemini" && pwd -P)/persona-judge-reviewer.md"

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

# Run setup.sh for one harness with HOME set to $1; CODEX_HOME is cleared so the scratch HOME decides.
run_for() {
	local home="$1"; shift
	env -u CODEX_HOME HOME="$home" PATH="$STUB:$PATH" bash "$REPO/setup.sh" "$@" 2>&1
}

# A stand-in gemini: `skills link DIR` and `skills uninstall NAME`, as setup.sh calls them, on the scratch HOME.
STUB="$SCRATCH/bin"
mkdir -p "$STUB"
cat > "$STUB/gemini" <<'STUBEOF'
#!/usr/bin/env bash
case "$1 $2" in
	"skills link") mkdir -p "$HOME/.gemini/skills" && ln -s "$3" "$HOME/.gemini/skills/persona-judge" ;;
	"skills uninstall") rm "$HOME/.gemini/skills/$3" ;;
	*) echo "stand-in gemini: unexpected $*" >&2; exit 1 ;;
esac
STUBEOF
chmod +x "$STUB/gemini"

# 9 to 13, for each of Codex and Gemini CLI: the agent link follows the skill link's rules.
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
H10="$SCRATCH/home10"
agent_cases gemini "$H10" "$H10/.gemini/agents/persona-judge-reviewer.md" "$GEMINI_AGENT" "Gemini CLI"

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
linked_re="$(printf '%s' "$H14/.gemini/skills/persona-judge" | sed 's/[][\\.^$*+?(){}|]/\\&/g')"
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
