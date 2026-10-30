#!/usr/bin/env python3
"""Close a plan: mark each hop cited or not cited, and report what the team's records show.

    python3 close.py --plan <plan file> --session <id> [--ledger <folder>] [--transcript <parent transcript>]
                     [--parent <persona>]

The skill's last step, run once the team's work is done. It reads the plan file, the session's ledger file and the
parent's transcript (--transcript, or else the transcript path the plan's dispatch records carry), and writes only the
plan file: each hop's `cited` and, where cited, its `citation`, and `closed_at`. A plan already closed is refused.

The team's dispatches are the session's subagent dispatch records written at or after the plan's `written_at`. A
resumption (a record continuing an earlier call) is left out of every count. The rest are told apart: the planner's
own dispatch; a member's own dispatch (its caller is an agent, not the parent); a dispatch the dispatch check refused;
a dispatch matching a plan entry by member and attempt; and a parent's dispatch the plan does not list. A dispatch
whose persona is unrecorded is listed as one with no persona, beside its other place.

**Hops.** A hop is cited when the parent's first output after the hop's return names the hop's output path or its
call id, or carries a run of at least 20 consecutive words of the hop's returned text, word for word. Where the hop's
member ran in a parallel group, the output read is the first after the group's last return. An output is a reply
(an assistant text block), a file the parent writes (Write, Edit, MultiEdit or NotebookEdit, its path and new text),
or the prompt of its next dispatch (Agent or Task). Reading a file is not an output, so reading the hop's output
alone is no citation. The output paths are the lines of the returned text's output section, read by the return
skill's output_section.py; the returned text is the ledger's copy of the return's answer. A word is a run of letters,
digits and underscores, with any inner apostrophe; a path or call id is named where it stands alone, not inside a
longer name. The hop's member's return is that of its last attempt that returned; a hop with none is not cited. The
report gives each hop the output it was judged by, so a miss of the 20-word value can be seen.

**What it reports**, as one JSON object:

  * `hops`: each hop, cited or not, with its citation or the reason, and the output read;
  * `dispatches`: the plan's entries and how many were dispatched, the entries not dispatched, and the dispatches
    the plan does not list, the planner's, members' own, refused, those with no persona and the resumptions left out;
  * `below_line`: the count of parts dispatched below the persona decision's line, and each part with its
    probability, line and line version;
  * `overrides`: the persona decision's override rate over the dispatches it decided, overall, by adequacy band
    (tenths from 0.0 to 1.0) and by parent, and the effort decision's overall, each a count of a count, never a
    percentage. The parent is --parent, or else the parent persona the overrides name where they name one;
  * `pending_never_dispatched`: every pending triage file and planner's file still in the session's pending folder,
    whose dispatch never happened. None is removed;
  * `faults`: a dispatch the plan does not list; an override lacking any value it records (for the persona
    decision: the decision's persona, its adequacy probability, the parent's persona, the persona chosen, the reason
    and the time; for the effort decision: the decision's level, the level passed, the reason and the time); a
    passed effort (`effort_assigned`) other than the one to pass (the last effort override's level, else the effort
    decision's level, else, where it gave none, the unaided level); and an unaided level stamped after the decision
    records.

Exit codes: 0 closed with no fault; 3 closed, with faults reported; 1 refused (a plan unreadable or already closed, or
no transcript); 2 cannot run (the ledger or return skill not found).
"""

import argparse
import datetime
import json
import math
import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

import brief as briefs  # noqa: E402
import decide  # noqa: E402
import plan as plans  # noqa: E402

PLANNER_MARK = "unrecorded (the planner's own dispatch"
REFUSED_CLASS = 'refused_by_check'
WORD = re.compile(r"\w+(?:['’]\w+)*")
RUN = 20
FILE_TOOLS = {'Write': ('file_path', 'content'), 'Edit': ('file_path', 'new_string'),
              'MultiEdit': ('file_path', None), 'NotebookEdit': ('notebook_path', 'new_source')}
DISPATCH_TOOLS = ('Agent', 'Task')
PERSONA, EFFORT = 'd3-figure', 'd4-effort'
NEEDS = {PERSONA: ('decision_persona', 'adequacy_probability', 'parent_persona', 'persona_chosen', 'reason', 'at'),
         EFFORT: ('decision_level', 'level_passed', 'reason', 'at')}
NO_PARENT = 'unrecorded (no parent named)'
SHOWN = 300


class Refused(Exception):
    pass


def when(text):
    if not isinstance(text, str) or not text:
        return None
    try:
        return datetime.datetime.fromisoformat(text.replace('Z', '+00:00'))
    except ValueError:
        return None


def value_of(row, name):
    held = row.get(name)
    return held.get('value') if isinstance(held, dict) else None


def stamp_of(row, name):
    held = row.get(name)
    return held.get('stamped_at') if isinstance(held, dict) else None


def decision(row, question):
    found = [r for r in value_of(row, 'decision_records') or [] if isinstance(r, dict) and r.get('question') == question]
    return found[-1] if found else None


def overrides_of(row):
    return [o for o in value_of(row, 'overrides') or [] if isinstance(o, dict)]


def summary(row):
    return {'call_id': row.get('call_id'), 'member': row.get('member'), 'attempt': row.get('attempt'),
            'persona': row.get('persona-name'), 'dispatched_at': row.get('dispatched_at')}


def number(value):
    return isinstance(value, (int, float)) and not isinstance(value, bool)


# ---------------------------------------------------------------------------
# Reading the ledger and the transcript
# ---------------------------------------------------------------------------

def ledger_rows(folder, session):
    import ledger
    path = Path(ledger._session_file(folder, session))
    if not path.is_file():
        return []
    rows = []
    for line in ledger.read_text(path, errors='replace').splitlines():
        try:
            row = json.loads(line)
        except ValueError:
            continue
        if isinstance(row, dict):
            rows.append(row)
    return rows


def answer_text(folder, session, returned):
    """The return's answer, from the ledger's copy, or None."""
    import ledger
    fingerprint = returned.get('answer_fingerprint') if isinstance(returned, dict) else None
    sha = fingerprint.get('sha256') if isinstance(fingerprint, dict) else None
    if not isinstance(sha, str):
        return None
    path = Path(ledger._copy_dir(folder, session)) / ('%s.md' % sha[:16])
    try:
        return path.read_text(encoding='utf-8')
    except (OSError, UnicodeDecodeError):
        return None


def outputs(path):
    """The parent's outputs in order: [{at, kind, tool, text}] from its own assistant rows."""
    import transcripts
    out = []
    for row in transcripts.rows_of(path):
        if row.get('type') != 'assistant' or row.get('isSidechain'):
            continue
        moment = when(row.get('timestamp'))
        message = row.get('message') if isinstance(row.get('message'), dict) else {}
        content = message.get('content')
        for block in content if isinstance(content, list) else []:
            if not isinstance(block, dict):
                continue
            if block.get('type') == 'text' and isinstance(block.get('text'), str):
                out.append({'at': moment, 'kind': 'reply', 'tool': None, 'text': block['text']})
                continue
            if block.get('type') != 'tool_use':
                continue
            tool, given = block.get('name'), block.get('input') if isinstance(block.get('input'), dict) else {}
            if tool in FILE_TOOLS:
                path_key, text_key = FILE_TOOLS[tool]
                parts = [given.get(path_key), given.get(text_key) if text_key else None]
                parts += [edit.get('new_string') for edit in given.get('edits') or [] if isinstance(edit, dict)]
                out.append({'at': moment, 'kind': 'file', 'tool': tool,
                            'text': '\n'.join(p for p in parts if isinstance(p, str))})
            elif tool in DISPATCH_TOOLS:
                prompt = given.get('prompt')
                out.append({'at': moment, 'kind': 'dispatch prompt', 'tool': tool,
                            'text': prompt if isinstance(prompt, str) else ''})
    return out


# ---------------------------------------------------------------------------
# The citation rule
# ---------------------------------------------------------------------------

def names(text, needle):
    """Whether `needle` stands alone in `text`, not inside a longer name."""
    if not needle:
        return False
    return re.search(r'(?<![\w.-])%s(?![\w-]|\.\w)' % re.escape(needle), text) is not None


def quoted_run(answer, text):
    """The first run of RUN consecutive words of `answer` that `text` carries word for word, or None."""
    source = WORD.findall(answer or '')
    if len(source) < RUN:
        return None
    runs = set(tuple(source[i:i + RUN]) for i in range(len(source) - RUN + 1))
    words = WORD.findall(text or '')
    for i in range(len(words) - RUN + 1):
        if tuple(words[i:i + RUN]) in runs:
            return ' '.join(words[i:i + RUN])
    return None


def citation(output, call_id, answer, output_section):
    """The citation the output makes of the hop, or None."""
    claims = []
    if answer:
        section = output_section.parse(answer)
        claims = section.claims if section.state == output_section.CLAIMS else []
    for path in claims:
        if names(output['text'], path):
            return 'path %s' % path
    if isinstance(call_id, str) and names(output['text'], call_id):
        return 'call id %s' % call_id
    run = quoted_run(answer, output['text'])
    if run:
        return '%d words quoted: "%s"' % (RUN, run)
    return None


def shown(output):
    if output is None:
        return None
    text = output['text']
    return {'kind': output['kind'], 'tool': output['tool'], 'at': output['at'].isoformat() if output['at'] else None,
            'text': text if len(text) <= SHOWN else text[:SHOWN - 3] + '...'}


def mark_hops(plan, planned, returns, said, folder, session, output_section):
    """The hops' report; marks each hop in `plan`."""
    groups = [group for group in plan.get('parallel') or [] if isinstance(group, list)]

    def last_return(member):
        attempts = sorted((attempt for (m, attempt) in planned if m == member), reverse=True)
        for attempt in attempts:
            row = planned[(member, attempt)]
            if row.get('call_id') in returns:
                return row, returns[row['call_id']]
        return None, None

    report = []
    for hop in plan.get('hops') or []:
        member = hop.get('from')
        entry = {'from': member, 'to': hop.get('to'), 'kind': hop.get('kind'), 'cited': False, 'citation': None,
                 'output': None, 'reason': None}
        sent, returned = last_return(member)
        if returned is None:
            entry['reason'] = 'no return on the record for member %s' % member
        else:
            group = next((g for g in groups if member in g), [member])
            moments = [when(r.get('returned_at')) for r in (last_return(m)[1] for m in group) if r is not None]
            moments = [m for m in moments if m is not None]
            moment = max(moments) if moments else None
            output = next((o for o in said if o['at'] is not None and o['at'] > moment), None) \
                if moment is not None else None
            entry['output'] = shown(output)
            if moment is None:
                entry['reason'] = 'the return\'s time cannot be read'
            elif output is None:
                entry['reason'] = 'the parent wrote no output after the return'
            else:
                found = citation(output, sent.get('call_id'), answer_text(folder, session, returned), output_section)
                if found:
                    entry.update(cited=True, citation=found)
                else:
                    entry['reason'] = 'the parent\'s first output after the return names neither the output path ' \
                                      'nor the call id, and quotes no %d words of the returned text' % RUN
        hop['cited'] = entry['cited']
        if entry['cited']:
            hop['citation'] = entry['citation']
        else:
            hop.pop('citation', None)
        report.append(entry)
    return report


# ---------------------------------------------------------------------------
# The records' report
# ---------------------------------------------------------------------------

def sort_dispatches(plan, rows):
    start = when(plan.get('written_at'))
    returns = {}
    for row in rows:
        if row.get('record') == 'return' and isinstance(row.get('call_id'), str):
            returns[row['call_id']] = row
    entries = set((m.get('member'), m.get('attempt', 1)) for m in plan.get('members') or [])
    out = {'planned': {}, 'not_in_plan': [], 'planner': [], 'members_own': [], 'refused': [], 'no_persona': [],
           'resumptions_left_out': 0}
    parents = []
    for row in rows:
        if row.get('record') != 'dispatch' or row.get('route') != 'subagent':
            continue
        sent = when(row.get('dispatched_at'))
        if start is not None and (sent is None or sent < start):
            continue
        continues = row.get('continues_call_id')
        if isinstance(continues, str) and not continues.startswith('unrecorded ('):
            out['resumptions_left_out'] += 1
            continue
        caller = row.get('caller', 'parent')
        if caller != 'parent':
            out['members_own'].append(summary(row))
            continue
        if str(row.get('member', '')).startswith(PLANNER_MARK):
            out['planner'].append(summary(row))
            continue
        returned = returns.get(row.get('call_id'))
        reason = returned.get('outcome_reason') if isinstance(returned, dict) else None
        if isinstance(reason, dict) and reason.get('class') == REFUSED_CLASS:
            out['refused'].append(summary(row))
            continue
        if str(row.get('persona-name', '')).startswith('unrecorded ('):
            out['no_persona'].append(summary(row))
        key = (row.get('member'), row.get('attempt'))
        if key in entries:
            out['planned'][key] = row
        else:
            out['not_in_plan'].append(summary(row))
        parents.append(row)
    return out, returns, parents


def band_of(probability):
    return min(int(math.floor(probability * 10 + 1e-9)), 9)


def band_label(index):
    return '%.1f to %.1f' % (index / 10.0, (index + 1) / 10.0)


def rate(count, total):
    return '%d of %d' % (count, total)


def override_rates(parents, parent):
    bands = dict((band_label(i), [0, 0]) for i in range(10))
    decided, overridden, named = 0, 0, set()
    effort_decided, effort_overridden = 0, 0
    for row in parents:
        found = decision(row, PERSONA)
        basis = found.get('uncertainty_basis') if isinstance(found, dict) else None
        probability = basis.get('adequacy') if isinstance(basis, dict) else None
        persona_overrides = [o for o in overrides_of(row) if o.get('decision') == PERSONA]
        if number(probability):
            label = band_label(band_of(probability))
            decided += 1
            bands[label][1] += 1
            if persona_overrides:
                overridden += 1
                bands[label][0] += 1
        named.update(o.get('parent_persona') for o in persona_overrides if plans.text(o.get('parent_persona')))
        if decision(row, EFFORT) is not None:
            effort_decided += 1
            if any(o.get('decision') == EFFORT for o in overrides_of(row)):
                effort_overridden += 1
    who = parent or (sorted(named)[0] if len(named) == 1 else NO_PARENT)
    return {'persona': {'overall': rate(overridden, decided),
                        'by_band': dict((label, rate(*counts)) for label, counts in bands.items()),
                        'by_parent': {who: rate(overridden, decided)}},
            'effort': {'overall': rate(effort_overridden, effort_decided)}}


def override_faults(row):
    out = []
    for entry in overrides_of(row):
        needs = NEEDS.get(entry.get('decision'))
        if needs is None:
            out.append('an override names no decision this skill records: %r' % entry.get('decision'))
            continue
        missing = [key for key in needs if entry.get(key) in (None, '') or (isinstance(entry.get(key), str)
                                                                             and not entry[key].strip())]
        if entry.get('decision') == PERSONA and 'adequacy_probability' not in missing \
                and not number(entry.get('adequacy_probability')):
            missing.append('adequacy_probability')
        if missing:
            out.append('the %s override lacks %s' % (entry['decision'], ', '.join(missing)))
    return out


def effort_faults(row):
    unaided = value_of(row, 'effort_unaided')
    if unaided is None:
        return []
    out = []
    level = decision(row, EFFORT)
    level = level.get('answer') if isinstance(level, dict) else None
    passed = row.get('effort_assigned')
    chosen = [o for o in overrides_of(row) if o.get('decision') == EFFORT]
    if chosen:
        expected, why = chosen[-1].get('level_passed'), 'the effort override records %s' % chosen[-1].get(
            'level_passed')
    elif level in decide.LEVELS:
        expected, why = level, 'the effort decision\'s level is %s and no override is recorded' % level
    else:
        expected, why = unaided, 'the effort decision gave no level (%s), so the unaided level %s is the one to ' \
                                 'pass' % (level, unaided)
    if passed != expected:
        out.append('passed effort %s, but %s' % (passed, why))
    first, then = when(stamp_of(row, 'effort_unaided')), when(stamp_of(row, 'decision_records'))
    if first is not None and then is not None and first > then:
        out.append('the unaided level was stamped after the decision records (%s after %s)'
                   % (stamp_of(row, 'effort_unaided'), stamp_of(row, 'decision_records')))
    return out


def pending_left(folder, session):
    import capture_claude_code as capture
    directory = Path(capture.pending_dir(folder, session))
    if not directory.is_dir():
        return []
    return sorted(path.name for path in directory.glob('*.json')
                  if path.name.startswith(('triage-', plans.PLANNER_PREFIX)))


def transcript_of(rows):
    for row in rows:
        payload = row.get('harness_payload') if isinstance(row.get('harness_payload'), dict) else {}
        path = payload.get('transcript_path')
        if isinstance(path, str) and path:
            return path
    return None


def close(args):
    decide.ledger_scripts()
    briefs.return_scripts()
    import ledger
    import output_section
    path = Path(args.plan)
    try:
        plan = json.loads(path.read_text(encoding='utf-8'))
    except (OSError, ValueError) as exc:
        raise Refused('the plan could not be read: %s' % exc)
    if not plans.is_plan(plan):
        raise Refused('%s is not a plan file' % path)
    if plan.get('closed_at'):
        raise Refused('the plan was already closed at %s' % plan['closed_at'])
    folder = ledger.ledger_folder(args.ledger)
    rows = ledger_rows(folder, args.session)
    sorted_out, returns, parents = sort_dispatches(plan, rows)
    planned = sorted_out['planned']
    transcript = args.transcript or transcript_of(list(planned.values()) + parents)
    if not transcript:
        raise Refused('no transcript is named, and no dispatch record of the plan carries the parent\'s: name it with '
                      '--transcript')
    try:
        said = outputs(transcript)
    except OSError as exc:
        raise Refused('the parent\'s transcript could not be read: %s' % exc)
    hops = mark_hops(plan, planned, returns, said, folder, args.session, output_section)

    faults = [{'call_id': d['call_id'], 'fault': 'dispatched as member %s, attempt %s, which the plan does not list'
               % (d['member'], d['attempt'])} for d in sorted_out['not_in_plan']]
    below = []
    for row in parents:
        mark = value_of(row, 'below_line')
        if isinstance(mark, dict):
            below.append(dict(summary(row), probability=mark.get('probability'), line=mark.get('line'),
                              line_version=mark.get('line_version')))
        for fault in override_faults(row) + effort_faults(row):
            faults.append({'call_id': row.get('call_id'), 'fault': fault})
    entries = [(m.get('member'), m.get('attempt', 1)) for m in plan.get('members') or []]
    plan['closed_at'] = decide.stamp()
    plans.write_json(path, plan)
    return {'plan_file': str(path), 'plan_request': plan.get('plan_request'), 'closed_at': plan['closed_at'],
            'transcript': transcript, 'hops': hops,
            'dispatches': {'planned': len(entries), 'dispatched': sum(1 for e in entries if e in planned),
                           'planned_not_dispatched': [{'member': m, 'attempt': a} for m, a in entries
                                                      if (m, a) not in planned],
                           'not_in_plan': sorted_out['not_in_plan'], 'planner': sorted_out['planner'],
                           'members_own': sorted_out['members_own'], 'refused': sorted_out['refused'],
                           'no_persona': sorted_out['no_persona'],
                           'resumptions_left_out': sorted_out['resumptions_left_out']},
            'below_line': {'count': len(below), 'parts': below},
            'overrides': override_rates(parents, args.parent),
            'pending_never_dispatched': pending_left(folder, args.session),
            'faults': faults}


def main(argv=None):
    parser = argparse.ArgumentParser(description='Close a plan.')
    parser.add_argument('--plan', required=True)
    parser.add_argument('--session', required=True)
    parser.add_argument('--ledger')
    parser.add_argument('--transcript')
    parser.add_argument('--parent')
    try:
        args = parser.parse_args(sys.argv[1:] if argv is None else argv)
    except SystemExit:
        return decide.fail(1, 'the arguments could not be read')
    try:
        report = close(args)
    except Refused as exc:
        return decide.fail(1, str(exc))
    except decide.CannotRun as exc:
        return decide.fail(2, str(exc))
    print(json.dumps(report, indent=1, ensure_ascii=False))
    return 3 if report['faults'] else 0


if __name__ == '__main__':
    sys.exit(main())
