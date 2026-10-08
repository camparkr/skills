#!/usr/bin/env bash
# fingerprint.sh — print one fingerprint of the real repository's state, leaving out the given paths.
# Usage: fingerprint.sh <record> [<test-index>]   run from inside the project's repository; paths from its root
# Covers uncommitted and staged changes to tracked files, new untracked files (not ignored ones), the
# current commit, local branches, tags and the stash; not remote-tracking branches, which a fetch moves.
# A path, absolute or relative, that resolves inside the repository (even through a symbolic link) counts as
# its path from the root; one outside it is skipped with a warning.
# Needs only git.

set -euo pipefail
[ $# -ge 1 ] || { sed -n '3p' "$0" >&2; exit 2; }
ROOT="$(cd "$(git rev-parse --show-toplevel)" && pwd -P)"
cd "$ROOT"
EXCLUDE=()
for p in "$@"; do
	# Resolve every path the same way, relative ones from the root, so 'sub/../../x' cannot slip through.
	case "$p" in
		/*) a="$p" ;;
		*) a="$ROOT/$p" ;;
	esac
	d="$(cd "$(dirname "$a")" 2>/dev/null && pwd -P || true)"
	if [ -z "$d" ]; then
		# The folder does not exist yet: keep a plain relative path, refuse one that climbs.
		case "/$p/" in
			/*/../*|/../*) echo "fingerprint.sh: $p cannot be resolved; not excluded" >&2 ;;
			*) case "$p" in /*) echo "fingerprint.sh: $p cannot be resolved; not excluded" >&2 ;; *) EXCLUDE+=(":(exclude)$p") ;; esac ;;
		esac
		continue
	fi
	case "$d/" in
		"$ROOT"/*) r="${d#"$ROOT"}"; r="${r#/}"; EXCLUDE+=(":(exclude)${r:+$r/}$(basename "$a")") ;;
		*) echo "fingerprint.sh: $p is outside the repository; not excluded" >&2 ;;
	esac
done
# The state of one untracked path: a file's blob hash, or, for a nested repository (listed as a directory),
# a hash of its commit, its uncommitted changes and its own untracked files.
state_of() {
	if [ -d "$1" ]; then
		{
			git -C "$1" rev-parse --verify --quiet HEAD || true
			git -C "$1" diff --no-ext-diff --no-textconv HEAD 2>/dev/null || true
			git -C "$1" ls-files -z -o --exclude-standard | while IFS= read -r -d '' g; do
				printf '%s %s\n' "$g" "$(git -C "$1" hash-object -- "$g" 2>/dev/null || echo unreadable)"
			done
		} | git hash-object --stdin
	else
		git hash-object -- "$1"
	fi
}
# A repository with no commits yet has no HEAD to compare against: use the empty tree.
BASE="$(git rev-parse --verify --quiet HEAD || git hash-object -t tree /dev/null)"
{
	echo "head $BASE"
	git for-each-ref --format='%(refname) %(objectname)' refs/heads refs/tags
	git stash list --format='%H' 2>/dev/null || true
	git diff --no-ext-diff --no-textconv "$BASE" -- . ${EXCLUDE[@]+"${EXCLUDE[@]}"}
	git diff --no-ext-diff --no-textconv --cached "$BASE" -- . ${EXCLUDE[@]+"${EXCLUDE[@]}"}
	git ls-files -z -o --exclude-standard -- . ${EXCLUDE[@]+"${EXCLUDE[@]}"} | while IFS= read -r -d '' f; do printf '%s %s\n' "$f" "$(state_of "$f")"; done
} | git hash-object --stdin
