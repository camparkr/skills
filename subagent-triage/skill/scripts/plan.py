#!/usr/bin/env python3
"""The plan file, a re-dispatch listed in it, and the planner's own pending file.

    python3 plan.py planner --ledger <folder> --session <id>
    python3 plan.py write --proposal <file> --out <plan file> [--plan-request <id>] [--history <folder> ...]
    python3 plan.py redispatch --plan <file> --member <id> --brief <path> --reason <text> [--persona <name>]

`planner` writes the planner's own pending file, <ledger>/.pending/<session>/planner-<plan-request-id>.json, before
the planner is dispatched, and prints the new plan-request id. The planner's brief names that id, standing alone; the
ledger's capture then records the dispatch as the planner's own and removes the file. Its name is its whole content
to the capture; it holds the id and the time it was written.

`write` writes the plan file from the proposal the parent approved, a JSON object with these keys and no others:
`task`, `members`, `parallel`, `synthesiser`, and optionally `plan_request`, `hops`, `changes` and `restore`. Each
member entry holds `member`, `part`, `act_kind`, `persona`, `brief`, `repository` and `write_set`, and optionally
`attempt` and `redispatch_reason`, and nothing else: the plan is an input to the calls, not their record, so it holds
no effort, decision value, override or check result. The plan file has the fields of references/plan-format.md:
`plan_request` (--plan-request, else the proposal's, else a new id), `task`, `written_at` from the clock, `pattern`
(the set of its parts' kinds, sorted), `members`, `parallel`, `synthesiser`, `hops` (each with `cited` null) and
`changes`. With no `hops`, each member's return to the parent is a hop, `synthesis` for a member that writes the
synthesis and `return` for the rest.

Refused, with exit 1 and nothing written: a key the format does not hold; a member id a pending file's name cannot keep;
attempts that are not 1, 2, ... for each member, or an attempt after the first with no reason; a kind not in the
ledger's kinds.json; a brief that is not an existing file by absolute path; a write set that is neither `none` nor a
list of relative paths, or whose repository is `none` (or a read-only member's that is not); a parallel order that
does not hold each member once; a synthesiser that is neither `parent` nor a member; a hop naming no member; a change
lacking its part, what was proposed, what was chosen or why; and an out path that already exists.

The next plan of a pattern: the most recent plan, by `closed_at`, found as a JSON file under the --history folders
(by default the out path's folder), that carries the same `pattern` and has been closed. Each hop that plan marked
`cited: false` is matched by its kind and the kinds of its two ends (`parent` for the parent); a hop of the new plan
that matches one is left out, and a change records it, unless the proposal's `restore` names it (`from`, `to`, `kind`)
with a reason, when it stays and a change records the restoring. A restore naming no hop that would be left out is
refused.

`redispatch` adds a re-dispatch to a plan not yet closed: a new entry under the member, with the next attempt, the
new brief, the reason and, where --persona is given, the persona; the rest copied from the member's last entry. It
never replaces an entry.

Output: one JSON object. Exit codes: 0 written; 1 refused; 2 cannot run (the ledger skill's scripts not found).
"""

import argparse
import json
import os
import re
import sys
import uuid
from pathlib import Path

HERE = Path(__file__).resolve().parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

import decide  # noqa: E402

PLANNER_PREFIX = 'planner-'
ID = re.compile(r'^[A-Za-z0-9][A-Za-z0-9._-]*$')
PLAN_KEYS = ('plan_request', 'task', 'members', 'parallel', 'synthesiser', 'hops', 'changes', 'restore')
MEMBER_KEYS = ('member', 'attempt', 'part', 'act_kind', 'persona', 'brief', 'repository', 'write_set',
               'redispatch_reason')
MEMBER_REQUIRED = ('member', 'part', 'act_kind', 'persona', 'brief', 'repository', 'write_set')
HOP_KINDS = ('return', 'synthesis')
CHANGE_KEYS = ('part', 'proposed', 'chosen', 'reason')
NONE = 'none'
PARENT = 'parent'


class Refused(Exception):
    pass


def stamp():
    return decide.stamp()


def text(value):
    return isinstance(value, str) and value.strip() != ''


def new_request_id():
    return 'plan-%s' % uuid.uuid4().hex[:12]


def write_json(path, data, exclusive=False):
    path = Path(path)
    body = json.dumps(data, indent=1, ensure_ascii=False) + '\n'
    if exclusive:
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(str(path), 'x', encoding='utf-8') as handle:
            handle.write(body)
        return
    writing = path.with_name(path.name + '.writing')
    writing.write_text(body, encoding='utf-8')
    os.replace(str(writing), str(path))


# ---------------------------------------------------------------------------
# The planner's own pending file
# ---------------------------------------------------------------------------

def planner(args):
    decide.ledger_scripts()
    import ledger
    request = new_request_id()
    folder = Path(ledger.ledger_folder(args.ledger)) / '.pending' / ledger.pending_name(args.session)
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / ('%s.json' % ledger.pending_name(PLANNER_PREFIX + request))
    write_json(path, {'plan_request': request, 'written_at': stamp()}, exclusive=True)
    return {'plan_request': request, 'pending_file': str(path),
            'name_in_brief': 'name %s, standing alone, in the planner\'s brief' % request}


# ---------------------------------------------------------------------------
# The plan file
# ---------------------------------------------------------------------------

def kinds():
    scripts = decide.ledger_scripts()
    return [entry['name'] for entry in decide.read_json(scripts / 'kinds.json')['kinds']]


def check_member(entry, known_kinds):
    if not isinstance(entry, dict):
        raise Refused('a member entry is not an object: %r' % (entry,))
    extra = sorted(set(entry) - set(MEMBER_KEYS))
    if extra:
        raise Refused('a member entry holds %s: the plan holds no value that belongs on a record' % ', '.join(extra))
    missing = [key for key in MEMBER_REQUIRED if key not in entry]
    if missing:
        raise Refused('member %s lacks %s' % (entry.get('member'), ', '.join(missing)))
    member = entry['member']
    if not isinstance(member, str) or not ID.match(member):
        raise Refused('the member id %r holds a character a pending file\'s name cannot keep' % (member,))
    for key in ('part', 'persona'):
        if not text(entry[key]):
            raise Refused('member %s has an empty %s' % (member, key))
    if entry['act_kind'] not in known_kinds:
        raise Refused('member %s: unknown kind %r; the kinds are %s' % (member, entry['act_kind'],
                                                                          ', '.join(known_kinds)))
    brief = entry['brief']
    if not isinstance(brief, str) or not os.path.isabs(brief) or not Path(brief).is_file():
        raise Refused('member %s: the brief %s is not an existing file by absolute path' % (member, brief))
    write_set, repository = entry['write_set'], entry['repository']
    if write_set == NONE:
        if repository != NONE:
            raise Refused('member %s writes nothing, so its repository is `none`, not %r' % (member, repository))
    elif isinstance(write_set, list) and write_set and all(text(p) and not os.path.isabs(p) for p in write_set):
        if not text(repository) or repository == NONE:
            raise Refused('member %s has a write set, so it names the repository the set lies in' % member)
    else:
        raise Refused('member %s: the write set is `none` or a list of paths relative to the repository: %r'
                      % (member, write_set))


def check_attempts(members):
    seen = {}
    for entry in members:
        attempt = entry.setdefault('attempt', 1)
        if isinstance(attempt, bool) or not isinstance(attempt, int):
            raise Refused('member %s: the attempt %r is not a whole number' % (entry['member'], attempt))
        expected = seen.get(entry['member'], 0) + 1
        if attempt != expected:
            raise Refused('member %s: attempt %d where %d comes next' % (entry['member'], attempt, expected))
        if attempt > 1 and not text(entry.get('redispatch_reason')):
            raise Refused('member %s: attempt %d gives no redispatch_reason' % (entry['member'], attempt))
        seen[entry['member']] = attempt
    return list(seen)


def check_order(proposal, ids):
    parallel = proposal.get('parallel')
    if not isinstance(parallel, list) or not all(isinstance(g, list) and g for g in parallel):
        raise Refused('the parallel order is a list of groups, each a list of member ids')
    listed = [member for group in parallel for member in group]
    unknown = sorted(set(listed) - set(ids))
    twice = sorted(set(m for m in listed if listed.count(m) > 1))
    absent = [member for member in ids if member not in listed]
    if unknown or twice or absent:
        raise Refused('the parallel order holds each member once: %s' % '; '.join(
            part for part in ('unknown %s' % ', '.join(unknown) if unknown else '',
                              'twice %s' % ', '.join(twice) if twice else '',
                              'missing %s' % ', '.join(absent) if absent else '') if part))
    synthesiser = proposal.get('synthesiser')
    if synthesiser != PARENT and synthesiser not in ids:
        raise Refused('the synthesiser is `parent` or a member id, not %r' % (synthesiser,))


def default_hops(ids, synthesiser):
    return [{'from': member, 'to': PARENT, 'kind': 'synthesis' if member == synthesiser else 'return', 'cited': None}
            for member in ids]


def check_hops(hops, ids):
    if not isinstance(hops, list):
        raise Refused('the hops are a list')
    out = []
    for hop in hops:
        if not isinstance(hop, dict) or set(hop) - {'from', 'to', 'kind', 'cited'}:
            raise Refused('a hop holds `from`, `to` and `kind` only: %r' % (hop,))
        if hop.get('from') not in ids or (hop.get('to') != PARENT and hop.get('to') not in ids) \
                or hop.get('kind') not in HOP_KINDS or hop.get('cited') is not None:
            raise Refused('a hop names a member, `parent` or a member, and a kind of %s, and is not yet cited: %r'
                          % (' or '.join(HOP_KINDS), hop))
        out.append({'from': hop['from'], 'to': hop['to'], 'kind': hop['kind'], 'cited': None})
    return out


def check_changes(changes):
    if not isinstance(changes, list):
        raise Refused('the changes are a list')
    for change in changes:
        if not isinstance(change, dict) or set(change) != set(CHANGE_KEYS) or not all(text(change[k])
                                                                                     for k in CHANGE_KEYS):
            raise Refused('a change holds its part, what was proposed, what was chosen and why, each as text: %r'
                          % (change,))
    return list(changes)


def is_plan(data):
    return isinstance(data, dict) and all(key in data for key in ('plan_request', 'pattern', 'members', 'hops'))


def last_closed(folders, pattern, out):
    """(the path and plan of the most recent closed plan with this pattern under `folders`, or (None, None))."""
    found = []
    for folder in folders:
        for path in sorted(Path(folder).rglob('*.json')):
            if path.resolve() == Path(out).resolve():
                continue
            try:
                data = json.loads(path.read_text(encoding='utf-8'))
            except (OSError, ValueError):
                continue
            if is_plan(data) and isinstance(data.get('closed_at'), str) and data.get('pattern') == pattern:
                found.append((data['closed_at'], str(path), data))
    if not found:
        return None, None
    found.sort(key=lambda item: (item[0], item[1]))
    return found[-1][1], found[-1][2]


def end_kind(plan_members, member):
    if member == PARENT:
        return PARENT
    for entry in plan_members:
        if entry.get('member') == member:
            return entry.get('act_kind')
    return None


def signature(members, hop):
    return (hop.get('kind'), end_kind(members, hop.get('from')), end_kind(members, hop.get('to')))


def leave_out(hops, members, history, restore):
    """(the hops kept, the hops left out, the changes made). Raises Refused for a restore naming no left-out hop."""
    path, previous = history
    restore = restore or []
    if not isinstance(restore, list) or not all(isinstance(r, dict) and set(r) == {'from', 'to', 'kind', 'reason'}
                                                and text(r['reason']) for r in restore):
        raise Refused('each restore names a hop by `from`, `to` and `kind`, with a `reason`')
    if previous is None:
        if restore:
            raise Refused('a restore names a hop, but no closed plan of this pattern left one out')
        return hops, [], []
    dropped = set(signature(previous['members'], hop) for hop in previous['hops'] if hop.get('cited') is False)
    kept, left, changes, used = [], [], [], []
    for hop in hops:
        if signature(members, hop) not in dropped:
            kept.append(hop)
            continue
        named = [r for r in restore if (r['from'], r['to'], r['kind']) == (hop['from'], hop['to'], hop['kind'])]
        shown = 'hop %s to %s (%s)' % (hop['from'], hop['to'], hop['kind'])
        because = 'marked not cited when plan %s closed at %s (%s)' % (previous['plan_request'], previous['closed_at'],
                                                                        path)
        if named:
            used.append(named[0])
            kept.append(hop)
            changes.append({'part': hop['from'], 'proposed': 'left out: %s' % because, 'chosen': 'restored',
                            'reason': named[0]['reason']})
        else:
            left.append({'from': hop['from'], 'to': hop['to'], 'kind': hop['kind']})
            changes.append({'part': hop['from'], 'proposed': shown, 'chosen': 'left out', 'reason': because})
    stray = [r for r in restore if r not in used]
    if stray:
        raise Refused('a restore names a hop that is not left out: %s' % ', '.join(
            '%s to %s (%s)' % (r['from'], r['to'], r['kind']) for r in stray))
    return kept, left, changes


def write(args):
    try:
        proposal = json.loads(Path(args.proposal).read_text(encoding='utf-8'))
    except (OSError, ValueError) as exc:
        raise Refused('the proposal could not be read: %s' % exc)
    if not isinstance(proposal, dict):
        raise Refused('the proposal is not a JSON object')
    extra = sorted(set(proposal) - set(PLAN_KEYS))
    if extra:
        raise Refused('the proposal holds %s: the plan holds no value that belongs on a record' % ', '.join(extra))
    out = Path(args.out)
    if out.exists() or out.is_symlink():
        raise Refused('the plan file %s already exists: write a re-dispatch with `redispatch`' % out)
    if not text(proposal.get('task')):
        raise Refused('the proposal names no task')
    members = proposal.get('members')
    if not isinstance(members, list) or not members:
        raise Refused('the proposal lists no member')
    known = kinds()
    for entry in members:
        check_member(entry, known)
    ids = check_attempts(members)
    check_order(proposal, ids)
    request = args.plan_request or proposal.get('plan_request') or new_request_id()
    if not isinstance(request, str) or not ID.match(request):
        raise Refused('the plan request id %r holds a character a pending file\'s name cannot keep' % (request,))
    hops = check_hops(proposal['hops'], ids) if 'hops' in proposal else default_hops(ids, proposal['synthesiser'])
    changes = check_changes(proposal.get('changes', []))
    pattern = sorted(set(entry['act_kind'] for entry in members))
    folders = args.history or [str(out.parent)]
    history = last_closed([f for f in folders if Path(f).is_dir()], pattern, out)
    hops, left, made = leave_out(hops, members, history, proposal.get('restore'))
    plan = {'plan_request': request, 'task': proposal['task'], 'written_at': stamp(), 'pattern': pattern,
            'members': [dict((key, entry[key]) for key in MEMBER_KEYS if key in entry) for entry in members],
            'parallel': proposal['parallel'], 'synthesiser': proposal['synthesiser'], 'hops': hops,
            'changes': changes + made}
    try:
        write_json(out, plan, exclusive=True)
    except FileExistsError:
        raise Refused('the plan file %s already exists' % out)
    return {'plan_file': str(out), 'plan_request': request, 'pattern': pattern, 'left_out': left,
            'history_plan': history[0]}


def redispatch(args):
    path = Path(args.plan)
    try:
        plan = json.loads(path.read_text(encoding='utf-8'))
    except (OSError, ValueError) as exc:
        raise Refused('the plan could not be read: %s' % exc)
    if not is_plan(plan):
        raise Refused('%s is not a plan file' % path)
    if plan.get('closed_at'):
        raise Refused('the plan was closed at %s: a closed plan takes no re-dispatch' % plan['closed_at'])
    if not text(args.reason):
        raise Refused('a re-dispatch gives its reason')
    entries = [entry for entry in plan['members'] if entry.get('member') == args.member]
    if not entries:
        raise Refused('the plan lists no member %s' % args.member)
    if not os.path.isabs(args.brief) or not Path(args.brief).is_file():
        raise Refused('the brief %s is not an existing file by absolute path' % args.brief)
    last = entries[-1]
    entry = dict((key, last[key]) for key in MEMBER_KEYS if key in last and key != 'redispatch_reason')
    entry.update(attempt=max(e.get('attempt', 1) for e in entries) + 1, brief=args.brief,
                 redispatch_reason=args.reason)
    if args.persona:
        entry['persona'] = args.persona
    plan['members'].append(entry)
    write_json(path, plan)
    return {'plan_file': str(path), 'entry': entry}


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    parser = argparse.ArgumentParser(description='The plan file and the planner\'s own pending file.')
    commands = parser.add_subparsers(dest='command')
    one = commands.add_parser('planner')
    one.add_argument('--ledger')
    one.add_argument('--session', required=True)
    two = commands.add_parser('write')
    two.add_argument('--proposal', required=True)
    two.add_argument('--out', required=True)
    two.add_argument('--plan-request')
    two.add_argument('--history', action='append')
    three = commands.add_parser('redispatch')
    for name in ('--plan', '--member', '--brief', '--reason'):
        three.add_argument(name, required=True)
    three.add_argument('--persona')
    try:
        args = parser.parse_args(argv)
    except SystemExit:
        return decide.fail(1, 'the arguments could not be read')
    if not args.command:
        return decide.fail(1, 'name a command: planner, write or redispatch')
    try:
        result = {'planner': planner, 'write': write, 'redispatch': redispatch}[args.command](args)
    except Refused as exc:
        return decide.fail(1, str(exc))
    except decide.CannotRun as exc:
        return decide.fail(2, str(exc))
    print(json.dumps(result, indent=1, ensure_ascii=False))
    return 0


if __name__ == '__main__':
    sys.exit(main())
