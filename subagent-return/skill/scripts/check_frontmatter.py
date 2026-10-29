#!/usr/bin/env python3
"""Check 2: every Markdown file of the kinds the settings name that the member wrote has front matter that conforms.

What the member wrote decides whether the check applies, never what its report names: the transcript's Write, Edit
and NotebookEdit calls whose results are not errors, and, for a writer, its worktree's changes against the baseline.
A file counts when its name ends `.md` and, where the settings give `markdown` (glob patterns read against the path
relative to the working root), it matches one of them. With no such file the result is `not_applicable`.

The validator is a setting, `return_check.validator` in the ledger folder's config.json: a command, to which each
file's path is added as its last argument. Exit 0 passes the file. A non-zero exit fails it, unless its output shows
the checker failed rather than the file: then the file is `not_checkable`. The check itself finds a file that no
longer exists, `not_checkable (path not found: ...)`. The validator's own output marks the rest by the patterns in
`return_check.validator_not_checkable` (regular expressions, searched in its standard output and standard error;
by default a Python traceback), so a path the validator excludes or a validator that cannot load its own inputs reads
`not_checkable`, never `fail`. With no validator set, the check is `not_checkable (no front-matter validator is set)`.

A transcript holding a write call with no result yet, or one whose result cannot be read as an error or not, gives
`not_checkable` with that reason, as does a worktree git cannot read against its baseline. Where one file fails and
another cannot be checked, the result is `fail`, naming both. A Markdown file the worktree's changes show deleted is
not read.
"""

import fnmatch
import os
import re
import shlex
import subprocess

import call_context as cc

CHECK, NAME = 2, 'frontmatter'
DEFAULT_NOT_CHECKABLE = (r'Traceback \(most recent call last\)',)
VALIDATOR_SECONDS = 5


def markdown_written(call):
    """(the canonical paths of the Markdown files the member wrote, of the kinds the settings name; problem)."""
    problem = call.write_problem()
    if problem:
        return None, problem
    paths = list(call.written())
    if call.writer:
        changed, problem = call.changes()
        if problem:
            return None, problem
        # A file the worktree's changes show deleted holds no front matter to read; a deleted file the transcript
        # wrote is still read, and found missing.
        paths += [path for path in changed if path not in paths and os.path.exists(path)]
    patterns = call.settings.get('markdown')
    patterns = [p for p in patterns if isinstance(p, str)] if isinstance(patterns, list) else None
    out = []
    for path in paths:
        if not path.endswith('.md'):
            continue
        if patterns is not None:
            shown = os.path.relpath(path, call.root) if call.root and cc.inside(path, call.root) else path
            if not any(fnmatch.fnmatch(shown, pattern) for pattern in patterns):
                continue
        out.append(path)
    return out, None


def first_line(text):
    for line in (text or '').splitlines():
        if line.strip():
            return cc.one_line(line, 160)
    return ''


def validate(command, path, patterns, seconds):
    """(`ok`, `fail` or `not_checkable`, the text that says why)."""
    if not os.path.exists(path):
        return cc.NOT_CHECKABLE, 'path not found: %s' % path
    try:
        done = subprocess.run(shlex.split(command) + [path], capture_output=True, text=True, timeout=seconds)
    except subprocess.TimeoutExpired:
        return cc.NOT_CHECKABLE, 'the validator timed out on %s' % path
    except (OSError, ValueError) as exc:
        return cc.NOT_CHECKABLE, 'the validator could not run: %s' % cc.one_line(exc)
    if done.returncode == 0:
        return 'ok', None
    said = '%s\n%s' % (done.stdout or '', done.stderr or '')
    for pattern in patterns:
        found = re.search(pattern, said)
        if found:
            line = next((line for line in said.splitlines() if re.search(pattern, line)), found.group(0))
            return cc.NOT_CHECKABLE, '%s: %s' % (path, cc.one_line(line, 160))
    return cc.FAIL, '%s: %s' % (path, first_line(done.stderr) or first_line(done.stdout)
                                  or 'the validator exited %d' % done.returncode)


def run(call):
    files, problem = markdown_written(call)
    if problem:
        return cc.result(CHECK, NAME, cc.NOT_CHECKABLE, reason=problem)
    if not files:
        return cc.result(CHECK, NAME, cc.NOT_APPLICABLE)
    command = call.settings.get('validator')
    if not isinstance(command, str) or not command.strip():
        return cc.result(CHECK, NAME, cc.NOT_CHECKABLE, reason='no front-matter validator is set')
    patterns = call.settings.get('validator_not_checkable')
    patterns = [p for p in patterns if isinstance(p, str)] if isinstance(patterns, list) else list(
        DEFAULT_NOT_CHECKABLE)
    seconds = call.settings.get('validator_seconds')
    seconds = seconds if isinstance(seconds, (int, float)) and not isinstance(seconds, bool) and seconds > 0 \
        else VALIDATOR_SECONDS
    failed, unchecked = [], []
    for path in files:
        verdict, why = validate(command, path, patterns, seconds)
        if verdict == cc.FAIL:
            failed.append((path, why))
        elif verdict == cc.NOT_CHECKABLE:
            unchecked.append((path, why))
    if failed:
        reason = '; '.join(why for _path, why in failed)
        if unchecked:
            reason += '; also not checkable: ' + '; '.join(why for _path, why in unchecked)
        repair = ' '.join('Run the validator on %s and fix what it names (%s), or send the member back to fix it.'
                          % (path, why.split(': ', 1)[-1]) for path, why in failed)
        return cc.result(CHECK, NAME, cc.FAIL, reason=reason, paths=[path for path, _why in failed], repair=repair)
    if unchecked:
        return cc.result(CHECK, NAME, cc.NOT_CHECKABLE, reason='; '.join(why for _path, why in unchecked))
    return cc.result(CHECK, NAME, cc.PASS)
