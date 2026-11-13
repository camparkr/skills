#!/usr/bin/env python3
"""Check 3: the member's call is on the ledger.

The check keys the call by agent id, member and attempt. A dispatch record carrying this member and attempt passes; a
call whose brief carries no member is keyed by the dispatch's call id, from the agent's meta file. With the capture
writing (the session's ledger file holds a session-start witness line) and no such record, the result is `fail`,
save where the parent's transcript shows the dispatch's own PreToolUse hook was cancelled before it could write: a
wrapper killed by the harness's time limit leaves no record and no error line, and the member is not at fault, so the
result is `not_checkable (the dispatch's hook was cancelled before it wrote its record: ...)`. With no session-start
witness line the result is `ledger_absent`. A ledger file that cannot be read, or a call that cannot be keyed at all,
is `not_checkable` with the reason.
"""

import json

import call_context as cc

CHECK, NAME = 3, 'ledger'
DISPATCH_TOOLS = ('Agent', 'Task')


def cancelled_dispatch(call):
    """The harness's note of a cancelled PreToolUse hook on this call's dispatch, from the parent's transcript, or
    None. Without the dispatch's call id, any cancelled dispatch hook whose call has no dispatch record counts."""
    path = call.payload.get('transcript_path')
    if not isinstance(path, str) or not path:
        return None
    recorded = set(row.get('call_id') for row in call.records or [] if row.get('record') == 'dispatch')
    try:
        handle = open(path, encoding='utf-8', errors='replace')
    except OSError:
        return None
    with handle:
        for line in handle:
            if 'hook_cancelled' not in line:
                continue
            try:
                row = json.loads(line)
            except ValueError:
                continue
            note = row.get('attachment') if isinstance(row, dict) else None
            if not isinstance(note, dict) or note.get('type') != 'hook_cancelled':
                continue
            if note.get('hookEvent') != 'PreToolUse':
                continue
            name = note.get('hookName') or ''
            if not any(name == 'PreToolUse:%s' % tool for tool in DISPATCH_TOOLS):
                continue
            called = note.get('toolUseID')
            if call.dispatch_call_id and called != call.dispatch_call_id:
                continue
            if not call.dispatch_call_id and called in recorded:
                continue
            how = 'timed out after %s ms' % note.get('durationMs') if note.get('timedOut') else 'cancelled'
            return '%s, %s' % (name, how)
    return None


def run(call):
    if call.records_problem:
        return cc.result(CHECK, NAME, cc.NOT_CHECKABLE, reason=call.records_problem)
    if not call.session_started:
        return cc.result(CHECK, NAME, cc.LEDGER_ABSENT)
    if not call.member_brief and not call.dispatch_call_id:
        return cc.result(CHECK, NAME, cc.NOT_CHECKABLE, reason='the call cannot be keyed: no member brief, and no '
                         "dispatch call id in the agent's meta file")
    if call.dispatch is not None:
        return cc.result(CHECK, NAME, cc.PASS)
    cancelled = cancelled_dispatch(call)
    if cancelled:
        return cc.result(CHECK, NAME, cc.NOT_CHECKABLE, reason="the dispatch's hook was cancelled before it wrote its "
                         "record: %s" % cancelled)
    named = ('member %s attempt %s' % (call.member, call.attempt) if call.member_brief
             else 'call %s' % call.dispatch_call_id)
    return cc.result(CHECK, NAME, cc.FAIL, reason='no dispatch record carries %s' % named,
                     repair='The ledger missed the dispatch of %s. Report it to the user. Do not send the member back '
                     'to repair the record: the record is the capture\'s, not the member\'s.' % named)
