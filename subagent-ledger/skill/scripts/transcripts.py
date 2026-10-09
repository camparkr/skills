#!/usr/bin/env python3
"""Read a Claude Code transcript: the model that ran, its four counters, its folder and its tool calls.

A Claude Code transcript is a JSON Lines file. Each assistant row carries `message.model` and a
`message.usage` block, but a row is not an API message: one message is written across several rows
while it streams, each holding the counters as they stood at that moment (output 1, then 1, then
206). Summing every row over-counts and taking the first under-counts. So the rows are grouped by
`message.id` (or the row's `uuid` where a row has no message id), each counter's maximum is kept
for the group, and the groups are summed.

The rules, in order:

  * a row counts when its `message.usage` holds at least one of `input_tokens`,
    `cache_creation_input_tokens`, `cache_read_input_tokens` and `output_tokens`;
  * the group key is `message.id`, then `uuid`, then the row's position;
  * each counter's maximum within a group, then the sum over groups;
  * the models are the distinct `message.model` values of each group's first row, in order;
  * `input` is the transcript's own `input_tokens`, which already excludes the cache counters.

The last request is the last group in the file; a harness hook that reports one request's usage is
compared with it.

`cwd` is read from the first row that carries one, and every `tool_use` block's `name` and `input`
is kept, so `isolation()` can list what the run touched outside its folder.

Use it as a module (`read(path)`, `isolation(reading)`, `lane_path(...)`) or as a command:

    python3 transcripts.py <transcript.jsonl>

which prints the reading as JSON. It changes nothing.
"""

import glob
import json
import os
import posixpath
import re
import sys
from pathlib import Path

COUNTERS = (
    ('input', 'input_tokens'),
    ('cache_write', 'cache_creation_input_tokens'),
    ('cache_read', 'cache_read_input_tokens'),
    ('output', 'output_tokens'),
)
PATH_KEYS = ('file_path', 'path', 'notebook_path')
COMMAND_KEYS = ('command',)
ISOLATION_LIMIT = ('none known for tool inputs; a shell command is listed when it names an absolute '
                   'path outside the folder, and a path a command reaches by other means is not seen')


def config_folder():
    """The Claude Code configuration folder: $CLAUDE_CONFIG_DIR, or ~/.claude."""
    named = os.environ.get('CLAUDE_CONFIG_DIR')
    return Path(named).expanduser() if named else Path.home() / '.claude'


def lane_path(session, agent_id, folder=None):
    """The subagent's transcript, <config>/projects/*/<session>/subagents/agent-<id>.jsonl, or None."""
    if not session or not agent_id:
        return None
    root = Path(folder) if folder else config_folder()
    found = sorted(glob.glob(str(root / 'projects' / '*' / glob.escape(session) / 'subagents'
                                 / ('agent-%s.jsonl' % glob.escape(agent_id)))))
    return Path(found[0]) if found else None


def rows_of(path):
    """Every JSON object in the file, one per line; a line that does not parse is skipped."""
    out = []
    with open(path, encoding='utf-8', errors='ignore') as handle:
        for line in handle:
            try:
                row = json.loads(line)
            except ValueError:
                continue
            if isinstance(row, dict):
                out.append(row)
    return out


def _usage(row):
    message = row.get('message')
    usage = message.get('usage') if isinstance(message, dict) else None
    if not isinstance(usage, dict):
        return None
    if not any(native in usage for _, native in COUNTERS):
        return None
    return usage


def _group_key(row, position):
    message = row.get('message')
    key = message.get('id') if isinstance(message, dict) else None
    if isinstance(key, str):
        return key
    key = row.get('uuid')
    if isinstance(key, str):
        return key
    return 'row-%d' % position


def read(path):
    """The reading of one transcript, as a dict. A file that cannot be read gives `error`."""
    reading = {'path': str(path), 'rows': 0, 'requests': 0, 'model': None, 'models': [],
               'tokens': None, 'last_request': None, 'cwd': None, 'tool_uses': [], 'error': None}
    try:
        rows = rows_of(path)
    except OSError as exc:
        reading['error'] = 'the transcript could not be read: %s' % exc
        return reading
    reading['rows'] = len(rows)
    groups, order = {}, []
    usage_rows = [row for row in rows if _usage(row) is not None]
    for position, row in enumerate(usage_rows):
        key = _group_key(row, position)
        if key not in groups:
            groups[key] = [row, dict((label, 0) for label, _ in COUNTERS)]
            order.append(key)
        usage = _usage(row)
        held = groups[key][1]
        for label, native in COUNTERS:
            value = usage.get(native)
            if isinstance(value, int) and not isinstance(value, bool):
                held[label] = max(held[label], value)
    for row in rows:
        if reading['cwd'] is None and isinstance(row.get('cwd'), str):
            reading['cwd'] = row['cwd']
        message = row.get('message')
        content = message.get('content') if isinstance(message, dict) else None
        if isinstance(content, list):
            for part in content:
                if isinstance(part, dict) and part.get('type') == 'tool_use':
                    reading['tool_uses'].append({'name': part.get('name'), 'input': part.get('input')})
    if not order:
        reading['error'] = 'no row of the transcript carries usage'
        return reading
    for key in order:
        message = groups[key][0].get('message') or {}
        model = message.get('model')
        if isinstance(model, str) and model not in reading['models']:
            reading['models'].append(model)
    reading['model'] = ', '.join(reading['models']) or None
    reading['requests'] = len(order)
    reading['tokens'] = dict((label, sum(groups[key][1][label] for key in order))
                             for label, _ in COUNTERS)
    reading['last_request'] = dict(groups[order[-1]][1])
    return reading


def _inside(path, folder):
    path = posixpath.normpath(path)
    folder = posixpath.normpath(folder)
    return path == folder or path.startswith(folder.rstrip('/') + '/')


def _absolute(value, folder):
    if value.startswith('~'):
        value = os.path.expanduser(value)
    if value.startswith('/'):
        return value
    return posixpath.join(folder, value)


ABSOLUTE = re.compile(r'''(?:^|[\s'"=:(])((?:~|/)[^\s'";|&<>()]*)''')


def isolation(reading):
    """What the run touched outside its folder, read from its own transcript (§3h)."""
    folder = reading.get('cwd')
    if not folder:
        return 'unrecorded (the transcript records no working folder)'
    outside = []
    for use in reading.get('tool_uses') or []:
        given = use.get('input')
        if not isinstance(given, dict):
            continue
        for key in PATH_KEYS:
            value = given.get(key)
            if isinstance(value, str) and value and not _inside(_absolute(value, folder), folder):
                outside.append({'tool': use.get('name'), key: value})
        for key in COMMAND_KEYS:
            value = given.get(key)
            if not isinstance(value, str):
                continue
            named = [found for found in ABSOLUTE.findall(value)
                     if not _inside(_absolute(found, folder), folder)]
            if named:
                outside.append({'tool': use.get('name'), key: value, 'paths': named})
    return {'folder': folder, 'outside': outside, 'read_from': reading.get('path'),
            'limit': ISOLATION_LIMIT}


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    if len(argv) != 1:
        print('usage: transcripts.py <transcript.jsonl>', file=sys.stderr)
        return 1
    reading = read(argv[0])
    reading['isolation'] = isolation(reading)
    reading.pop('tool_uses', None)
    print(json.dumps(reading, indent=2))
    return 0


if __name__ == '__main__':
    sys.exit(main())
