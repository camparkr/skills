#!/usr/bin/env python3
"""What the four checks read about one member's call, gathered once per hook run.

return_check.py builds a Call from the hook's payload (a hand-back's PreToolUse, or a SubagentStop) and hands it to
each check. Nothing here judges the member; it only reads:

  * the key: the agent id from the payload, the dispatch's call id from the agent's meta file beside its transcript
    (`toolUseId`), and the member and attempt from the brief, found by the ledger capture's own rule (the first
    readable file the prompt names) and read with the capture's own reader;
  * the report the parent receives: at a hand-back, its message; at a stop, the last delivered hand-back's message
    where the transcript shows one, otherwise the final message. A hand-back member (the payload's `permission_mode`
    is `auto`) that stops with no delivered hand-back has no report at that stop: the result names the final message
    and its SHA-256, and check 1 does not apply there;
  * the member's transcript: every Write, Edit and NotebookEdit call, each tool-use id once, with whether its result
    is an error, and whether the member is shell-using (a call to Bash, Agent or Task);
  * the ledger: the session's records, whether a session-start witness line is among them, and the dispatch record
    that carries this member and attempt (or, for a call with no member brief, the dispatch's call id);
  * for a writer, its worktree's root and its changes against the baseline on the dispatch record, committed or not;
  * the settings: config.json's `return_check` object in the ledger folder.

Each reading that fails is kept as a problem with its reason, never raised, so each check can say why it could not run.

The ledger skill's scripts are found at $SUBAGENT_LEDGER_SCRIPTS, which the wrapper sets, or beside this skill in the
same repository. Standard library only, besides those scripts.
"""

import datetime
import hashlib
import json
import os
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
SETTINGS_KEY = 'return_check'
HANDBACK_MODE = 'auto'
WRITE_TOOLS = {'Write': 'file_path', 'Edit': 'file_path', 'NotebookEdit': 'notebook_path'}
SHELL_USING_TOOLS = ('Bash', 'Agent', 'Task')
SESSION_START = 'SessionStart'
HANDBACK_REPORT = 'hand-back message'
FINAL_REPORT = 'final message'
GIT_SECONDS = 20


def ledger_scripts():
    """The ledger skill's scripts folder, put on the import path."""
    named = os.environ.get('SUBAGENT_LEDGER_SCRIPTS')
    folder = Path(named) if named else HERE.parents[2] / 'subagent-ledger' / 'skill' / 'scripts'
    if str(folder) not in sys.path:
        sys.path.insert(0, str(folder))
    return folder


ledger_scripts()
import capture_claude_code as capture  # noqa: E402
import ledger  # noqa: E402
import transcripts  # noqa: E402


def real(value):
    """Whether `value` is a filled value: text that is not `unrecorded (...)`."""
    return isinstance(value, str) and bool(value) and not value.startswith('unrecorded (')


def sha256(text):
    return hashlib.sha256(text.encode('utf-8')).hexdigest() if isinstance(text, str) else None


def one_line(text, limit=200):
    text = ' '.join(str(text).split())
    return text if len(text) <= limit else text[:limit - 3] + '...'


def parse_time(text):
    if not isinstance(text, str):
        return None
    try:
        return datetime.datetime.fromisoformat(text.replace('Z', '+00:00'))
    except ValueError:
        return None


def canonical(path, base=None):
    """The path with links and `..` resolved; a relative path is read against `base`."""
    path = Path(os.path.expanduser(str(path)))
    if not path.is_absolute() and base:
        path = Path(base) / path
    return os.path.realpath(str(path))


def inside(path, folder):
    """Whether the canonical `path` is `folder` or under it (both canonical)."""
    if not path or not folder:
        return False
    return path == folder or path.startswith(folder.rstrip(os.sep) + os.sep)


def git(root, *args):
    """(stdout, problem): a git command run in `root`, bounded."""
    try:
        done = subprocess.run(['git', '-C', str(root)] + list(args), capture_output=True, text=True,
                              timeout=GIT_SECONDS)
    except (OSError, subprocess.SubprocessError) as exc:
        return None, one_line(exc)
    if done.returncode != 0:
        return None, one_line(done.stderr or 'git exited %d' % done.returncode)
    return done.stdout, None


PASS, FAIL, NOT_APPLICABLE, NOT_CHECKABLE, LEDGER_ABSENT = (
    'pass', 'fail', 'not_applicable', 'not_checkable', 'ledger_absent')
RESULTS = (PASS, FAIL, NOT_APPLICABLE, NOT_CHECKABLE, LEDGER_ABSENT)


def result(check, name, value, reason=None, paths=None, repair=None):
    """One check's result: `result` is one of the closed set, `reason` the text in its brackets where it has one,
    `paths` the paths a fail names, `repair` the recommended repair a fail carries. return_check.py adds the id."""
    out = {'check': check, 'name': name, 'result': value, 'reason': reason}
    if paths:
        out['paths'] = list(paths)
    if value == FAIL:
        out['repair'] = repair
    return out


def shown(found):
    """A result as one line: `fail (no output section)`, `pass`."""
    reason = found.get('reason')
    return '%s (%s)' % (found['result'], reason) if reason else found['result']


def text_of(content):
    """The text of a transcript message's content: a string, or the text parts of a list."""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return '\n'.join(part.get('text') for part in content
                         if isinstance(part, dict) and part.get('type') == 'text' and isinstance(part.get('text'), str))
    return None


class Write(object):
    """One write call in the member's transcript."""

    def __init__(self, call_id, tool, path):
        self.call_id = call_id
        self.tool = tool
        self.path = path
        self.state = 'no result'  # `ok`, `error`, `no result` or `unreadable`


class Call(object):
    """One member's call, as the hook at `event` sees it. Build with Call.read(payload, folder)."""

    def __init__(self, event, payload, folder):
        self.event = event
        self.payload = payload
        self.folder = Path(folder) if folder else None
        self.session = payload.get('session_id') if isinstance(payload.get('session_id'), str) else None
        self.agent_id = payload.get('agent_id') if isinstance(payload.get('agent_id'), str) else None
        self.cwd = payload.get('cwd') if isinstance(payload.get('cwd'), str) else None
        self.settings = {}
        self.lane = None
        self.rows = None
        self.lane_problem = None
        self.dispatch_call_id = None
        self.prompt = None
        self.brief = None
        self.brief_source = None
        self.member = None
        self.attempt = None
        self.member_brief = False
        self.write_set = None
        self.writer = False
        self.report_name = None
        self.report_text = None
        self.report_applies = True
        self.report_problem = None
        self.writes = []
        self.shell_using = False
        self.records = None
        self.records_problem = None
        self.session_started = False
        self.dispatch = None
        self.root = None
        self.root_problem = None
        self._changes = None

    # -- building --------------------------------------------------------------------------------------------------

    @classmethod
    def read(cls, payload, folder):
        event = payload.get('hook_event_name')
        call = cls(event, payload, folder)
        call._read_settings()
        call._read_lane()
        call._read_brief()
        call._read_report()
        call._read_writes()
        call._read_ledger()
        call._read_root()
        return call

    def _read_settings(self):
        try:
            data = json.loads((self.folder / ledger.CONFIG_FILE).read_text(encoding='utf-8'))
            found = data.get(SETTINGS_KEY) if isinstance(data, dict) else None
            self.settings = found if isinstance(found, dict) else {}
        except (OSError, ValueError, TypeError, AttributeError):
            self.settings = {}

    def _lane_path(self):
        named = self.payload.get('agent_transcript_path')
        if isinstance(named, str) and named:
            return Path(named)
        parent = self.payload.get('transcript_path')
        if isinstance(parent, str) and parent and self.session and self.agent_id:
            candidate = Path(parent).parent / self.session / 'subagents' / ('agent-%s.jsonl' % self.agent_id)
            if candidate.is_file():
                return candidate
        return transcripts.lane_path(self.session, self.agent_id)

    def _read_lane(self):
        if not self.agent_id:
            self.lane_problem = 'agent_id absent from %s' % self.event
            return
        path = self._lane_path()
        if path is None or not Path(path).is_file():
            self.lane_problem = "the member's transcript could not be found"
            return
        self.lane = Path(path)
        try:
            self.rows = transcripts.rows_of(self.lane)
        except OSError as exc:
            self.rows, self.lane_problem = None, "the member's transcript could not be read: %s" % one_line(exc)
            return
        meta = self.lane.with_name(self.lane.name[:-len('.jsonl')] + '.meta.json')
        try:
            found = json.loads(meta.read_text(encoding='utf-8')).get('toolUseId')
            self.dispatch_call_id = found if isinstance(found, str) and found else None
        except (OSError, ValueError, AttributeError):
            self.dispatch_call_id = None
        for row in self.rows:
            if row.get('type') == 'user' and isinstance(row.get('message'), dict):
                self.prompt = text_of(row['message'].get('content'))
                break

    def _read_brief(self):
        if self.prompt is None:
            return
        brief, source = capture.brief_of(self.prompt, self.cwd)
        self.brief, self.brief_source = (brief, source) if source else (None, None)
        read, _not_a_brief = capture.brief_read(str(self.folder), self.brief, self.brief_source)
        member, attempt = read.get('member'), read.get('attempt')
        if isinstance(member, str) and not member.startswith('unrecorded ('):
            self.member, self.attempt, self.member_brief = member, attempt, True
        if self.brief is not None:
            self.write_set = capture.write_set_of(self.brief)
            self.writer = capture.is_writer(self.brief)

    def handback_member(self):
        return self.payload.get('permission_mode') == HANDBACK_MODE

    def _read_report(self):
        if self.event == 'PreToolUse':
            key = capture.handback_tools(capture.HARNESS).get(self.payload.get('tool_name'))
            given = self.payload.get('tool_input') if isinstance(self.payload.get('tool_input'), dict) else {}
            self.report_name = HANDBACK_REPORT
            value = given.get(key) if key else None
            if isinstance(value, str):
                self.report_text = value
            else:
                self.report_problem = 'tool_input.%s absent from PreToolUse' % (key or 'message')
            return
        delivered = []
        if self.rows is not None:
            delivered = transcripts.delivered_handbacks(self.lane, capture.handback_tools(capture.HARNESS),
                                                        rows=self.rows)
        final = self.payload.get('last_assistant_message')
        if delivered:
            self.report_name, self.report_text = HANDBACK_REPORT, delivered[-1]
            return
        self.report_name = FINAL_REPORT
        if self.rows is None and self.handback_member():
            # Whether a hand-back was delivered is unknown, so so is the text the parent received.
            self.report_problem = '%s: no delivered hand-back can be read' % (
                self.lane_problem or "the member's transcript could not be read")
            return
        if isinstance(final, str):
            self.report_text = final
        else:
            self.report_problem = 'last_assistant_message absent from SubagentStop'
        if self.handback_member():
            # Claude Code refuses this stop itself until the member hands back: no report reaches the parent here.
            self.report_applies = False

    def _read_writes(self):
        if self.rows is None:
            return
        found, order, results = {}, [], {}
        for row in self.rows:
            message = row.get('message') if isinstance(row.get('message'), dict) else {}
            content = message.get('content')
            for part in content if isinstance(content, list) else []:
                if not isinstance(part, dict):
                    continue
                if part.get('type') == 'tool_use':
                    name = part.get('name')
                    if name in SHELL_USING_TOOLS:
                        self.shell_using = True
                    if name in WRITE_TOOLS and isinstance(part.get('id'), str) and part['id'] not in found:
                        given = part.get('input') if isinstance(part.get('input'), dict) else {}
                        path = given.get(WRITE_TOOLS[name])
                        found[part['id']] = Write(part['id'], name, path if isinstance(path, str) else None)
                        order.append(part['id'])
                elif part.get('type') == 'tool_result' and isinstance(part.get('tool_use_id'), str):
                    results.setdefault(part['tool_use_id'], part.get('is_error', False))
        for call_id in order:
            write = found[call_id]
            if call_id in results:
                flag = results[call_id]
                write.state = 'error' if flag is True else 'ok' if flag in (False, None) else 'unreadable'
            self.writes.append(write)

    def _read_ledger(self):
        if self.folder is None or not self.session:
            self.records_problem = 'no ledger folder or session to read'
            return
        path = self.folder / ('%s.jsonl' % self.session)
        try:
            text = path.read_text(encoding='utf-8', errors='replace') if path.exists() else ''
        except OSError as exc:
            self.records_problem = 'the ledger file could not be read: %s' % one_line(exc)
            return
        self.records = []
        for line in text.splitlines():
            try:
                row = json.loads(line)
            except ValueError:
                continue
            if isinstance(row, dict):
                self.records.append(row)
        self.session_started = any(row.get('record') == 'witness' and row.get('event') == SESSION_START
                                   for row in self.records)
        # A resumption's dispatch record continues another call; the member's own dispatch is the one it continues.
        dispatches = [row for row in self.records if row.get('record') == 'dispatch'
                      and not real(row.get('continues_call_id'))]
        if self.member_brief:
            matched = [row for row in dispatches if row.get('member') == self.member
                       and str(row.get('attempt')) == str(self.attempt)]
            if self.dispatch_call_id:
                exact = [row for row in matched if row.get('call_id') == self.dispatch_call_id]
                matched = exact or matched
        elif self.dispatch_call_id:
            matched = [row for row in dispatches if row.get('call_id') == self.dispatch_call_id]
        else:
            matched = []
        self.dispatch = matched[-1] if matched else None

    def _read_root(self):
        if not self.cwd:
            self.root_problem = 'cwd absent from %s' % self.event
            return
        out, problem = git(self.cwd, 'rev-parse', '--show-toplevel')
        if problem:
            self.root_problem = 'git could not read the working folder: %s' % problem
            return
        self.root = canonical(out.strip())

    # -- readings the checks share ---------------------------------------------------------------------------------

    def key(self):
        return {'agent_id': self.agent_id or 'unrecorded (agent_id absent from %s)' % self.event,
                'call_id': (self.dispatch or {}).get('call_id') or self.dispatch_call_id
                or 'unrecorded (no dispatch record or meta file names the call)',
                'member': self.member if self.member_brief else 'unrecorded (no member brief)',
                'attempt': self.attempt if self.member_brief else 'unrecorded (no member brief)'}

    def dispatched_at(self):
        return parse_time((self.dispatch or {}).get('dispatched_at'))

    def baseline(self):
        """(commit, problem) from the dispatch record."""
        if self.dispatch is None:
            return None, 'no dispatch record for this member and attempt: no baseline or dispatch time to read against'
        found = self.dispatch.get('baseline')
        if isinstance(found, dict) and isinstance(found.get('commit'), str):
            return found['commit'], None
        if isinstance(found, str):
            return None, 'the dispatch record reads %s' % found
        return None, 'the dispatch record carries no baseline'

    def changes(self):
        """(canonical paths changed in the worktree against the baseline, committed or not, untracked included;
        problem)."""
        if self._changes is not None:
            return self._changes
        commit, problem = self.baseline()
        if problem:
            self._changes = (None, problem)
            return self._changes
        if self.root_problem:
            self._changes = (None, self.root_problem)
            return self._changes
        tracked, problem = git(self.root, 'diff', '--name-only', '--no-renames', '-z', commit)
        if problem is None:
            untracked, problem = git(self.root, 'ls-files', '--others', '--exclude-standard', '-z')
        if problem:
            self._changes = (None, "the worktree could not be read against its baseline: %s" % problem)
            return self._changes
        names = [name for name in (tracked + untracked).split('\0') if name]
        self._changes = (sorted(set(canonical(name, self.root) for name in names)), None)
        return self._changes

    def scratch_folders(self):
        out = []
        named = self.payload.get('scratchpad_dir')
        if isinstance(named, str) and named:
            out.append(canonical(named))
        extra = self.settings.get('scratch')
        for item in extra if isinstance(extra, list) else [extra] if isinstance(extra, str) else []:
            if isinstance(item, str) and item:
                out.append(canonical(item.replace('{session}', self.session or '')))
        return out

    def write_problem(self):
        """The reason the transcript's writes cannot be read in full, or None."""
        if self.rows is None:
            return self.lane_problem or "the member's transcript could not be read"
        waiting = [write.call_id for write in self.writes if write.state == 'no result']
        if waiting:
            return 'the transcript holds a write call with no result yet: %s' % ', '.join(waiting)
        unread = [write.call_id for write in self.writes if write.state == 'unreadable']
        if unread:
            return 'a write call\'s result cannot be read as an error or not: %s' % ', '.join(unread)
        return None

    def written(self):
        """The canonical paths of the transcript's write calls whose results are not errors, each once."""
        out = []
        for write in self.writes:
            if write.state == 'ok' and write.path:
                path = canonical(write.path, self.cwd)
                if path not in out:
                    out.append(path)
        return out

    def report_digest(self):
        return sha256(self.report_text) or 'unrecorded (%s)' % (self.report_problem or 'no report text')
