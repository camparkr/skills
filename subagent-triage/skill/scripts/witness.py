#!/usr/bin/env python3
"""Check the ledger is writing for this session before a team's first dispatch.

    python3 witness.py [--ledger <folder>] [--session <id>]

The ledger skill's capture writes a witness line at the session's start: a `witness` record whose `event` is
`SessionStart`. This script reads this session's own ledger file, <ledger>/<session>.jsonl, for that line, and for
one naming this session. A line found only in another session's file, or one in this session's file that names
another session, does not count: the skill stops.

The session id is --session, or else CLAUDE_CODE_SESSION_ID where the harness sets it; the output says which. The
ledger folder is --ledger, or else the ledger skill's own default (SUBAGENT_LEDGER_DIR, then <git top>/.subagent-ledger).

Output: one JSON object, {"session", "session_from", "ledger_file", "witness", "stop", "reason"}. `witness` is the line
found, or null. Exit codes: 0 the line is found; 1 stop, with the reason (no session id, no ledger file, no line, or
another session's); 2 cannot run (the ledger skill's scripts not found). It writes nothing.
"""

import argparse
import json
import os
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

import decide  # noqa: E402

SESSION_VARIABLE = 'CLAUDE_CODE_SESSION_ID'
SESSION_START = 'SessionStart'
STOP_TAIL = 'The ledger is not recording this session: send no member.'


def witness_lines(path):
    """The session-start witness lines in the ledger file at `path`, in order."""
    import ledger
    out = []
    for line in ledger.read_text(path, errors='replace').splitlines():
        try:
            row = json.loads(line)
        except ValueError:
            continue
        if isinstance(row, dict) and row.get('record') == 'witness' and row.get('event') == SESSION_START:
            out.append(row)
    return out


def check(folder, session):
    """(stop, reason, the line found or None, the ledger file's path or None)."""
    import ledger
    if not session:
        return True, 'no session id: pass --session, or run where %s is set. %s' % (SESSION_VARIABLE, STOP_TAIL), \
            None, None
    path = Path(ledger._session_file(folder, session))
    if not path.is_file():
        return True, 'the ledger file %s does not exist: the capture has written nothing for this session. %s' % (
            path, STOP_TAIL), None, path
    lines = witness_lines(path)
    own = [row for row in lines if row.get('session') == session]
    if own:
        return False, 'the session-start witness line is in %s' % path, own[0], path
    others = sorted(set(str(row.get('session')) for row in lines))
    if others:
        return True, 'the session-start witness line in %s is another session\'s (%s), not this one\'s. %s' % (
            path, ', '.join(others), STOP_TAIL), None, path
    return True, 'no session-start witness line in %s. %s' % (path, STOP_TAIL), None, path


def main(argv=None):
    parser = argparse.ArgumentParser(description='Check the ledger is writing for this session.')
    parser.add_argument('--ledger')
    parser.add_argument('--session')
    try:
        args = parser.parse_args(sys.argv[1:] if argv is None else argv)
    except SystemExit:
        return decide.fail(2, 'the arguments could not be read')
    try:
        decide.ledger_scripts()
        import ledger
    except decide.CannotRun as exc:
        return decide.fail(2, str(exc))
    session, source = args.session, '--session'
    if not session and os.environ.get(SESSION_VARIABLE):
        session, source = os.environ[SESSION_VARIABLE], SESSION_VARIABLE
    if not session:
        source = None
    folder = ledger.ledger_folder(args.ledger)
    stop, reason, found, path = check(folder, session)
    print(json.dumps({'session': session, 'session_from': source, 'ledger_file': str(path) if path else None,
                      'witness': found, 'stop': stop, 'reason': reason}, indent=1, ensure_ascii=False))
    return 1 if stop else 0


if __name__ == '__main__':
    sys.exit(main())
