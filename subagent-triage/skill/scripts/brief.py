#!/usr/bin/env python3
"""Write one member's brief: its front matter, the opening instruction, the task, the write set and the return
skill's instruction, in that order. A path that does not resolve stops the brief.

    python3 brief.py --out <brief path> --member <id> --attempt <n> --persona <name> --persona-file <path>
                     --kind <kind> --task <id> --body <file> --write-set <path> [--write-set <path> ...]
                     [--repository <folder>] [--pending <pending triage file>] [--ledger <folder>]

    --write-set none                  for a read-only member

The front matter carries the persona, the kind, the task, the member and the attempt, each at the key the ledger
folder's config.json `frontmatter` map names for it (the capture's own defaults where it names none), so the capture
reads them. The kind is written as the value config.json's `kind_names` map gives it; an unknown kind is refused.

The body's parts and their wording have one home each, and are read from it, never written here:

  * the opening instruction and the below-the-line sentence: the fenced blocks under '1. The opening instruction'
    and '3. Below the line' in this skill's references/brief-format.md;
  * the closing instruction: the fenced block under '## The instruction' in the return skill's
    references/brief-instruction.md, copied word for word with its two placeholders filled from the return check's
    settings (config.json's `return_check`): `<validator>` from `validator`, and `<kinds>` from `markdown`;
  * the output section's grammar: the return skill's output_section.py. The closing instruction must quote that
    parser's heading and its `none` word, or the brief is not written.

The task is the --body file's text, less any front matter. The below-the-line sentence is written where the
--pending file carries `below_line`, from its probability, line and version. A --pending file whose persona or kind
differs from --persona or --kind stops the brief: record the override first.

What stops the brief, each with the reason and exit 1, writing nothing:

  * the persona file, or the memory index beside it (`index.md` in the persona file's folder), is not a file;
  * an absolute path the task names does not exist. A path is `~/` and a name, a drive letter, or `/` and at least
    two names: a word of one name after `/`, such as a quoted slash command, is not a path;
  * a write-set path is absolute, or leaves the repository; a writer's repository is not a git working tree's top
    folder (--repository, or the working folder's git top); a write-set path may name a file still to be created;
  * the task holds a `## Write set` section of its own, which the capture would read as the write set;
  * the member id holds a character a pending file's name cannot keep, or the attempt is not a whole number from 1;
  * the out path already exists: a brief is never overwritten;
  * the settings name no front-matter validator, so the instruction's `<validator>` cannot be filled.

Before writing, the brief is read back with the capture's own readers: its front matter must give the member and
attempt, and its write-set section the paths given. Output: one JSON object naming the brief and what it holds. Exit
codes: 0 written; 1 refused; 2 cannot run (a reference file, the ledger skill or the return skill not found).
"""

import argparse
import json
import os
import posixpath
import re
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

import decide  # noqa: E402

FORMAT = decide.SKILL / 'references' / 'brief-format.md'
OPENING_LABEL = '**1. The opening instruction.**'
BELOW_LABEL = '**3. Below the line'
INSTRUCTION_HEADING = '## The instruction'
PERSONA_SLOT = '<absolute path>'
MEMBER_ID = re.compile(r'^[A-Za-z0-9][A-Za-z0-9._-]*$')
FIELDS = ('persona-name', 'act_kind', 'task', 'member', 'attempt')
PLAIN = re.compile(r'^[A-Za-z_][A-Za-z0-9_./-]*(?: [A-Za-z0-9_./-]+)*$')
YAML_WORDS = ('y', 'n', 'yes', 'no', 'true', 'false', 'on', 'off', 'null', '~')


class Refused(Exception):
    pass


def return_scripts():
    """The return skill's scripts folder: SUBAGENT_RETURN_SCRIPTS, else beside this skill in a repository or install."""
    named = os.environ.get('SUBAGENT_RETURN_SCRIPTS')
    tried = [Path(named)] if named else []
    tried += [decide.SKILL.parent.parent / 'subagent-return' / 'skill' / 'scripts',
              decide.SKILL.parent / 'subagent-return' / 'scripts']
    for folder in tried:
        if (folder / 'output_section.py').is_file() and (folder.parent / 'references' / 'brief-instruction.md').is_file():
            if str(folder) not in sys.path:
                sys.path.insert(0, str(folder))
            return folder
    raise decide.CannotRun('output_section.py and references/brief-instruction.md not found at %s'
                           % ', '.join(str(p) for p in tried))


def fenced_block(path, label):
    """The text of the first fenced block after the first line of the file at `path` that begins with `label`."""
    lines = Path(path).read_text(encoding='utf-8').splitlines()
    starts = [at for at, line in enumerate(lines) if line.startswith(label)]
    if not starts:
        raise decide.CannotRun('%s holds no line beginning %r' % (path, label))
    opened = next((at for at in range(starts[0] + 1, len(lines)) if lines[at].startswith('```')), None)
    closed = next((at for at in range(opened + 1, len(lines)) if lines[at].startswith('```')), None) \
        if opened is not None else None
    if closed is None:
        raise decide.CannotRun('%s holds no fenced block after %r' % (path, label))
    return '\n'.join(lines[opened + 1:closed])


def scalar(value):
    """A front matter value: a whole number or a plain word as it stands, anything else in single quotes."""
    if isinstance(value, int):
        return str(value)
    if PLAIN.match(value) and value.lower() not in YAML_WORDS:
        return value
    return "'%s'" % value.replace("'", "''")


def front_matter(values):
    """YAML front matter for {dotted key: value}, a dotted key written as nested mappings, in the order given."""
    tree = {}
    for dotted, value in values:
        node = tree
        parts = dotted.split('.')
        for part in parts[:-1]:
            node = node.setdefault(part, {})
            if not isinstance(node, dict):
                raise Refused('the front matter key %s sits under a key that already holds a value' % dotted)
        node[parts[-1]] = value
    lines = []

    def emit(node, indent):
        for key, value in node.items():
            if isinstance(value, dict):
                lines.append('%s%s:' % (' ' * indent, key))
                emit(value, indent + 2)
            else:
                lines.append('%s%s: %s' % (' ' * indent, key, scalar(value)))
    emit(tree, 0)
    return '---\n%s\n---\n' % '\n'.join(lines)


def git_top(folder):
    try:
        done = subprocess.run(['git', '-C', str(folder), 'rev-parse', '--show-toplevel'], capture_output=True,
                              text=True, timeout=20)
    except (OSError, subprocess.SubprocessError):
        return None
    return done.stdout.strip() if done.returncode == 0 and done.stdout.strip() else None


def write_set_paths(given, repository):
    """(the write set's lines, the repository's top folder or None for a read-only member)."""
    if [path.strip() for path in given] == ['none']:
        return ['none'], None
    if not given or any(not path.strip() for path in given) or 'none' in [path.strip() for path in given]:
        raise Refused('the write set is one path or folder prefix a line, or the single word `none`: %r' % given)
    folder = repository or git_top(os.getcwd())
    if not folder or not Path(folder).is_dir():
        raise Refused('the repository %s does not exist' % (folder or '(none named, and the working folder is in '
                                                                     'no git repository)'))
    top = git_top(folder)
    if not top or os.path.realpath(top) != os.path.realpath(folder):
        raise Refused('the repository %s is not the top folder of a git working tree' % folder)
    out = []
    for path in given:
        path = path.strip()
        if posixpath.isabs(path) or re.match(r'^[A-Za-z]:[\\/]', path) or path.startswith('~'):
            raise Refused('the write-set path %s is absolute: give it relative to the repository\'s root' % path)
        tidy = posixpath.normpath(path.replace('\\', '/'))
        if tidy == '..' or tidy.startswith('../'):
            raise Refused('the write-set path %s leaves the repository' % path)
        out.append(path)
    return out, folder


def inputs_named(body):
    """Each absolute path the task names, in order, and whether it exists."""
    out = []
    for found in decide.ABSOLUTE_PATH.findall(body):
        path = found.rstrip('.,;:!?')
        if path not in [p for p, _ in out]:
            out.append((path, os.path.exists(os.path.expanduser(path))))
    return out


def stamped_value(data, key):
    held = data.get(key) if isinstance(data, dict) else None
    return held.get('value') if isinstance(held, dict) else None


def compose(args, capture, output_section, call_context):
    """(the brief's text, what the output reports). Raises Refused."""
    if not MEMBER_ID.match(args.member):
        raise Refused('the member id %r holds a character a pending file\'s name cannot keep: use letters, digits, '
                      '".", "_" and "-"' % args.member)
    if not args.attempt.isdigit() or int(args.attempt) < 1:
        raise Refused('the attempt %r is not a whole number from 1' % args.attempt)
    attempt = int(args.attempt)
    if not args.persona.strip() or '\n' in args.persona:
        raise Refused('the persona name is empty or holds a line break')
    out = Path(args.out)
    if out.exists() or out.is_symlink():
        raise Refused('the brief %s already exists: a brief is never overwritten' % out)

    folder = args.ledger_folder
    config, _ = capture.read_config(folder)
    keys = capture.frontmatter_keys(config)
    for name in ('member', 'attempt'):
        if not keys.get(name):
            raise Refused('the ledger\'s settings name no front matter key for %s' % name)
    table, why = capture.kind_names(folder)
    if table is None:
        raise decide.CannotRun(why)
    if args.kind not in table:
        raise Refused('unknown kind %r: the kinds are %s' % (args.kind, ', '.join(table)))
    kind_value = table[args.kind] or args.kind
    settings = config.get(call_context.SETTINGS_KEY) if isinstance(config.get(call_context.SETTINGS_KEY), dict) else {}
    validator = settings.get('validator')
    if not isinstance(validator, str) or not validator.strip():
        raise Refused('the ledger\'s settings name no front-matter validator (%s.validator), so the brief '
                      'instruction\'s <validator> cannot be filled' % call_context.SETTINGS_KEY)
    patterns = [p for p in settings.get('markdown') or [] if isinstance(p, str)] \
        if isinstance(settings.get('markdown'), list) else []
    kinds_text = 'Markdown (%s)' % ', '.join('`%s`' % p for p in patterns) if patterns else 'Markdown'

    persona_file = Path(os.path.abspath(os.path.expanduser(args.persona_file)))
    if not persona_file.is_file():
        raise Refused('the persona file %s does not resolve' % persona_file)
    memory_index = persona_file.parent / 'index.md'
    if not memory_index.is_file():
        raise Refused('the memory index %s, beside the persona file, does not resolve' % memory_index)

    try:
        task_text = decide.full_body(Path(args.body).read_text(encoding='utf-8'))
    except OSError as exc:
        raise Refused('the task text could not be read: %s' % exc)
    if not task_text:
        raise Refused('the task text %s is empty' % args.body)
    if capture.write_set_of(task_text) is not None:
        raise Refused('the task text holds a %s section of its own, which the capture would read as the write set; '
                      'give the write set with --write-set' % capture.WRITE_SET_HEADING)
    named = inputs_named(task_text)
    missing = [path for path, exists in named if not exists]
    if missing:
        raise Refused('a path the task names does not resolve: %s' % ', '.join(missing))
    write_set, repository = write_set_paths(args.write_set, args.repository)

    below = None
    if args.pending:
        try:
            pending = json.loads(Path(args.pending).read_text(encoding='utf-8'))
        except (OSError, ValueError) as exc:
            raise Refused('the pending triage file could not be read: %s' % exc)
        named_persona = stamped_value(pending, 'triage_persona')
        if named_persona is not None and named_persona != args.persona:
            raise Refused('the pending triage file names the persona %s, not %s: record the override first'
                          % (named_persona, args.persona))
        named_kind = stamped_value(pending, 'kind')
        if named_kind is not None and named_kind != args.kind:
            raise Refused('the pending triage file read the kind as %s, not %s' % (named_kind, args.kind))
        mark = stamped_value(pending, 'below_line')
        if isinstance(mark, dict):
            below = {'probability': mark.get('probability'), 'line': mark.get('line'),
                     'line_version': mark.get('line_version')}

    opening = fenced_block(FORMAT, OPENING_LABEL)
    if opening.count(PERSONA_SLOT) != 2:
        raise decide.CannotRun('the opening instruction in %s does not hold two %s slots' % (FORMAT, PERSONA_SLOT))
    opening = opening.replace(PERSONA_SLOT, str(persona_file), 1).replace(PERSONA_SLOT, str(memory_index), 1)
    references = Path(output_section.__file__).resolve().parent.parent / 'references'
    instruction = fenced_block(references / 'brief-instruction.md', INSTRUCTION_HEADING)
    for word in (output_section.HEADING, output_section.NONE):
        if '`%s`' % word not in instruction:
            raise decide.CannotRun('the brief instruction does not quote the output section\'s %r, as '
                                   'output_section.py reads it' % word)
    instruction = instruction.replace('<validator>', '`%s`' % validator.strip()).replace('<kinds>', kinds_text)

    values = [(keys['persona-name'], args.persona), (keys['act_kind'], kind_value), (keys['task'], args.task),
              (keys['member'], args.member), (keys['attempt'], attempt)]
    parts = [front_matter([(key, value) for key, value in values if key]), opening, task_text]
    if below is not None:
        sentence = fenced_block(FORMAT, BELOW_LABEL)
        for slot, value in (('<probability>', below['probability']), ('<line>', below['line']),
                            ('<version>', below['line_version'])):
            sentence = sentence.replace(slot, str(value))
        parts.append(sentence)
    parts.append('%s\n\n%s' % (capture.WRITE_SET_HEADING, '\n'.join(write_set)))
    parts.append(instruction)
    text = parts[0] + '\n' + '\n\n'.join(parts[1:]) + '\n'

    # Read back with the capture's own readers: the brief must give what was asked of it.
    meta = capture.frontmatter(text)
    if capture.lookup(meta, keys['member']) != args.member or capture.lookup(meta, keys['attempt']) != str(attempt):
        raise decide.CannotRun('the brief\'s front matter does not read back as member %s, attempt %s'
                               % (args.member, attempt))
    if capture.write_set_of(text) != write_set:
        raise decide.CannotRun('the brief\'s write set does not read back as %s' % write_set)
    for slot in (PERSONA_SLOT, '<validator>', '<kinds>', '<probability>', '<line>', '<version>'):
        if slot in text:
            raise decide.CannotRun('the brief still holds the placeholder %s' % slot)
    report = {'brief': str(out), 'member': args.member, 'attempt': attempt, 'persona': args.persona,
              'kind': args.kind, 'task': args.task,
              'front_matter': dict((key, value) for key, value in values if key),
              'persona_file': str(persona_file), 'memory_index': str(memory_index),
              'inputs': [path for path, _ in named], 'write_set': write_set, 'repository': repository,
              'below_line': below}
    return text, report


def main(argv=None):
    parser = argparse.ArgumentParser(description='Write one member\'s brief.')
    for name in ('--out', '--member', '--attempt', '--persona', '--persona-file', '--kind', '--task', '--body'):
        parser.add_argument(name, required=True)
    parser.add_argument('--write-set', action='append', required=True)
    parser.add_argument('--repository')
    parser.add_argument('--pending')
    parser.add_argument('--ledger')
    try:
        args = parser.parse_args(sys.argv[1:] if argv is None else argv)
    except SystemExit:
        return decide.fail(1, 'the arguments could not be read')
    try:
        decide.ledger_scripts()
        return_scripts()
        import capture_claude_code as capture
        import ledger
        import output_section
        import call_context
        args.ledger_folder = ledger.ledger_folder(args.ledger)
        text, report = compose(args, capture, output_section, call_context)
    except Refused as exc:
        return decide.fail(1, str(exc))
    except decide.CannotRun as exc:
        return decide.fail(2, str(exc))
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    try:
        with open(str(out), 'x', encoding='utf-8') as handle:
            handle.write(text)
    except FileExistsError:
        return decide.fail(1, 'the brief %s already exists: a brief is never overwritten' % out)
    print(json.dumps(report, indent=1, ensure_ascii=False))
    return 0


if __name__ == '__main__':
    sys.exit(main())
