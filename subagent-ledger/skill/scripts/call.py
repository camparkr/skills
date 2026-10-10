#!/usr/bin/env python3
"""Make one call to Gemini CLI or Cursor from a fresh working folder, and write both records.

    python3 call.py --harness gemini-cli|cursor --brief <path> [--model <m>] [--ledger <folder>]
                    [--session <id>]

The dispatch record is written first. The script then makes a fresh folder under $TMPDIR and starts
the harness with that folder as its working directory, set on the child process itself rather than
through PWD, and with the harness's configuration-folder variable set to the folder the ledger's
`config.json` names under `harness_homes` (Gemini CLI `GEMINI_CLI_HOME`, Cursor `CURSOR_CONFIG_DIR`).
It sets no time limit: the run time is the two records' times.

The return record reads:

  * from the envelope the harness prints (`gemini -o json`, `cursor-agent --output-format json`):
    the outcome and the four counters;
  * from the harness's own record of the run (Gemini CLI's chat under its configuration folder,
    Cursor's chat store): the model, the isolation evidence, which is the folder that record
    names and every tool call's path or command outside it, and the run's session id.

The run is a whole agent session, so the records name it as `agent_id`: the dispatch reads
`unrecorded (not yet returned)`, and the return carries the session id the run's own record names
(the first row of the Gemini CLI chat; the Cursor chat store's meta.json), or
`unrecorded (the run's own record names no session: <why>)`. A script's own single model request,
which has no agent, reads `unrecorded (no agent: script call)`; this script never writes that.

A non-zero exit, a sign-in prompt or a usage limit gives `failed`, its class read from reasons.json.
The answer is printed on standard output. The exit code is 0 when the call was served or came back
empty, 1 when it failed, and 2 for a usage error, which writes no record.

The dispatch record's `act_kind` is read from the brief's frontmatter and translated as the hook
captures do (capture_claude_code.py's kind_of()). Where the ledger folder's `config.json` names a
`triage_command`, it runs on the brief before the call, as at a hook capture's dispatch: its reading
is `triage_kind`, and `act_kind` takes it where the brief names no kind. `user_answer` for a
user-decision call is unrecorded, since a call script is given no transcript of its caller.
`effort_assigned` reads that this script takes no effort setting for the call.

The calling session is `--session`, or the one self-identification variable set
(`CLAUDE_CODE_SESSION_ID` for Claude Code, `CODEX_THREAD_ID` for Codex), whose harness the records
name; with neither, or both, the session is unrecorded and says why.
"""

import argparse
import glob
import json
import os
import re
import shutil
import sqlite3
import subprocess
import sys
import tempfile
import uuid
from pathlib import Path

HERE = Path(__file__).resolve().parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

import capture_claude_code as shared  # noqa: E402
import ledger  # noqa: E402
import transcripts  # noqa: E402

NOT_YET = 'unrecorded (not yet returned)'
NO_SESSION = "unrecorded (the run's own record names no session: %s)"
NOT_REACHED = 'the run did not reach the harness'
NO_CALLER = 'unrecorded (a call script cannot tell a lane from its parent)'
NO_COST = 'unrecorded (the harness reports no cost for this route)'
NO_EFFORT = 'unrecorded (a call script reads no effort level)'
NO_SPEND = 'unrecorded (this call script keeps no spend line)'
LIMIT = ('each tool call is listed as the model wrote it, when it names an absolute path outside the '
         'folder; a read inside a script it ran is not seen')
CURSOR_LIMIT = LIMIT + '; untested against a planted read'
SESSION_VARIABLES = (('CLAUDE_CODE_SESSION_ID', 'claude-code'), ('CODEX_THREAD_ID', 'codex'))
HARNESSES = {
    'gemini-cli': {'program': 'gemini', 'variable': 'GEMINI_CLI_HOME',
                   'auth': ('GEMINI_API_KEY', 'GOOGLE_API_KEY', 'GOOGLE_GENAI_USE_VERTEXAI')},
    'cursor': {'program': 'cursor-agent', 'variable': 'CURSOR_CONFIG_DIR', 'auth': ('CURSOR_API_KEY',)},
}
MODEL_NAME = re.compile(r'"modelName"\s*:\s*"([^"]+)"')
STDERR_KEPT = 2000
# The keys a Cursor chat store's meta.json could name its session under. The stores seen so far name none.
CURSOR_SESSION_KEYS = ('sessionId', 'agentId')
NO_TRANSCRIPT = 'unrecorded (a call script reads no transcript of its caller)'


class Held:
    """What an error line written before the dispatch names: the call script's session and call id."""

    def __init__(self, session, call_id, harness):
        self.session, self.call_id, self.harness = session, call_id, harness

    def error(self, folder, stage, reason, record='unknown'):
        ledger.error(ledger=folder, stage=stage, reason=reason, session=self.session, call_id=self.call_id,
                     agent_id=NOT_YET, harness=self.harness, event='call.py', record=record)


def kind_fields(folder, brief, held):
    """act_kind, triage_kind and user_answer for the dispatch record, and the seconds the triage ran.

    The brief's frontmatter gives its kind, and the ledger folder's triage_command, where named, reads
    one as the hook captures do (capture_claude_code.py's dispatch_kind()); the brief's governs.
    """
    if isinstance(brief, str):
        found, seconds = shared.dispatch_kind(folder, brief, held)
        kind, triage_kind = found['act_kind'], found['triage_kind']
    else:
        kind, triage_kind, seconds = shared.NO_KIND, shared.NO_TRIAGE, None
    return {'act_kind': kind, 'triage_kind': triage_kind,
            'user_answer': NO_TRANSCRIPT if kind == shared.USER_DECISION else shared.NOT_A_DECISION}, seconds


def main(argv=None):
    parser = argparse.ArgumentParser(prog='call.py', description='Make one call and write both records.')
    parser.add_argument('--harness', required=True, choices=sorted(HARNESSES))
    parser.add_argument('--brief', required=True)
    parser.add_argument('--model')
    parser.add_argument('--ledger')
    parser.add_argument('--session')
    try:
        args = parser.parse_args(sys.argv[1:] if argv is None else argv)
    except SystemExit as exc:
        return 2 if exc.code else 0
    spec = HARNESSES[args.harness]
    folder = ledger.ledger_folder(args.ledger)
    session, caller_harness = calling_session(args.session)
    call_id = str(uuid.uuid4())
    home, home_reason = harness_home(folder, args.harness)
    base = {'call_id': call_id, 'session': session, 'agent_id': NOT_YET, 'route': 'script',
            'harness': caller_harness, 'caller': NO_CALLER}

    try:
        brief = Path(args.brief).expanduser().read_text(encoding='utf-8')
    except (OSError, UnicodeDecodeError) as exc:
        brief, brief_error = None, 'the brief could not be read: %s' % exc
    else:
        brief_error = None
    command = command_for(args.harness, '<the brief>', args.model)
    kinds, seconds = kind_fields(folder, brief, Held(session, call_id, caller_harness))
    ledger.dispatch(ledger=folder, model_requested=args.model, brief=brief,
                    auth_route=auth_route(spec, home, home_reason), brief_source=args.brief,
                    effort_assigned=shared.NO_EFFORT_SETTING,
                    harness_payload=shared.with_triage_time({'called_harness': args.harness, 'command': command},
                                                            seconds), **dict(base, **kinds))
    if brief is None:
        return finish(folder, base, 'failed', {'class': 'other', 'text': brief_error},
                      payload={'called_harness': args.harness}, answer=None)

    work = make_folder()
    env = dict(os.environ)
    if home:
        env[spec['variable']] = home
    if shutil.which(spec['program'], path=env.get('PATH')) is None:
        return finish(folder, base, 'failed', {'class': 'harness_error',
                                               'text': '%s was not found on PATH' % spec['program']},
                      payload={'called_harness': args.harness, 'working_folder': work}, answer=None)
    try:
        done = launch(command_for(args.harness, brief, args.model), work, env)
    except OSError as exc:
        return finish(folder, base, 'failed', {'class': 'harness_error', 'text': str(exc)[:ledger.REASON_LIMIT]},
                      payload={'called_harness': args.harness, 'working_folder': work}, answer=None)

    envelope = envelope_of(done.stdout)
    payload = {'called_harness': args.harness, 'command': command, 'working_folder': work,
               'exit_code': done.returncode, 'stderr': (done.stderr or '')[-STDERR_KEPT:]}
    if envelope is not None:
        payload['envelope'] = dict((k, v) for k, v in envelope.items() if k not in ('response', 'result'))
    elif done.stdout:
        payload['stdout'] = done.stdout[-STDERR_KEPT:]
    reader = read_gemini if args.harness == 'gemini-cli' else read_cursor
    outcome, reason, answer = outcome_of(args.harness, done, envelope)
    fields = reader(envelope or {}, env.get(spec['variable']), work)
    return finish(folder, base, outcome, reason, payload=payload, answer=answer, **fields)


def finish(folder, base, outcome, reason, payload, answer, **fields):
    record = dict(base)
    record['agent_id'] = session_of_run(fields)
    record.update({'outcome': outcome, 'outcome_reason': reason, 'cost': NO_COST, 'effort': NO_EFFORT,
                   'spend_line': NO_SPEND, 'harness_payload': payload})
    for name in ('model', 'tokens', 'isolation'):
        record[name] = fields.get(name, 'unrecorded (the run did not reach the harness)')
    if fields.get('model_check'):
        record['model_check'] = fields['model_check']
    ledger.ret(ledger=folder, answer=answer, **record)
    if isinstance(answer, str):
        sys.stdout.write(answer if answer.endswith('\n') or not answer else answer + '\n')
    return 0 if outcome in ('served', 'empty') else 1


def session_of_run(fields):
    """The run's session id as its own record names it, or why there is none. Never `no agent`."""
    found = fields.get('agent_id')
    return found if isinstance(found, str) and found else NO_SESSION % NOT_REACHED


# ---------------------------------------------------------------------------
# Before the call
# ---------------------------------------------------------------------------

def calling_session(named=None):
    """The calling session's id and harness, or why they cannot be read."""
    if named:
        return named, 'unrecorded (the session was named on the command line, not by its harness)'
    found = [(variable, harness) for variable, harness in SESSION_VARIABLES if os.environ.get(variable)]
    if len(found) == 1:
        return os.environ[found[0][0]], found[0][1]
    if not found:
        why = 'unrecorded (none of %s is set)' % ', '.join(v for v, _ in SESSION_VARIABLES)
    else:
        why = 'unrecorded (more than one of %s is set)' % ', '.join(v for v, _ in found)
    return why, why


def harness_home(folder, harness):
    """The configuration folder config.json names for the harness, or None and why."""
    path = Path(folder) / ledger.CONFIG_FILE
    try:
        homes = json.loads(path.read_text(encoding='utf-8')).get('harness_homes') if path.is_file() else None
    except (OSError, ValueError, AttributeError) as exc:
        return None, '%s could not be read: %s' % (path, exc)
    home = homes.get(harness) if isinstance(homes, dict) else None
    if isinstance(home, str) and home:
        return os.path.expanduser(home), None
    return None, '%s names no harness_homes entry for %s' % (ledger.CONFIG_FILE, harness)


def auth_route(spec, home, why):
    """The configuration folder and the names (never the values) of the sign-in variables set."""
    named = [name for name in spec['auth'] if os.environ.get(name)]
    shown = 'environment: %s' % ', '.join(named) if named else 'no sign-in variable set'
    if home:
        return '%s=%s; %s' % (spec['variable'], home, shown)
    return 'unrecorded (%s; %s left unset; %s)' % (why, spec['variable'], shown)


def command_for(harness, brief, model):
    if harness == 'gemini-cli':
        argv = ['gemini', '-p', brief, '-o', 'json', '--skip-trust']
    else:
        argv = ['cursor-agent', '-p', '--output-format', 'json', '--trust']
    if model:
        argv += ['--model', model] if harness == 'cursor' else ['-m', model]
    if harness == 'cursor':
        argv.append(brief)
    return argv


def make_folder():
    """A fresh, empty working folder under $TMPDIR, by its real path."""
    return os.path.realpath(tempfile.mkdtemp(prefix='subagent-ledger-call-', dir=os.environ.get('TMPDIR')))


def launch(argv, folder, env):
    """Run the harness with its working directory set on the child process. No time limit."""
    return subprocess.run(argv, cwd=folder, env=env, capture_output=True, text=True,
                          stdin=subprocess.DEVNULL)


# ---------------------------------------------------------------------------
# After the call
# ---------------------------------------------------------------------------

def envelope_of(text):
    stripped = (text or '').strip()
    start = stripped.find('{')
    if start < 0:
        return None
    try:
        found = json.loads(stripped[start:])
    except ValueError:
        return None
    return found if isinstance(found, dict) else None


def outcome_of(harness, done, envelope):
    """outcome, outcome_reason and the answer, from the exit code, the envelope and standard error."""
    if harness == 'gemini-cli':
        answer = envelope.get('response') if envelope and isinstance(envelope.get('response'), str) else None
        error = envelope.get('error') if envelope else None
    else:
        answer = envelope.get('result') if envelope and isinstance(envelope.get('result'), str) else None
        error = envelope.get('result') if envelope and envelope.get('is_error') else None
    if done.returncode != 0 or error:
        texts = [t for t in (done.stderr, json.dumps(error) if error and not isinstance(error, str) else error,
                             done.stdout) if t]
        if not texts:
            texts = ['the harness exited %d and printed nothing' % done.returncode]
        return 'failed', ledger.reason_for(harness, *texts, fallback='harness_error'), answer
    if envelope is None:
        return 'failed', {'class': 'unreadable', 'text': ('the harness printed no JSON envelope: %s'
                                                          % (done.stdout or '')[:300])}, None
    if answer is None:
        return 'failed', {'class': 'unreadable', 'text': 'the envelope carries no answer'}, None
    if not answer.strip():
        return 'empty', {'class': 'empty_answer', 'text': 'the call was served and its answer was empty'}, answer
    return 'served', 'none (served)', answer


def counter(value):
    return value if isinstance(value, int) and not isinstance(value, bool) else None


def isolation_of(folder, uses, read_from, limit, work):
    found = transcripts.isolation({'cwd': folder, 'tool_uses': uses, 'path': read_from,
                                   'isolation_limit': limit})
    if isinstance(found, dict):
        found['script_folder'] = work
    return found


def read_gemini(envelope, home, work):
    """Counters from the printed stats; model and isolation from the chat under GEMINI_CLI_HOME."""
    out = {}
    models = (envelope.get('stats') or {}).get('models') if isinstance(envelope.get('stats'), dict) else None
    if isinstance(models, dict) and models:
        sums = {'input': 0, 'cached': 0, 'candidates': 0}
        for entry in models.values():
            tokens = entry.get('tokens') if isinstance(entry, dict) else None
            for key in sums:
                value = counter((tokens or {}).get(key))
                sums[key] += value or 0
        out['tokens'] = {'input': sums['input'], 'cache_write': 'unrecorded (Gemini CLI reports no cache-write counter)',
                         'cache_read': sums['cached'], 'output': sums['candidates']}
    else:
        out['tokens'] = 'unrecorded (the envelope carries no stats.models block)'
    printed = sorted(models) if isinstance(models, dict) else []
    session = envelope.get('session_id')
    if not isinstance(session, str) or not session:
        why = 'unrecorded (the envelope names no session, so the chat cannot be found)'
        out['model'] = ', '.join(printed) or why
        out['isolation'] = why
        out['agent_id'] = NO_SESSION % 'the envelope names no session, so the chat cannot be found'
        return out
    root = Path(home).expanduser() if home else Path.home()
    pattern = str(root / '.gemini' / 'tmp' / '*' / 'chats' / ('session-*-%s.jsonl' % glob.escape(session[:8])))
    chat = None
    for path in sorted(glob.glob(pattern)):
        rows = transcripts.rows_of(path)
        if rows and rows[0].get('sessionId') == session:
            chat, chat_rows = Path(path), rows
            break
    if chat is None:
        why = 'unrecorded (no chat for session %s at %s)' % (session, pattern)
        out['model'] = ', '.join(printed) or why
        out['isolation'] = why
        out['agent_id'] = NO_SESSION % ('no chat for session %s at %s' % (session, pattern))
        return out
    out['agent_id'] = chat_rows[0]['sessionId']
    names, uses, seen = [], [], set()
    for row in chat_rows:
        for message in [row] + list((row.get('$set') or {}).get('messages') or []):
            if not isinstance(message, dict):
                continue
            if message.get('type') == 'gemini' and isinstance(message.get('model'), str):
                if message['model'] not in names:
                    names.append(message['model'])
            for call in message.get('toolCalls') or []:
                if isinstance(call, dict) and call.get('id') not in seen:
                    seen.add(call.get('id'))
                    uses.append({'name': call.get('name'), 'input': call.get('args')})
    out['model'] = ', '.join(names) or ', '.join(printed) or 'unrecorded (neither the chat nor the envelope names a model)'
    if names and printed and sorted(names) != printed:
        out['model_check'] = {'harness': printed, 'transcript': names}
    try:
        folder = (chat.parent.parent / '.project_root').read_text(encoding='utf-8').strip()
    except OSError:
        folder = None
    out['isolation'] = (isolation_of(folder, uses, str(chat), LIMIT, work) if folder else
                        'unrecorded (no .project_root beside the chat at %s)' % chat.parent.parent)
    return out


def cursor_session(meta, error, store):
    """The session id the chat store's meta.json names, or why it names none. The store's `meta` table, which
    also holds its encryption key, is never read."""
    for key in CURSOR_SESSION_KEYS:
        if isinstance(meta.get(key), str) and meta[key]:
            return meta[key]
    if error:
        return NO_SESSION % error
    return NO_SESSION % ('%s carries none of %s' % (store / 'meta.json', ', '.join(CURSOR_SESSION_KEYS)))


def read_cursor(envelope, config, work):
    """Counters from the printed usage; model and isolation from the chat store under CURSOR_CONFIG_DIR."""
    out = {}
    usage = envelope.get('usage') if isinstance(envelope.get('usage'), dict) else None
    if usage is not None:
        names = (('input', 'inputTokens'), ('cache_write', 'cacheWriteTokens'),
                 ('cache_read', 'cacheReadTokens'), ('output', 'outputTokens'))
        out['tokens'] = dict((ours, counter(usage.get(theirs)) if counter(usage.get(theirs)) is not None
                              else 'unrecorded (the envelope\'s usage carries no %s)' % theirs)
                             for ours, theirs in names)
    else:
        out['tokens'] = 'unrecorded (the envelope carries no usage block)'
    session = envelope.get('session_id')
    if not isinstance(session, str) or not session:
        why = 'unrecorded (the envelope names no session, so the chat store cannot be found)'
        out['model'], out['isolation'] = why, why
        out['agent_id'] = NO_SESSION % 'the envelope names no session, so the chat store cannot be found'
        return out
    root = Path(config).expanduser() if config else Path.home() / '.cursor'
    pattern = str(root / 'chats' / '*' / glob.escape(session))
    found = sorted(glob.glob(pattern))
    if not found:
        why = 'unrecorded (no chat store for session %s at %s)' % (session, pattern)
        out['model'], out['isolation'] = why, why
        out['agent_id'] = NO_SESSION % ('no chat store for session %s at %s' % (session, pattern))
        return out
    store = Path(found[0])
    try:
        meta = json.loads((store / 'meta.json').read_text(encoding='utf-8'))
    except (OSError, ValueError) as exc:
        meta, meta_error = {}, '%s could not be read: %s' % (store / 'meta.json', exc)
    else:
        meta_error = None
    meta = meta if isinstance(meta, dict) else {}
    folder = meta.get('cwd')
    out['agent_id'] = cursor_session(meta, meta_error, store)
    names, uses = [], []
    try:
        db = sqlite3.connect('file:%s?mode=ro' % (store / 'store.db'), uri=True)
        try:
            blobs = db.execute('select data from blobs').fetchall()
        finally:
            db.close()
    except sqlite3.Error as exc:
        blobs, store_error = [], str(exc)
    else:
        store_error = None
    for (data,) in blobs:
        text = data.decode('utf-8', 'ignore') if isinstance(data, (bytes, bytearray)) else str(data or '')
        for name in MODEL_NAME.findall(text):
            if name not in names:
                names.append(name)
        start = text.find('{"')
        try:
            message = json.loads(text[start:]) if start >= 0 else None
        except ValueError:
            message = None
        if isinstance(message, dict) and isinstance(message.get('content'), list):
            for part in message['content']:
                if isinstance(part, dict) and part.get('type') == 'tool-call':
                    uses.append({'name': part.get('toolName'), 'input': part.get('args')})
    if names:
        out['model'] = ', '.join(names)
    elif store_error:
        out['model'] = 'unrecorded (the chat store could not be read: %s)' % store_error
    else:
        out['model'] = 'unrecorded (neither the envelope nor the chat store names a model)'
    out['isolation'] = (isolation_of(folder, uses, str(store), CURSOR_LIMIT, work) if folder else
                        'unrecorded (no cwd in %s)' % (store / 'meta.json'))
    return out


if __name__ == '__main__':
    sys.exit(main())
