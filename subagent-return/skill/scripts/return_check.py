#!/usr/bin/env python3
"""The return check: runs the four checks on a member's report, and reads their results back for the parent.

    python3 return_check.py                    (a check the ledger's wrapper runs, payload on standard input)
    python3 return_check.py --context          (the wrapper's context step, payload on standard input)
    python3 return_check.py --merge-plan --call <call id> --worktree <folder> [--main <folder>]
                            [--session <id>] [--ledger <folder>]

As a check. The ledger's wrapper runs it at each hand-back's PreToolUse and at each SubagentStop (config.json `checks`,
`handback` and `stop`), with the payload on standard input and SUBAGENT_LEDGER_DIR, SUBAGENT_LEDGER_SESSION and
SUBAGENT_LEDGER_SCRIPTS in its environment. It reads the call once (call_context.py), runs check_authorship.py,
check_frontmatter.py, check_ledger.py and check_write_set.py, and prints one object:

    {"refuse": false, "reason": "", "key": {...}, "report": ..., "sha256": ..., "checks": [four results]}

It refuses nothing, ever: the results are recorded, and each `fail` carries a recommended repair. `key` holds the
agent id, the dispatch's call id, the member and the attempt. `report` names the text check 1 read, `hand-back
message` or `final message`, and `sha256` that text's SHA-256. Each result carries an id unique in its call: this
run's own random part, then the check's number. One fault is one `fail`: at a stop, a `fail` the latest hand-back run
of the same call, member and attempt found on the same check with the same finding keeps that run's id (stable_ids()),
so the gate counts it once and one disposition settles it on both lines. A fault found only at the stop, or one whose
finding changed, takes this run's id. A check that raises reads `not_checkable (check error: <reason>)`, and the
others still run. The wrapper keeps the object for the call's witness line and its return.

With --context, it prints {"refuse": false, "reason": "", "context": "<text>"}: the results the ledger holds for the
calls the payload names, for the wrapper to hand the parent as additionalContext. At an Agent or Task call's
PostToolUse (a foreground call, `completed`) that is the call's own results; at the parent's UserPromptSubmit, the
results of each agent the prompt names, such as a background member's hand-back notification. Each failing result is
given with its id and its recommended repair, and the command that records a disposition, naming with --ledger the
ledger folder this step read. Where the payload names no call with results, `context` is absent.

With --merge-plan, it reads the ledger and the member's worktree and prints which of its paths may come home without
asking: a writer's worktree is merged, path by path, only when its return records every check `pass` or
`not_applicable`; a `fail`, `not_checkable` or `unrecorded` result, or no return, means its merge is asked for in
chat. A path is merged only where the main checkout's state of it still equals the baseline's; where another session
has changed it since, that path is not merged and the parent asks. A merge is committed by path and never pushed. The
plan changes nothing: the merge and its commit are the parent's acts. Exit 0 with a plan; 1 refused on its input; 2
cannot run.
"""

import argparse
import json
import os
import re
import secrets
import sys
import traceback
from pathlib import Path

HERE = Path(__file__).resolve().parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

import call_context as cc  # noqa: E402
import check_authorship  # noqa: E402
import check_frontmatter  # noqa: E402
import check_ledger  # noqa: E402
import check_write_set  # noqa: E402
import disposition  # noqa: E402
import results  # noqa: E402

CHECKS = (check_authorship, check_frontmatter, check_ledger, check_write_set)
PASSED = (cc.PASS, cc.NOT_APPLICABLE)


def run_id(taken=()):
    """This run's own random part: one no id of the call already starts with."""
    while True:
        found = secrets.token_hex(4)
        if not any(i.startswith(found + '-') for i in taken):
            return found


def finding(item):
    """What a result found: everything it carries but its id."""
    return dict((k, v) for k, v in item.items() if k != 'id')


def handback_run(call, key):
    """The latest hand-back run on the ledger for this stop's call, member and attempt, or None.

    A hand-back's run sits on its witness line (`event` PreToolUse) before the stop's check runs, since the wrapper
    writes that line at the hand-back's PreToolUse. Runs are matched by the key results.Run reads, so a run with no
    call id named is matched by its agent, as the gate matches it. A run that could not finish carries no results and
    is passed over. Where the hand-back's witness line was never written, the stop's results take ids of their own."""
    if call.event != 'SubagentStop' or not call.records:
        return None
    mine = results.Run({'key': key}, {'record': 'witness', 'agent_id': call.agent_id})
    found = None
    for run in results.runs(call.records):
        if run.record.get('record') == 'witness' and run.record.get('event') == 'PreToolUse' and run.checks \
                and (run.call_id, run.member, run.attempt) == (mine.call_id, mine.member, mine.attempt):
            found = run
    return found


def stable_ids(call, key, found, run):
    """Give each of this run's results its id. A `fail` the stop finds that the latest hand-back run of the same call,
    member and attempt found as well, on the same check with the same finding, keeps the hand-back's id: one fault is
    one `fail`, and a disposition naming that id settles it on both lines. Any other result takes this run's id."""
    before = handback_run(call, key)
    earlier = dict((c.get('check'), c) for c in before.checks) if before is not None else {}
    for item in found:
        prior = earlier.get(item['check'])
        if item.get('result') == cc.FAIL and prior is not None and prior.get('result') == cc.FAIL \
                and isinstance(prior.get('id'), str) and finding(prior) == finding(item):
            item['id'] = prior['id']
        else:
            item['id'] = '%s-%d' % (run, item['check'])


def check(payload, folder):
    """The object the check prints for one hook payload."""
    run = run_id()
    out = {'refuse': False, 'reason': ''}
    try:
        call = cc.Call.read(payload, folder)
    except Exception as exc:  # the reading itself failed: every check says so
        why = 'check error: %s: %s' % (type(exc).__name__, cc.one_line(exc))
        found = [cc.result(module.CHECK, module.NAME, cc.NOT_CHECKABLE, reason=why) for module in CHECKS]
        for item in found:
            item['id'] = '%s-%d' % (run, item['check'])
        out.update(key={'agent_id': payload.get('agent_id')}, checks=found)
        return out
    found = []
    for module in CHECKS:
        try:
            item = module.run(call)
        except Exception as exc:
            item = cc.result(module.CHECK, module.NAME, cc.NOT_CHECKABLE, reason='check error: %s: %s' % (
                type(exc).__name__, cc.one_line(exc)))
        found.append(item)
    key = call.key()
    mine = results.Run({'key': key}, {'record': 'witness', 'agent_id': call.agent_id})
    run = run_id(results.results_of(call.records or [], mine.call_id))
    stable_ids(call, key, found, run)
    out.update(key=key, report=call.report_name, sha256=call.report_digest(), checks=found)
    if not call.report_applies:
        out['report_reached_parent'] = False
    return out


# ---------------------------------------------------------------------------------------------------------------
# The context handed to the parent
# ---------------------------------------------------------------------------------------------------------------

def disposition_command(call_id, ids, folder, session=None):
    """The disposition command for `call_id`'s standing fails, naming the ledger folder this step read and the
    session from the hook payload."""
    return disposition.command_for(call_id, ids, folder, session)


def summary(records, call_id, folder, session=None):
    """Lines describing one call's results: the latest run's four results, then every fail with its repair."""
    found = [run for run in results.runs(records) if run.call_id == call_id]
    if not found:
        return []
    latest = found[-1]
    lines = ['Return check, member %s attempt %s (agent %s, call %s), %s:' % (
        latest.member, latest.attempt, latest.agent_id, call_id, latest.data.get('report') or 'no report named')]
    if latest.checks:
        lines.append('  ' + '; '.join('check %s %s' % (c.get('check'), results.shown(c)) for c in latest.checks))
    else:
        lines.append('  the check could not run: %s' % latest.data.get('result'))
    done = results.settled(records)
    open_ids = []
    for item in results.fails(records):
        if item.call_id != call_id:
            continue
        state = 'settled' if (item.call_id, item.id) in done else 'stands'
        lines.append('  FAIL %s (check %s, %s): %s. Recommended repair: %s' % (
            item.id, item.result.get('check'), state, results.shown(item.result), item.result.get('repair')))
        if state == 'stands':
            open_ids.append(item.id)
    if open_ids:
        lines.append('  A fail stops your tool calls, save reads and questions, until you record a decision: %s'
                     % disposition_command(call_id, open_ids, folder, session))
    return lines


def context(payload, folder):
    out = {'refuse': False, 'reason': ''}
    if payload.get('agent_id'):
        return out
    session = payload.get('session_id')
    records, problem = results.rows(folder, session) if session else (None, 'no session')
    if problem or not records:
        return out
    known = results.call_ids(records)
    calls = []
    event = payload.get('hook_event_name')
    if event == 'PostToolUse':
        response = payload.get('tool_response') if isinstance(payload.get('tool_response'), dict) else {}
        if response.get('status') == 'completed' and payload.get('tool_use_id') in known:
            calls.append(payload['tool_use_id'])
        agent = response.get('agentId')
        if not calls and isinstance(agent, str) and agent:
            calls += [c for c in known if c == 'agent:%s' % agent]
    elif event == 'UserPromptSubmit':
        prompt = payload.get('prompt') if isinstance(payload.get('prompt'), str) else ''
        for run in results.runs(records):
            if run.agent_id and re.search(r'(?<![A-Za-z0-9])%s(?![A-Za-z0-9])' % re.escape(run.agent_id), prompt) \
                    and run.call_id not in calls:
                calls.append(run.call_id)
    lines = []
    for call_id in calls:
        lines += summary(records, call_id, folder, session)
    if lines:
        out['context'] = '\n'.join(lines)
    return out


# ---------------------------------------------------------------------------------------------------------------
# The merge plan
# ---------------------------------------------------------------------------------------------------------------

def blob(root, commit, path):
    """The git object id of `path` at `commit`, or None where it did not exist there."""
    out, problem = cc.git(root, 'rev-parse', '--verify', '--quiet', '%s:%s' % (commit, path))
    return out.strip() if out and not problem else None


def file_blob(root, path):
    full = Path(root) / path
    if not full.is_file():
        return None
    out, problem = cc.git(root, 'hash-object', '--', str(full))
    return out.strip() if out and not problem else None


def merge_plan(folder, session, call_id, worktree, main):
    records, problem = results.rows(folder, session)
    if problem:
        raise CannotRun(problem)
    plan = {'call_id': call_id, 'merge': [], 'ask': [], 'ask_all': None, 'commit': 'by path, without asking',
            'push': 'never under this plan: a push needs the user\'s word'}
    back = [r for r in records if r.get('record') == 'return' and r.get('call_id') == call_id]
    sent = results.dispatch_of(records, call_id)
    if sent is None:
        raise Refused('the ledger holds no dispatch record for call %s' % call_id)
    baseline = sent.get('baseline')
    if not (isinstance(baseline, dict) and isinstance(baseline.get('commit'), str)):
        raise Refused('call %s is no writer: its dispatch record carries no baseline' % call_id)
    commit = baseline['commit']
    if not back:
        plan['ask_all'] = 'no return record for the call: its results are not all on the record'
    else:
        entries = back[-1].get('check_results')
        entries = entries if isinstance(entries, list) else []
        if not entries:
            plan['ask_all'] = 'its return carries no check result'
        for entry in entries:
            if isinstance(entry, str):
                plan['ask_all'] = 'its return carries %s' % entry
                break
            checks = entry.get('checks') if isinstance(entry.get('checks'), list) else None
            if checks is None:
                plan['ask_all'] = 'its return carries a check run that could not finish: %s' % entry.get('result')
                break
            bad = [c for c in checks if c.get('result') not in PASSED]
            if bad:
                plan['ask_all'] = 'its return records %s' % '; '.join(
                    'check %s %s' % (c.get('check'), results.shown(c)) for c in bad)
                break
    tracked, problem = cc.git(worktree, 'diff', '--name-only', '--no-renames', '-z', commit)
    if problem is None:
        untracked, problem = cc.git(worktree, 'ls-files', '--others', '--exclude-standard', '-z')
    if problem:
        raise CannotRun('the worktree could not be read against its baseline: %s' % problem)
    paths = sorted(set(name for name in (tracked + untracked).split('\0') if name))
    if plan['ask_all']:
        plan['ask'] = [{'path': path, 'why': plan['ask_all']} for path in paths]
        return plan
    for path in paths:
        if blob(main, commit, path) == file_blob(main, path):
            plan['merge'].append(path)
        else:
            plan['ask'].append({'path': path, 'why': 'the main checkout changed it after the baseline %s'
                                % commit[:12]})
    return plan


class Refused(Exception):
    pass


class CannotRun(Exception):
    pass


def merge_main(argv):
    parser = argparse.ArgumentParser(prog='return_check.py --merge-plan')
    parser.add_argument('--call', required=True)
    parser.add_argument('--worktree', required=True)
    parser.add_argument('--main')
    parser.add_argument('--session')
    parser.add_argument('--ledger')
    try:
        args = parser.parse_args(argv)
    except SystemExit as exc:
        return 1 if exc.code else 0
    session = args.session or os.environ.get('CLAUDE_CODE_SESSION_ID') or os.environ.get('SUBAGENT_LEDGER_SESSION')
    if not session:
        print('return_check: cannot run: no session id (give --session)', file=sys.stderr)
        return 2
    folder = cc.ledger.ledger_folder(args.ledger)
    main_root = args.main
    if not main_root:
        out, problem = cc.git(os.getcwd(), 'rev-parse', '--show-toplevel')
        if problem:
            print('return_check: cannot run: %s' % problem, file=sys.stderr)
            return 2
        main_root = out.strip()
    try:
        plan = merge_plan(folder, session, args.call, args.worktree, main_root)
    except Refused as exc:
        print('return_check: refused: %s' % exc, file=sys.stderr)
        return 1
    except CannotRun as exc:
        print('return_check: cannot run: %s' % exc, file=sys.stderr)
        return 2
    print(json.dumps(plan, ensure_ascii=False, indent=2))
    return 0


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    if argv[:1] == ['--merge-plan']:
        return merge_main(argv[1:])
    try:
        payload = json.loads(sys.stdin.read())
        payload = payload if isinstance(payload, dict) else {}
    except ValueError:
        payload = {}
    folder = os.environ.get('SUBAGENT_LEDGER_DIR') or cc.ledger.ledger_folder()
    try:
        out = context(payload, folder) if argv[:1] == ['--context'] else check(payload, folder)
    except Exception:
        print(traceback.format_exc(), file=sys.stderr)
        return 3
    print(json.dumps(out, ensure_ascii=False))
    return 0


if __name__ == '__main__':
    sys.exit(main())
