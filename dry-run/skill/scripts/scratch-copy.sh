#!/usr/bin/env bash
# scratch-copy.sh — make or remove the scratch copies a dry run checks in, outside the repository.
# Usage: scratch-copy.sh make <scratch> <tag> [<base-commit>]   run from inside the project's repository
#        scratch-copy.sh remove <scratch> <tag>   fails if a copy, clone or redraft folder (<tag>a, <tag>b) remains
# make: <scratch>/dry-run-<tag> holds the working tree as it stands (uncommitted, new and deleted files;
# ignored files left out); with <base-commit>, <scratch>/dry-run-<tag>-base holds the old code.
# Neither touches the real working tree or index. make does add to the real .git: a worktree entry per copy
# and one snapshot commit, held only by its copy. remove deletes the entries; once the copy is gone, git's
# routine garbage collection deletes the commit.

set -euo pipefail

usage() { sed -n '3,4p' "$0" >&2; exit 2; }
[ $# -ge 3 ] || usage
ACTION="$1" SCRATCH="$2" TAG="$3" BASE="${4:-}"
case "$TAG" in ""|*[!A-Za-z0-9._-]*) echo "The tag may use only letters, digits, dots, hyphens and underscores." >&2; exit 2 ;; esac
ROOT="$(cd "$(git rev-parse --show-toplevel)" && pwd -P)"
git -C "$ROOT" rev-parse --verify --quiet HEAD >/dev/null || { echo "The repository has no commits yet; commit once, or copy the folder by hand." >&2; exit 1; }
# Resolve the scratch folder through its parent, so the check below runs before anything is created.
PARENT="$(cd "$(dirname "$SCRATCH")" 2>/dev/null && pwd -P)" || { echo "No such folder: $(dirname "$SCRATCH")" >&2; exit 1; }
SCRATCH="$PARENT/$(basename "$SCRATCH")"
case "$SCRATCH" in "$ROOT"|"$ROOT"/*) echo "The scratch folder must be outside the repository." >&2; exit 1 ;; esac
# Work from the repository root from here on; every path above is already absolute.
cd "$ROOT"
COPY="$SCRATCH/dry-run-$TAG"
BASE_COPY="$COPY-base"

# True when the given path is registered as a worktree of the real repository.
registered() { git -C "$ROOT" worktree list --porcelain | grep -qxF "worktree $1"; }

case "$ACTION" in
	make)
		for c in "$COPY" "$BASE_COPY"; do
			if [ -e "$c" ]; then echo "$c already exists; it may be another session's copy. Use another <tag>." >&2; exit 1; fi
		done
		# Resolve the base commit first, so a bad one fails before anything is made.
		BASE_HASH=""
		if [ -n "$BASE" ]; then BASE_HASH="$(git -C "$ROOT" rev-parse --verify "$BASE^{commit}")"; fi
		mkdir -p "$SCRATCH"
		# Snapshot the working tree through a throwaway index inside the git folder, so the real index
		# is never staged and no system temp folder is needed.
		TMP_INDEX="$(git -C "$ROOT" rev-parse --absolute-git-dir)/dry-run-$TAG.index"
		trap 'rm -f "$TMP_INDEX"' EXIT
		cp "$(git rev-parse --git-path index)" "$TMP_INDEX" 2>/dev/null || true
		# add -A stages into the throwaway index only, never the real one.
		GIT_INDEX_FILE="$TMP_INDEX" git -C "$ROOT" add -A
		TREE="$(GIT_INDEX_FILE="$TMP_INDEX" git -C "$ROOT" write-tree)"
		# A snapshot commit needs an identity; supply one only where git has none, for this commit only.
		SNAP="$(GIT_AUTHOR_NAME="${GIT_AUTHOR_NAME:-$(git config user.name || echo 'Lorem Ipsum')}" \
			GIT_AUTHOR_EMAIL="${GIT_AUTHOR_EMAIL:-$(git config user.email || echo lorem.ipsum@example.com)}" \
			GIT_COMMITTER_NAME="${GIT_COMMITTER_NAME:-$(git config user.name || echo 'Lorem Ipsum')}" \
			GIT_COMMITTER_EMAIL="${GIT_COMMITTER_EMAIL:-$(git config user.email || echo lorem.ipsum@example.com)}" \
			git -C "$ROOT" commit-tree "$TREE" -p HEAD -m "dry-run $TAG: working tree snapshot")"
		git -C "$ROOT" worktree add --quiet --detach "$COPY" "$SNAP"
		echo "Copy: $COPY (HEAD $(git -C "$ROOT" rev-parse --short HEAD) plus the working tree, snapshot $SNAP)"
		if [ -n "$BASE_HASH" ]; then
			if ! git -C "$ROOT" worktree add --quiet --detach "$BASE_COPY" "$BASE_HASH"; then
				git -C "$ROOT" worktree remove --force "$COPY"
				echo "Could not make the old-code copy; removed $COPY again." >&2
				exit 1
			fi
			echo "Old code: $BASE_COPY (at $BASE_HASH)"
		fi
		;;
	remove)
		for f in "$SCRATCH/${TAG}a" "$SCRATCH/${TAG}b"; do
			if [ -e "$f" ]; then echo "$f is a leftover redraft folder; delete it by hand, then run remove again." >&2; exit 1; fi
		done
		if [ -e "$SCRATCH/$TAG-clone" ]; then
			echo "$SCRATCH/$TAG-clone is a leftover clone of a copy; delete it by hand, then run remove again." >&2
			exit 1
		fi
		for c in "$COPY" "$BASE_COPY"; do
			if registered "$c"; then
				git -C "$ROOT" worktree remove --force "$c"
				echo "Removed: $c"
			fi
		done
		for c in "$COPY" "$BASE_COPY"; do
			if [ -e "$c" ]; then echo "$c is still there but is not a registered copy; check it and delete it by hand." >&2; exit 1; fi
		done
		if registered "$COPY" || registered "$BASE_COPY"; then
			echo "A dry-run-$TAG copy is still registered:" >&2
			git -C "$ROOT" worktree list >&2
			exit 1
		fi
		echo "No dry-run-$TAG copies remain."
		;;
	*) usage ;;
esac
