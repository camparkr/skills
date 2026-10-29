"""The world the return check's tests run in: a repository, members with briefs, worktrees and transcripts, and a
ledger of their own.

Nothing here touches a real ledger, a real transcript or a live service. Each world is a temporary folder holding:

  * `repo/`, a git repository, the main checkout, with `docs/existing.md` (conforming front matter) and `src/app.py`
    committed;
  * `config/`, standing for the harness's configuration folder (CLAUDE_CONFIG_DIR): the parent's transcript at
    `projects/p/<session>.jsonl`, each member's beside it under `<session>/subagents/`, with its meta file;
  * `ledger/`, the ledger folder, whose config.json switches on the return check's commands;
  * `briefs/`, `wt/` (one worktree per writer, made after its dispatch, as the harness makes it) and `scratch/`.

Hooks run as the harness runs them: the ledger's wrapper in a new process, the payload on standard input, with HOME and
CLAUDE_CONFIG_DIR naming folders in the world and SUBAGENT_LEDGER_DIR removed. The front-matter validator is the
stand-in in `fixtures/validator.py`.
"""

import hashlib
import json
import os
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
SKILL = HERE.parent / 'skill' / 'scripts'
LEDGER_SCRIPTS = HERE.parents[1] / 'subagent-ledger' / 'skill' / 'scripts'
WRAPPER = LEDGER_SCRIPTS / 'wrapper.py'
CALLS = LEDGER_SCRIPTS / 'calls.py'
RETURN_CHECK = SKILL / 'return_check.py'
GATE = SKILL / 'gate.py'
DISPOSITION = SKILL / 'disposition.py'
VALIDATOR = HERE / 'fixtures' / 'validator.py'
SESSION = '1a1a1a1a-2b2b-4c3c-8d4d-5e5e5e5e5e5e'
GOOD_FRONT = '---\ntype: concept\ntitle: A page\n---\n\nBody.\n'
BAD_FRONT = '---\ntitle: No type here\n---\n\nBody.\n'
CLOSING = 'All finished here.'
NOT_CHECKABLE_TEXTS = ['Path not found', '0 files examined', 'VISIBLE ERROR']

for folder in (SKILL, LEDGER_SCRIPTS):
    if str(folder) not in sys.path:
        sys.path.insert(0, str(folder))


def lines(path):
    path = Path(path)
    if not path.is_file():
        return []
    return [json.loads(line) for line in path.read_text(encoding='utf-8').splitlines() if line.strip()]


def sha(text):
    return hashlib.sha256(text.encode('utf-8')).hexdigest()


def usage(output=3):
    return {'input_tokens': 10, 'cache_creation_input_tokens': 0, 'cache_read_input_tokens': 0,
            'output_tokens': output}


def git(root, *args):
    done = subprocess.run(['git', '-C', str(root)] + list(args), capture_output=True, text=True, timeout=60)
    if done.returncode != 0:
        raise RuntimeError('git %s: %s' % (' '.join(args), done.stderr))
    return done.stdout


def report(*claims, prose='The work is done.'):
    """A report ending with an output section listing `claims`, or `none` where there are none."""
    return '%s\n\n## Output\n%s\n' % (prose, '\n'.join(claims) if claims else 'none')


class Member(object):
    """One member of the team: its brief, its agent id, its working folder and its transcript."""

    def __init__(self, world, name, write_set, attempt=1, mode='auto', background=True, brief=True,
                 seq=None):
        self.world = world
        self.name = name
        self.write_set = write_set
        self.attempt = attempt
        self.mode = mode
        self.background = background
        seq = seq if seq is not None else world.next_seq()
        self.agent = 'a%016x' % (0xabc000 + seq)
        self.call_id = 'toolu_%s_%d' % (name.replace('-', '_'), attempt)
        self.writer = bool(write_set) and write_set != ['none']
        self.root = world.repo
        self.brief_path = world.briefs / ('%s-%d.md' % (name, attempt))
        if brief:
            self.brief_path.write_text(world.brief_text(name, attempt, write_set), encoding='utf-8')
            self.prompt = 'Read your brief at %s and do it.' % self.brief_path
        else:
            self.prompt = 'Plan the team for the delegation. No brief file.'
        self.lane = world.project / SESSION / 'subagents' / ('agent-%s.jsonl' % self.agent)
        self.lane.parent.mkdir(parents=True, exist_ok=True)
        self.rows = [{'type': 'user', 'uuid': 'u0', 'message': {'role': 'user', 'content': self.prompt}}]
        self.flush()
        meta = self.lane.with_name('agent-%s.meta.json' % self.agent)
        meta.write_text(json.dumps({'agentType': 'general-purpose', 'toolUseId': self.call_id}), encoding='utf-8')
        self.count = 0

    # -- the transcript --------------------------------------------------------------------------------------

    def flush(self):
        self.lane.write_text(''.join(json.dumps(r) + '\n' for r in self.rows), encoding='utf-8')

    def tool(self, name, given, result=True, twice=False):
        """A tool call in the transcript, with its result (True: not an error; False: an error; None: no result
        yet; any other value: written as `is_error` as it is)."""
        self.count += 1
        call = 't%s-%d' % (self.name, self.count)
        use = {'type': 'assistant', 'uuid': call + '-a', 'message': {
            'id': 'm-' + call, 'model': 'test-model', 'role': 'assistant', 'stop_reason': 'tool_use',
            'content': [{'type': 'tool_use', 'id': call, 'name': name, 'input': given}], 'usage': usage()}}
        self.rows.append(use)
        if twice:
            self.rows.append(json.loads(json.dumps(use)))
        if result is not None:
            part = {'type': 'tool_result', 'tool_use_id': call, 'content': 'done'}
            if result is not True:
                part['is_error'] = True if result is False else result
            self.rows.append({'type': 'user', 'uuid': call + '-r', 'message': {'role': 'user', 'content': [part]}})
        self.flush()
        return call

    def write(self, relative, text, tool='Write', path=None, twice=False, result=True):
        """Write a file in the member's working folder, and the call that wrote it in the transcript."""
        target = Path(path) if path else self.root / relative
        if result is True:
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(text, encoding='utf-8')
        key = 'notebook_path' if tool == 'NotebookEdit' else 'file_path'
        return self.tool(tool, {key: str(target), 'content': text}, result=result, twice=twice)

    def shell(self, command, run=True):
        """A shell command, run in the member's working folder, and its call in the transcript."""
        if run:
            subprocess.run(command, shell=True, cwd=str(self.root), check=True, capture_output=True)
        return self.tool('Bash', {'command': command})

    def closing(self, text=CLOSING):
        self.rows.append({'type': 'assistant', 'uuid': 'c%d' % len(self.rows), 'message': {
            'id': 'mc%d' % len(self.rows), 'model': 'test-model', 'role': 'assistant', 'stop_reason': 'end_turn',
            'content': [{'type': 'text', 'text': text}], 'usage': usage()}})
        self.flush()

    # -- the hook payloads -----------------------------------------------------------------------------------

    def base(self, event):
        return {'session_id': SESSION, 'transcript_path': str(self.world.parent_transcript),
                'cwd': str(self.root), 'permission_mode': self.mode, 'agent_id': self.agent,
                'agent_type': 'general-purpose', 'hook_event_name': event, 'effort': {'level': 'low'},
                'scratchpad_dir': str(self.world.scratchpad)}


class World(object):

    def __init__(self, tmp, checks=('stop', 'handback', 'gate', 'context'), settings=None, wait=5):
        self.tmp = Path(tmp)
        self.repo = self.tmp / 'repo'
        self.repo.mkdir()
        git(self.repo, 'init', '-q', '-b', 'main')
        git(self.repo, 'config', 'user.email', 'test@example.invalid')
        git(self.repo, 'config', 'user.name', 'Test')
        (self.repo / 'docs').mkdir()
        (self.repo / 'src').mkdir()
        (self.repo / 'docs' / 'existing.md').write_text(GOOD_FRONT, encoding='utf-8')
        (self.repo / 'src' / 'app.py').write_text('print(1)\n', encoding='utf-8')
        git(self.repo, 'add', '-A')
        git(self.repo, 'commit', '-q', '-m', 'base')
        self.config = self.tmp / 'config'
        self.project = self.config / 'projects' / 'p'
        self.project.mkdir(parents=True)
        self.parent_transcript = self.project / ('%s.jsonl' % SESSION)
        self.parent_rows = []
        self.flush_parent()
        self.ledger = self.tmp / 'ledger'
        self.ledger.mkdir()
        self.briefs = self.tmp / 'briefs'
        self.briefs.mkdir()
        self.worktrees = self.tmp / 'wt'
        self.worktrees.mkdir()
        self.scratchpad = self.tmp / 'scratch' / SESSION / 'scratchpad'
        self.scratchpad.mkdir(parents=True)
        self.outside = self.tmp / 'outside'
        self.outside.mkdir()
        self.seq = 0
        self.configure(checks, settings, wait)

    def next_seq(self):
        self.seq += 1
        return self.seq

    def configure(self, checks=('stop', 'handback', 'gate', 'context'), settings=None, wait=5, gate=None):
        commands = {'stop': '"%s" "%s"' % (sys.executable, RETURN_CHECK),
                    'handback': '"%s" "%s"' % (sys.executable, RETURN_CHECK),
                    'gate': gate or '"%s" "%s"' % (sys.executable, GATE),
                    'context': '"%s" "%s" --context' % (sys.executable, RETURN_CHECK)}
        found = {'validator': '"%s" "%s"' % (sys.executable, VALIDATOR),
                 'validator_not_checkable': NOT_CHECKABLE_TEXTS}
        found.update(settings or {})
        config = {'fields': 'all', 'checks': dict((k, commands[k]) for k in checks), 'check_seconds': 30,
                  'background_wait_seconds': wait, 'return_check': found}
        (self.ledger / 'config.json').write_text(json.dumps(config), encoding='utf-8')

    def brief_text(self, name, attempt, write_set):
        sets = '\n'.join(write_set) if write_set else 'none'
        return ('---\nmember: %s\nattempt: %d\n---\n\nBefore your first act, read your file.\n\n## Task\n\nDo the '
                'part.\n\n## Write set\n\n%s\n' % (name, attempt, sets))

    def flush_parent(self):
        self.parent_transcript.write_text(''.join(json.dumps(r) + '\n' for r in self.parent_rows), encoding='utf-8')

    # -- running hooks ---------------------------------------------------------------------------------------

    def env(self):
        env = dict(os.environ, HOME=str(self.tmp / 'home'), CLAUDE_CONFIG_DIR=str(self.config),
                   CLAUDE_CODE_SESSION_ID=SESSION)
        for name in ('SUBAGENT_LEDGER_DIR', 'SUBAGENT_LEDGER_SCRIPTS', 'SUBAGENT_LEDGER_SESSION'):
            env.pop(name, None)
        return env

    def hook(self, event, payload, cwd=None):
        """Run the wrapper on one event. Returns (exit code, the decision printed or None, standard error)."""
        done = subprocess.run([sys.executable, str(WRAPPER), event, '--ledger', str(self.ledger)],
                              input=json.dumps(payload), capture_output=True, text=True, env=self.env(),
                              cwd=str(cwd or self.repo), timeout=120)
        text = done.stdout.strip()
        return done.returncode, (json.loads(text) if text else None), done.stderr

    def start(self):
        self.hook('SessionStart', {'session_id': SESSION, 'hook_event_name': 'SessionStart', 'cwd': str(self.repo),
                                   'transcript_path': str(self.parent_transcript), 'source': 'startup'})

    def records(self):
        return lines(self.ledger / ('%s.jsonl' % SESSION))

    def pending(self):
        return self.ledger / '.pending' / SESSION

    # -- the parent's calls ----------------------------------------------------------------------------------

    def parent_payload(self, tool, given, call_id=None):
        self.seq += 1
        return {'session_id': SESSION, 'transcript_path': str(self.parent_transcript), 'cwd': str(self.repo),
                'permission_mode': 'auto', 'hook_event_name': 'PreToolUse', 'tool_name': tool,
                'tool_input': given, 'tool_use_id': call_id or 'toolu_parent_%d' % self.seq,
                'effort': {'level': 'high'}, 'scratchpad_dir': str(self.scratchpad)}

    def parent(self, tool, given, call_id=None):
        """The parent's PreToolUse on `tool`: (exit code, decision, standard error)."""
        return self.hook('PreToolUse', self.parent_payload(tool, given, call_id))

    def denied(self, decision):
        if not decision:
            return None
        found = decision.get('hookSpecificOutput') or {}
        return found.get('permissionDecisionReason') if found.get('permissionDecision') == 'deny' else None

    def member(self, name, write_set, **kwargs):
        return Member(self, name, write_set, **kwargs)

    def dispatch(self, member, worktree=True):
        """The parent dispatches `member`: PreToolUse on Agent, the worktree made, and for a background call the
        launch's PostToolUse. Returns the PreToolUse decision."""
        self.parent_rows.append({'type': 'assistant', 'uuid': 'p' + member.call_id, 'message': {
            'id': 'p' + member.call_id, 'role': 'assistant', 'model': 'test-model', 'stop_reason': 'tool_use',
            'content': [{'type': 'tool_use', 'id': member.call_id, 'name': 'Agent',
                         'input': {'prompt': member.prompt}}], 'usage': usage(1)}})
        self.flush_parent()
        given = {'description': member.name, 'prompt': member.prompt, 'subagent_type': 'general-purpose',
                 'run_in_background': member.background}
        _code, decision, _err = self.hook('PreToolUse', self.parent_payload('Agent', given, member.call_id))
        if self.denied(decision):
            return decision
        if member.writer and worktree:
            folder = self.worktrees / ('%s-%d' % (member.name, member.attempt))
            git(self.repo, 'worktree', 'add', '-q', '-b', 'wt-%s-%d' % (member.name, member.attempt), str(folder),
                'HEAD')
            member.root = folder
        if member.background:
            payload = self.parent_payload('Agent', given, member.call_id)
            payload.update(hook_event_name='PostToolUse', tool_response={
                'status': 'async_launched', 'agentId': member.agent, 'isAsync': True})
            self.hook('PostToolUse', payload)
        return decision

    def handback(self, member, message, delivered=True, refused_by_other=False):
        """The member hands back `message`: the wrapper at its PreToolUse; then, where delivered, its result in the
        transcript and its PostToolUse. A stand-in for another hook's refusal leaves an error result and no
        PostToolUse. Returns the PreToolUse decision."""
        member.count += 1
        call = 'h%s-%d' % (member.name, member.count)
        member.rows.append({'type': 'assistant', 'uuid': call + '-a', 'message': {
            'id': 'm-' + call, 'model': 'test-model', 'role': 'assistant', 'stop_reason': 'tool_use',
            'content': [{'type': 'tool_use', 'id': call, 'name': 'SubagentHandback', 'input': {'message': message}}],
            'usage': usage()}})
        member.flush()
        payload = member.base('PreToolUse')
        payload.update(tool_name='SubagentHandback', tool_input={'message': message}, tool_use_id=call)
        _code, decision, _err = self.hook('PreToolUse', payload, cwd=member.root)
        part = {'type': 'tool_result', 'tool_use_id': call, 'content': 'Report delivered to your caller.'}
        if refused_by_other or not delivered:
            part['is_error'] = True
        member.rows.append({'type': 'user', 'uuid': call + '-r', 'message': {'role': 'user', 'content': [part]}})
        member.flush()
        if delivered and not refused_by_other:
            post = member.base('PostToolUse')
            post.update(tool_name='SubagentHandback', tool_input={'message': message}, tool_use_id=call,
                        tool_response={'success': True, 'message': 'Report delivered to your caller.'})
            self.hook('PostToolUse', post, cwd=member.root)
        return decision

    def stop(self, member, closing=CLOSING, active=False):
        """The member's SubagentStop, its closing text written first. Returns the decision."""
        member.closing(closing)
        payload = member.base('SubagentStop')
        payload.update(stop_hook_active=active, agent_transcript_path=str(member.lane),
                       last_assistant_message=closing)
        if member.background:
            payload['background_tasks'] = [{'id': member.agent, 'type': 'subagent'}]
        _code, decision, _err = self.hook('SubagentStop', payload, cwd=member.root)
        return decision

    def foreground_post(self, member, handback_text=None):
        """The Agent call's PostToolUse on the foreground route. Returns the decision (its context, if any)."""
        response = {'status': 'completed', 'agentId': member.agent, 'resolvedModel': 'test-model',
                    'content': [{'type': 'text', 'text': 'This agent\'s report was delivered to you as a message.'}]}
        if handback_text is not None:
            response['handbackReport'] = {'text': handback_text}
        payload = self.parent_payload('Agent', {'prompt': member.prompt}, member.call_id)
        payload.update(hook_event_name='PostToolUse', tool_response=response)
        _code, decision, _err = self.hook('PostToolUse', payload)
        return decision

    # -- reading the record ----------------------------------------------------------------------------------

    def witnesses(self, member, event=None):
        return [r for r in self.records() if r.get('record') == 'witness' and r.get('agent_id') == member.agent
                and (event is None or r.get('event') == event)]

    def returns(self, member):
        return [r for r in self.records() if r.get('record') == 'return' and r.get('call_id') == member.call_id]

    def runs(self, record):
        return [r for r in record.get('check_results') or [] if isinstance(r, dict)]

    def results(self, record, n=-1):
        """{check number: result} of the record's n-th run."""
        found = self.runs(record)[n]
        return dict((c['check'], c) for c in found['checks'])

    def disposition(self, *args, cwd=None):
        """Run the disposition script as the parent's shell would. Returns the finished process."""
        return subprocess.run([sys.executable, str(DISPOSITION)] + list(args), capture_output=True, text=True,
                              env=dict(self.env(), SUBAGENT_LEDGER_DIR=str(self.ledger)), cwd=str(cwd or self.repo),
                              timeout=60)

    def disposition_call(self, command):
        """The parent's Bash call running `command`: its PreToolUse (the gate), the command itself when let
        through, then its PostToolUse, where the capture writes the disposition line. Returns the PreToolUse
        decision and the finished process, or None where refused."""
        payload = self.parent_payload('Bash', {'command': command})
        _code, decision, _err = self.hook('PreToolUse', payload)
        if self.denied(decision):
            return decision, None
        done = subprocess.run(command, shell=True, capture_output=True, text=True,
                              env=dict(self.env(), SUBAGENT_LEDGER_DIR=str(self.ledger)), cwd=str(self.repo),
                              timeout=60)
        if done.returncode == 0:
            post = dict(payload, hook_event_name='PostToolUse',
                        tool_response={'stdout': done.stdout, 'stderr': done.stderr, 'interrupted': False})
            self.hook('PostToolUse', post)
        else:  # the harness sends a command that exits non-zero to PostToolUseFailure
            self.hook('PostToolUseFailure', dict(payload, hook_event_name='PostToolUseFailure',
                                                 error='Exit code %d\n%s' % (done.returncode, done.stderr)))
        return decision, done

    def count_check(self):
        done = subprocess.run([sys.executable, str(CALLS), '--session', SESSION, '--ledger', str(self.ledger),
                               '--json', '--count-check', '--harness', 'claude-code', '--transcript',
                               str(self.parent_transcript)], capture_output=True, text=True, env=self.env(),
                              timeout=120)
        return done.returncode, json.loads(done.stdout) if done.stdout.strip() else {}
