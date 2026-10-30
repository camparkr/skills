#!/usr/bin/env python3
"""Read a task's stage exactly, from named files only.

    python3 stage.py --task <id> [--build-root <folder> ...] [--ratified-root <folder> ...]
                     [--task-key task_id] [--status-key status]

A build specification exists for a task when a file named `*-build-spec.md`, anywhere under a build folder, carries
that task's id at the task key of its front matter. A ratified specification exists when a file named
`*-surviving-spec.md` or `*-architectural-spec*.md`, anywhere under a ratified folder, carries that task's id and
`ratified` at the status key. No other file counts, whatever it carries: a proposal, findings, test criteria and an
amendment are named otherwise.

The stage is, in this order:

  * `build specification`, where a build specification exists;
  * `ratified specification`, where a ratified specification exists and no build specification does;
  * `unrecorded (no specification found for <task-id>)` otherwise.

The folders are arguments, never written into this script: each --build-root and --ratified-root names one folder,
and may hold a glob pattern, such as `<root>/projects/*/docs`, to name several. A folder is read to any depth, without
following links. A file whose front matter cannot be read is listed under `unreadable` and not counted. With no task
id the stage is `unrecorded (no task id was given)`; with no folder, `unrecorded (no folder is named for the stage
read)`.

decide.py imports this module and passes the stage to the persona and effort decisions as a fact.

Output: one JSON object, {"task", "stage", "found": {"build", "ratified"}, "unreadable", "roots"}. Exit codes: 0 read
(whatever the stage); 2 cannot run (PyYAML is not installed to read front matter). It writes nothing.
"""

import argparse
import fnmatch
import glob
import json
import os
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

import decide  # noqa: E402

BUILD_NAMES = ('*-build-spec.md',)
RATIFIED_NAMES = ('*-surviving-spec.md', '*-architectural-spec*.md')
RATIFIED = 'ratified'
BUILD_STAGE = 'build specification'
RATIFIED_STAGE = 'ratified specification'
NOT_FOUND = 'unrecorded (no specification found for %s)'
NO_TASK = 'unrecorded (no task id was given)'
NO_ROOT = 'unrecorded (no folder is named for the stage read)'
SKIPPED_FOLDERS = ('.git',)


def add_arguments(parser):
    """The stage read's options, shared with decide.py."""
    parser.add_argument('--task')
    parser.add_argument('--build-root', action='append', default=[])
    parser.add_argument('--ratified-root', action='append', default=[])
    parser.add_argument('--task-key', default='task_id')
    parser.add_argument('--status-key', default='status')


def folders(roots):
    """(the folders the roots name, in order and once each; the roots that named none)."""
    out, absent = [], []
    for root in roots:
        named = sorted(glob.glob(os.path.expanduser(root))) if glob.has_magic(root) else [os.path.expanduser(root)]
        found = [Path(path) for path in named if Path(path).is_dir()]
        if not found:
            absent.append(root)
        for folder in found:
            if folder not in out:
                out.append(folder)
    return out, absent


def named_files(folder, patterns):
    """Every file under `folder`, to any depth and following no link, whose name matches one of `patterns`."""
    out = []
    for top, subfolders, files in os.walk(str(folder), followlinks=False):
        subfolders[:] = sorted(name for name in subfolders if name not in SKIPPED_FOLDERS)
        for name in sorted(files):
            if any(fnmatch.fnmatchcase(name, pattern) for pattern in patterns):
                out.append(Path(top) / name)
    return out


def carries(path, task, task_key, status_key, ratified, unreadable):
    """Whether the file's front matter carries the task's id, and, where `ratified`, the status `ratified`."""
    try:
        meta = decide.frontmatter(path)
    except decide.CannotRun:
        raise
    except Exception:
        unreadable.append(str(path))
        return False
    value = decide.dig(meta, task_key)
    if value is None or str(value) != task:
        return False
    return not ratified or decide.dig(meta, status_key) == RATIFIED


def read(task, build_roots, ratified_roots, task_key='task_id', status_key='status'):
    """The stage reading: {task, stage, found: {build, ratified}, unreadable, roots}. Raises decide.CannotRun where
    PyYAML is missing."""
    build_folders, build_absent = folders(build_roots or [])
    ratified_folders, ratified_absent = folders(ratified_roots or [])
    reading = {'task': task, 'stage': None, 'found': {'build': [], 'ratified': []}, 'unreadable': [],
               'roots': {'build': [str(f) for f in build_folders], 'ratified': [str(f) for f in ratified_folders],
                         'naming_no_folder': build_absent + ratified_absent}}
    if not task:
        reading['stage'] = NO_TASK
        return reading
    if not build_roots and not ratified_roots:
        reading['stage'] = NO_ROOT
        return reading
    unreadable = reading['unreadable']
    for kind, found_in, patterns, ratified in (('build', build_folders, BUILD_NAMES, False),
                                               ('ratified', ratified_folders, RATIFIED_NAMES, True)):
        seen = reading['found'][kind]
        for folder in found_in:
            for path in named_files(folder, patterns):
                if str(path) not in seen and carries(path, task, task_key, status_key, ratified, unreadable):
                    seen.append(str(path))
    if reading['found']['build']:
        reading['stage'] = BUILD_STAGE
    elif reading['found']['ratified']:
        reading['stage'] = RATIFIED_STAGE
    else:
        reading['stage'] = NOT_FOUND % task
    return reading


def from_arguments(args):
    return read(args.task, args.build_root, args.ratified_root, args.task_key, args.status_key)


def main(argv=None):
    parser = argparse.ArgumentParser(description='Read a task\'s stage from named files only.')
    add_arguments(parser)
    try:
        args = parser.parse_args(sys.argv[1:] if argv is None else argv)
    except SystemExit:
        return decide.fail(2, 'the arguments could not be read')
    try:
        reading = from_arguments(args)
    except decide.CannotRun as exc:
        return decide.fail(2, str(exc))
    print(json.dumps(reading, indent=1, ensure_ascii=False))
    return 0


if __name__ == '__main__':
    sys.exit(main())
