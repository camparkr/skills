#!/usr/bin/env python3
"""Ask Jev the act, form, persona, harness, model and effort decisions for one part of a delegation, and write its
pending triage file.

    python3 decide.py --delegation <file> --roster <file> --ledger <folder> --session <id> --member <id>
                      --effort-unaided <level> [--attempt 1] [--pending-ledger <folder>] [--key-from-zsh]
                      [--rows-key rows] [--name-key name] [--group-key group] [--file-key file]
                      [--goal-key declaration.goal] [--does-key declaration.does] [--ratified-key declaration-ratified]
                      [--file-root <folder>] [--user <name> ...]
                      [--task <id>] [--build-root <folder> ...] [--ratified-root <folder> ...]
                      [--task-key task_id] [--status-key status]
                      [--register <file>] [--register-rows-key rows] [--unit-key unit] [--custodian-key custodian]
                      [--work-call <call id>] [--forms <file>] [--forms-key builders]
                      [--reachable <file>] [--reachable-key harnesses] [--parent-harness <name>] [--parent-model <name>]
                      [--parent-persona <name>]

The act decision (decisions/d1-act.json). Each of the nine kinds in the ledger skill's kinds.json is asked as a
Noul, one request each, with the definition's instructions and the kind's test as its criterion. Their lines are
unset, so each probability is printed and no line is applied. The provisional Choice over the nine kinds, `none` and
`two-or-more`, each criterion the kind's test, gives the answer. A part read as `none` goes back to the parent as a
finding; one read as `two-or-more` goes back to be split into one part per kind, each triaged on its own. Neither
gets a persona or a pending file.

The form decision (decisions/d5-form.json), asked only of a part read as `build`: one Choice, whether code or a
model's inference decides the output of what the part builds, or both, or none (it builds no capability). `code` or
`model` names the builder through the forms map --forms names: a JSON or YAML file whose object at --forms-key maps
`code` and `model` to a persona each. `both` sends the part back to be split. `none` leaves the persona to the
persona Choice. An answer below the definition's line goes to the builder the map names for `model`, and its record
marks it below the line with its probability, the line and the line's version.

The persona decision (decisions/d3-figure.json), asked only when the act decision read one kind and nothing split
the part. Eligibility is exact: a persona is a row of the roster whose file exists and whose frontmatter carries a
non-empty value at the ratified key and a goal, and whose name is not one given by --user. The roster is a YAML or
JSON file; the --*-key options name where its rows and their fields are, so the script reads any roster without
knowing its workspace. Where the form named a builder, the decision's answer is that builder, if it is eligible, and
Jev is not asked; a map with no builder for the form, or a builder not eligible, sends the part back as a finding.
With no eligible persona, the answer is `none adequate` with the rule that emptied the set, and Jev is not asked.
Otherwise one Choice over the eligible personas, each criterion `<persona>: <goal>`, followed by what it declares it
does (--does-key) where it declares it, with the part, its kind and the task's stage as state; then the adequacy Noul
on the persona it ranks first, against the definition's line. No decision reads who sent the part, or any group a
kind is paired with.

The custodian rule. Where --register names a register (a YAML or JSON file whose list at --register-rows-key holds
rows, each with a unit at --unit-key and a custodian at --custodian-key), a part that names a unit the register lists
reaches only that unit's custodians: every other persona is excluded with the rule as its reason. A unit is named
where its text stands whole in the delegation's body, with no path character joining it on either side, so an
absolute path ending in the unit, or the unit with a suffix, is not it. A part naming several units needs a persona
recorded against each. A part naming none, or no register given, changes nothing. A register that cannot be read
stops the script with exit 2.

The review rule. A part read as `verdict-or-review` calls work to account. The persona that did that work is read
from the work's own dispatch record: the record in the ledger folder whose call id --work-call names, at its
`persona-name`. Every persona in that persona's roster group is excluded, with the rule as its reason. Where no
--work-call is given, no record has the id, or the record or the roster gives no persona or group, no persona is
chosen and the part goes back to the parent as a finding. The sender is never read for this rule.

The sender, --parent-persona, is recorded in the pending file as `sender`, who sent the part, or `unrecorded
(<reason>)`. No decision reads it.

The task's stage is read by stage.py, from the task --task names and the folders --build-root and --ratified-root
name, before any decision is asked. It is a fact of the persona decision (its state, its exact evidence and the pending
file's persona facts) and of the effort decision.

The harness decision (decisions/d6-harness.json) and the model decision (decisions/d7-model.json), asked after the
persona decision and before the effort decision, whatever the others read. The reachable list --reachable names is a
JSON or YAML file whose list at --reachable-key holds each harness, with its `name`, a `description` and its `models`,
each with a `name`, a `description` and the effort `levels` it is offered on that harness. The harness is chosen from
the list, then the model from the models it gives that harness: with one listed, it is assigned without asking; with
several, one Choice, each criterion `<name>: <description>`. Where the list names none, the parent's own is assigned:
--parent-harness (by default the harness the session's own variables name) and --parent-model. Where a request
fails or answers off the list, the parent's own is passed and the record says why. An answer off the list is never
assigned. A reachable list that cannot be read, or a harness or model with no name, stops the script with exit 2.

The effort decision (decisions/d4-effort.json), asked last whatever the others read. The parent's unaided level,
--effort-unaided, is stamped from the clock before Jev is asked anything. One Choice over the levels the assigned
harness offers the assigned model (every level, low to max, where the list gives none), with the part and these exact
facts as state: the kind (or `none`), the persona (or `none`), the stage as stage.py read it, the delegation's length
in words, how many of the absolute paths it names outside its write set are files and their total size in bytes, the
number of paths in its `## Write set` (or `none`), and the harness and model assigned. Where the request fails, or no
level is offered, the level reads `unrecorded (<reason>)` and the output says to pass the unaided level.

Each Jev request is recorded as its own dispatch and return through the ledger skill's ledger.py, in the ledger
folder --ledger names, under --session. The part's text goes to Jev only; no record holds it. A retry on HTTP 429 or
5xx is a request of its own with its own pair.

The pending triage file is <pending-ledger>/.pending/<session>/triage-<member>-<attempt>.json, in the ledger's
pending.schema.json shape, each value stamped from the clock when it is decided: among them `harness_assigned`, the
harness to pass, and `sender`. --pending-ledger defaults to --ledger. Where the act decision reads the part as none,
or a decision splits it, no pending file is written, since the part is not dispatched: the output's `pending_file`
is null and `no_pending_file` says why. A part whose act request failed still has its file, holding the failure.

Output: one JSON object on standard output, whose `harness.pass`, `model.pass` and `effort.pass` are the values to
pass. Exit codes: 0 answered; 1 refused on its input; 2 cannot run (the ledger scripts, kinds.json or a decision file
not found, or the roster, register or reachable list unreadable); 3 a decision's request to Jev failed (the output
and the pending file record the failure).

The override, when the parent passes a level other than the effort decision's:

    python3 decide.py override --pending <file> --decision d4-effort --level <level> --reason <text>

It appends to the pending file's `overrides` list the decision's level (read from the file's own d4-effort record),
the level passed instead, the reason and the time, and restamps the list. It refuses, with exit 1 and the file
unchanged, a file with no d4-effort record, an unknown level, a level the assigned model is not offered (after a
model override, the model passed, by the d7-model record's `levels_offered`), an empty reason or another decision.

The override, when the parent passes a harness or a model other than the decision's:

    python3 decide.py override --pending <file> --decision d6-harness --harness <name> --reason <text>
    python3 decide.py override --pending <file> --decision d7-model --model <name> --reason <text>

It appends to the `overrides` list the decision's value (`decision_harness` or `decision_model`, read from the file's
own record), the value passed instead (`harness_passed` or `model_passed`), the reason and the time. An override of
the harness also sets `harness_assigned` to the harness passed, restamped. It refuses, with exit 1 and the file
unchanged, a file with no such record, a value off the reachable list the record names (the parent's own where it
names none), the decision's own value and an empty reason.

The override, when the parent sends the part to a persona other than the persona decision's:

    python3 decide.py override --pending <file> --decision d3-figure --persona <name> --parent-persona <name>
                               --reason <text>

It appends to the `overrides` list the six values an override of the persona records, the first two read from the
file's own d3-figure record: the decision's persona (`decision_persona`, its answer less any below-the-line mark),
its adequacy probability (`adequacy_probability`, or `not asked (...)` where the forms map named the builder), the
parent's own persona (`parent_persona`), the persona chosen instead (`persona_chosen`), the reason and the time. It
sets `triage_persona` to the persona chosen and `chosen_by` to the dispatching agent, each restamped; the decision's
record is left as it was. It refuses, with exit 1 and the file unchanged, a file with no d3-figure record, a record
with no adequacy probability and no forms map's builder (the decision chose no persona to override), a persona the
roster does not list (the record's eligible and excluded names: an unknown name is refused, never matched), the
decision's own persona, an empty parent persona and an empty reason.

The override, when the parent sends the part with no persona at all (R-11: such a dispatch goes out as an override
with its reason):

    python3 decide.py override --decision no-persona --ledger <folder> --session <id> --member <id> [--attempt 1]
                               --reason <text>
    python3 decide.py override --decision no-persona --pending <file> --reason <text>

It appends to the `overrides` list the decision (`no-persona`), the persona decision's persona where the file holds a
d3-figure record that named one (`decision_persona`, else `unrecorded (...)` saying why), the reason and the time. It
removes `triage_persona`, since no persona goes out, and sets `chosen_by` to the dispatching agent, restamped; any
decision record is left as it was. Where no triage ran, the first form writes the member's pending triage file,
<ledger>/.pending/<session>/triage-<member>-<attempt>.json, holding the override alone; the dispatch's brief names
that member and attempt as any brief does. The second form takes a pending file that exists. The dispatch check lets
the dispatch through and says why. It refuses, with exit 1 and nothing written, an empty reason, a named pending file
that does not exist, and a call that names neither the file nor the member's ledger, session and id.

The key is JEV_API_KEY; --key-from-zsh fills it, when it is not set, from what zsh sets it to on starting. The
endpoint is SUBAGENT_TRIAGE_JEV_URL where set, for a stand-in, else Jev's own.
"""

import argparse
import datetime
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import time
import urllib.error
import urllib.request
import uuid
from pathlib import Path

HERE = Path(__file__).resolve().parent
SKILL = HERE.parent
DECISIONS = SKILL / 'decisions'

JEV_URL = 'https://api.typesafe.ai/v1/systemone'
KEY_VARIABLE = 'JEV_API_KEY'
URL_VARIABLE = 'SUBAGENT_TRIAGE_JEV_URL'
WAIT_VARIABLE = 'SUBAGENT_TRIAGE_RETRY_WAIT'
CALL_ID_VARIABLE = 'SUBAGENT_LEDGER_CALL_ID'
RETRIES = 3
RETRY_STATUSES = (429, 500, 502, 503, 504)
STATE_LIMIT = 12000
NONE_LABEL = 'none'

NO_AGENT = 'unrecorded (no agent: script call)'
NOT_YET = 'unrecorded (not yet returned)'
NO_CALLER = 'unrecorded (the triage cannot tell a lane from its parent)'
NO_CACHE = 'unrecorded (Jev reports none)'
NO_COST = 'unrecorded (Jev reports no cost)'
NO_SPEND = 'unrecorded (Jev has no spend ledger)'
NO_ISOLATION = 'unrecorded (a Jev request runs no tools)'
NO_EFFORT = 'unrecorded (Jev takes no effort level)'
NO_REQUEST = 'unrecorded (no request was sent)'
UNCHECKED = 'unchecked: returned by Jev and not checked against anything else'
CHOSEN_BY = 'the planning skill'
OVERRIDE_CHOSEN_BY = 'the dispatching agent'
LEVELS = ('low', 'medium', 'high', 'xhigh', 'max')  # the levels the Agent tool offers
EFFORT_DECISION = 'd4-effort'
PERSONA_DECISION = 'd3-figure'
FORM_DECISION = 'd5-form'
HARNESS_DECISION = 'd6-harness'
MODEL_DECISION = 'd7-model'
NO_PERSONA = 'no-persona'  # R-11: the parent's dispatch with no persona, recorded as an override
BELOW_LINE = ', below the line'
SPLIT_LABEL = 'two-or-more'  # the act Choice's answer for a part that asks for two or more kinds (R-37)
MAKING_KIND = 'build'  # the kind whose parts the form decision asks of (R-38)
REVIEW_KIND = 'verdict-or-review'  # the kind whose candidates lose the group of the work's own persona (R-37)
FORMS = ('code', 'model')  # the form answers the settings' forms map names a builder for
MAP_CHOSEN = 'not asked (the forms map named the builder)'
NO_SENDER = 'unrecorded (no --parent-persona was given)'
REVIEW_RULE = 'the persona shares its group (%s) with %s, who performed the work called to account'
# An absolute path: `~/` and one name or more, a drive letter, or `/` and at least two names. A word of one name
# after `/`, such as a quoted slash command (`/dry-run`), is not read as a path (dry run 17, H4).
ABSOLUTE_PATH = re.compile(r'(?:(?<=[\s`\'"(<\[])|^)(~/[^\s`\'"<>()\[\]{}]+|/[^\s`\'"<>()\[\]{}/]+/[^\s`\'"<>()\[\]{}]*'
                           r'|[A-Za-z]:[\\/][^\s`\'"<>()\[\]{}]+)', re.MULTILINE)


class CannotRun(Exception):
    pass


class JevFailure(Exception):
    def __init__(self, reason):
        Exception.__init__(self, reason)
        self.reason = reason


# ---------------------------------------------------------------------------
# Finding the ledger skill, and reading the inputs
# ---------------------------------------------------------------------------

def ledger_scripts():
    """The ledger skill's scripts folder: SUBAGENT_LEDGER_SCRIPTS, else beside this skill in a repository or install."""
    named = os.environ.get('SUBAGENT_LEDGER_SCRIPTS')
    tried = [Path(named)] if named else []
    tried += [SKILL.parent.parent / 'subagent-ledger' / 'skill' / 'scripts', SKILL.parent / 'subagent-ledger' / 'scripts']
    for folder in tried:
        if (folder / 'ledger.py').is_file() and (folder / 'kinds.json').is_file():
            if str(folder) not in sys.path:
                sys.path.insert(0, str(folder))
            return folder
    raise CannotRun('ledger.py and kinds.json not found at %s' % ', '.join(str(p) for p in tried))


def read_json(path):
    return json.loads(Path(path).read_text(encoding='utf-8'))


def read_structured(path):
    """A JSON or YAML file. YAML needs PyYAML."""
    text = Path(path).read_text(encoding='utf-8')
    try:
        return json.loads(text)
    except ValueError:
        pass
    try:
        import yaml
    except ImportError:
        raise CannotRun('%s is not JSON, and PyYAML is not installed to read it as YAML' % path)
    return yaml.safe_load(text)


def frontmatter(path):
    text = Path(path).read_text(encoding='utf-8')
    if not text.startswith('---'):
        return {}
    end = text.find('\n---', 3)
    if end == -1:
        return {}
    try:
        import yaml
    except ImportError:
        raise CannotRun('PyYAML is not installed to read the frontmatter of %s' % path)
    data = yaml.safe_load(text[3:end])
    return data if isinstance(data, dict) else {}


def dig(data, dotted):
    """The value at a dotted key path, or None. A key holding a dot is tried whole before it is split."""
    if not dotted:
        return data
    if isinstance(data, dict) and dotted in data:
        return data[dotted]
    head, _, rest = dotted.partition('.')
    if not rest or not isinstance(data, dict) or head not in data:
        return None
    return dig(data[head], rest)


def full_body(text):
    if text.startswith('---'):
        end = text.find('\n---', 3)
        if end != -1:
            text = text[end + 4:]
    return text.strip()


def body_of(text):
    return full_body(text)[:STATE_LIMIT]


def split_write_set(body):
    """(the body less its `## Write set` section, the section's paths or None where it has none or says `none`)."""
    lines = body.splitlines()
    for start, line in enumerate(lines):
        if line.strip().lower() == '## write set':
            break
    else:
        return body, None
    end = next((i for i in range(start + 1, len(lines)) if lines[i].lstrip().startswith('#')), len(lines))
    paths = [line.strip() for line in lines[start + 1:end]
             if line.strip() and not line.strip().startswith(('```', '<!--'))]
    rest = '\n'.join(lines[:start] + lines[end:])
    return rest, (None if paths == ['none'] or not paths else paths)


def named_inputs(body):
    """(named, resolving, bytes): the absolute paths the body names outside its write set, in order and once each;
    those that are files; and their total size."""
    rest, _ = split_write_set(body)
    named = []
    for found in ABSOLUTE_PATH.findall(rest):
        path = found.rstrip('.,;:!?')
        if path not in named:
            named.append(path)
    resolving = [path for path in named if Path(os.path.expanduser(path)).is_file()]
    return named, resolving, sum(Path(os.path.expanduser(path)).stat().st_size for path in resolving)


def git_commit(path):
    try:
        done = subprocess.run(['git', '-C', str(Path(path).parent), 'log', '-1', '--format=%h', '--', str(path)],
                              capture_output=True, text=True, timeout=20)
    except (OSError, subprocess.SubprocessError):
        return None
    return done.stdout.strip() or None


def stamp():
    return datetime.datetime.now(datetime.timezone.utc).strftime('%Y-%m-%dT%H:%M:%S.%fZ')


def stamped(value):
    return {'value': value, 'stamped_at': stamp()}


# ---------------------------------------------------------------------------
# The roster
# ---------------------------------------------------------------------------

CUSTODIAN_RULE = 'the part names a unit the register records against other personas only'


def read_register(args):
    """{unit: [custodian, ...]} from the register --register names, or None where it names none."""
    if not args.register:
        return None
    try:
        data = read_structured(args.register)
    except (OSError, ValueError) as exc:
        raise CannotRun('the register %s could not be read: %s' % (args.register, exc))
    except CannotRun:
        raise
    except Exception as exc:
        raise CannotRun('the register %s could not be read: %s: %s' % (args.register, type(exc).__name__, exc))
    rows = data if isinstance(data, list) else dig(data, args.register_rows_key) if isinstance(data, dict) else None
    if not isinstance(rows, list):
        raise CannotRun('the register %s holds no list at %r' % (args.register, args.register_rows_key))
    held = {}
    for row in rows:
        if not isinstance(row, dict):
            continue
        unit, custodian = dig(row, args.unit_key), dig(row, args.custodian_key)
        if isinstance(unit, str) and unit.strip() and isinstance(custodian, str) and custodian.strip():
            held.setdefault(unit.strip(), [])
            if custodian.strip() not in held[unit.strip()]:
                held[unit.strip()].append(custodian.strip())
    return held


def units_named(text, register):
    """The register's units the text names, in register order. A unit is named where it stands whole: no path
    character joins it on either side, so an absolute path ending in the unit, or the unit with a suffix, is not it."""
    return [unit for unit in register or {}
            if re.search(r'(?<![\w/.~-])' + re.escape(unit) + r'(?![\w/~-])(?!\.\w)', text)]


def read_roster(args, text=''):
    """(eligible, excluded, rows, units, groups): eligible as [{name, group, goal, file}] in roster order; excluded
    as {name: rule}; the number of rows; the register's units `text` names; and every named row's group."""
    register = read_register(args)
    units = units_named(text, register)
    data = read_structured(args.roster)
    rows = data if isinstance(data, list) else dig(data, args.rows_key) if isinstance(data, dict) else None
    if rows is None:
        rows = []
    if not isinstance(rows, list):
        raise CannotRun('the roster\'s %r is not a list' % args.rows_key)
    root = Path(args.file_root) if args.file_root else Path(args.roster).resolve().parent
    users = set(args.user or [])
    eligible, excluded, groups = [], {}, {}
    for row in rows:
        name = dig(row, args.name_key) if isinstance(row, dict) else None
        if not isinstance(name, str) or not name:
            continue
        group = dig(row, args.group_key)
        groups.setdefault(name, group if isinstance(group, str) and group else 'unrecorded (no group)')
        if name in users:
            excluded[name] = 'the persona is the user'
            continue
        named = dig(row, args.file_key)
        path = (root / named) if isinstance(named, str) and named else None
        if path is None or not path.is_file():
            excluded[name] = 'its file %s does not exist' % (named or '(none named)')
            continue
        meta = frontmatter(path)
        if not dig(meta, args.ratified_key):
            excluded[name] = 'its file carries no ratified declaration'
            continue
        goal = dig(meta, args.goal_key)
        if not isinstance(goal, str) or not goal.strip():
            excluded[name] = 'its ratified declaration names no goal'
            continue
        does = dig(meta, args.does_key)
        missing = [unit for unit in units if name not in register[unit]]
        if missing:
            excluded[name] = '%s (%s)' % (CUSTODIAN_RULE, ', '.join(missing))
            continue
        eligible.append({'name': name, 'group': groups[name], 'goal': ' '.join(goal.split()),
                         'does': ' '.join(does.split()) if isinstance(does, str) and does.strip() else None,
                         'file': str(path)})
    return eligible, excluded, len(rows), units, groups


def sender_of(parent):
    """Who sent the part: the name --parent-persona gives, or unrecorded. Recorded only; no decision reads it."""
    return parent.strip() if parent and parent.strip() else NO_SENDER


def work_performer(folder, call_id):
    """(the persona that did the work `call_id` names, read from that work's own dispatch record in the ledger
    folder, or None; and why there is none). Never read from the sender."""
    if not call_id or not call_id.strip():
        return None, 'no --work-call names the work the part calls to account'
    call_id = call_id.strip()
    for path in sorted(Path(folder).glob('*.jsonl')):
        try:
            lines = path.read_text(encoding='utf-8').splitlines()
        except OSError:
            continue
        for line in lines:
            if call_id not in line:
                continue
            try:
                row = json.loads(line)
            except ValueError:
                continue
            if isinstance(row, dict) and row.get('record') == 'dispatch' and row.get('call_id') == call_id:
                persona = row.get('persona-name')
                if isinstance(persona, str) and persona.strip() and not persona.startswith('unrecorded ('):
                    return persona.strip(), None
                return None, 'the dispatch record of %s names no persona (%s)' % (call_id, persona)
    return None, 'no dispatch record in %s has the call id %s' % (folder, call_id)


def review_rule(args, eligible, excluded, groups):
    """(eligible, excluded, facts, finding) for a verdict-or-review part: every persona in the group of the persona
    that did the work is excluded; where no record names that persona, the finding says why."""
    performer, why = work_performer(args.ledger, args.work_call)
    group = groups.get(performer) if performer else None
    if performer and (not isinstance(group, str) or group.startswith('unrecorded (')):
        why = 'the roster gives no group for %s, who did the work %s names' % (performer, args.work_call)
        performer = None
    if performer is None:
        return eligible, excluded, {'work_call': args.work_call or NONE_LABEL}, \
            'no persona is recorded as having done the work called to account: %s' % why
    kept, excluded = [], dict(excluded)
    for persona in eligible:
        if persona['group'] == group:
            excluded[persona['name']] = REVIEW_RULE % (group, performer)
        else:
            kept.append(persona)
    return kept, excluded, {'work_call': args.work_call, 'work_persona': performer, 'work_group': group}, None


def form_builder(args, form):
    """(the persona the settings' forms map names for `form`, or None; and why there is none)."""
    if not args.forms:
        return None, 'no forms map was given, so no builder is named for %s' % form
    try:
        data = read_structured(args.forms)
    except CannotRun as exc:
        return None, 'the forms map %s could not be read for %s: %s' % (args.forms, form, exc)
    except Exception as exc:
        return None, 'the forms map %s could not be read for %s: %s: %s' % (args.forms, form, type(exc).__name__, exc)
    builders = dig(data, args.forms_key) if isinstance(data, dict) else None
    name = builders.get(form) if isinstance(builders, dict) else None
    if not isinstance(name, str) or not name.strip():
        return None, 'the forms map %s names no builder for %s at %r' % (args.forms, form, args.forms_key)
    return name.strip(), None


def read_reachable(args):
    """The reachable list as [{name, description, models: [{name, description, levels}]}]; [] where none is named.
    A list that cannot be read, or a harness or model with no name, stops the script."""
    if not args.reachable:
        return []
    try:
        data = read_structured(args.reachable)
    except CannotRun:
        raise
    except Exception as exc:
        raise CannotRun('the reachable list %s could not be read: %s: %s' % (args.reachable, type(exc).__name__, exc))
    rows = data if isinstance(data, list) else dig(data, args.reachable_key) if isinstance(data, dict) else None
    if not isinstance(rows, list):
        raise CannotRun('the reachable list %s holds no list at %r' % (args.reachable, args.reachable_key))

    def named(row, what):
        name = row.get('name') if isinstance(row, dict) else None
        if not isinstance(name, str) or not name.strip():
            raise CannotRun('the reachable list %s holds a %s with no name' % (args.reachable, what))
        return name.strip(), ' '.join(str(row.get('description') or '').split())

    out = []
    for row in rows:
        name, description = named(row, 'harness')
        models = []
        for entry in row.get('models') or []:
            model, text = named(entry, 'model')
            levels = entry.get('levels')
            if levels is not None and (not isinstance(levels, list) or not all(isinstance(x, str) for x in levels)):
                raise CannotRun('the reachable list %s gives %s levels that are not a list of names' % (
                    args.reachable, model))
            models.append({'name': model, 'description': text, 'levels': levels})
        out.append({'name': name, 'description': description, 'models': models})
    return out


def models_of(harnesses, harness):
    for entry in harnesses:
        if entry['name'] == harness:
            return entry['models']
    return []


def levels_for(harnesses, harness, model):
    """The levels the reachable list gives `model` on `harness`, in LEVELS order; every level where it gives none."""
    for entry in models_of(harnesses, harness):
        if entry['name'] == model and entry['levels'] is not None:
            return [level for level in LEVELS if level in entry['levels']]
    return list(LEVELS)


# ---------------------------------------------------------------------------
# Jev, with every request recorded
# ---------------------------------------------------------------------------

def counter(usage, name):
    value = usage.get(name)
    return value if isinstance(value, int) else 'unrecorded (Jev reported no %s)' % name


def calling_harness():
    found = [harness for name, harness in (('CLAUDE_CODE_SESSION_ID', 'claude-code'), ('CODEX_THREAD_ID', 'codex'))
             if os.environ.get(name)]
    if len(found) == 1:
        return found[0]
    return 'unrecorded (none of CLAUDE_CODE_SESSION_ID, CODEX_THREAD_ID is set)' if not found else \
        'unrecorded (more than one harness session variable is set)'


def project_of(cwd):
    for folder in [Path(cwd)] + list(Path(cwd).parents):
        if (folder / '.git').exists():
            return folder.name
    return 'unrecorded (the working folder is in no git repository)'


def revision(question):
    data = json.dumps(question, sort_keys=True, ensure_ascii=False).encode('utf-8')
    return hashlib.sha1(b'blob %d\0' % len(data) + data).hexdigest()


class Jev:
    def __init__(self, folder, session, model):
        import ledger
        self.ledger = ledger
        self.folder = str(folder)
        self.session = session
        self.model = model
        self.harness = calling_harness()
        self.project = project_of(os.getcwd())
        self.serves = os.environ.get(CALL_ID_VARIABLE) or 'unrecorded (no dispatch named: %s is not set)' % CALL_ID_VARIABLE
        self.url = os.environ.get(URL_VARIABLE) or JEV_URL
        self.calls = []

    def base(self):
        return {'session': self.session, 'agent_id': NO_AGENT, 'route': 'script', 'harness': self.harness,
                'caller': NO_CALLER, 'project': self.project}

    def dispatch(self, call_id, item, question, tries, auth):
        brief = json.dumps({'endpoint': 'Jev, %s' % self.model, 'questions': '%s (question_revision %s)'
                            % (item, revision(question)), 'state': 'the part, not copied here'}, ensure_ascii=False)
        payload = {'endpoint': self.url, 'try': tries, 'question_revision': revision(question),
                   'serves_call_id': self.serves, 'item': item}
        result = self.ledger.dispatch(ledger=self.folder, brief=brief, call_id=call_id,
                                      dispatched_at=self.ledger.now(), outcome=NOT_YET, model_requested=self.model,
                                      auth_route=auth, act_kind=NO_AGENT,
                                      brief_source='unrecorded (the brief is the triage\'s question, not a file)',
                                      harness_payload=payload, **self.base())
        return getattr(result, 'ok', False)

    def record_return(self, call_id, item, question, outcome, reason, status, response=None, answer=None):
        model, tokens = NO_REQUEST, NO_REQUEST
        if isinstance(response, dict):
            got = response.get('usage') if isinstance(response.get('usage'), dict) else {}
            model = response.get('model') or 'unrecorded (the answer named no model)'
            tokens = {'input': counter(got, 'input_tokens'), 'cache_write': NO_CACHE, 'cache_read': NO_CACHE,
                      'output': counter(got, 'output_tokens')}
        elif status is not None:
            model = tokens = 'unrecorded (Jev answered HTTP %s)' % status
        payload = {'http_status': status if status is not None else 'unrecorded (no HTTP answer)',
                   'question_revision': revision(question), 'serves_call_id': self.serves, 'item': item}
        result = self.ledger.ret(call_id, ledger=self.folder, answer=answer, returned_at=self.ledger.now(),
                                 outcome=outcome, outcome_reason=reason, model=model, tokens=tokens, cost=NO_COST,
                                 isolation=NO_ISOLATION, effort=NO_EFFORT, spend_line=NO_SPEND,
                                 harness_payload=payload, **self.base())
        return getattr(result, 'ok', False)

    def note(self, call_id, item, tries, outcome, written):
        self.calls.append({'call_id': call_id, 'item': item, 'try': tries, 'outcome': outcome,
                           'recorded': written})

    def ask(self, item, state, qid, question):
        """The answer object for one question, or JevFailure. One request; retried as requests of their own."""
        questions = {qid: question}
        if not os.environ.get(KEY_VARIABLE):
            call_id = str(uuid.uuid4())
            ok = self.dispatch(call_id, item, questions, 0, 'environment: %s (not set)' % KEY_VARIABLE)
            reason = self.ledger.reason_for('jev', '%s is not set' % KEY_VARIABLE, fixed='missing_key')
            ok = self.record_return(call_id, item, questions, 'failed', reason, None) and ok
            self.note(call_id, item, 0, 'failed', ok)
            raise JevFailure('the Jev key is missing: %s is not set' % KEY_VARIABLE)
        body = json.dumps({'model': self.model, 'state': state, 'questions': questions}).encode('utf-8')
        wait = float(os.environ.get(WAIT_VARIABLE, '2'))
        tries = 0
        while True:
            tries += 1
            call_id = str(uuid.uuid4())
            ok = self.dispatch(call_id, item, questions, tries, 'environment: %s' % KEY_VARIABLE)
            status = None
            try:
                sent = urllib.request.Request(self.url, data=body, headers={
                    'Authorization': 'Bearer ' + os.environ.get(KEY_VARIABLE, ''),
                    'Content-Type': 'application/json'})
                with urllib.request.urlopen(sent) as handle:
                    status = handle.status
                    raw = handle.read()
            except urllib.error.HTTPError as exc:
                status = exc.code
                try:
                    text = exc.read()[:300].decode('utf-8', 'replace')
                except Exception:
                    text = ''
                error = 'HTTP %d: %s' % (exc.code, text)
                reason = self.ledger.reason_for('jev', error, fixed='rate_limited' if exc.code == 429 else None)
                ok = self.record_return(call_id, item, questions, 'failed', reason, status) and ok
                self.note(call_id, item, tries, 'failed', ok)
                if exc.code in RETRY_STATUSES and tries <= RETRIES:
                    time.sleep(wait * tries)
                    continue
                raise JevFailure('Jev failed: %s' % ' '.join(error.split())[:200])
            except Exception as exc:
                error = '%s: %s' % (type(exc).__name__, getattr(exc, 'reason', exc))
                ok = self.record_return(call_id, item, questions, 'failed', self.ledger.reason_for('jev', error),
                                        status) and ok
                self.note(call_id, item, tries, 'failed', ok)
                raise JevFailure('Jev is unreachable: %s' % error[:200])
            try:
                response = json.loads(raw)
                answer = response['answers'][qid]
                kept = self.readable(question, answer)
            except (ValueError, KeyError, TypeError) as exc:
                text = 'the answer could not be read: %s' % (exc if str(exc) else type(exc).__name__)
                ok = self.record_return(call_id, item, questions, 'failed', {'class': 'unreadable', 'text': text[:400]},
                                        status) and ok
                self.note(call_id, item, tries, 'failed', ok)
                raise JevFailure('Jev failed: %s' % text[:200])
            ok = self.record_return(call_id, item, questions, 'served', 'none (served)', status, response,
                                    answer=json.dumps(kept, sort_keys=True)) and ok
            self.note(call_id, item, tries, 'served', ok)
            return kept

    @staticmethod
    def readable(question, answer):
        if question['type'] == 'noul':
            value = answer.get('noul')
            if not isinstance(value, (int, float)):
                raise ValueError('the Noul carried no probability')
            return {'noul': value}
        labels = list(question['criteria'])
        probabilities = answer.get('probabilities')
        if answer.get('choice') not in labels or not isinstance(probabilities, dict) or not all(
                isinstance(probabilities.get(label), (int, float)) for label in labels):
            raise ValueError('the Choice carried no label among its options with a probability for each')
        return {'choice': answer['choice'], 'probabilities': dict((label, probabilities[label]) for label in labels)}


# ---------------------------------------------------------------------------
# The two decisions
# ---------------------------------------------------------------------------

def outcome(definition, when_starts):
    for entry in definition['outcomes']:
        if entry['when'].startswith(when_starts):
            return entry
    raise CannotRun('%s has no outcome beginning %r' % (definition['id'], when_starts))


def record(definition, subject, quote, answer, basis, lane_from, decided_by, exact=None):
    out = {'question': definition['id'], 'definition_version': definition['definition_version'],
           'subject': subject}
    if quote is not None:
        out['quote'] = quote
    out.update({'answer': answer, 'uncertainty_basis': basis,
                'decision_point_classification': definition['decision_point_classification']})
    if exact is not None:
        out['exact_evidence'] = exact
    out['lane'] = lane_from['lane']
    if lane_from['lane'] == 'delivered':
        out['delegated_authority'] = lane_from['delegated_authority']
    out.update({'evidence_state': UNCHECKED, 'decided_by': decided_by, 'final_disposition': 'pending'})
    return out


def act_decision(jev, definition, kinds, part, subject, quote, decided_by):
    """The printed act section and its decision record. Every Noul is asked; no line is applied."""
    names = definition['kinds']['names']
    tests = dict(kinds)
    missing = [name for name in names if name not in tests]
    if missing:
        raise CannotRun('kinds.json names no test for %s' % ', '.join(missing))
    composition = definition['composition']
    state = {'part': part}
    nouls, failures = {}, {}
    for name in names:
        question = {'type': 'noul',
                    'instructions': composition['nouls']['instructions_template'].format(test=tests[name]),
                    'criteria': {'true': tests[name]}}
        try:
            nouls[name] = jev.ask('d1-act noul %s' % name, state, 'kind_%s' % name.replace('-', '_'), question)['noul']
        except JevFailure as failure:
            nouls[name] = None
            failures[name] = failure.reason
    lines = composition['nouls']['lines']
    reading = composition['provisional_reading']
    criteria = dict((name, tests[name]) for name in names)
    criteria[reading['none']['label']] = reading['none']['criterion']
    criteria[reading['split']['label']] = reading['split']['criterion']
    choice_question = {'type': 'choice', 'instructions': reading['instructions'], 'criteria': criteria}
    section = {'nouls': nouls, 'noul_failures': failures, 'lines': None if all(v is None for v in lines.values())
               else lines, 'line_applied': False, 'provisional': definition['provisional'], 'split': False}
    try:
        choice = jev.ask('d1-act provisional choice', state, 'kind', choice_question)
    except JevFailure as failure:
        answer = 'unrecorded (%s)' % failure.reason
        section.update(choice=None, kind=None, answer=answer, failure=failure.reason)
        basis = {'nouls': nouls, 'lines': lines, 'choice': None, 'definition_version': definition['definition_version']}
        return section, record(definition, subject, quote, answer, basis, outcome(definition, 'the request fails'),
                               decided_by)
    read = choice['choice']
    if read == NONE_LABEL:
        answer = 'none (the provisional Choice read none: %s)' % reading['none']['criterion']
        lane_from = outcome(definition, 'no Noul')
        kind = None
    elif read == reading['split']['label']:
        answer = 'split (the provisional Choice read two or more kinds: %s)' % reading['split']['criterion']
        lane_from = outcome(definition, 'two or more Nouls')
        kind = None
        section['split'] = True
    else:
        answer = read
        kind = read
        lane_from = outcome(definition, 'user-decision' if read == 'user-decision' else 'exactly one')
    section.update(choice=choice, kind=kind, answer=answer)
    basis = {'nouls': nouls, 'lines': lines, 'line_applied': False,
             'choice': choice['probabilities'], 'provisional': 'the Choice gives the answer while any line is unset',
             'definition_version': definition['definition_version']}
    return section, record(definition, subject, quote, answer, basis, lane_from, decided_by)


def form_decision(jev, definition, part, subject, quote, decided_by):
    """The printed form section and its decision record, for a build part (R-38). One Choice over code, model, both
    and none; an answer below the line goes to the model builder, marked."""
    composition = definition['composition']['choice']
    line, version = composition['line'], composition['line_version']
    criteria = dict(composition['criteria'])
    question = {'type': 'choice', 'instructions': composition['instructions'], 'criteria': criteria}
    section = {'choice': None, 'answer': None, 'form': None, 'split': False, 'below_line': None, 'probability': None,
               'line': line, 'line_version': version}
    try:
        choice = jev.ask('%s choice' % definition['id'], {'part': part}, 'form', question)
    except JevFailure as failure:
        answer = 'unrecorded (%s)' % failure.reason
        section.update(answer=answer, failure=failure.reason)
        basis = {'choice': None, 'line': line, 'line_version': version,
                 'definition_version': definition['definition_version']}
        return section, record(definition, subject, quote, answer, basis, outcome(definition, 'the request fails'),
                               decided_by)
    read = choice['choice']
    probability = choice['probabilities'][read]
    below = probability < line
    section.update(choice=choice, probability=probability, below_line=below)
    if below:
        answer, form = read + BELOW_LINE, 'model'
        lane_from = outcome(definition, "the Choice's answer is below")
    elif read == 'both':
        answer, form = 'split (the part builds both: %s)' % criteria['both'], None
        lane_from = outcome(definition, 'the Choice reads both')
        section['split'] = True
    elif read == NONE_LABEL:
        answer, form = 'none (the part builds no capability)', None
        lane_from = outcome(definition, 'the Choice reads none')
    else:
        answer, form = read, read
        lane_from = outcome(definition, 'the Choice reads code or model')
    section.update(answer=answer, form=form)
    basis = {'choice': choice['probabilities'], 'probability': probability, 'line': line, 'line_version': version,
             'definition_version': definition['definition_version']}
    return section, record(definition, subject, quote, answer, basis, lane_from, decided_by)


def persona_decision(jev, definition, part, kind, eligible, excluded, rows, subject, quote, decided_by, stage,
                     units, extra=None, builder=None, finding=None):
    """The persona section and its decision record. Its facts are the part, its kind, the stage and each candidate's
    declared goal and acts: never the sender, and never a group paired with the kind (R-37). `builder` is the
    persona the forms map names for the part's form; `finding` is why the part goes back with no persona."""
    composition = definition['composition']
    line = composition['adequacy']['line']
    line_version = composition['adequacy']['line_version']
    exact = {'eligible': [p['name'] for p in eligible], 'excluded': excluded, 'roster_rows': rows,
             'units_named': units, 'kind': kind, 'stage': stage}
    exact.update(extra or {})
    section = {'eligible': exact['eligible'], 'excluded': excluded, 'units_named': units, 'line': line,
               'line_version': line_version, 'choice': None, 'persona': None, 'adequacy': None, 'below_line': None}
    names = dict((p['name'], p) for p in eligible)
    if finding is None and builder is not None and builder not in names:
        finding = 'the forms map names %s for %s, and %s is not eligible: %s' % (
            builder, exact.get('form'), builder, excluded.get(builder, 'the roster does not list it'))
    if finding is not None or not eligible:
        rules = [finding] if finding else (sorted(set(excluded.values())) or ['the roster lists no persona'])
        answer = 'none adequate (%s)' % '; '.join(rules)
        section['answer'] = answer
        basis = {'requests': 'none: no persona is chosen', 'line': line, 'line_version': line_version}
        when = 'the forms map names no' if exact.get('form') in FORMS else 'no persona'
        return section, record(definition, subject, quote, answer, basis, outcome(definition, when),
                               decided_by, exact=exact)
    if builder is not None:
        chosen = names[builder]
        section.update(persona=builder, group=chosen['group'], goal=chosen['goal'], does=chosen['does'],
                       adequacy=MAP_CHOSEN, below_line=False, answer=builder)
        basis = {'requests': 'none: the forms map names the builder', 'form_builder': exact.get('form'),
                 'adequacy': MAP_CHOSEN}
        return section, record(definition, subject, quote, builder, basis,
                               outcome(definition, 'the forms map names an'), decided_by, exact=exact)
    state = {'part': part, 'kind': kind, 'stage': stage}
    template = composition['choice']['criterion_template']
    does_template = composition['choice']['does_template']
    criteria = dict((p['name'], template.format(persona=p['name'], goal=p['goal'])
                     + (does_template.format(does=p['does']) if p['does'] else '')) for p in eligible)
    question = {'type': 'choice', 'instructions': composition['choice']['instructions'], 'criteria': criteria}
    try:
        choice = jev.ask('d3-figure choice', state, 'persona', question)
        probabilities = choice['probabilities']
        first = max(eligible, key=lambda p: probabilities[p['name']])
        section['choice'] = choice
        adequacy_q = {'type': 'noul', 'instructions': composition['adequacy']['instructions'],
                      'criteria': {'true': composition['adequacy']['instructions'].rsplit('. ', 1)[-1]}}
        adequacy = jev.ask('d3-figure adequacy %s' % first['name'], {
            'part': part, 'persona': first['name'], 'goal': first['goal'], 'does': first['does'] or NONE_LABEL},
            'adequate', adequacy_q)['noul']
    except JevFailure as failure:
        answer = 'unrecorded (%s)' % failure.reason
        section.update(answer=answer, failure=failure.reason)
        basis = {'choice': section['choice'] and section['choice']['probabilities'], 'line': line,
                 'line_version': line_version}
        return section, record(definition, subject, quote, answer, basis, outcome(definition, 'the request fails'),
                               decided_by, exact=exact)
    below = adequacy < line
    if below:
        answer = first['name'] + BELOW_LINE
        lane_from = outcome(definition, 'the adequacy Noul is below')
    else:
        answer = first['name']
        lane_from = outcome(definition, 'the adequacy Noul is at or above')
    section.update(persona=first['name'], group=first['group'], goal=first['goal'], does=first['does'],
                   adequacy=adequacy, below_line=below, answer=answer)
    basis = {'choice': probabilities, 'adequacy': adequacy, 'line': line, 'line_version': line_version}
    return section, record(definition, subject, quote, answer, basis, lane_from, decided_by, exact=exact)


def listed_decision(jev, definition, qid, options, parent, state, subject, quote, decided_by, nothing, levels=None):
    """The harness or model section and its decision record (R-39): chosen from `options`, the reachable list's
    entries; the parent's own where the list names none or the decision gives none. `nothing` says why the list
    names none. `pass` is the value to pass; an answer off the list is never it. `levels`, for the model decision,
    gives the levels each listed model is offered on the assigned harness, so an effort override after a model
    override can be checked against the model passed."""
    names = [o['name'] for o in options]
    exact = {'reachable': names, 'parent_%s' % qid: parent}
    if levels is not None:
        exact['levels_offered'] = levels
    section = {'reachable': names, 'parent': parent, 'choice': None}
    if not options:
        lane_from = outcome(definition, 'the settings list nothing')
        basis = {'requests': 'none: %s, so the parent\'s own is assigned' % nothing}
        section.update(answer=parent, route=lane_from['route'], **{'pass': parent})
        return section, record(definition, subject, None, parent, basis, lane_from, decided_by, exact=exact)
    if len(options) == 1:
        lane_from = outcome(definition, 'the settings list one')
        basis = {'requests': 'none: the settings list one %s' % qid}
        section.update(answer=names[0], route=lane_from['route'], **{'pass': names[0]})
        return section, record(definition, subject, None, names[0], basis, lane_from, decided_by, exact=exact)
    template = definition['composition']['choice']['criterion_template']
    criteria = dict((o['name'], template.format(name=o['name'], description=o['description'] or o['name']))
                    for o in options)
    question = {'type': 'choice', 'instructions': definition['composition']['choice']['instructions'],
                'criteria': criteria}
    try:
        choice = jev.ask('%s choice' % definition['id'], state, qid, question)
    except JevFailure as failure:
        answer = 'unrecorded (%s)' % failure.reason
        lane_from = outcome(definition, 'the request fails')
        section.update(answer=answer, failure=failure.reason, route=lane_from['route'], **{'pass': parent})
        basis = {'choice': None, 'definition_version': definition['definition_version']}
        return section, record(definition, subject, quote, answer, basis, lane_from, decided_by, exact=exact)
    answer = choice['choice']
    lane_from = outcome(definition, 'the Choice returns')
    section.update(choice=choice, answer=answer, route=lane_from['route'], **{'pass': answer})
    basis = {'choice': choice['probabilities'], 'definition_version': definition['definition_version']}
    return section, record(definition, subject, quote, answer, basis, lane_from, decided_by, exact=exact)


def effort_decision(jev, definition, part, body, kind, persona, unaided, subject, quote, decided_by, stage,
                    harness, model, levels):
    """The printed effort section and its decision record. Asked whatever the act and persona decisions read, over
    `levels`, the levels the assigned harness offers the assigned model (R-39)."""
    named, resolving, size = named_inputs(body)
    _, write_set = split_write_set(body)
    facts = {'kind': kind or NONE_LABEL, 'persona': persona or NONE_LABEL, 'stage': stage,
             'words': len(body.split()), 'input_files_resolving': len(resolving), 'input_bytes': size,
             'write_set_paths': len(write_set) if write_set else NONE_LABEL, 'harness': harness, 'model': model}
    exact = dict(facts, levels_offered=list(levels))
    composition = definition['composition']['choice']
    criteria = dict((level, composition['criteria'][level]) for level in levels)
    question = {'type': 'choice', 'instructions': composition['instructions'], 'criteria': criteria}
    state = dict({'part': part}, **facts)
    section = {'unaided': unaided, 'facts': facts, 'levels_offered': list(levels), 'input_files_named': len(named),
               'choice': None, 'level': None}
    if not levels:
        answer = 'unrecorded (the assigned harness %s offers the assigned model %s no level this decision defines)' % (
            harness, model)
        lane_from = outcome(definition, 'the request fails')
        section.update(answer=answer, route=lane_from['route'], **{'pass': unaided})
        basis = {'choice': None, 'definition_version': definition['definition_version'],
                 'provisional': definition['provisional']}
        return section, record(definition, subject, quote, answer, basis, lane_from, decided_by, exact=exact)
    try:
        choice = jev.ask('%s choice' % definition['id'], state, 'effort', question)
    except JevFailure as failure:
        answer = 'unrecorded (%s)' % failure.reason
        lane_from = outcome(definition, 'the request fails')
        section.update(answer=answer, failure=failure.reason, route=lane_from['route'], **{'pass': unaided})
        basis = {'choice': None, 'definition_version': definition['definition_version'],
                 'provisional': definition['provisional']}
        return section, record(definition, subject, quote, answer, basis, lane_from, decided_by, exact=exact)
    answer = choice['choice']
    lane_from = outcome(definition, 'the Choice returns')
    section.update(choice=choice, level=answer, answer=answer, route=lane_from['route'], **{'pass': answer})
    basis = {'choice': choice['probabilities'], 'definition_version': definition['definition_version'],
             'provisional': definition['provisional']}
    return section, record(definition, subject, quote, answer, basis, lane_from, decided_by, exact=exact)


# ---------------------------------------------------------------------------
# The override
# ---------------------------------------------------------------------------

def effort_override(args, record, data):
    """The override entry for the effort decision, or the reason it is refused: a level the assigned harness does
    not offer the assigned model, where a record names the levels offered. The assigned model is the decision's,
    or, once the parent has overridden the model, the model passed (R-39): its levels are the ones the d7-model
    record gives it."""
    exact = record.get('exact_evidence') if isinstance(record.get('exact_evidence'), dict) else {}
    offered = exact.get('levels_offered')
    kept = data.get('overrides')
    passed = [entry.get('model_passed') for entry in (kept.get('value') if isinstance(kept, dict) else None) or []
              if isinstance(entry, dict) and entry.get('decision') == MODEL_DECISION]
    if passed:
        held = data.get('decision_records')
        models = [r for r in (held.get('value') if isinstance(held, dict) else None) or []
                  if isinstance(r, dict) and r.get('question') == MODEL_DECISION]
        model_exact = models[-1].get('exact_evidence') if models else None
        by_model = model_exact.get('levels_offered') if isinstance(model_exact, dict) else None
        offered = by_model.get(passed[-1]) if isinstance(by_model, dict) else None
        if not isinstance(offered, list):
            return None, 'the %s record gives no levels for %s, the model passed: the level cannot be checked' % (
                MODEL_DECISION, passed[-1])
    if isinstance(offered, list) and args.level not in offered:
        return None, 'the level %s is not one the assigned harness offers the assigned model: %s' % (
            args.level, ', '.join(offered) or 'none')
    return {'decision': args.decision, 'decision_level': record.get('answer'), 'level_passed': args.level,
            'reason': args.reason, 'at': stamp()}, None


def listed_override(args, record):
    """The override entry for the harness or model decision, or the reason it is refused: a value off the reachable
    list the record names (the parent's own where it names none), or the decision's own value."""
    what = 'harness' if args.decision == HARNESS_DECISION else 'model'
    value = args.harness if what == 'harness' else args.model
    exact = record.get('exact_evidence') if isinstance(record.get('exact_evidence'), dict) else {}
    reachable = list(exact.get('reachable') or []) or [exact.get('parent_%s' % what)]
    if value not in reachable:
        return None, 'the %s %r is not on the reachable list: %s' % (what, value, ', '.join(
            str(v) for v in reachable))
    if value == record.get('answer'):
        return None, '%s is the decision\'s own %s: there is nothing to override' % (value, what)
    return {'decision': args.decision, 'decision_%s' % what: record.get('answer'), '%s_passed' % what: value,
            'reason': args.reason, 'at': stamp()}, None


def persona_override(args, record):
    """The override entry for the persona decision, or the reason it is refused."""
    basis = record.get('uncertainty_basis') if isinstance(record.get('uncertainty_basis'), dict) else {}
    probability = basis.get('adequacy')
    if probability != MAP_CHOSEN and (isinstance(probability, bool) or not isinstance(probability, (int, float))):
        return None, ('the %s record carries no adequacy probability: the decision chose no persona to override '
                      '(its answer: %s)' % (args.decision, record.get('answer')))
    exact = record.get('exact_evidence') if isinstance(record.get('exact_evidence'), dict) else {}
    excluded = exact.get('excluded') if isinstance(exact.get('excluded'), dict) else {}
    roster = list(exact.get('eligible') or []) + list(excluded)
    if args.persona not in roster:
        return None, 'unknown persona %r: the roster lists %s' % (args.persona, ', '.join(roster) or 'no persona')
    answer = record.get('answer')
    persona = answer[:-len(BELOW_LINE)] if isinstance(answer, str) and answer.endswith(BELOW_LINE) else answer
    if args.persona == persona:
        return None, '%s is the decision\'s own persona: there is nothing to override' % args.persona
    if not (args.parent_persona or '').strip():
        return None, 'the parent\'s own persona is empty'
    return {'decision': args.decision, 'decision_persona': persona, 'adequacy_probability': probability,
            'parent_persona': args.parent_persona, 'persona_chosen': args.persona, 'reason': args.reason,
            'at': stamp()}, None


def no_persona_override(args, record):
    """The override entry for a dispatch with no persona. `record` is the file's d3-figure record, or None."""
    if record is None:
        persona = 'unrecorded (the pending file holds no %s record)' % PERSONA_DECISION
    else:
        answer = record.get('answer')
        basis = record.get('uncertainty_basis') if isinstance(record.get('uncertainty_basis'), dict) else {}
        named = isinstance(answer, str) and answer and (basis.get('adequacy') == MAP_CHOSEN or (
            isinstance(basis.get('adequacy'), (int, float)) and not isinstance(basis.get('adequacy'), bool)))
        persona = (answer[:-len(BELOW_LINE)] if answer.endswith(BELOW_LINE) else answer) if named else \
            'unrecorded (the %s record named no persona: %s)' % (PERSONA_DECISION, answer)
    return {'decision': NO_PERSONA, 'decision_persona': persona, 'reason': args.reason, 'at': stamp()}, None


def no_persona_path(args):
    """(the pending file to write, whether it may be created, or the refusal)."""
    if args.pending:
        path = Path(args.pending)
        if not path.is_file():
            return None, False, 'the pending file %s does not exist: name the member with --ledger, --session and ' \
                                '--member instead, and the file is written' % path
        return path, False, None
    if not (args.ledger and args.session and args.member):
        return None, False, 'an override of %s names --pending <file>, or the member\'s --ledger, --session and ' \
                            '--member' % NO_PERSONA
    try:
        ledger_scripts()
        import ledger
    except CannotRun as exc:
        return None, False, str(exc)
    folder = Path(args.ledger) / '.pending' / ledger.pending_name(args.session)
    name = '%s.json' % ledger.pending_name('triage-%s-%s' % (args.member, args.attempt))
    return folder / name, True, None


def override(argv):
    parser = argparse.ArgumentParser(prog='decide.py override',
                                     description='Record a level, persona, harness or model the parent passes '
                                                 'instead of the decision\'s, or a dispatch with no persona.')
    parser.add_argument('--pending')
    parser.add_argument('--ledger')
    parser.add_argument('--session')
    parser.add_argument('--member')
    parser.add_argument('--attempt', default='1')
    parser.add_argument('--decision', required=True)
    parser.add_argument('--level')
    parser.add_argument('--persona')
    parser.add_argument('--parent-persona')
    parser.add_argument('--harness')
    parser.add_argument('--model')
    parser.add_argument('--reason', required=True)
    try:
        args = parser.parse_args(argv)
    except SystemExit:
        return fail(1, 'the arguments could not be read')
    takes = (PERSONA_DECISION, EFFORT_DECISION, HARNESS_DECISION, MODEL_DECISION, NO_PERSONA)
    if args.decision not in takes:
        return fail(1, 'only %s take an override here, not %s' % (', '.join(takes), args.decision))
    if args.decision == EFFORT_DECISION and args.level not in LEVELS:
        return fail(1, 'unknown level %r: the levels are %s' % (args.level, ', '.join(LEVELS)))
    if args.decision == PERSONA_DECISION and not args.persona:
        return fail(1, 'an override of %s names the persona chosen instead, with --persona' % PERSONA_DECISION)
    for decision, value, option in ((HARNESS_DECISION, args.harness, '--harness'),
                                    (MODEL_DECISION, args.model, '--model')):
        if args.decision == decision and not (value or '').strip():
            return fail(1, 'an override of %s names the value passed instead, with %s' % (decision, option))
    if not args.reason.strip():
        return fail(1, 'the reason is empty')
    if args.decision == NO_PERSONA:
        path, creatable, refusal = no_persona_path(args)
        if refusal:
            return fail(1, refusal)
    elif not args.pending:
        return fail(1, 'an override of %s names its pending file, with --pending' % args.decision)
    else:
        path, creatable = Path(args.pending), False
    if creatable and not path.exists():
        data = {}
    else:
        try:
            data = json.loads(path.read_text(encoding='utf-8'))
        except (OSError, ValueError) as exc:
            return fail(1, 'the pending file could not be read: %s' % exc)
        if not isinstance(data, dict):
            return fail(1, 'the pending file holds no JSON object: %s' % path)
    held = data.get('decision_records')
    records = held.get('value') if isinstance(held, dict) else None
    question = PERSONA_DECISION if args.decision == NO_PERSONA else args.decision
    found = [r for r in records or [] if isinstance(r, dict) and r.get('question') == question]
    if args.decision == NO_PERSONA:
        entry, refusal = no_persona_override(args, found[-1] if found else None)
    elif not found:
        return fail(1, 'the pending file holds no %s record: %s' % (args.decision, path))
    else:
        make = {EFFORT_DECISION: lambda a, r: effort_override(a, r, data), PERSONA_DECISION: persona_override,
                HARNESS_DECISION: listed_override, MODEL_DECISION: listed_override}[args.decision]
        entry, refusal = make(args, found[-1])
    if refusal:
        return fail(1, refusal)
    kept = data.get('overrides')
    entries = list(kept['value']) if isinstance(kept, dict) and isinstance(kept.get('value'), list) else []
    entries.append(entry)
    data['overrides'] = stamped(entries)
    if args.decision == PERSONA_DECISION:
        data['triage_persona'] = stamped(args.persona)
        data['chosen_by'] = stamped(OVERRIDE_CHOSEN_BY)
    elif args.decision == NO_PERSONA:
        data.pop('triage_persona', None)
        data['chosen_by'] = stamped(OVERRIDE_CHOSEN_BY)
    elif args.decision == HARNESS_DECISION:
        data['harness_assigned'] = stamped(args.harness)
    path.parent.mkdir(parents=True, exist_ok=True)
    written = path.with_name(path.name + '.writing')
    written.write_text(json.dumps(data, indent=1, ensure_ascii=False) + '\n', encoding='utf-8')
    os.replace(str(written), str(path))
    print(json.dumps({'pending_file': str(path), 'override': entry}, indent=1, ensure_ascii=False))
    return 0


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def key_from_zsh():
    """Set JEV_API_KEY, where it is not set, to the value zsh gives it on starting; never prints the key."""
    if os.environ.get(KEY_VARIABLE):
        return
    zsh = shutil.which('zsh') or ('/bin/zsh' if os.path.exists('/bin/zsh') else None)
    if not zsh:
        return
    try:
        done = subprocess.run([zsh, '-c', 'printf %%s "$%s"' % KEY_VARIABLE], capture_output=True, text=True,
                              stdin=subprocess.DEVNULL, timeout=20)
    except (OSError, subprocess.SubprocessError):
        return
    value = done.stdout.strip()
    if done.returncode == 0 and value:
        os.environ[KEY_VARIABLE] = value


def parse(argv):
    parser = argparse.ArgumentParser(description='Ask the act, form, persona, harness, model and effort decisions '
                                                 'for one part.')
    parser.add_argument('--delegation', required=True)
    parser.add_argument('--roster', required=True)
    parser.add_argument('--ledger', required=True)
    parser.add_argument('--session', required=True)
    parser.add_argument('--member', required=True)
    parser.add_argument('--effort-unaided', required=True, choices=LEVELS)
    parser.add_argument('--attempt', default='1')
    parser.add_argument('--pending-ledger')
    parser.add_argument('--key-from-zsh', action='store_true')
    parser.add_argument('--rows-key', default='rows')
    parser.add_argument('--name-key', default='name')
    parser.add_argument('--group-key', default='group')
    parser.add_argument('--file-key', default='file')
    parser.add_argument('--goal-key', default='declaration.goal')
    parser.add_argument('--does-key', default='declaration.does')
    parser.add_argument('--ratified-key', default='declaration-ratified')
    parser.add_argument('--file-root')
    parser.add_argument('--user', action='append')
    parser.add_argument('--work-call')
    parser.add_argument('--forms')
    parser.add_argument('--forms-key', default='builders')
    parser.add_argument('--reachable')
    parser.add_argument('--reachable-key', default='harnesses')
    parser.add_argument('--parent-harness')
    parser.add_argument('--parent-model')
    parser.add_argument('--register')
    parser.add_argument('--register-rows-key', default='rows')
    parser.add_argument('--unit-key', default='unit')
    parser.add_argument('--custodian-key', default='custodian')
    parser.add_argument('--parent-persona')
    import stage
    stage.add_arguments(parser)
    return parser.parse_args(argv)


def fail(code, text):
    print(json.dumps({'error': text}, ensure_ascii=False))
    return code


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    if argv[:1] == ['override']:
        return override(argv[1:])
    try:
        args = parse(argv)
    except SystemExit:
        return fail(1, 'the arguments could not be read')
    delegation = Path(args.delegation)
    try:
        text = delegation.read_text(encoding='utf-8')
    except OSError as exc:
        return fail(1, 'the delegation could not be read: %s' % exc)
    part = body_of(text)
    body = full_body(text)
    if not part:
        return fail(1, 'the delegation is empty')
    try:
        scripts = ledger_scripts()
        import ledger
        kinds = [(k['name'], k['test']) for k in read_json(scripts / 'kinds.json')['kinds']]
        d1 = read_json(DECISIONS / 'd1-act.json')
        d3 = read_json(DECISIONS / 'd3-figure.json')
        d4 = read_json(DECISIONS / 'd4-effort.json')
        d5 = read_json(DECISIONS / 'd5-form.json')
        d6 = read_json(DECISIONS / 'd6-harness.json')
        d7 = read_json(DECISIONS / 'd7-model.json')
        eligible, excluded, rows, units, groups = read_roster(args, body)
        harnesses = read_reachable(args)
    except CannotRun as exc:
        return fail(2, str(exc))
    except Exception as exc:
        return fail(2, '%s: %s' % (type(exc).__name__, exc))
    if args.key_from_zsh:
        key_from_zsh()

    commit = git_commit(delegation)
    digest = hashlib.sha256(text.encode('utf-8')).hexdigest()[:12]
    subject = 'member %s, attempt %s: %s@%s' % (args.member, args.attempt, delegation.resolve(),
                                                commit or 'sha256:%s' % digest)
    quote = part if '\n' not in part else None
    model = d1['engine']['model']
    decided_by = '%s at %s' % (d1['engine']['name'], model)
    jev = Jev(args.ledger, args.session, model)

    # The unaided level is stamped before Jev is asked anything, so its stamp precedes the effort decision's.
    pending = {'effort_unaided': stamped(args.effort_unaided)}
    import stage
    try:
        reading = stage.from_arguments(args)
    except CannotRun as exc:
        return fail(2, str(exc))
    act, act_record = act_decision(jev, d1, kinds, part, subject, quote, decided_by)
    records = [act_record]
    failures = []
    if act.get('failure'):
        failures.append('act decision: %s' % act['failure'])

    def engine(definition):
        return '%s at %s' % (definition['engine']['name'], definition['engine']['model'])

    kind = act['kind']
    read_as = '%s, read as %s' % (subject, kind)
    form = None
    if kind == MAKING_KIND:
        form, form_record = form_decision(jev, d5, part, read_as, quote, engine(d5))
        records.append(form_record)
        if form.get('failure'):
            failures.append('form decision: %s' % form['failure'])
    split = act['split'] or bool(form and form['split'])
    persona = None
    if kind and not split:
        pending['kind'] = stamped(kind)
        candidates, ruled_out, extra, finding, builder = eligible, excluded, {}, None, None
        if kind == REVIEW_KIND:
            candidates, ruled_out, extra, finding = review_rule(args, eligible, excluded, groups)
        if form and form['form'] in FORMS:
            extra['form'] = form['form']
            if finding is None:
                builder, finding = form_builder(args, form['form'])
        persona, persona_record = persona_decision(jev, d3, part, kind, candidates, ruled_out, rows, read_as, quote,
                                                   engine(d3), reading['stage'], units, extra=extra,
                                                   builder=builder, finding=finding)
        records.append(persona_record)
        if persona.get('failure'):
            failures.append('persona decision: %s' % persona['failure'])
        if persona['persona']:
            pending['triage_persona'] = stamped(persona['persona'])
            pending['persona_facts'] = stamped({'persona': persona['persona'], 'goal': persona['goal'],
                                                'does': persona['does'], 'eligible': persona['eligible'],
                                                'choice': persona['choice'] and persona['choice']['probabilities'],
                                                'adequacy': persona['adequacy'], 'stage': reading['stage'],
                                                'form': form and form['form']})
            pending['chosen_by'] = stamped(CHOSEN_BY)
            if persona['below_line']:
                pending['below_line'] = stamped({'probability': persona['adequacy'], 'line': persona['line'],
                                                 'line_version': persona['line_version']})
    chosen = persona and persona['persona']

    # The harness, then the model it offers, each from the reachable list (R-39): after the persona, before the
    # effort. Where the list names none, or a decision gives none, the parent's own is passed.
    parent_harness = (args.parent_harness or '').strip() or calling_harness()
    parent_model = (args.parent_model or '').strip() or 'unrecorded (no --parent-model was given)'
    state = {'part': part, 'kind': kind or NONE_LABEL, 'persona': chosen or NONE_LABEL}
    harness, harness_record = listed_decision(jev, d6, 'harness', harnesses, parent_harness, state, subject, quote,
                                              engine(d6), 'the settings list no reachable harness')
    records.append(harness_record)
    if harness.get('failure'):
        failures.append('harness decision: %s' % harness['failure'])
    models = models_of(harnesses, harness['pass'])
    model, model_record = listed_decision(jev, d7, 'model', models, parent_model,
                                          dict(state, harness=harness['pass']), subject, quote, engine(d7),
                                          'the settings list no model for the harness %s' % harness['pass'],
                                          levels=dict((m['name'], levels_for(harnesses, harness['pass'], m['name']))
                                                      for m in models))
    records.append(model_record)
    if model.get('failure'):
        failures.append('model decision: %s' % model['failure'])
    levels = levels_for(harnesses, harness['pass'], model['pass'])
    effort, effort_record = effort_decision(jev, d4, part, body, kind, chosen, args.effort_unaided, subject, quote,
                                            engine(d4), reading['stage'], harness['pass'], model['pass'], levels)
    records.append(effort_record)
    if effort.get('failure'):
        failures.append('effort decision: %s' % effort['failure'])
    pending['harness_assigned'] = stamped(harness['pass'])
    pending['sender'] = stamped(sender_of(args.parent_persona))
    pending['decision_records'] = stamped(records)
    if failures:
        pending['triage_failure'] = stamped('; '.join(failures))

    # A part the act decision read as none is never dispatched: a pending file for it would be listed at the close as
    # never dispatched. A part whose act request failed is not one of these; its file holds the failure.
    read_none = act['kind'] is None and not act.get('failure') and not act['split']
    path, skipped = None, None
    if read_none:
        skipped = 'none written: the act decision read the part as none, so it is not dispatched'
    elif split:
        why = 'the act decision read two or more kinds' if act['split'] else 'the form decision read both forms'
        skipped = 'none written: the part is to be split (%s), so it is not dispatched; split it and triage each ' \
                  'part' % why
    else:
        folder = Path(args.pending_ledger or args.ledger) / '.pending' / ledger.pending_name(args.session)
        folder.mkdir(parents=True, exist_ok=True)
        path = folder / ('%s.json' % ledger.pending_name('triage-%s-%s' % (args.member, args.attempt)))
        path.write_text(json.dumps(pending, indent=1, ensure_ascii=False) + '\n', encoding='utf-8')

    shown = {'delegation': str(delegation.resolve()), 'session': args.session, 'member': args.member,
             'attempt': args.attempt, 'sender': pending['sender']['value'], 'effort_unaided': pending['effort_unaided'],
             'stage': reading, 'act': act, 'form': form, 'persona': persona, 'harness': harness, 'model': model,
             'effort': effort, 'decision_records': records, 'jev_calls': jev.calls,
             'pending_file': str(path) if path else None}
    if skipped:
        shown['no_pending_file'] = skipped
    print(json.dumps(shown, indent=1, ensure_ascii=False))
    return 3 if failures else 0


if __name__ == '__main__':
    sys.exit(main())
