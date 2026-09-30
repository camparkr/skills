#!/usr/bin/env bash
# setup.sh — link the /dry-run skill into each agent harness on this machine.
# Safe to run twice. Usage: setup.sh [--dry-run] [--uninstall] [--harness claude|codex|gemini]
# Gemini asks for consent, so run from a terminal, or pass --harness claude or codex when unattended.

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
			case "$ONLY" in claude|codex|gemini) ;; *) echo "--harness takes claude, codex or gemini" >&2; exit 2 ;; esac
			;;
		-h|--help) sed -n '2,4p' "$0"; exit 0 ;;
		*) echo "Unknown option: $1" >&2; exit 2 ;;
	esac
	shift
done

# The skill folder is skill/, beside this script at the repository root.
SKILL_DIR="$(cd "$(dirname "$0")/skill" 2>/dev/null && pwd -P)" || SKILL_DIR="$(dirname "$0")/skill"
if [ ! -f "$SKILL_DIR/SKILL.md" ]; then
	echo "No SKILL.md in $SKILL_DIR; run this script from the repository root it came with." >&2
	exit 1
fi
NAME="dry-run"
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

# Resolved target of a symlink to a folder, or empty if it does not resolve.
resolve() { (cd "$1" 2>/dev/null && pwd -P); }

# Handle one harness. $1 label, $2 link path, $3 install command (empty = plain symlink),
# $4 uninstall command (empty = plain rm).
handle() {
	local label="$1" link="$2" install_cmd="$3" uninstall_cmd="$4"
	echo "$label: $link"
	if [ "$UNINSTALL" -eq 1 ]; then
		if [ -L "$link" ] && [ "$(resolve "$link")" = "$SKILL_DIR" ]; then
			if [ -n "$uninstall_cmd" ]; then run $uninstall_cmd; else run rm "$link"; fi
			RESULTS+=("$label: link ${WOULD}removed")
		elif [ -e "$link" ] || [ -L "$link" ]; then
			echo "  left alone: it is not a link to this skill folder"
			RESULTS+=("$label: not ours, left alone")
		else
			RESULTS+=("$label: nothing to remove")
		fi
		return
	fi
	if [ -L "$link" ] && [ "$(resolve "$link")" = "$SKILL_DIR" ]; then
		RESULTS+=("$label: already linked, left as is")
	elif [ -e "$link" ] || [ -L "$link" ]; then
		# Never overwrite: Gemini's own link command would delete whatever is here.
		echo "  stopped: something else is at this path:"
		echo "    $(ls -ld "$link")"
		RESULTS+=("$label: STOPPED, path occupied (see above)")
	else
		run mkdir -p "$(dirname "$link")"
		if [ -n "$install_cmd" ]; then run $install_cmd "$SKILL_DIR"; else run ln -s "$SKILL_DIR" "$link"; fi
		RESULTS+=("$label: ${WOULD}linked")
	fi
}

wanted() { [ -z "$ONLY" ] || [ "$ONLY" = "$1" ]; }

if wanted claude; then
	if command -v claude >/dev/null 2>&1 || [ -d "$HOME/.claude" ]; then
		handle "Claude Code" "$HOME/.claude/skills/$NAME" "" ""
	else
		RESULTS+=("Claude Code: not installed, skipped")
	fi
fi

if wanted codex; then
	CODEX_DIR="${CODEX_HOME:-$HOME/.codex}"
	if command -v codex >/dev/null 2>&1 || [ -d "$CODEX_DIR" ]; then
		handle "Codex CLI" "$CODEX_DIR/skills/$NAME" "" ""
	else
		RESULTS+=("Codex CLI: not installed, skipped")
	fi
fi

if wanted gemini; then
	# gemini skills link writes a user-scope symlink at ~/.gemini/skills/<name> and asks for consent,
	# so run this script from a terminal; unattended, it waits for an answer.
	if command -v gemini >/dev/null 2>&1; then
		handle "Gemini CLI" "$HOME/.gemini/skills/$NAME" "gemini skills link" "gemini skills uninstall $NAME"
	else
		RESULTS+=("Gemini CLI: not installed, skipped")
	fi
fi

echo
[ "$DRY_RUN" -eq 1 ] && echo "Dry run: nothing was changed."
echo "Skill folder: $SKILL_DIR"
for r in "${RESULTS[@]}"; do echo "  $r"; done
echo "Date: $(date +%F)"
