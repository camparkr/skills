#!/usr/bin/env bash
# test_setup.sh: test setup.sh with HOME set to a scratch folder and --harness claude (T-I).
# The installer runs from a scratch copy of persona-judge/ holding a stand-in SKILL.md, so the test
# needs no prose file and writes nothing outside the scratch folders.
# Usage: tests/test_setup.sh. Exit 0 when every case holds, 1 when any does not.

set -u
HERE="$(cd "$(dirname "$0")" && pwd -P)"
SRC="$HERE/../setup.sh"
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

echo "cases not met: $FAILURES"
[ "$FAILURES" -eq 0 ]
