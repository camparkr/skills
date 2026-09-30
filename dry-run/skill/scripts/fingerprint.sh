#!/usr/bin/env bash
# fingerprint.sh — print one fingerprint of the real repository's state, leaving out the given paths.
# Usage: fingerprint.sh <record> [<test-index>]   run from inside the project's repository; paths from its root
# Covers uncommitted and staged changes to tracked files, new untracked files (not ignored ones), the
# current commit, local branches, tags and the stash; not remote-tracking branches, which a fetch moves.
# An absolute path inside the repository, even through a symbolic link, counts as its path from the root;
# one outside it is skipped with a warning.
# Needs only git.

set -euo pipefail
[ $# -ge 1 ] || { sed -n '3p' "$0" >&2; exit 2; }
ROOT="$(cd "$(git rev-parse --show-toplevel)" && pwd -P)"
cd "$ROOT"
EXCLUDE=()
for p in "$@"; do
	case "$p" in
		/*)
			d="$(cd "$(dirname "$p")" 2>/dev/null && pwd -P || true)"
			case "$d/" in
				"$ROOT"/*) r="${d#"$ROOT"}"; r="${r#/}"; EXCLUDE+=(":(exclude)${r:+$r/}$(basename "$p")") ;;
				*) echo "fingerprint.sh: $p is outside the repository; not excluded" >&2 ;;
			esac ;;
		../*) echo "fingerprint.sh: $p is outside the repository; not excluded" >&2 ;;
		*) EXCLUDE+=(":(exclude)$p") ;;
	esac
done
# A repository with no commits yet has no HEAD to compare against: use the empty tree.
BASE="$(git rev-parse --verify --quiet HEAD || git hash-object -t tree /dev/null)"
{
	echo "head $BASE"
	git for-each-ref --format='%(refname) %(objectname)' refs/heads refs/tags
	git stash list --format='%H' 2>/dev/null || true
	git diff "$BASE" -- . ${EXCLUDE[@]+"${EXCLUDE[@]}"}
	git diff --cached "$BASE" -- . ${EXCLUDE[@]+"${EXCLUDE[@]}"}
	git ls-files -z -o --exclude-standard -- . ${EXCLUDE[@]+"${EXCLUDE[@]}"} | while IFS= read -r -d '' f; do printf '%s %s\n' "$f" "$(git hash-object -- "$f")"; done
} | git hash-object --stdin
