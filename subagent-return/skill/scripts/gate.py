#!/usr/bin/env python3
"""The gate: while a failing return check result stands with no disposition, the parent's tool calls are refused.

    python3 gate.py      (a check the ledger's wrapper runs at the parent's PreToolUse, payload on standard input)

The ledger's wrapper runs it at every PreToolUse of the parent (config.json `checks`, `gate`), with SUBAGENT_LEDGER_DIR
in its environment. It decides only at the parent, a payload with no `agent_id`: a member's tool call is never
refused, so a member can always hand back. It reads the session's ledger file, never a pending file (results.py).

While a `fail` of the session stands that no disposition record settles, a member's own dispatch included, it refuses
each of the parent's tool calls, printing {"refuse": true, "reason": ...}. The reason names the refused call, each
failing result with its call, member, attempt, check and id, the recommended repair it carries, and the command that
records a disposition, naming with --ledger the ledger folder the gate read (disposition.command_for()). It lets
through only:

  * Read, Grep and Glob, so the parent can inspect the output;
  * TaskStop;
  * AskUserQuestion, so the parent can ask the user; and
  * the Bash call that runs the disposition script in its closed grammar (disposition.parse_command()).

A Bash call that names the disposition script (its file name, disposition.py) but breaks that grammar is refused with
the grammar's fault first, the reason disposition.parse_command() gives, then the ordinary refusal. Any other refused
call gets the ordinary refusal alone.

Otherwise it prints {"refuse": false, "reason": ""}. A result that is `not_checkable`, `unrecorded` or `ledger_absent`
stops nothing. The gate is a check like any other the wrapper runs: where it raises, exits non-zero or overruns the
wrapper's bound, the wrapper refuses nothing and records the gate's result as `not_checkable`.
"""

import json
import os
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

import disposition  # noqa: E402
import results  # noqa: E402

LET_THROUGH = ('Read', 'Grep', 'Glob', 'TaskStop', 'AskUserQuestion')
SHELL = 'Bash'
SCRIPT_NAME = 'disposition.py'


def names_the_script(command):
    """Whether a Bash command is an attempt at the disposition script: it names the script's file name."""
    return isinstance(command, str) and SCRIPT_NAME in command


def reason(tool, call, standing, folder, fault=None):
    lines = []
    if fault:
        lines.append('This Bash call runs the disposition script outside its grammar, so it is refused: %s. '
                     'Run the printed command below with only its placeholders filled.' % fault)
    lines += ['The return check holds this %s call%s: %d failing result%s stand%s with no disposition.' % (
        tool, ' (%s)' % call if call else '', len(standing), '' if len(standing) == 1 else 's',
        's' if len(standing) == 1 else '')]
    by_call = {}
    for item in standing:
        by_call.setdefault(item.call_id, []).append(item)
    for call_id, items in by_call.items():
        first = items[0]
        lines.append('Call %s, member %s attempt %s (agent %s):' % (call_id, first.member, first.attempt,
                                                                     first.agent_id))
        for item in items:
            lines.append('  %s, check %s: %s. Recommended repair: %s' % (
                item.id, item.result.get('check'), results.shown(item.result), item.result.get('repair')))
        lines.append('  To record your decision: %s' % disposition.command_for(
            call_id, [item.id for item in items], folder))
    lines.append('Read, Grep, Glob, TaskStop and AskUserQuestion still run.')
    return '\n'.join(lines)


def decide(payload, folder):
    if payload.get('agent_id'):
        return {'refuse': False, 'reason': ''}
    session = payload.get('session_id')
    if not isinstance(session, str) or not session:
        raise ValueError('session_id absent from the payload')
    records, problem = results.rows(folder, session)
    if problem:
        raise OSError(problem)
    standing = results.standing(records)
    if not standing:
        return {'refuse': False, 'reason': ''}
    tool = payload.get('tool_name')
    if tool in LET_THROUGH:
        return {'refuse': False, 'reason': '', 'standing': len(standing)}
    fault = None
    if tool == SHELL:
        given = payload.get('tool_input') if isinstance(payload.get('tool_input'), dict) else {}
        parsed, why = disposition.parse_command(given.get('command'), payload.get('cwd'))
        if parsed is not None:
            return {'refuse': False, 'reason': '', 'standing': len(standing)}
        if names_the_script(given.get('command')):
            fault = why
    return {'refuse': True, 'reason': reason(tool, payload.get('tool_use_id'), standing, folder, fault),
            'standing': len(standing)}


def main(argv=None):
    payload = json.loads(sys.stdin.read())
    if not isinstance(payload, dict):
        raise ValueError('the payload is not a JSON object')
    folder = os.environ.get('SUBAGENT_LEDGER_DIR')
    if not folder:
        import call_context
        folder = call_context.ledger.ledger_folder()
    print(json.dumps(decide(payload, folder), ensure_ascii=False))
    return 0


if __name__ == '__main__':
    sys.exit(main())
