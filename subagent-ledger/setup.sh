#!/usr/bin/env bash
# setup.sh links the subagent-ledger skill and its OpenCode plugin into each harness, and prints the hook entries.
# The skill goes into Claude Code and Codex, the plugin into OpenCode. The hook entries each harness needs are
# printed with this machine's paths filled in; no settings file is ever written: you add the entries yourself.
# Safe to run twice. Usage: setup.sh [--dry-run] [--uninstall] [--harness claude|codex|opencode]

set -u

DRY_RUN=0
UNINSTALL=0
ONLY=""
while [ $# -gt 0 ]; do
	case "$1" in
		--dry-run) DRY_RUN=1 ;;
		--uninstall) UNINSTALL=1 ;;
		--harness)
			ONLY="${2:-}"
			shift
			case "$ONLY" in claude|codex|opencode) ;; *) echo "--harness takes claude, codex or opencode" >&2; exit 2 ;; esac
			;;
		-h|--help) sed -n '2,5p' "$0"; exit 0 ;;
		*) echo "Unknown option: $1" >&2; exit 2 ;;
	esac
	shift
done

# The skill folder is skill/, beside this script.
SKILL_DIR="$(cd "$(dirname "$0")/skill" 2>/dev/null && pwd -P)" || SKILL_DIR="$(dirname "$0")/skill"
if [ ! -f "$SKILL_DIR/SKILL.md" ]; then
	echo "No SKILL.md in $SKILL_DIR; run this script from the repository it came with." >&2
	exit 1
fi
NAME="subagent-ledger"
SCRIPTS="$SKILL_DIR/scripts"
PLUGIN="$SCRIPTS/opencode-plugin/subagent-ledger.js"

# The captures are Python, and they lock the ledger file: with fcntl on macOS and Linux, with msvcrt on Windows.
if ! command -v python3 >/dev/null 2>&1; then
	echo "python3 was not found. The capture needs Python 3; install it and run this again. Nothing was changed." >&2
	exit 1
fi
if ! python3 -c 'import sys; sys.path.insert(0, sys.argv[1]); import ledger; ledger.lock_module()' "$SCRIPTS" >/dev/null 2>&1; then
	echo "The capture cannot run here: python3 cannot import the ledger's file lock (fcntl, or msvcrt on Windows). Nothing was changed." >&2
	exit 1
fi

case "$SKILL_DIR" in
	/tmp/*|/private/tmp/*|/var/folders/*)
		echo "Warning: $SKILL_DIR is a temporary folder; the links break when it is cleared. Run this from a permanent clone." >&2 ;;
esac
RESULTS=()
# In a dry run, report what would happen rather than what did.
if [ "$DRY_RUN" -eq 1 ]; then WOULD="would be "; else WOULD=""; fi

run() {
	if [ "$DRY_RUN" -eq 1 ]; then
		echo "  would run: $*"
	else
		"$@"
	fi
}

# Handle one link. $1 label, $2 link path, $3 what it points to. The link is ours only when it points at
# exactly that path; anything else at the path is left alone, and nothing is ever overwritten.
handle() {
	local label="$1" link="$2" target="$3"
	echo "$label: $link"
	if [ "$UNINSTALL" -eq 1 ]; then
		if [ -L "$link" ] && [ "$(readlink "$link")" = "$target" ]; then
			run rm "$link"
			RESULTS+=("$label: link ${WOULD}removed")
		elif [ -e "$link" ] || [ -L "$link" ]; then
			echo "  left alone: it is not a link this script made"
			RESULTS+=("$label: not ours, left alone")
		else
			RESULTS+=("$label: nothing to remove")
		fi
		return
	fi
	if [ -L "$link" ] && [ "$(readlink "$link")" = "$target" ]; then
		RESULTS+=("$label: already linked, left as is")
	elif [ -e "$link" ] || [ -L "$link" ]; then
		echo "  stopped: something else is at this path:"
		echo "    $(ls -ld "$link")"
		RESULTS+=("$label: STOPPED, path occupied (see above)")
	else
		run mkdir -p "$(dirname "$link")"
		run ln -s "$target" "$link"
		RESULTS+=("$label: ${WOULD}linked")
	fi
}

wanted() { [ -z "$ONLY" ] || [ "$ONLY" = "$1" ]; }

CLAUDE_ON=0
CODEX_ON=0
OPENCODE_ON=0

if wanted claude; then
	if command -v claude >/dev/null 2>&1 || [ -d "$HOME/.claude" ]; then
		handle "Claude Code" "$HOME/.claude/skills/$NAME" "$SKILL_DIR"
		CLAUDE_ON=1
	else
		RESULTS+=("Claude Code: not installed, skipped")
	fi
fi

if wanted codex; then
	CODEX_DIR="${CODEX_HOME:-$HOME/.codex}"
	if command -v codex >/dev/null 2>&1 || [ -d "$CODEX_DIR" ]; then
		handle "Codex CLI" "$CODEX_DIR/skills/$NAME" "$SKILL_DIR"
		CODEX_ON=1
	else
		RESULTS+=("Codex CLI: not installed, skipped")
	fi
fi

if wanted opencode; then
	OPENCODE_DIR="${XDG_CONFIG_HOME:-$HOME/.config}/opencode"
	if command -v opencode >/dev/null 2>&1 || [ -d "$OPENCODE_DIR" ]; then
		handle "OpenCode plugin" "$OPENCODE_DIR/plugins/$NAME.js" "$PLUGIN"
		OPENCODE_ON=1
	else
		RESULTS+=("OpenCode: not installed, skipped")
	fi
fi

echo
[ "$DRY_RUN" -eq 1 ] && echo "Dry run: nothing was changed."
echo "Skill folder: $SKILL_DIR"
for r in "${RESULTS[@]}"; do echo "  $r"; done

# The hook entries. Printed, never written: each harness's settings file is yours to edit.
if [ "$UNINSTALL" -eq 0 ]; then
	claude_hook() { printf '{"type": "command", "command": "python3 \\"%s/capture_claude_code.py\\" %s"}' "$SCRIPTS" "$1"; }
	codex_hook() { printf '{"type": "command", "command": "python3 \\"%s/capture_codex.py\\" %s"}' "$SCRIPTS" "$1"; }
	if [ "$CLAUDE_ON" -eq 1 ]; then
		echo
		echo "Claude Code: add these to the \"hooks\" object of your settings file (~/.claude/settings.json, or a"
		echo "project's .claude/settings.json), beside any entries already there:"
		echo
		cat <<EOF
{
  "PreToolUse":         [{"matcher": "Agent|Task|Bash|SendMessage|TaskStop|WebSearch|WebFetch|mcp__.*", "hooks": [$(claude_hook PreToolUse)]}],
  "PostToolUse":        [{"matcher": "Agent|Task|Bash|SendMessage|TaskStop|WebSearch|WebFetch|mcp__.*", "hooks": [$(claude_hook PostToolUse)]}],
  "PostToolUseFailure": [{"matcher": "Agent|Task|Bash|SendMessage|WebSearch|WebFetch|mcp__.*", "hooks": [$(claude_hook PostToolUseFailure)]}],
  "SubagentStart":      [{"hooks": [$(claude_hook SubagentStart)]}],
  "SubagentStop":       [{"hooks": [$(claude_hook SubagentStop)]}]
}
EOF
	fi
	if [ "$CODEX_ON" -eq 1 ]; then
		echo
		echo "Codex: add these to the \"hooks\" object of hooks.json in ${CODEX_DIR}. The matcher names each tool"
		echo "every way Codex has named it: Agent and Bash, the older spawn_agent and exec_command, and the app's"
		echo "collaborationspawn_agent, with its two message tools collaborationsend_message and"
		echo "collaborationfollowup_task. mcp__.* admits every MCP tool."
		echo
		cat <<EOF
{
  "PreToolUse":    [{"matcher": "Agent|Bash|spawn_agent|exec_command|collaborationspawn_agent|collaborationsend_message|collaborationfollowup_task|mcp__.*", "hooks": [$(codex_hook PreToolUse)]}],
  "PostToolUse":   [{"matcher": "Agent|Bash|spawn_agent|exec_command|collaborationspawn_agent|collaborationsend_message|collaborationfollowup_task|mcp__.*", "hooks": [$(codex_hook PostToolUse)]}],
  "SubagentStart": [{"hooks": [$(codex_hook SubagentStart)]}],
  "SubagentStop":  [{"hooks": [$(codex_hook SubagentStop)]}]
}
EOF
		echo
		echo "Codex runs a hook only once you have trusted it: trust the hooks in the app's Settings → Hooks, or"
		echo "with /hooks in an interactive CLI session, then start a fresh session; hooks that change need review"
		echo "again."
	fi
	if [ "$OPENCODE_ON" -eq 1 ]; then
		echo
		echo "OpenCode: the plugin is linked above. Set these in the environment OpenCode starts with:"
		echo
		echo "  export SUBAGENT_LEDGER_DIR=\"<the folder that keeps the ledger>\""
		echo "  export SUBAGENT_LEDGER_SCRIPTS=\"$SCRIPTS\""
	fi
	echo
	echo "Each capture writes to the folder SUBAGENT_LEDGER_DIR names; without it, to .subagent-ledger in the"
	echo "git repository the harness runs in. Add --ledger <folder> to a command above to name one instead."
fi
echo "Date: $(date +%F)"
