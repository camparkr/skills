#!/usr/bin/env python3
"""The dispatch check: refuse an Agent or Task call that no triage reached.

    python3 dispatch_check.py              (the payload on standard input)

Run by the ledger skill's wrapper at PreToolUse on Agent and Task, as config.json's `checks.dispatch`, before the
capture in the same process, so it reads the pending files before the capture removes them. It is placed in settings
other sessions load only by the user.

It finds the brief as the capture does (the first readable file the prompt names) and reads its member and attempt at
the keys config.json's `frontmatter` map names, with the capture's own functions, so the rule has one home. Then:

  * a member's own dispatch (a payload carrying `agent_id`) is never refused: the check runs at the parent only;
  * a brief carrying a member is let through where the pending triage file for that member and attempt exists in
    the session's pending folder, whatever it holds: a file recording that the triage was attempted and failed lets
    the dispatch through, and the capture copies the failure onto the record;
  * a dispatch with no member brief is let through where the planner's own pending file, planner-<plan-request-id>.json,
    exists for a plan request the brief (or the prompt, where it names no file) names, standing alone;
  * anything else is refused, with the reason: no pending triage file for the member and attempt, or no member brief
    and no planner's file. A dispatch whose first file is not a brief is read as one no triage reached.

It reads the ledger folder from SUBAGENT_LEDGER_DIR (which the wrapper sets) and the session from the payload, or
SUBAGENT_LEDGER_SESSION. It prints one JSON object, {"refuse": true or false, "reason": "<text>"}, and exits 0. A
payload it cannot read exits 2, so the wrapper records `not_checkable (check error: ...)` and refuses nothing. It
writes and removes nothing.
"""

import json
import os
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

import decide  # noqa: E402

DISPATCH_TOOLS = ('Agent', 'Task')
TRIAGE_HINT = 'Run the triage skill for this part before dispatching it.'


def decide_dispatch(payload, folder, session):
    """(refuse, reason)."""
    import capture_claude_code as capture
    import pending
    if payload.get('tool_name') not in DISPATCH_TOOLS:
        return False, 'not an Agent or Task call: nothing to check'
    if payload.get('agent_id'):
        return False, 'a member\'s own dispatch: the check runs at the parent only'
    given = payload.get('tool_input') if isinstance(payload.get('tool_input'), dict) else {}
    prompt = given.get('prompt') if isinstance(given.get('prompt'), str) else ''
    brief, source = capture.brief_of(prompt, payload.get('cwd'))
    read, not_a_brief = capture.brief_read(folder, brief, source)
    directory = capture.pending_dir(folder, session)
    member, attempt = read['member'], read['attempt']
    if not str(member).startswith('unrecorded ('):
        name = pending.triage_file_name(member, attempt, capture._safe)
        path = Path(directory) / name
        if path.exists() or path.is_symlink():
            try:
                data = json.loads(path.read_text(encoding='utf-8'))
            except (OSError, ValueError) as exc:
                return False, 'the pending triage file %s exists, but could not be read (%s): the capture records ' \
                              'that' % (name, type(exc).__name__)
            failure = data.get('triage_failure') if isinstance(data, dict) else None
            if isinstance(failure, dict) and failure.get('value'):
                return False, 'the triage was attempted and failed (%s): the dispatch goes out, and the parent ' \
                              'chooses' % failure['value']
            return False, 'the pending triage file %s exists' % name
        return True, 'no pending triage file %s for member %s, attempt %s: no triage reached this dispatch. %s' % (
            name, member, attempt, TRIAGE_HINT)
    taken = pending.take_planner(directory, brief if source else prompt)
    if taken is not None:
        return False, 'the planner\'s own dispatch, plan request %s' % taken.request_id
    why = not_a_brief or (str(member)[len('unrecorded ('):-1] if str(member).startswith('unrecorded (') else member)
    return True, 'no triage reached this dispatch: %s, and the prompt names no planner\'s plan request. %s' % (
        why, TRIAGE_HINT)


def main(argv=None):
    try:
        payload = json.loads(sys.stdin.read())
        if not isinstance(payload, dict):
            raise ValueError('the payload is not a JSON object')
    except ValueError as exc:
        print('dispatch_check: the payload could not be read: %s' % exc, file=sys.stderr)
        return 2
    try:
        decide.ledger_scripts()
        import ledger
        folder = ledger.ledger_folder(None)
        session = payload.get('session_id') or os.environ.get('SUBAGENT_LEDGER_SESSION') or ''
        refuse, reason = decide_dispatch(payload, folder, session)
    except Exception as exc:  # an error is the wrapper's to record: it refuses nothing
        print('dispatch_check: %s: %s' % (type(exc).__name__, exc), file=sys.stderr)
        return 2
    print(json.dumps({'refuse': refuse, 'reason': reason}, ensure_ascii=False))
    return 0


if __name__ == '__main__':
    sys.exit(main())
