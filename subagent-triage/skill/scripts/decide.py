#!/usr/bin/env python3
"""Ask Jev the act, persona and effort decisions for one part of a delegation, and write its pending triage file.

    python3 decide.py --delegation <file> --roster <file> --ledger <folder> --session <id> --member <id>
                      --effort-unaided <level> [--attempt 1] [--pending-ledger <folder>] [--key-from-zsh]
                      [--rows-key rows] [--name-key name] [--group-key group] [--file-key file]
                      [--goal-key declaration.goal] [--ratified-key declaration-ratified]
                      [--file-root <folder>] [--user <name> ...]
                      [--task <id>] [--build-root <folder> ...] [--ratified-root <folder> ...]
                      [--task-key task_id] [--status-key status]
                      [--kind-groups <file>] [--kind-groups-key pairs]

The act decision (decisions/d1-act.json). Each of the eight kinds in the ledger skill's kinds.json is asked as a
Noul, one request each, with the definition's instructions and the kind's test as its criterion. Their lines are
unset, so each probability is printed and no line is applied. The provisional Choice over the eight kinds and `none`,
each criterion the kind's test, gives the answer.

The persona decision (decisions/d3-figure.json), asked only when the act decision read one kind. Eligibility is
exact: a persona is a row of the roster whose file exists and whose frontmatter carries a non-empty value at the
ratified key, and whose name is not one given by --user. The roster is a YAML or JSON file; the --*-key options name
where its rows and their fields are, so the script reads any roster without knowing its workspace. With no eligible
persona, the answer is `none adequate` with the rule that emptied the set, and Jev is not asked. Otherwise one Choice
over the eligible personas, each criterion `<persona>, in <group>: <goal>`, with the part, its kind and the task's
stage as state, then the adequacy Noul on the persona it ranks first, against the definition's line.

The task's stage is read by stage.py, from the task --task names and the folders --build-root and --ratified-root
name, before any decision is asked. It is a fact of the persona decision (its state, its exact evidence and the pending
file's persona facts) and of the effort decision.

The effort decision (decisions/d4-effort.json), asked after the other two whatever they read. The parent's unaided
level, --effort-unaided, is stamped from the clock before Jev is asked anything. One Choice over the levels the Agent
tool offers (low, medium, high, xhigh, max), with the part and these exact facts as state: the kind (or `none`), the
persona (or `none`), the stage as stage.py read it, the delegation's length in words, how many of
the absolute paths it names outside its write set are files and their total size in bytes, and the number of paths
in its `## Write set` (or `none`). Where the request fails, the level reads `unrecorded (<reason>)` and the output
says to pass the unaided level.

Each Jev request is recorded as its own dispatch and return through the ledger skill's ledger.py, in the ledger
folder --ledger names, under --session. The part's text goes to Jev only; no record holds it. A retry on HTTP 429 or
5xx is a request of its own with its own pair.

The group the part's kind is paired with (`kind_paired_grouping`) is read, once the act decision reads one kind, from
the table --kind-groups names: a JSON or YAML file whose object at --kind-groups-key (a dotted path, `pairs` by
default) maps each kind to its group. It is a fact for the pending file, never the record's own grouping. With no
table given, a table that cannot be read or holds no object at the key, a kind the table lacks, or no kind read, the
value reads `unrecorded (<reason>)` and the triage goes on: the value is never guessed.

The pending triage file is <pending-ledger>/.pending/<session>/triage-<member>-<attempt>.json, in the ledger's
pending.schema.json shape, each value stamped from the clock when it is decided. --pending-ledger defaults to
--ledger. Where the act decision reads the part as none, no pending file is written, since the part is not dispatched:
the output's `pending_file` is null and `no_pending_file` says why. A part whose act request failed still has its file,
holding the failure.

Output: one JSON object on standard output. Exit codes: 0 answered; 1 refused on its input; 2 cannot run (the ledger
scripts, kinds.json or a decision file not found, or the roster unreadable); 3 a decision's request to Jev failed (the
output and the pending file record the failure).

The override, when the parent passes a level other than the effort decision's:

    python3 decide.py override --pending <file> --decision d4-effort --level <level> --reason <text>

It appends to the pending file's `overrides` list the decision's level (read from the file's own d4-effort record),
the level passed instead, the reason and the time, and restamps the list. It refuses, with exit 1 and the file
unchanged, a file with no d4-effort record, an unknown level, an empty reason or another decision.

The override, when the parent sends the part to a persona other than the persona decision's:

    python3 decide.py override --pending <file> --decision d3-figure --persona <name> --parent-persona <name>
                               --reason <text>

It appends to the `overrides` list the six values an override of the persona records, the first two read from the
file's own d3-figure record: the decision's persona (`decision_persona`, its answer less any below-the-line mark),
its adequacy probability (`adequacy_probability`), the parent's own persona (`parent_persona`), the persona chosen
instead (`persona_chosen`), the reason and the time. It sets `triage_persona` to the persona chosen and `chosen_by`
to the dispatching agent, each restamped; the decision's record is left as it was. It refuses, with exit 1 and the
file unchanged, a file with no d3-figure record, a record with no adequacy probability (the decision chose no persona
to override), a persona the roster does not list (the record's eligible and excluded names: an unknown name is
refused, never matched), the decision's own persona, an empty parent persona and an empty reason.

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
NO_PERSONA = 'no-persona'  # R-11: the parent's dispatch with no persona, recorded as an override
BELOW_LINE = ', below the line'
ABSOLUTE_PATH = re.compile(r'(?:(?<=[\s`\'"(<\[])|^)(~?/[^\s`\'"<>()\[\]{}]+|[A-Za-z]:[\\/][^\s`\'"<>()\[\]{}]+)',
                           re.MULTILINE)


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


def kind_paired_group(path, key, kind):
    """The group the table at `path` pairs with `kind`, or `unrecorded (<reason>)`. Never raises, never guesses."""
    if not kind:
        return 'unrecorded (the act decision read no kind)'
    if not path:
        return 'unrecorded (no kind-to-group table was given)'
    try:
        data = read_structured(path)
    except (OSError, ValueError, CannotRun) as exc:
        return 'unrecorded (the kind-to-group table %s could not be read: %s)' % (path, exc)
    except Exception as exc:
        return 'unrecorded (the kind-to-group table %s could not be read: %s: %s)' % (path, type(exc).__name__, exc)
    pairs = dig(data, key)
    if not isinstance(pairs, dict):
        return 'unrecorded (the kind-to-group table %s holds no pairs at %r)' % (path, key)
    group = pairs.get(kind)
    if not isinstance(group, str) or not group.strip():
        return 'unrecorded (the kind-to-group table %s pairs no group with %s)' % (path, kind)
    return group


def stamp():
    return datetime.datetime.now(datetime.timezone.utc).strftime('%Y-%m-%dT%H:%M:%S.%fZ')


def stamped(value):
    return {'value': value, 'stamped_at': stamp()}


# ---------------------------------------------------------------------------
# The roster
# ---------------------------------------------------------------------------

def read_roster(args):
    """(eligible, excluded): eligible as [{name, group, goal, file}] in roster order; excluded as {name: rule}."""
    data = read_structured(args.roster)
    rows = data if isinstance(data, list) else dig(data, args.rows_key) if isinstance(data, dict) else None
    if rows is None:
        rows = []
    if not isinstance(rows, list):
        raise CannotRun('the roster\'s %r is not a list' % args.rows_key)
    root = Path(args.file_root) if args.file_root else Path(args.roster).resolve().parent
    users = set(args.user or [])
    eligible, excluded = [], {}
    for row in rows:
        name = dig(row, args.name_key) if isinstance(row, dict) else None
        if not isinstance(name, str) or not name:
            continue
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
        group = dig(row, args.group_key)
        eligible.append({'name': name, 'group': group if isinstance(group, str) and group else 'unrecorded (no group)',
                         'goal': ' '.join(goal.split()), 'file': str(path)})
    return eligible, excluded, len(rows)


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
    choice_question = {'type': 'choice', 'instructions': reading['instructions'], 'criteria': criteria}
    section = {'nouls': nouls, 'noul_failures': failures, 'lines': None if all(v is None for v in lines.values())
               else lines, 'line_applied': False, 'provisional': definition['provisional']}
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
    else:
        answer = read
        kind = read
        lane_from = outcome(definition, 'user-decision' if read == 'user-decision' else 'exactly one')
    section.update(choice=choice, kind=kind, answer=answer)
    basis = {'nouls': nouls, 'lines': lines, 'line_applied': False,
             'choice': choice['probabilities'], 'provisional': 'the Choice gives the answer while any line is unset',
             'definition_version': definition['definition_version']}
    return section, record(definition, subject, quote, answer, basis, lane_from, decided_by)


def persona_decision(jev, definition, part, kind, eligible, excluded, rows, subject, quote, decided_by, stage):
    composition = definition['composition']
    line = composition['adequacy']['line']
    line_version = composition['adequacy']['line_version']
    exact = {'eligible': [p['name'] for p in eligible], 'excluded': excluded, 'roster_rows': rows, 'kind': kind,
             'stage': stage}
    section = {'eligible': exact['eligible'], 'excluded': excluded, 'line': line, 'line_version': line_version,
               'choice': None, 'persona': None, 'adequacy': None, 'below_line': None}
    if not eligible:
        rules = sorted(set(excluded.values())) or ['the roster lists no persona']
        answer = 'none adequate (%s)' % '; '.join(rules)
        section['answer'] = answer
        basis = {'requests': 'none: no persona is eligible', 'line': line, 'line_version': line_version}
        return section, record(definition, subject, quote, answer, basis, outcome(definition, 'no persona'),
                               decided_by, exact=exact)
    state = {'part': part, 'kind': kind, 'stage': stage}
    template = composition['choice']['criterion_template']
    criteria = dict((p['name'], template.format(persona=p['name'], group=p['group'], goal=p['goal'])) for p in eligible)
    question = {'type': 'choice', 'instructions': composition['choice']['instructions'], 'criteria': criteria}
    try:
        choice = jev.ask('d3-figure choice', state, 'persona', question)
        probabilities = choice['probabilities']
        first = max(eligible, key=lambda p: probabilities[p['name']])
        section['choice'] = choice
        adequacy_q = {'type': 'noul', 'instructions': composition['adequacy']['instructions'],
                      'criteria': {'true': composition['adequacy']['instructions'].rsplit('. ', 1)[-1]}}
        adequacy = jev.ask('d3-figure adequacy %s' % first['name'], {
            'part': part, 'persona': first['name'], 'group': first['group'], 'goal': first['goal']},
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
    section.update(persona=first['name'], group=first['group'], goal=first['goal'], adequacy=adequacy,
                   below_line=below, answer=answer)
    basis = {'choice': probabilities, 'adequacy': adequacy, 'line': line, 'line_version': line_version}
    return section, record(definition, subject, quote, answer, basis, lane_from, decided_by, exact=exact)


def effort_decision(jev, definition, part, body, kind, persona, unaided, subject, quote, decided_by, stage):
    """The printed effort section and its decision record. Asked whatever the act and persona decisions read."""
    named, resolving, size = named_inputs(body)
    _, write_set = split_write_set(body)
    facts = {'kind': kind or NONE_LABEL, 'persona': persona or NONE_LABEL, 'stage': stage,
             'words': len(body.split()), 'input_files_resolving': len(resolving), 'input_bytes': size,
             'write_set_paths': len(write_set) if write_set else NONE_LABEL}
    composition = definition['composition']['choice']
    criteria = dict((level, composition['criteria'][level]) for level in LEVELS)
    question = {'type': 'choice', 'instructions': composition['instructions'], 'criteria': criteria}
    state = dict({'part': part}, **facts)
    section = {'unaided': unaided, 'facts': facts, 'input_files_named': len(named), 'choice': None, 'level': None}
    try:
        choice = jev.ask('%s choice' % definition['id'], state, 'effort', question)
    except JevFailure as failure:
        answer = 'unrecorded (%s)' % failure.reason
        lane_from = outcome(definition, 'the request fails')
        section.update(answer=answer, failure=failure.reason, route=lane_from['route'], **{'pass': unaided})
        basis = {'choice': None, 'definition_version': definition['definition_version'],
                 'provisional': definition['provisional']}
        return section, record(definition, subject, quote, answer, basis, lane_from, decided_by, exact=facts)
    answer = choice['choice']
    lane_from = outcome(definition, 'the Choice returns')
    section.update(choice=choice, level=answer, answer=answer, route=lane_from['route'], **{'pass': answer})
    basis = {'choice': choice['probabilities'], 'definition_version': definition['definition_version'],
             'provisional': definition['provisional']}
    return section, record(definition, subject, quote, answer, basis, lane_from, decided_by, exact=facts)


# ---------------------------------------------------------------------------
# The override
# ---------------------------------------------------------------------------

def effort_override(args, record):
    """The override entry for the effort decision; its level is checked before the file is read."""
    return {'decision': args.decision, 'decision_level': record.get('answer'), 'level_passed': args.level,
            'reason': args.reason, 'at': stamp()}, None


def persona_override(args, record):
    """The override entry for the persona decision, or the reason it is refused."""
    basis = record.get('uncertainty_basis') if isinstance(record.get('uncertainty_basis'), dict) else {}
    probability = basis.get('adequacy')
    if isinstance(probability, bool) or not isinstance(probability, (int, float)):
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
        named = isinstance(answer, str) and answer and isinstance(basis.get('adequacy'), (int, float)) \
            and not isinstance(basis.get('adequacy'), bool)
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
                                     description='Record a level or persona the parent passes instead of the '
                                                 'decision\'s, or a dispatch with no persona.')
    parser.add_argument('--pending')
    parser.add_argument('--ledger')
    parser.add_argument('--session')
    parser.add_argument('--member')
    parser.add_argument('--attempt', default='1')
    parser.add_argument('--decision', required=True)
    parser.add_argument('--level')
    parser.add_argument('--persona')
    parser.add_argument('--parent-persona')
    parser.add_argument('--reason', required=True)
    try:
        args = parser.parse_args(argv)
    except SystemExit:
        return fail(1, 'the arguments could not be read')
    if args.decision not in (PERSONA_DECISION, EFFORT_DECISION, NO_PERSONA):
        return fail(1, 'only %s, %s and %s take an override here, not %s' % (PERSONA_DECISION, EFFORT_DECISION,
                                                                              NO_PERSONA, args.decision))
    if args.decision == EFFORT_DECISION and args.level not in LEVELS:
        return fail(1, 'unknown level %r: the levels are %s' % (args.level, ', '.join(LEVELS)))
    if args.decision == PERSONA_DECISION and not args.persona:
        return fail(1, 'an override of %s names the persona chosen instead, with --persona' % PERSONA_DECISION)
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
        make = effort_override if args.decision == EFFORT_DECISION else persona_override
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
    parser = argparse.ArgumentParser(description='Ask the act, persona and effort decisions for one part.')
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
    parser.add_argument('--ratified-key', default='declaration-ratified')
    parser.add_argument('--file-root')
    parser.add_argument('--user', action='append')
    parser.add_argument('--kind-groups')
    parser.add_argument('--kind-groups-key', default='pairs')
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
        eligible, excluded, rows = read_roster(args)
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
    if act['kind']:
        pending['kind'] = stamped(act['kind'])
        persona, persona_record = persona_decision(jev, d3, part, act['kind'], eligible, excluded, rows,
                                                   '%s, read as %s' % (subject, act['kind']), quote,
                                                   '%s at %s' % (d3['engine']['name'], d3['engine']['model']),
                                                   reading['stage'])
        records.append(persona_record)
        if persona.get('failure'):
            failures.append('persona decision: %s' % persona['failure'])
        if persona['persona']:
            pending['triage_persona'] = stamped(persona['persona'])
            pending['persona_facts'] = stamped({'persona': persona['persona'], 'group': persona['group'],
                                                'goal': persona['goal'], 'eligible': persona['eligible'],
                                                'choice': persona['choice']['probabilities'],
                                                'adequacy': persona['adequacy'], 'stage': reading['stage']})
            pending['chosen_by'] = stamped(CHOSEN_BY)
            if persona['below_line']:
                pending['below_line'] = stamped({'probability': persona['adequacy'], 'line': persona['line'],
                                                 'line_version': persona['line_version']})
    else:
        persona = None
    paired = kind_paired_group(args.kind_groups, args.kind_groups_key, act['kind'])
    pending['kind_paired_grouping'] = stamped(paired)
    effort, effort_record = effort_decision(jev, d4, part, body, act['kind'], persona and persona['persona'],
                                            args.effort_unaided, subject, quote,
                                            '%s at %s' % (d4['engine']['name'], d4['engine']['model']),
                                            reading['stage'])
    records.append(effort_record)
    if effort.get('failure'):
        failures.append('effort decision: %s' % effort['failure'])
    pending['decision_records'] = stamped(records)
    if failures:
        pending['triage_failure'] = stamped('; '.join(failures))

    # A part the act decision read as none is never dispatched: a pending file for it would be listed at the close as
    # never dispatched. A part whose act request failed is not one of these; its file holds the failure.
    read_none = act['kind'] is None and not act.get('failure')
    path, skipped = None, None
    if read_none:
        skipped = 'none written: the act decision read the part as none, so it is not dispatched'
    else:
        folder = Path(args.pending_ledger or args.ledger) / '.pending' / ledger.pending_name(args.session)
        folder.mkdir(parents=True, exist_ok=True)
        path = folder / ('%s.json' % ledger.pending_name('triage-%s-%s' % (args.member, args.attempt)))
        path.write_text(json.dumps(pending, indent=1, ensure_ascii=False) + '\n', encoding='utf-8')

    shown = {'delegation': str(delegation.resolve()), 'session': args.session, 'member': args.member,
             'attempt': args.attempt, 'effort_unaided': pending['effort_unaided'], 'stage': reading, 'act': act,
             'persona': persona, 'kind_paired_grouping': paired, 'effort': effort, 'decision_records': records,
             'jev_calls': jev.calls, 'pending_file': str(path) if path else None}
    if skipped:
        shown['no_pending_file'] = skipped
    print(json.dumps(shown, indent=1, ensure_ascii=False))
    return 3 if failures else 0


if __name__ == '__main__':
    sys.exit(main())
