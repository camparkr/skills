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
is one word of its part, as the quotes make it.
"""

import os
import re
import shlex

HEREDOC = re.compile(r"<<(-?)\s*(['\"]?)([A-Za-z_][A-Za-z0-9_]*)\2")
SEPARATORS = {';', '&&', '||', '|', '&', '|&', ';;', '(', ')', '((', '))', '{', '}'}
ASSIGNMENT = re.compile(r'^([A-Za-z_][A-Za-z0-9_]*)=(.*)$', re.S)
# Shell words that come before the program they run.
SKIP = ('do', 'then', 'else', 'elif', 'time', 'nohup', 'exec', 'command', '!')


class Part:
    """One part of a command: its words, its program, its assignments and its here-document bodies."""

    def __init__(self, words, assigned, fed):
        self.words = words
        self.program = os.path.basename(words[0]) if words else None
        self.assigned = assigned
        self.fed = fed

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
    """The text with every new line outside quotes made a ';', so a line ends its command."""
    out, quote, escaped = [], None, False
    for char in text:
        if escaped:
            escaped = False
        elif char == '\\' and quote != "'":
            escaped = True
        elif quote:
            if char == quote:
                quote = None
        elif char in ('"', "'"):
            quote = char
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
    try:
        return list(lexer)
    except ValueError:
        return re.split(r'\s+|(;|&&|\|\||\|)', text)


def _parts(command, skip):
    text, bodies = strip_heredocs(command)
    bodies = list(bodies)
    part = []
    for token in tokens_of(unquoted_newlines(text)) + [';']:
        if token is None or token == '':
            continue
        if token not in SEPARATORS:
            part.append(token)
            continue
        if not part:
            continue
        words = list(part)
        part = []
        fed = []
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
        yield Part(words, assigned, fed)
