#!/usr/bin/env python3
"""Split a shell command into the parts the shell runs, and name each part's program.

    import commands
    for part in commands.parts('cd x && FOO=1 claude -p "a | b"'):
        part.program, part.words, part.assigned, part.fed

A command is split at ;, &&, ||, |, &, parentheses and new lines outside quotes. A here-document's
body is text fed to a program, not a command the shell runs, so it is set aside before the split and
handed to the part that reads it, never split itself. In each part, leading VAR=value assignments,
`env` and the shell words in `skip` are passed over, and the next word is the program, named by its
base name.

Each part is a Part:

  * `words`: the part's words, from its program on; empty when the part held only assignments;
  * `program`: the base name of the first word, or None;
  * `assigned`: the VAR=value assignments passed over, as a mapping;
  * `fed`: the bodies of the here-documents the part reads, in order.

A `$( )` substitution is its own part where it stands outside double quotes. Inside double quotes it
is one word of its part, as the quotes make it. A part opened by a compound command (`for`, `while`,
`until`, `if`, `case`, `select`, braces or parentheses) has `compound` true.

`reading(command, patterns, cwd)` reads a command for the model calls it makes, by cli-patterns.json, and
returns a Reading: its `sites`, each {how, program or host, where}, and its `notes`. Every rule is a reading of
text, with no model and no network; each is named in RULES, so a test can switch one off:

  * `wrapper`: the words in cli-patterns.json `wrappers` (`timeout`, `time`, `nice`, `xargs` and the rest), with
    their options and arguments, are passed over before the program, as assignments and `env` are;
  * `compound`: a loop's condition (`while`, `until`, `if`) is read as a part, and a `$( )` or backquoted
    substitution inside double quotes is read as a command of its own;
  * `heredoc`: a here-document body fed to a shell (`bash`, `sh`, `zsh`) is read as commands, and one fed to
    Python (`python`, `python3`, with `-` or nothing) is read as program text;
  * `script`: a part that runs a script file has the file read, to a depth of two, resolved against `cwd` as
    the command's own `cd` and assignments leave it. A shell script is read as commands; a Python script is a
    call where it passes a listed program to `subprocess` or `os.system`. A file that cannot be read is no
    match, and a note says why. A script naming SUBAGENT_LEDGER_SCRIPTS or SUBAGENT_LEDGER_DIR, or one in this
    folder, writes its own records, and is not matched;
  * `host`: Python program text naming a host in cli-patterns.json `model_hosts` is a call.

A site's `where` names the part's program and call marker, or the script's path, never the prompt. A part that
matches with no rule's help has `how` `direct`.
"""

import ast
import os
import re
import shlex

HEREDOC = re.compile(r"<<(-?)\s*(['\"]?)([A-Za-z_][A-Za-z0-9_]*)\2")
SEPARATORS = {';', '&&', '||', '|', '&', '|&', ';;', '(', ')', '((', '))', '{', '}'}
ASSIGNMENT = re.compile(r'^([A-Za-z_][A-Za-z0-9_]*)=(.*)$', re.S)
# Shell words that come before the program they run.
SKIP = ('do', 'then', 'else', 'elif', 'time', 'nohup', 'exec', 'command', '!')
# The rules reading() applies beyond the program after assignments and `env`; a test switches one off.
RULES = {'wrapper', 'compound', 'heredoc', 'script', 'host'}
# Shell words a part starts with when a compound command opens it.
COMPOUND_WORDS = ('for', 'while', 'until', 'if', 'case', 'select')
# The words passed over when the compound rule is on: a loop's or a test's condition is a command.
KEYWORDS = ('do', 'then', 'else', 'elif', '!', 'while', 'until', 'if')
OPENS = {'(', '((', '{'}
CLOSES = {')', '))', '}'}
ENDS = ('done', 'fi', 'esac')
SHELLS = ('bash', 'sh', 'zsh')
PYTHONS = ('python', 'python3')
DEPTH = 2
SCRIPT_LIMIT = 1000000
WHERE_LIMIT = 200
LEDGER_MARKERS = ('SUBAGENT_LEDGER_SCRIPTS', 'SUBAGENT_LEDGER_DIR')
HERE = os.path.dirname(os.path.realpath(__file__))
VARIABLE = re.compile(r'\$\{([A-Za-z_][A-Za-z0-9_]*)\}|\$([A-Za-z_][A-Za-z0-9_]*)')
RUNNERS = {'run', 'Popen', 'call', 'check_call', 'check_output', 'getoutput', 'getstatusoutput', 'system',
           'popen', 'create_subprocess_exec', 'create_subprocess_shell', 'execvp', 'execv', 'spawnvp'}


class Part:
    """One part of a command: its words, its program, its assignments and its here-document bodies."""

    def __init__(self, words, assigned, fed, compound=False):
        self.words = words
        self.program = os.path.basename(words[0]) if words else None
        self.assigned = assigned
        self.fed = fed
        self.compound = compound

    def __repr__(self):
        return 'Part(program=%r, words=%r)' % (self.program, self.words)


def parts(command, skip=SKIP):
    """The command's parts, in order, each a Part."""
    return list(_parts(command or '', tuple(skip or ())))


def strip_heredocs(command):
    """The command with each here-document's body taken out, and the bodies in order."""
    lines = (command or '').split('\n')
    kept, bodies = [], []
    at = 0
    while at < len(lines):
        line = lines[at]
        kept.append(line)
        at += 1
        for dash, _, word in HEREDOC.findall(line):
            body = []
            while at < len(lines):
                end = lines[at].lstrip('\t') if dash else lines[at]
                at += 1
                if end == word:
                    break
                body.append(lines[at - 1])
            bodies.append('\n'.join(body))
    return '\n'.join(kept), bodies


def unquoted_newlines(text):
    """The text with every new line outside quotes made a ';', so a line ends its command, and each comment (a
    '#' outside quotes that starts a word) taken out to the end of its line, so it does not swallow the lines
    after it once they are joined."""
    out, quote, escaped, comment = [], None, False, False
    for char in text:
        if comment:
            if char != '\n':
                continue
            comment = False
        if escaped:
            escaped = False
        elif char == '\\' and quote != "'":
            escaped = True
        elif quote:
            if char == quote:
                quote = None
        elif char in ('"', "'"):
            quote = char
        elif char == '#' and (not out or out[-1] in ' \t;&|()'):
            comment = True
            continue
        elif char == '\n':
            out.append(' ; ')
            continue
        out.append(char)
    return ''.join(out)


def tokens_of(text):
    """The shell's words and operators, quotes honoured; a split at spaces and operators if the
    quotes do not close."""
    lexer = shlex.shlex(text, posix=True, punctuation_chars=True)
    lexer.whitespace_split = True
    lexer.commenters = ''  # unquoted_newlines() has taken the comments out; a '#' left is inside a word
    try:
        return list(lexer)
    except ValueError:
        return re.split(r'\s+|(;|&&|\|\||\|)', text)


def _parts(command, skip):
    text, bodies = strip_heredocs(command)
    bodies = list(bodies)
    part = []
    depth = 0
    for token in tokens_of(unquoted_newlines(text)) + [';']:
        if token is None or token == '':
            continue
        if token not in SEPARATORS:
            part.append(token)
            continue
        opened = depth > 0
        if token in OPENS:
            depth += 1
        elif token in CLOSES:
            depth = max(depth - 1, 0)
        if not part:
            continue
        words = list(part)
        part = []
        fed = []
        if words[0] in COMPOUND_WORDS:
            depth += 1
        compound = opened or depth > 0 or words[0] in ENDS
        if words[0] in ENDS:
            depth = max(depth - 1, 0)
        for word in words:
            if word.startswith('<<') and not word.startswith('<<<'):
                if bodies:
                    fed.append(bodies.pop(0))
        assigned = {}
        while words and (ASSIGNMENT.match(words[0]) or words[0] == 'env' or words[0] in skip):
            match = ASSIGNMENT.match(words[0])
            if match:
                assigned[match.group(1)] = match.group(2)
            words.pop(0)
        yield Part(words, assigned, fed, compound)


# ---------------------------------------------------------------------------
# Reading a command for the model calls it makes
# ---------------------------------------------------------------------------

class Reading:
    """The sites a command makes a model call at, the pattern entry and words of each program site, and notes."""

    def __init__(self):
        self.sites = []
        self.calls = []
        self.notes = []

    def add(self, how, where, entry=None, words=None, host=None):
        site = {'how': how}
        if entry is not None:
            site['program'] = entry['program']
        else:
            site['host'] = host
        site['where'] = (where or '')[:WHERE_LIMIT]
        if site not in self.sites:
            self.sites.append(site)
            if entry is not None:
                self.calls.append((entry, list(words or [])))

    def note(self, text):
        if text not in self.notes:
            self.notes.append(text)


def reading(command, patterns, cwd=None, environ=None):
    """The model calls the command makes, by cli-patterns.json's rules: a Reading."""
    out = Reading()
    if isinstance(command, str) and command.strip():
        _read(command, patterns, out, cwd if isinstance(cwd, str) and cwd else None,
              os.environ if environ is None else environ, level=0, how=None, at=None, seen=frozenset())
    return out


def program_entry(words, patterns):
    """The cli-patterns.json entry whose call the words make, or None: the program by its base name, a call
    marker among its arguments, and none of the words under not_a_call."""
    if not words:
        return None
    program = os.path.basename(words[0])
    args = words[1:]
    for entry in patterns.get('patterns', []):
        if program != entry['program']:
            continue
        if any(word in patterns.get('not_a_call', []) for word in args):
            continue
        if any(word in entry['flags'] for word in args) or (args and args[0] in entry['subcommands']):
            return entry
    return None


def unwrap(words, wrappers):
    """(the words from the program a wrapper runs on, the wrappers passed over). A wrapper is passed over with its
    options (a word starting with '-', taking the next word too where `options_with_value` names it) and its own
    `arguments`; assignments after it, as `env` takes them, are passed over too."""
    table = dict((entry['name'], entry) for entry in wrappers or [] if isinstance(entry, dict) and entry.get('name'))
    words = list(words)
    passed = []
    while words:
        if ASSIGNMENT.match(words[0]):
            words.pop(0)
            continue
        entry = table.get(os.path.basename(words[0]))
        if entry is None:
            break
        passed.append(entry['name'])
        words.pop(0)
        with_value = entry.get('options_with_value') or []
        while words and words[0].startswith('-') and len(words[0]) > 1:
            option = words.pop(0)
            if option == '--':
                break
            if option in with_value and words:
                words.pop(0)
        for _ in range(int(entry.get('arguments') or 0)):
            if words and not ASSIGNMENT.match(words[0]):
                words.pop(0)
    return words, passed


def where_of(words, start, entry):
    """The part's words up to its call marker: any wrappers, the program and the marker, never the prompt.
    `start` is the program's place in `words`."""
    for at in range(start + 1, len(words)):
        if words[at] in entry['flags'] or (at == start + 1 and words[at] in entry['subcommands']):
            return ' '.join(words[:at + 1])
    return ' '.join(words[:start + 1])


def substitutions(word):
    """The bodies of the `$( )` and backquoted substitutions inside one word, outermost only."""
    out = []
    at = 0
    while at < len(word):
        if word.startswith('$(', at) and not word.startswith('$((', at):
            depth, end = 1, at + 2
            while end < len(word) and depth:
                if word[end] == '(':
                    depth += 1
                elif word[end] == ')':
                    depth -= 1
                end += 1
            out.append(word[at + 2:end - 1] if depth == 0 else word[at + 2:])
            at = end
        elif word[at] == '`':
            end = word.find('`', at + 1)
            out.append(word[at + 1:end] if end > 0 else word[at + 1:])
            at = len(word) if end < 0 else end + 1
        else:
            at += 1
    return [body for body in out if body.strip()]


def expand(word, assigned, environ):
    """A word with the command's own assignments, then the environment, put in for $NAME and ${NAME}."""
    def value(match):
        name = match.group(1) or match.group(2)
        found = assigned.get(name, environ.get(name))
        return found if isinstance(found, str) else match.group(0)
    return os.path.expanduser(VARIABLE.sub(value, word))


def arguments(words):
    """A part's arguments less its redirections: an operator made of <, > and & with the word after it."""
    out = []
    skip_next = False
    for word in words:
        if skip_next:
            skip_next = False
            continue
        if word and set(word) <= set('<>&'):
            skip_next = True
            continue
        out.append(word)
    return out


def script_of(words):
    """(the script a part runs, its kind: 'shell', 'python' or None to read from its first line), or (None, None).
    A script is run by a shell or Python with the path as its first argument, or named as the program: a path
    ending in .sh or .py, or starting with ./"""
    program = os.path.basename(words[0])
    if program in SHELLS + PYTHONS:
        for word in words[1:]:
            if word in ('-c', '-m', '-', '-s'):
                return None, None
            if word.startswith('-'):
                continue
            return word, ('shell' if program in SHELLS else 'python')
        return None, None
    if words[0].endswith('.sh'):
        return words[0], 'shell'
    if words[0].endswith('.py'):
        return words[0], 'python'
    if words[0].startswith('./'):
        return words[0], None
    return None, None


def _skip_words(rules):
    words = ('do', 'then', 'else', 'elif', '!')
    if 'compound' in rules:
        words += ('while', 'until', 'if')
    if 'wrapper' not in rules:
        words += ('time', 'nohup', 'exec', 'command')
    return words


def _read(command, patterns, out, cwd, environ, level, how, at, seen):
    """Read shell text into `out`. `how` is the rule that led here, if any; `at` is the script file the text came
    from, which every site found in it names."""
    rules = RULES
    here = cwd
    assigned = {}
    for part in parts(command, _skip_words(rules)):
        assigned.update(getattr(part, 'assigned', None) or {})
        full = part.words
        if not full and 'compound' in rules:
            for value in (getattr(part, 'assigned', None) or {}).values():
                for body in substitutions(value):
                    _read(body, patterns, out, here, environ, level, how or 'loop', at, seen)
        if not full:
            continue
        if full[0] == 'cd':
            target = expand(full[1], assigned, environ) if len(full) > 1 else os.path.expanduser('~')
            here = target if os.path.isabs(target) else (os.path.join(here, target) if here else None)
            continue
        words, passed = unwrap(full, patterns.get('wrappers')) if 'wrapper' in rules else (full, [])
        compound = getattr(part, 'compound', False) and 'compound' in rules
        if 'compound' in rules:
            for word in full[1:] + list((getattr(part, 'assigned', None) or {}).values()):
                for body in substitutions(word):
                    _read(body, patterns, out, here, environ, level, how or 'loop', at, seen)
        if not words:
            continue
        entry = program_entry(words, patterns)
        if entry is not None:
            kind = how or ('loop' if compound else 'wrapper' if passed else 'direct')
            out.add(kind, at or where_of(full, len(full) - len(words), entry), entry=entry, words=words)
            continue
        program = os.path.basename(words[0])
        fed = getattr(part, 'fed', None) or []
        if fed and 'heredoc' in rules:
            rest = [word for word in arguments(words[1:]) if word != '-' and not word.startswith('-')]
            if program in SHELLS and not rest:
                for body in fed:
                    _read(body, patterns, out, here, environ, level, how or 'heredoc', at, seen)
                continue
            if program in PYTHONS and not rest:
                for body in fed:
                    python_text(body, patterns, out, here, environ, level, how or 'heredoc',
                                at or 'here-document fed to %s' % program, seen)
                continue
        if 'script' in rules and level < DEPTH:
            path, kind = script_of([expand(word, assigned, environ) for word in words])
            if path:
                read_script(path, kind, patterns, out, here, environ, level, seen)


def read_script(path, kind, patterns, out, cwd, environ, level, seen):
    """Read a script file a part runs, at the next level: a shell script's commands, or a Python script's text."""
    full = path if os.path.isabs(path) else (os.path.join(cwd, path) if cwd else None)
    if full is None:
        out.note('script unread: %s: no working folder to resolve it against' % path)
        return
    full = os.path.normpath(full)
    if full in seen:
        return
    try:
        with open(full, encoding='utf-8', errors='replace') as handle:
            text = handle.read(SCRIPT_LIMIT)
    except OSError as exc:
        out.note('script unread: %s: %s' % (full, exc.strerror or type(exc).__name__))
        return
    seen = seen | {full}
    if os.path.dirname(os.path.realpath(full)) == HERE or any(marker in text for marker in LEDGER_MARKERS):
        out.note('script writes its own records: %s' % full)
        return
    if kind is None:
        first = text.split('\n', 1)[0]
        if first.startswith('#!') and 'python' in first:
            kind = 'python'
        elif first.startswith('#!') and any(shell in first for shell in SHELLS):
            kind = 'shell'
        else:
            return
    if kind == 'shell':
        _read(text, patterns, out, cwd, environ, level + 1, 'script', full, seen)
    else:
        python_text(text, patterns, out, cwd, environ, level + 1, 'script', full, seen)


def python_text(text, patterns, out, cwd, environ, level, how, where, seen):
    """Python program text: a call where it passes a listed program to subprocess or os.system, or names a host
    in model_hosts. A command string it passes is read as shell text, and a script it runs is read while the depth
    allows."""
    if 'host' in RULES:
        for entry in patterns.get('model_hosts', []):
            host = entry.get('host') if isinstance(entry, dict) else None
            if host and host in text:
                out.add('host', where, host=host)
    for words, line in subprocess_words(text):
        if line is not None:
            _read(line, patterns, out, cwd, environ, level, how, where, seen)
            continue
        entry = program_entry(words, patterns)
        if entry is not None:
            out.add(how, where, entry=entry, words=words)
            continue
        if 'script' in RULES and level < DEPTH:
            path, kind = script_of(words)
            if path:
                read_script(path, kind, patterns, out, cwd, environ, level, seen)


def subprocess_words(text):
    """[(words, None) or (None, a command line)] for each argument list or command string the Python text passes
    to subprocess, os.system and their kin, read with the ast module. A name is followed to the list or string
    assigned to it, and a list added to by `+` gives its leading list."""
    try:
        tree = ast.parse(text)
    except (SyntaxError, ValueError):
        return []
    named = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign) and len(node.targets) == 1 and isinstance(node.targets[0], ast.Name):
            named.setdefault(node.targets[0].id, node.value)

    def literal(node, depth=0):
        if depth > 3 or node is None:
            return None
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            return node.value
        if isinstance(node, (ast.List, ast.Tuple)):
            words = []
            for item in node.elts:
                if not (isinstance(item, ast.Constant) and isinstance(item.value, str)):
                    break
                words.append(item.value)
            return words
        if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Add):
            return literal(node.left, depth + 1)
        if isinstance(node, ast.Name):
            return literal(named.get(node.id), depth + 1)
        return None

    found = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call) or not node.args:
            continue
        func = node.func
        name = func.attr if isinstance(func, ast.Attribute) else func.id if isinstance(func, ast.Name) else None
        if name not in RUNNERS:
            continue
        value = literal(node.args[0])
        if isinstance(value, list) and value:
            found.append((value, None))
        elif isinstance(value, str) and value.strip():
            found.append(([], value))
    return found
