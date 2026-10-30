#!/usr/bin/env python3
"""Refuse a writer's dispatch whose worktree would not hold its write set as the main checkout has it.

    python3 worktree_check.py --brief <path> [--repository <folder>] [--base default|head]

Run before every writer's dispatch, in every session. The write set is read from the brief by the ledger capture's own
reader of its `## Write set` section; a brief whose write set is `none`, or that has none, is a read-only member's,
and is not checked.

A worktree branches from a commit and carries no uncommitted or untracked file. Which commit is --base: `head`, the
local HEAD, where the harness branches worktrees from it (Claude Code's `worktree.baseRef: "head"`), as the
specification and the capture's baseline read a writer's changes; or `default`, the remote's default branch
(origin/HEAD), where the harness branches worktrees from that. The default is `head`. A base that cannot be read
refuses the dispatch.

For each write-set path, every file it names in the main checkout (tracked, or untracked and not ignored; a file named
exactly is read even where ignored) and every file it names at the base commit is compared by its git blob id. A
folder prefix names every file under it. Where a file's state differs, or is present on one side only, the dispatch is
refused with the reason, naming each file. A write set whose paths lie in two repositories (a path inside a
repository nested in this one) is refused too, as is a path given absolute or leaving the repository. A file the
write set names that exists on neither side is a file still to be created, and passes.

Output: one JSON object, {"brief", "repository", "base", "write_set", "compared", "differences", "refuse", "reason"}.
Exit codes: 0 passed; 1 refused; 2 cannot run (the ledger skill's scripts not found). It writes nothing.
"""

import argparse
import hashlib
import json
import os
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

import brief as briefs  # noqa: E402
import decide  # noqa: E402

BASES = {'default': 'origin/HEAD', 'head': 'HEAD'}
ABSENT = 'absent'
SHOWN = 20


class Refused(Exception):
    pass


def git(repo, *arguments, stdin=None):
    """(exit code, standard output, standard error) of git in `repo`, pathspecs read literally."""
    try:
        done = subprocess.run(['git', '--literal-pathspecs', '-C', str(repo)] + list(arguments), input=stdin,
                              capture_output=True, text=True, timeout=60)
    except (OSError, subprocess.SubprocessError) as exc:
        return 1, '', str(exc)
    return done.returncode, done.stdout, done.stderr


def base_commit(repo, setting):
    ref = BASES[setting]
    code, out, _ = git(repo, 'rev-parse', '--verify', '--quiet', ref + '^{commit}')
    return ref, out.strip() if code == 0 and out.strip() else None


def nearest_top(path):
    """The git top folder of the nearest folder that exists at or above `path`."""
    probe = Path(path)
    while not probe.exists() and probe != probe.parent:
        probe = probe.parent
    folder = probe if probe.is_dir() else probe.parent
    return briefs.git_top(folder)


def main_files(repo, entry):
    """The files `entry` names in the main checkout: tracked, or untracked and not ignored; and the entry itself where
    it is a file, ignored or not."""
    code, out, err = git(repo, 'ls-files', '-z', '--cached', '--others', '--exclude-standard', '--', entry)
    if code != 0:
        raise Refused('git could not list %s in the main checkout: %s' % (entry, ' '.join(err.split())[:200]))
    found = [path for path in out.split('\0') if path]
    full = Path(repo) / entry
    if not entry.endswith('/') and (full.is_file() or full.is_symlink()) and entry not in found:
        found.append(entry)
    return found


def base_files(repo, commit, entry):
    """{path: blob id} for the files `entry` names at the base commit."""
    code, out, err = git(repo, 'ls-tree', '-r', '-z', commit, '--', entry.rstrip('/') or '.')
    if code != 0:
        raise Refused('git could not list %s at %s: %s' % (entry, commit, ' '.join(err.split())[:200]))
    found = {}
    for line in out.split('\0'):
        if '\t' not in line:
            continue
        meta, path = line.split('\t', 1)
        parts = meta.split()
        if entry.endswith('/') or path == entry or path.startswith(entry.rstrip('/') + '/'):
            found[path] = parts[2] if parts[1] == 'blob' else '%s %s' % (parts[1], parts[2])
    return found


def main_state(repo, paths):
    """{path: blob id or ABSENT} for each path in the main checkout, hashed as git would store it."""
    states, hashed = {}, []
    for path in paths:
        full = Path(repo) / path
        if full.is_symlink():
            target = os.readlink(str(full)).encode('utf-8')
            states[path] = hashlib.sha1(b'blob %d\0' % len(target) + target).hexdigest()
        elif full.is_file():
            hashed.append(path)
        else:
            states[path] = ABSENT
    if hashed:
        code, out, err = git(repo, 'hash-object', '--stdin-paths', stdin='\n'.join(hashed) + '\n')
        ids = out.split()
        if code != 0 or len(ids) != len(hashed):
            raise Refused('git could not hash the write set\'s files: %s' % ' '.join(err.split())[:200])
        states.update(zip(hashed, ids))
    return states


def why(main, base, ref):
    if main == ABSENT:
        return 'absent from the main checkout, present at %s' % ref
    if base == ABSENT:
        return 'in the main checkout, not at %s' % ref
    return 'differs from %s' % ref


def check(brief_path, repository, setting):
    """The result object. Raises Refused for a brief, repository or base that cannot be read."""
    decide.ledger_scripts()
    import capture_claude_code as capture
    try:
        text = Path(brief_path).read_text(encoding='utf-8')
    except (OSError, UnicodeDecodeError) as exc:
        raise Refused('the brief could not be read: %s' % exc)
    result = {'brief': str(brief_path), 'repository': None, 'base': None, 'write_set': None, 'compared': 0,
              'differences': [], 'refuse': False, 'reason': None}
    lines = capture.write_set_of(text)
    if not capture.is_writer(text):
        result.update(write_set=lines or ['none'], reason='not a writer: the brief\'s write set is none, so no '
                                                          'worktree is made')
        return result
    try:
        write_set, repo = briefs.write_set_paths(lines, repository)
    except briefs.Refused as exc:
        raise Refused(str(exc))
    result.update(write_set=write_set, repository=repo)
    top = os.path.realpath(repo)
    elsewhere = [path for path in write_set if os.path.realpath(nearest_top(Path(repo) / path) or '') != top]
    if elsewhere:
        raise Refused('the write set spans two repositories: %s lie in another repository than %s. Split the part '
                      'into one member for each repository' % (', '.join(elsewhere), repo))
    ref, commit = base_commit(repo, setting)
    result['base'] = {'setting': setting, 'ref': ref, 'commit': commit}
    if commit is None:
        hint = '. Where the harness branches worktrees from local HEAD, pass --base head' if setting == 'default' else ''
        raise Refused('the commit the worktree will branch from, %s, cannot be read in %s%s' % (ref, repo, hint))
    paths, at_base = [], {}
    for entry in write_set:
        at_base.update(base_files(repo, commit, entry))
        for path in main_files(repo, entry):
            if path not in paths:
                paths.append(path)
    for path in at_base:
        if path not in paths:
            paths.append(path)
    states = main_state(repo, paths)
    result['compared'] = len(paths)
    for path in sorted(paths):
        main, base = states[path], at_base.get(path, ABSENT)
        if main != base:
            result['differences'].append({'path': path, 'main': main, 'base': base, 'why': why(main, base, ref)})
    if result['differences']:
        shown = result['differences'][:SHOWN]
        more = len(result['differences']) - len(shown)
        result['refuse'] = True
        result['reason'] = ('the worktree branches from %s at %s and would not hold the write set as the main checkout '
                            'has it: %s%s. Commit each write-set file you have changed, by path, before the '
                            'dispatch; a commit %s lacks is not in the worktree either'
                            % (ref, commit[:12], '; '.join('%s (%s)' % (d['path'], d['why']) for d in shown),
                               ' and %d more' % more if more else '', ref))
    else:
        result['reason'] = 'the worktree will hold the write set as the main checkout has it (%d files compared ' \
                           'at %s)' % (len(paths), ref)
    return result


def main(argv=None):
    parser = argparse.ArgumentParser(description='Refuse a writer whose worktree would not hold its write set.')
    parser.add_argument('--brief', required=True)
    parser.add_argument('--repository')
    parser.add_argument('--base', choices=sorted(BASES), default='head')
    try:
        args = parser.parse_args(sys.argv[1:] if argv is None else argv)
    except SystemExit:
        return decide.fail(1, 'the arguments could not be read')
    try:
        result = check(args.brief, args.repository, args.base)
    except Refused as exc:
        result = {'brief': args.brief, 'refuse': True, 'reason': str(exc)}
    except decide.CannotRun as exc:
        return decide.fail(2, str(exc))
    print(json.dumps(result, indent=1, ensure_ascii=False))
    return 1 if result['refuse'] else 0


if __name__ == '__main__':
    sys.exit(main())
