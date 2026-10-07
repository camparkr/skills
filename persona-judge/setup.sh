#!/usr/bin/env bash
# setup.sh links the persona-judge skill, and the reviewer's agent file for Codex and OpenCode, into each harness,
# links the persona-judge extension, which holds both, into Gemini CLI, and installs the Gemini CLI policy that limits
# the reviewer's shell.
# Safe to run twice. Usage: setup.sh [--dry-run] [--uninstall] [--harness claude|codex|gemini|opencode]
# Gemini asks for consent, so run from a terminal, or pass --harness claude, codex or opencode when unattended.

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
			case "$ONLY" in claude|codex|gemini|opencode) ;; *) echo "--harness takes claude, codex, gemini or opencode" >&2; exit 2 ;; esac
			;;
		-h|--help) sed -n '2,6p' "$0"; exit 0 ;;
		*) echo "Unknown option: $1" >&2; exit 2 ;;
	esac
	shift
done

# The skill folder is skill/, beside this script at the plugin root.
SKILL_DIR="$(cd "$(dirname "$0")/skill" 2>/dev/null && pwd -P)" || SKILL_DIR="$(dirname "$0")/skill"
if [ ! -f "$SKILL_DIR/SKILL.md" ]; then
	echo "No SKILL.md in $SKILL_DIR; run this script from the repository root it came with." >&2
	exit 1
fi
NAME="persona-judge"
# The generated agent files for Codex and OpenCode; Claude Code gets its agent from the plugin instead.
ROOT_DIR="$(cd "$(dirname "$0")" 2>/dev/null && pwd -P)"
CODEX_AGENT="$ROOT_DIR/plugin/harness-agents/codex/$NAME-reviewer.toml"
OPENCODE_AGENT="$ROOT_DIR/plugin/harness-agents/opencode/$NAME-reviewer.md"
# The Gemini CLI extension: the reviewer's agent file, and a link to skill/, so one copy of the skill exists.
GEMINI_EXT="$ROOT_DIR/plugin/harness-agents/gemini"
# The Gemini CLI policy, with a placeholder for the skill folder's paths that install_policy fills.
GEMINI_POLICY="$ROOT_DIR/plugin/harness-agents/gemini/$NAME.toml"
POLICY_PLACEHOLDER="@SKILL_DIRS@"
# The first line of every policy file this script writes; a file without it is someone else's and is left alone.
POLICY_MARK="# Installed by persona-judge's setup.sh; setup.sh --uninstall removes this file."
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
		# Never overwrite what someone else put here.
		echo "  stopped: something else is at this path:"
		echo "    $(ls -ld "$link")"
		RESULTS+=("$label: STOPPED, path occupied (see above)")
	else
		run mkdir -p "$(dirname "$link")"
		if [ -n "$install_cmd" ]; then run $install_cmd "$SKILL_DIR"; else run ln -s "$SKILL_DIR" "$link"; fi
		RESULTS+=("$label: ${WOULD}linked")
	fi
}

# Handle one agent file link. $1 label, $2 link path, $3 the generated file it points to.
# The link is ours only when it points at exactly that file; anything else at the path is left alone.
handle_file() {
	local label="$1" link="$2" target="$3"
	echo "$label: $link"
	if [ "$UNINSTALL" -eq 1 ]; then
		if [ -L "$link" ] && [ "$(readlink "$link")" = "$target" ]; then
			run rm "$link"
			RESULTS+=("$label: link ${WOULD}removed")
		elif [ -e "$link" ] || [ -L "$link" ]; then
			echo "  left alone: it is not a link to this skill's agent file"
			RESULTS+=("$label: not ours, left alone")
		else
			RESULTS+=("$label: nothing to remove")
		fi
		return
	fi
	if [ ! -f "$target" ]; then
		RESULTS+=("$label: no generated file at $target, skipped")
	elif [ -L "$link" ] && [ "$(readlink "$link")" = "$target" ]; then
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

# Remove a link an earlier version of this script made, at $2, when it points into this package; leave anything else.
# $1 label. Used on install and on uninstall alike, since the link is no longer how the harness is set up.
remove_old_link() {
	local label="$1" link="$2" target
	[ -L "$link" ] || { [ -e "$link" ] && RESULTS+=("$label: not a link, left alone"); return; }
	target="$(readlink "$link")"
	case "$target" in /*) ;; *) target="$(dirname "$link")/$target" ;; esac
	echo "$label: $link"
	case "$target" in
		"$ROOT_DIR"/*)
			run rm "$link"
			RESULTS+=("$label: ${WOULD}removed") ;;
		*)
			if [ "$(resolve "$link")" = "$SKILL_DIR" ]; then
				run rm "$link"
				RESULTS+=("$label: ${WOULD}removed")
			else
				echo "  left alone: it does not point into this package"
				RESULTS+=("$label: not ours, left alone")
			fi ;;
	esac
}

# Handle the Gemini CLI extension. $1 label, $2 the extension's folder in Gemini's home, $3 the folder it links to.
# The extension is ours only when Gemini's install record names exactly that folder as a link.
handle_extension() {
	local label="$1" dir="$2" source="$3" record="$2/.gemini-extension-install.json" ours=0
	echo "$label: $dir"
	if [ -f "$record" ] && grep -qF "\"source\": \"$source\"" "$record" && grep -qF '"type": "link"' "$record"; then
		ours=1
	fi
	if [ "$UNINSTALL" -eq 1 ]; then
		if [ "$ours" -eq 1 ]; then
			run gemini extensions uninstall "$NAME"
			RESULTS+=("$label: ${WOULD}uninstalled")
		elif [ -e "$dir" ] || [ -L "$dir" ]; then
			echo "  left alone: it is not a link to this package's extension"
			RESULTS+=("$label: not ours, left alone")
		else
			RESULTS+=("$label: nothing to remove")
		fi
		return
	fi
	if [ ! -f "$source/gemini-extension.json" ]; then
		RESULTS+=("$label: no gemini-extension.json in $source, skipped")
	elif [ "$ours" -eq 1 ]; then
		RESULTS+=("$label: already linked, left as is")
	elif [ -e "$dir" ] || [ -L "$dir" ]; then
		echo "  stopped: another extension named $NAME is installed:"
		echo "    $(ls -ld "$dir")"
		RESULTS+=("$label: STOPPED, path occupied (see above)")
	else
		run gemini extensions link "$source"
		RESULTS+=("$label: ${WOULD}linked")
	fi
}

# A path as a literal in a regular expression: each character the expression would read as syntax gets a backslash.
regex_literal() { printf '%s' "$1" | sed 's/[][\\.^$*+?(){}|]/\\&/g'; }

# The policy text, with every placeholder replaced by $1. Bash's own replacement would read & and \ in $1, so the
# text is cut at each placeholder instead.
fill_policy() {
	local rest out="" group="$1"
	rest="$(cat "$GEMINI_POLICY")"
	while [[ "$rest" == *"$POLICY_PLACEHOLDER"* ]]; do
		out+="${rest%%"$POLICY_PLACEHOLDER"*}$group"
		rest="${rest#*"$POLICY_PLACEHOLDER"}"
	done
	printf '%s\n%s%s\n' "$POLICY_MARK" "$out" "$rest"
}

# Install, or with --uninstall remove, the Gemini CLI policy at $1, for the skill linked at $2.
# Gemini CLI reads user policy files from ~/.gemini/policies/, and drops the allow rules of a policy inside an
# extension, so the file goes there. Its patterns name the skill folder by both the path Gemini CLI reports, inside
# the extension, and the folder it points to, because the reviewer may be given either.
install_policy() {
	local label="Gemini CLI policy" policy="$1" link="$2" group text
	echo "$label: $policy"
	if [ "$UNINSTALL" -eq 1 ]; then
		if [ -f "$policy" ] && [ ! -L "$policy" ] && [ "$(head -n 1 "$policy")" = "$POLICY_MARK" ]; then
			run rm "$policy"
			RESULTS+=("$label: file ${WOULD}removed")
		elif [ -e "$policy" ] || [ -L "$policy" ]; then
			echo "  left alone: this script did not write it"
			RESULTS+=("$label: not ours, left alone")
		else
			RESULTS+=("$label: nothing to remove")
		fi
		return
	fi
	if [ ! -f "$GEMINI_POLICY" ]; then
		RESULTS+=("$label: no policy file at $GEMINI_POLICY, skipped")
		return
	fi
	# A quote, a backslash, a space or a control character in a path cannot be matched as the reviewer types it.
	case "$SKILL_DIR$link" in
		*[\'\"\\\ ]*|*[[:cntrl:]]*)
			echo "  stopped: the skill's path holds a quote, a backslash, a space or a control character"
			RESULTS+=("$label: STOPPED, path not supported (see above)")
			return ;;
	esac
	group="($(regex_literal "$link")|$(regex_literal "$SKILL_DIR"))"
	text="$(fill_policy "$group")"
	if [ -f "$policy" ] && [ ! -L "$policy" ] && [ "$(head -n 1 "$policy")" = "$POLICY_MARK" ]; then
		if [ "$(cat "$policy")" = "$text" ]; then
			RESULTS+=("$label: already installed, left as is")
			return
		fi
		RESULTS+=("$label: ${WOULD}refreshed")
	elif [ -e "$policy" ] || [ -L "$policy" ]; then
		echo "  stopped: something else is at this path:"
		echo "    $(ls -ld "$policy")"
		RESULTS+=("$label: STOPPED, path occupied (see above)")
		return
	else
		RESULTS+=("$label: ${WOULD}installed")
	fi
	if [ "$DRY_RUN" -eq 1 ]; then
		echo "  would write:"
		printf '%s\n' "$text" | sed 's/^/    /'
	else
		mkdir -p "$(dirname "$policy")"
		printf '%s\n' "$text" > "$policy"
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
		handle_file "Codex CLI agent" "$CODEX_DIR/agents/$NAME-reviewer.toml" "$CODEX_AGENT"
	else
		RESULTS+=("Codex CLI: not installed, skipped")
	fi
fi

if wanted gemini; then
	# gemini extensions link records the extension in ~/.gemini/extensions/<name> and asks for consent,
	# so run this script from a terminal; unattended, it waits for an answer.
	if command -v gemini >/dev/null 2>&1; then
		GEMINI_DIR="${GEMINI_CLI_HOME:-$HOME}/.gemini"
		# Gemini CLI skips an agent file that is a symlink, so the extension replaces both of these links.
		remove_old_link "Gemini CLI old skill link" "$GEMINI_DIR/skills/$NAME"
		remove_old_link "Gemini CLI old agent link" "$GEMINI_DIR/agents/$NAME-reviewer.md"
		handle_extension "Gemini CLI extension" "$GEMINI_DIR/extensions/$NAME" "$GEMINI_EXT"
		install_policy "$GEMINI_DIR/policies/$NAME.toml" "$GEMINI_EXT/skills/$NAME"
	else
		RESULTS+=("Gemini CLI: not installed, skipped")
	fi
fi

if wanted opencode; then
	OPENCODE_DIR="${XDG_CONFIG_HOME:-$HOME/.config}/opencode"
	if command -v opencode >/dev/null 2>&1 || [ -d "$OPENCODE_DIR" ]; then
		# OpenCode also finds skills in ~/.claude/skills and ~/.agents/skills, so its own link is made only when
		# neither holds the skill; a skill found in two places would be offered twice.
		found=""
		for other in "$HOME/.claude/skills/$NAME" "$HOME/.agents/skills/$NAME"; do
			if [ -e "$other" ] || [ -L "$other" ]; then found="$other"; break; fi
		done
		if [ -n "$found" ] && [ "$UNINSTALL" -eq 0 ]; then
			echo "OpenCode: $OPENCODE_DIR/skills/$NAME"
			RESULTS+=("OpenCode: not linked, since OpenCode finds the skill at $found")
		else
			handle "OpenCode" "$OPENCODE_DIR/skills/$NAME" "" ""
		fi
		handle_file "OpenCode agent" "$OPENCODE_DIR/agents/$NAME-reviewer.md" "$OPENCODE_AGENT"
	else
		RESULTS+=("OpenCode: not installed, skipped")
	fi
fi

echo
[ "$DRY_RUN" -eq 1 ] && echo "Dry run: nothing was changed."
echo "Skill folder: $SKILL_DIR"
for r in "${RESULTS[@]}"; do echo "  $r"; done
echo "Date: $(date +%F)"
