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

A Codex rollout is read by the rules its own record keeps (the reader tells it by its first row,
`session_meta`). Each `token_count` event carries a cumulative `total_token_usage`, so the last clean
one is the run's total; summing them over-counts. Its `input_tokens` includes the cache, so `input`
is that less `cached_input_tokens` (the cache read) and less `cache_write_input_tokens` where the
rollout writes one; where it does not, the cache-write counter is unrecorded. A row whose total is
non-zero while every counter it breaks into is zero is passed over. The models are the distinct
`payload.model` values, the effort is `turn_context.effort`, the folder is `turn_context.cwd`, and
each `exec_command`'s text is kept for `isolation()`. A rollout that Codex continued in a second file
after compaction is not read short: its counters are unrecorded, saying so.

`question_calls(path, tool)` lists the answered calls of the harness's tool for putting a question to
the user (Claude Code's `AskUserQuestion`): each `tool_use` of that name whose `tool_result` stands
later in the transcript and is not an error, with the time of each row.

Use it as a module (`read(path)`, `isolation(reading)`, `lane_path(...)`, `question_calls(...)`) or as a
command:

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
PATH_KEYS = ('file_path', 'path', 'notebook_path', 'filePath', 'dir_path')
COMMAND_KEYS = ('command',)
ISOLATION_LIMIT = ('none known for tool inputs; a shell command is listed when it names an absolute '
                   'path outside the folder, and a path a command reaches by other means is not seen')
CODEX_LIMIT = ('each command is listed as the model wrote it, when it names an absolute path outside '
               'the folder; a read inside a script it ran is not seen')
CODEX_COUNTERS = ('input_tokens', 'cached_input_tokens', 'cache_write_input_tokens', 'output_tokens')
CODEX_NO_CACHE_WRITE = 'unrecorded (the rollout records no cache-write counter)'
CODEX_CONTINUED = 'unrecorded (the session continues in another rollout)'
CODEX_ENDS = ('task_complete', 'turn_aborted')


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


def read(path, span=None):
    """The reading of one transcript, as a dict. A file that cannot be read gives `error`.

    With `span`, (first row, last row) counted from 0, only those rows of a Claude Code transcript are read: one
    turn of a subagent that was resumed later in the same file."""
    reading = {'path': str(path), 'rows': 0, 'requests': 0, 'model': None, 'models': [],
               'tokens': None, 'last_request': None, 'cwd': None, 'tool_uses': [], 'error': None,
               'harness': 'claude-code'}
    try:
        rows = rows_of(path)
    except OSError as exc:
        reading['error'] = 'the transcript could not be read: %s' % exc
        return reading
    if span is not None and not is_codex(rows):
        rows = rows[span[0]:span[1] + 1]
        reading['span'] = list(span)
    reading['rows'] = len(rows)
    if is_codex(rows):
        return read_codex(path, rows, reading)
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


# ---------------------------------------------------------------------------
# Codex rollouts
# ---------------------------------------------------------------------------

def is_codex(rows):
    """A Codex rollout opens with a `session_meta` row."""
    return bool(rows) and rows[0].get('type') == 'session_meta'


def _payload(row):
    payload = row.get('payload')
    return payload if isinstance(payload, dict) else {}


def _count(value):
    return isinstance(value, int) and not isinstance(value, bool)


def _clean_usages(rows):
    """Each counter row's cumulative usage, less the rows whose counters are all zero under a total."""
    found = []
    for row in rows:
        payload = _payload(row)
        if row.get('type') != 'event_msg' or payload.get('type') != 'token_count':
            continue
        info = payload.get('info')
        usage = info.get('total_token_usage') if isinstance(info, dict) else None
        if not isinstance(usage, dict) or not any(key in usage for key in CODEX_COUNTERS):
            continue
        parts = [usage.get(key) for key in CODEX_COUNTERS if key in usage]
        if _count(usage.get('total_tokens')) and usage['total_tokens'] > 0 and all(
                _count(value) and value == 0 for value in parts):
            continue
        found.append(usage)
    return found


def codex_usage(usages):
    """The run's total: the last cumulative value. Never a sum of them, which over-counts."""
    return usages[-1]


def codex_complete(path, answer=None):
    """True once the rollout holds the run's end, as far as Codex writes it before SubagentStop returns.

    Codex writes `task_complete` only after its SubagentStop hook has returned, so a hook that waited
    for it would wait for ever. What it has written by then is the answer, as an `agent_message`, and
    the counter row after it. So the last turn is complete when it
    holds `answer` in an `agent_message` followed by a `token_count`, or when it has ended
    (`task_complete` or `turn_aborted`). With no answer to look for, a `token_count` after the last
    `agent_message` will do.
    """
    try:
        rows = rows_of(path)
    except OSError:
        return False
    started = -1
    for position, row in enumerate(rows):
        if row.get('type') == 'event_msg' and _payload(row).get('type') == 'task_started':
            started = position
    wanted = (answer or '').strip()
    said = -1
    for position, row in enumerate(rows):
        if position <= started or row.get('type') != 'event_msg':
            continue
        payload = _payload(row)
        kind = payload.get('type')
        if kind in CODEX_ENDS:
            return True
        if kind == 'agent_message' and isinstance(payload.get('message'), str):
            if not wanted or wanted in payload['message']:
                said = position
        if kind == 'token_count' and said >= 0 and position > said:
            return True
    return False


def codex_continues(path, rows):
    """True when Codex continued this session in another rollout after compaction."""
    own = _payload(rows[0]).get('id') if rows else None
    path = Path(path)
    if not isinstance(own, str) or not own:
        return False
    if '_' in path.name:
        return True
    store = next((parent for parent in path.parents if parent.name == 'sessions'), None)
    if store is None:
        return False
    return bool(glob.glob(str(store / '*' / '*' / '*' / ('rollout-*-%s_*.jsonl' % glob.escape(own)))))


def read_codex(path, rows, reading):
    reading['harness'] = 'codex'
    reading['isolation_limit'] = CODEX_LIMIT
    reading['complete'] = any(_payload(row).get('type') in CODEX_ENDS for row in rows
                              if row.get('type') == 'event_msg')
    for row in rows:
        payload = _payload(row)
        model = payload.get('model')
        if isinstance(model, str) and model and model not in reading['models']:
            reading['models'].append(model)
        if row.get('type') == 'turn_context':
            if isinstance(payload.get('cwd'), str) and reading['cwd'] is None:
                reading['cwd'] = payload['cwd']
            if isinstance(payload.get('effort'), str) and payload['effort']:
                reading['effort'] = payload['effort']
        if row.get('type') == 'response_item' and payload.get('type') == 'function_call':
            given = payload.get('arguments')
            try:
                given = json.loads(given) if isinstance(given, str) else given
            except ValueError:
                given = {'command': given}
            if not isinstance(given, dict):
                continue
            command = given.get('cmd', given.get('command'))
            if isinstance(command, list):
                command = ' '.join(str(word) for word in command)
            kept = {}
            if isinstance(command, str):
                kept['command'] = command
            if isinstance(given.get('workdir'), str):
                kept['workdir'] = given['workdir']
            reading['tool_uses'].append({'name': payload.get('name'), 'input': kept})
    if reading['cwd'] is None and isinstance(_payload(rows[0]).get('cwd'), str):
        reading['cwd'] = _payload(rows[0])['cwd']
    reading['model'] = ', '.join(reading['models']) or None
    if codex_continues(path, rows):
        reading['tokens'] = CODEX_CONTINUED
        return reading
    usages = _clean_usages(rows)
    if not usages:
        reading['error'] = 'no row of the rollout carries a clean counter'
        return reading
    reading['requests'] = len(usages)
    usage = codex_usage(usages)
    cache_read = usage.get('cached_input_tokens', 0)
    cache_write = usage.get('cache_write_input_tokens')
    fresh = usage.get('input_tokens', 0) - cache_read - (cache_write if _count(cache_write) else 0)
    reading['tokens'] = {'input': fresh,
                         'cache_write': cache_write if _count(cache_write) else CODEX_NO_CACHE_WRITE,
                         'cache_read': cache_read, 'output': usage.get('output_tokens', 0)}
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
    """What the run touched outside its folder, read from its own transcript."""
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
        workdir = given.get('workdir')
        if isinstance(workdir, str) and workdir and not _inside(_absolute(workdir, folder), folder):
            outside.append({'tool': use.get('name'), 'workdir': workdir})
        for key in COMMAND_KEYS:
            value = given.get(key)
            if not isinstance(value, str):
                continue
            named = [found for found in ABSOLUTE.findall(value)
                     if not _inside(_absolute(found, folder), folder)]
            if named:
                outside.append({'tool': use.get('name'), key: value, 'paths': named})
    return {'folder': folder, 'outside': outside, 'read_from': reading.get('path'),
            'limit': reading.get('isolation_limit') or ISOLATION_LIMIT}


def question_calls(path, tool):
    """[{id, asked_at, answered_at}] for each answered call of `tool` in the transcript, in order.

    A call counts when its `tool_result` is in the file and is not marked `is_error`. Raises OSError
    when the file cannot be read.
    """
    asked, answered = {}, {}
    for row in rows_of(path):
        message = row.get('message') if isinstance(row.get('message'), dict) else {}
        content = message.get('content')
        if not isinstance(content, list):
            continue
        for block in content:
            if not isinstance(block, dict):
                continue
            if block.get('type') == 'tool_use' and block.get('name') == tool and isinstance(block.get('id'), str):
                asked.setdefault(block['id'], row.get('timestamp'))
            elif (block.get('type') == 'tool_result' and block.get('tool_use_id') in asked
                  and not block.get('is_error')):
                answered.setdefault(block['tool_use_id'], row.get('timestamp'))
    return [{'id': call_id, 'asked_at': at, 'answered_at': answered[call_id]}
            for call_id, at in asked.items() if call_id in answered]


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
