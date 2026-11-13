#!/usr/bin/env python3
"""Record the parent's decision on a failing return check result: the disposition that lifts the gate's stop.

    python3 disposition.py --call <call id> --result <id> [--result <id> ...] --kind <kind> --reason <text>
                           --decided-by <parent|user> [--path <path> ...] [--quote <text>]
                           [--session <id>] [--ledger <folder>]

The parent runs it in a Bash call whose command is this script's path and its arguments and nothing else, optionally
after `python3`: no separator, pipe, redirection, substitution or second line. That closed grammar is
parse_command(), which the gate uses to let this one call through while a `fail` stands. A command holding any of
`;`, `&`, `|`, `<`, `>`, a backtick, `$` or a line break is outside it, wherever the character sits, and so is a
flag not listed above.

The kinds: `accepted` (the output stands as it is); `repaired` (the parent changes it itself, and names each path it
will change with `--path`); `sent-back` (the parent resumes the member); `re-dispatched` (the parent dispatches the
member's next attempt); `discarded` (the output is dropped). `--decided-by` says who decided: `parent`, or `user`
where a standing rule asks for the user, with the user's words in `--quote`. Who decided is the parent's statement:
the record is evidence of the path taken, not a control against a parent that misstates it.

The script refuses, writing nothing, where: the ledger holds no check result for the call; a `--result` is not a
result of that call; `repaired` names no path; `user` gives no quote; or the call is a failed writer (its dispatch
record carries a baseline, and a result of it is `fail`) and the kind is `discarded` decided by `parent`, since a
failed writer's worktree is discarded only once its paths are settled with the user. An `accepted` or `repaired`
failed writer is recorded, and the script says its merge still needs the user's word in chat.

Otherwise it writes the pending file `<ledger>/.pending/<session>/disposition-<call id>.json` (`-2`, `-3` ... where one
already waits), under the capture's lock, and prints what it recorded. The capture turns the file into a disposition
record at this Bash call's PostToolUse and removes it; the gate reads only that record. The session is --session, or
$CLAUDE_CODE_SESSION_ID where the command names none (the printed command names it: command_for()); the ledger folder
is --ledger, or the ledger's own rule. Exit 0 written; 1 refused; 2 cannot run.
"""

import argparse
import json
import os
import shlex
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

import results  # noqa: E402

KINDS = {'accepted': 'accepted', 'repaired': 'repaired', 'sent-back': 'sent back', 'sent back': 'sent back',
         're-dispatched': 're-dispatched', 'discarded': 'discarded'}
DECIDERS = ('parent', 'user')
FORBIDDEN = (';', '&', '|', '<', '>', '`', '$', '\n', '\r')
PREFIX = 'disposition-'


class Refused(Exception):
    pass


class CannotRun(Exception):
    pass


class Parser(argparse.ArgumentParser):
    def error(self, message):
        raise Refused(message)


def parser():
    made = Parser(prog='disposition.py', add_help=False)
    made.add_argument('--call', required=True)
    made.add_argument('--result', action='append', required=True)
    made.add_argument('--kind', required=True)
    made.add_argument('--reason', required=True)
    made.add_argument('--decided-by', required=True)
    made.add_argument('--path', action='append', default=[])
    made.add_argument('--quote')
    made.add_argument('--session')
    made.add_argument('--ledger')
    return made


def parse_arguments(argv):
    args = parser().parse_args(argv)
    kind = KINDS.get(args.kind)
    if kind is None:
        raise Refused('--kind must be one of accepted, repaired, sent-back, re-dispatched or discarded, not %r'
                      % args.kind)
    args.kind = kind
    if args.decided_by not in DECIDERS:
        raise Refused('--decided-by must be parent or user, not %r' % args.decided_by)
    if not args.reason.strip():
        raise Refused('--reason is empty')
    if kind == 'repaired' and not args.path:
        raise Refused('a repaired disposition names each path the parent will change, with --path')
    if args.decided_by == 'user' and not (args.quote or '').strip():
        raise Refused("a disposition the user decided quotes the user's words, with --quote")
    return args


def parse_command(command, cwd=None, script=None):
    """(the parsed arguments, None) where `command` is this script's call in the closed grammar, else (None, why)."""
    script = os.path.realpath(str(script or Path(__file__).resolve()))
    if not isinstance(command, str) or not command.strip():
        return None, 'no command'
    held = [c for c in FORBIDDEN if c in command]
    if held:
        return None, 'the command holds %s' % ', '.join(repr(c) for c in held)
    try:
        words = shlex.split(command)
    except ValueError as exc:
        return None, 'the command cannot be read: %s' % exc
    if words and os.path.basename(words[0]).startswith('python') and len(words) > 1:
        words = words[1:]
    if not words:
        return None, 'no script named'
    named = os.path.realpath(os.path.join(cwd or os.getcwd(), os.path.expanduser(words[0])))
    if named != script:
        return None, 'the command runs %s, not the disposition script' % words[0]
    try:
        return parse_arguments(words[1:]), None
    except Refused as exc:
        return None, str(exc)


def literal_session(session):
    """`session` where the grammar holds it as one bare word, else None: no forbidden character, no quote or
    backslash, no whitespace, and no leading `-` that would read as a flag."""
    if not isinstance(session, str) or not session or session.startswith('-'):
        return None
    if any(c in FORBIDDEN or c in '"\'\\' or c.isspace() for c in session):
        return None
    return session


def command_for(call_id, ids, folder, session=None):
    """The command the gate's refusal and the parent's context print for recording a disposition on `call_id`'s
    results `ids`. It names the ledger folder the gate or the check read, by its absolute path in double quotes, so the
    parent's shell needs neither SUBAGENT_LEDGER_DIR nor a working folder inside the ledger's repository: the wrapper
    sets that variable only for its own checks, never for the parent. It names `session`, the id from the hook
    payload, as a literal `--session <id>`, so the parent's shell needs no CLAUDE_CODE_SESSION_ID. A session id the
    grammar cannot hold as one bare word, or none, is left out, and the script falls back to that variable."""
    named = literal_session(session)
    return ('python3 "%s" --call %s %s --kind <accepted|repaired|sent-back|re-dispatched|discarded> '
            '--reason "<why>" --decided-by <parent|user>%s --ledger "%s"'
            % (Path(__file__).resolve(), call_id, ' '.join('--result %s' % i for i in ids),
               ' --session %s' % named if named else '', os.path.abspath(str(folder))))


def ledger_side():
    """call_context, imported only where the ledger is written: parse_command() stays light for the gate."""
    import call_context
    return call_context


def pending_path(folder, session, call_id):
    cc = ledger_side()
    directory = cc.capture.pending_dir(str(folder), session)
    stem = cc.capture._safe(PREFIX + call_id)
    path = Path(directory) / ('%s.json' % stem)
    count = 2
    while path.exists():
        path = Path(directory) / ('%s-%d.json' % (stem, count))
        count += 1
    return path


def record(args, session, folder, cwd):
    """The pending file's content, after every refusal rule; raises Refused or CannotRun."""
    cc = ledger_side()
    records, problem = results.rows(folder, session)
    if problem:
        raise CannotRun(problem)
    found = results.results_of(records, args.call)
    if not found:
        raise Refused('the ledger holds no check result for call %s' % args.call)
    unknown = [i for i in args.result if i not in found]
    if unknown:
        raise Refused('not a result of call %s: %s' % (args.call, ', '.join(unknown)))
    failed_writer = results.is_writer(records, args.call) and any(
        r.get('result') == results.FAIL for r in found.values())
    if failed_writer and args.kind == 'discarded' and args.decided_by == 'parent':
        raise Refused("a failed writer's worktree is discarded only once its paths are settled with the user: "
                      "record --decided-by user with the user's words in --quote")
    agent, member, attempt = results.key_of(records, args.call)
    repository = None
    if args.path:
        out, problem = cc.git(cwd, 'rev-parse', '--show-toplevel')
        repository = out.strip() if out and not problem else 'unrecorded (git could not read %s: %s)' % (cwd, problem)
    data = {'call_id': args.call, 'agent_id': agent, 'member': member, 'attempt': attempt,
            'result_ids': list(dict.fromkeys(args.result)), 'kind': args.kind, 'reason': args.reason,
            'decided_by': args.decided_by, 'decided_at': cc.ledger.now()}
    if args.quote:
        data['quote'] = args.quote
    if args.path:
        data['paths'] = list(dict.fromkeys(args.path))
        data['repository'] = repository
    note = None
    if failed_writer and args.kind in ('accepted', 'repaired'):
        note = 'This writer failed a check: its merge still needs the user\'s word, asked for in chat.'
    return data, note


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    try:
        args = parse_arguments(argv)
    except Refused as exc:
        print('disposition: refused: %s' % exc, file=sys.stderr)
        return 1
    session = args.session or os.environ.get('CLAUDE_CODE_SESSION_ID')
    if not session:
        print('disposition: cannot run: no session id (give --session)', file=sys.stderr)
        return 2
    cc = ledger_side()
    folder = Path(cc.ledger.ledger_folder(args.ledger))
    try:
        data, note = record(args, session, folder, os.getcwd())
        with cc.capture.pending_lock(str(folder), session):
            path = pending_path(folder, session, args.call)
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps(data, ensure_ascii=False), encoding='utf-8')
    except Refused as exc:
        print('disposition: refused: %s' % exc, file=sys.stderr)
        return 1
    except (CannotRun, OSError) as exc:
        print('disposition: cannot run: %s' % exc, file=sys.stderr)
        return 2
    shown = {'pending': str(path), 'settles': data['result_ids'], 'call_id': args.call, 'kind': data['kind'],
             'decided_by': data['decided_by']}
    if note:
        shown['note'] = note
    print(json.dumps(shown, ensure_ascii=False))
    return 0


if __name__ == '__main__':
    sys.exit(main())
