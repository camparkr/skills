"""Shared reader for persona-judge: reads a persona file into its lines, frontmatter, body and bound parts.

The other scripts import this module; it is not run on its own. It reads Markdown files with optional
YAML frontmatter, and Codex agent files in TOML, whose developer_instructions are their prose.

Frontmatter is read by a minimal reader of top-level keys: plain, quoted and folded scalars, inline
lists and block lists. A key it cannot read, such as a nested mapping, is kept in `unparsed` and named
there, so a check that needs it is not scored rather than guessed.
"""

import os
import re
import tomllib
from dataclasses import dataclass, field

# The label a file read from standard input carries in every output.
SESSION_TEXT = "<session text>"

# Bound parts: the settings and named code a harness applies, as the union of the fields recorded for
# Claude Code, Gemini CLI and Codex (persona synthesis, conclusion 3; build specification §3a).
BOUND_PART_FIELDS = (
    "tools",
    "disallowedTools",
    "permissionMode",
    "hooks",
    "mcpServers",
    "mcp_servers",
    "model",
    "temperature",
    "max_turns",
    "sandbox_mode",
    "skills",
)

# The field that holds a Codex agent's prose.
TOML_PROSE_FIELD = "developer_instructions"

# A path a line names: in backticks, or as a Markdown link's target, ending in a file extension of one to
# five letters or digits (build specification §3c, the missing-path kind).
BACKTICK_PATH = re.compile(r"`([^`\s]+\.[A-Za-z0-9]{1,5})`")
LINK_PATH = re.compile(r"\]\(([^)\s#]+\.[A-Za-z0-9]{1,5})(?:#[^)]*)?\)")
# Characters that make a backticked string a pattern, a placeholder or an address rather than a path
# (build specification §3e, adopted from round 1).
NOT_A_PATH = re.compile(r"[*?<>{}$|]|://|^mailto:")
# The line that opens or closes a fenced code block; what lies between is an example, not an instruction.
FENCE = re.compile(r"^\s*(```|~~~)")


def named_paths(text):
    """The paths a line names, in backticks and then as link targets, skipping patterns and placeholders."""
    found = [m.group(1) for m in BACKTICK_PATH.finditer(text)] + [m.group(1) for m in LINK_PATH.finditer(text)]
    return [ref for ref in found if not NOT_A_PATH.search(ref)]


def outside_fences(body):
    """The (line number, text) pairs of a body that lie outside fenced code blocks."""
    inside = False
    for n, text in body:
        if FENCE.match(text):
            inside = not inside
            continue
        if not inside:
            yield n, text


# The mask (build specification §3c, Sophos, 3 October 2026): quoted and example text is not the file's own
# instruction. Fenced code, Markdown block quotes and quoted spans are replaced by spaces before any check reads
# the body, so every line keeps its number and its length.
BLOCK_QUOTE = re.compile(r"^\s*>")
# A list item starts a new paragraph: a bullet or a number, then a space.
LIST_ITEM = re.compile(r"^\s*([-*+]|\d+[.)])\s")
# Opening marks and, for each, the marks that close it: single marks first, since Australian English quotes with
# single marks and keeps double marks for a quotation within a quotation (QUOT-001, QUOT-002).
OPENING = {"'": "'’", "‘": "'’", '"': '"”', "“": '"”'}
# What may stand before an opening mark, and after a closing one, besides a space or the paragraph's edge.
BEFORE_OPENING = "([:"
AFTER_CLOSING = ".,;:!?)]"


def _apostrophe(text, i):
    """A mark with a letter on both sides, as in harness's or don't, neither opens nor closes."""
    return 0 < i < len(text) - 1 and text[i - 1].isalpha() and text[i + 1].isalpha()


def _opens(text, i):
    if text[i] not in OPENING or _apostrophe(text, i):
        return False
    before_ok = i == 0 or text[i - 1].isspace() or text[i - 1] in BEFORE_OPENING
    return before_ok and i + 1 < len(text) and not text[i + 1].isspace()


def _closes(text, i, marks):
    if text[i] not in marks or _apostrophe(text, i):
        return False
    after_ok = i == len(text) - 1 or text[i + 1].isspace() or text[i + 1] in AFTER_CLOSING
    return i > 0 and not text[i - 1].isspace() and after_ok


def mask_spans(text):
    """Text with each quoted span, its marks included, replaced by spaces; line breaks are kept. A span runs
    from an opening mark to the next closing mark of the same kind; an opening with no closing opens nothing."""
    chars = list(text)
    i = 0
    while i < len(text):
        if _opens(text, i):
            marks = OPENING[text[i]]
            j = next((k for k in range(i + 1, len(text)) if _closes(text, k, marks)), None)
            if j is not None:
                for k in range(i, j + 1):
                    if chars[k] != "\n":
                        chars[k] = " "
                i = j + 1
                continue
        i += 1
    return "".join(chars)


def paragraphs(body):
    """The body's paragraphs, as lists of indexes into body: runs of non-blank lines, a list item starting a
    new one."""
    out, current = [], []
    for i, (_, text) in enumerate(body):
        if not text.strip():
            if current:
                out.append(current)
            current = []
            continue
        if LIST_ITEM.match(text) and current:
            out.append(current)
            current = []
        current.append(i)
    if current:
        out.append(current)
    return out


def masked_body(pf):
    """The body as (line number, text) with fenced code, block quotes and quoted spans replaced by spaces."""
    lines = [text for _, text in pf.body]
    inside = False
    for i, text in enumerate(lines):
        if FENCE.match(text):
            inside = not inside
            lines[i] = " " * len(text)
        elif inside or BLOCK_QUOTE.match(text):
            lines[i] = " " * len(text)
    body = list(zip([n for n, _ in pf.body], lines))
    for para in paragraphs(body):
        masked = mask_spans("\n".join(lines[i] for i in para)).split("\n")
        for i, text in zip(para, masked):
            lines[i] = text
    return list(zip([n for n, _ in pf.body], lines))


# A sentence tells the agent to read a path only when a read verb in it is addressed to the agent as an instruction
# (specification §3c, Sophos, 3 October 2026, option 2). The verbs, in their base form only.
BASE_VERBS = ("read", "open", "load", "see", "consult", "follow", "refer", "look")
# After 'you have' or "you've", the past participle counts instead.
PARTICIPLES = ("read", "opened", "loaded", "seen", "consulted", "followed", "referred", "looked")
# At most one of these may stand before a verb that opens a sentence or follows its opening clause.
LEADING_WORDS = ("always", "first", "then", "also", "next", "now", "only")
# A sentence that opens with one of these has an opening clause, ended by its first comma.
CLAUSE_OPENERS = ("before", "after", "when", "whenever", "once", "if", "until", "while", "as soon as")
# The modals that may stand between 'you' and the verb.
MODALS = ("must", "should", "can", "may", "will", "do", "need to", "have to", "ought to")

_SENTENCE_MARKER = re.compile(r"^([-*+]|\d+\.)\s+")
_EMPHASIS = "*_"
_LEADING = re.compile(r"^(?:" + "|".join(LEADING_WORDS) + r")\b,?\s*", re.IGNORECASE)
_OPENER = re.compile(r"^(?:" + "|".join(o.replace(" ", r"\s+") for o in CLAUSE_OPENERS) + r")\b", re.IGNORECASE)
_FIRST_VERB = re.compile(r"^(?:" + "|".join(BASE_VERBS) + r")(?![\w'’-])", re.IGNORECASE)
_AFTER_YOU = re.compile(
    r"\b(?:please|you(?:\s+(?:" + "|".join(m.replace(" ", r"\s+") for m in MODALS) + r"))?)\s+(?:"
    + "|".join(BASE_VERBS) + r")(?![\w'’-])",
    re.IGNORECASE,
)
_AFTER_YOU_HAVE = re.compile(
    r"\b(?:you\s+have|you[’']ve)\s+(?:" + "|".join(PARTICIPLES) + r")(?![\w'’-])", re.IGNORECASE
)


BACKTICKED = re.compile(r"`([^`\n]+)`")
LINK_TARGET = re.compile(r"\]\(([^)\s]+)\)")
# A path holds a / or ends in a file extension of one to five letters or digits.
PATH_SHAPE = re.compile(r"/|\.[A-Za-z0-9]{1,5}$")


def sentences(text):
    """(start, end) of each sentence in a paragraph's text, split at . ! ? or ; followed by a space or line
    break, with backticked text held whole."""
    out, start, in_tick = [], 0, False
    for i, c in enumerate(text):
        if c == "`":
            in_tick = not in_tick
        elif not in_tick and c in ".!?;" and (i + 1 == len(text) or text[i + 1].isspace()):
            out.append((start, i + 1))
            start = i + 1
    if start < len(text):
        out.append((start, len(text)))
    return out


def _verb_first(text):
    """Whether text starts with a base read verb, after emphasis marks and at most one leading word."""
    text = text.lstrip().lstrip(_EMPHASIS).lstrip()
    text = _LEADING.sub("", text, count=1).lstrip(_EMPHASIS).lstrip()
    return bool(_FIRST_VERB.match(text))


def addressed(sentence):
    """Whether a sentence tells the agent to read: a base read verb first in it, first after its opening clause,
    or after 'you', a modal or 'please' (a participle after 'you have'). Backticked text and link targets are
    read as names, not words."""
    text = LINK_TARGET.sub("]", BACKTICKED.sub("CODE", sentence)).strip()
    text = _SENTENCE_MARKER.sub("", text, count=1).lstrip(_EMPHASIS).lstrip()
    if _verb_first(text):
        return True
    if _OPENER.match(text) and "," in text and _verb_first(text.split(",", 1)[1]):
        return True
    return bool(_AFTER_YOU.search(text) or _AFTER_YOU_HAVE.search(text))


def _paths_in(text):
    """(offset, path) for each path in text, in backticks or as a link target, as §3c shapes a pointer."""
    found = []
    for m in BACKTICKED.finditer(text):
        ref = m.group(1)
        if " " in ref or "\t" in ref:  # a command line, not a path
            continue
        found.append((m.start(), ref))
    for m in LINK_TARGET.finditer(text):
        found.append((m.start(), m.group(1).split("#", 1)[0]))
    return [(o, r) for o, r in found if r and PATH_SHAPE.search(r) and not NOT_A_PATH.search(r)]


def pointers(pf):
    """(line number, path) for each pointer in the body: a path in a sentence that tells the agent to read it, as
    addressed() reads it, with the mask applied. A list item also counts when the line ending in a colon that
    introduces its list counts."""
    masked = masked_body(pf)
    lines = [t for _, t in masked]
    numbers = [n for n, _ in masked]
    out = []
    paras = paragraphs(masked)
    para_of = {i: k for k, para in enumerate(paras) for i in para}
    for para in paras:
        text = "\n".join(lines[i] for i in para)
        offsets = []  # the offset at which each of the paragraph's lines starts
        pos = 0
        for i in para:
            offsets.append(pos)
            pos += len(lines[i]) + 1
        introduced = False
        if LIST_ITEM.match(lines[para[0]]):
            # The line just before the list: skip back over blank lines and the list's earlier items.
            j = para[0] - 1
            while j >= 0 and (not lines[j].strip() or LIST_ITEM.match(lines[paras[para_of[j]][0]])):
                j -= 1
            if j >= 0 and lines[j].rstrip().endswith(":"):
                intro = paras[para_of[j]]
                intro_text = "\n".join(lines[i] for i in intro)
                last = sentences(intro_text)[-1]
                introduced = addressed(intro_text[last[0]:last[1]])
        for start, end in sentences(text):
            sentence = text[start:end]
            if not (introduced or addressed(sentence)):
                continue
            for offset, ref in _paths_in(sentence):
                at = start + offset
                row = max(r for r, o in enumerate(offsets) if o <= at)
                out.append((numbers[para[row]], ref))
    return out


def resolve_up(ref, folder, root):
    """The absolute path a pointer names when it exists in the file's folder or any folder above it, up to the
    project root (specification §3c); otherwise None."""
    ref = ref[2:] if ref.startswith("./") else ref
    if ref.startswith("~"):
        found = os.path.expanduser(ref)
        return found if os.path.exists(found) else None
    if os.path.isabs(ref):
        return ref if os.path.exists(ref) else None
    root = os.path.abspath(root)
    current = os.path.abspath(folder)
    while True:
        candidate = os.path.join(current, ref)
        if os.path.exists(candidate):
            return os.path.normpath(candidate)
        if current == root or os.path.dirname(current) == current or not (current + os.sep).startswith(root + os.sep):
            break
        current = os.path.dirname(current)
    candidate = os.path.join(root, ref)
    return os.path.normpath(candidate) if os.path.exists(candidate) else None


def resolve(ref, folder, root):
    """The absolute path a named path refers to when it exists, from the file's folder or the project root;
    otherwise None."""
    ref = ref[2:] if ref.startswith("./") else ref
    if ref.startswith("~"):
        candidates = [os.path.expanduser(ref)]
    elif os.path.isabs(ref):
        candidates = [ref]
    else:
        candidates = [os.path.join(folder, ref), os.path.join(root, ref)]
    for c in candidates:
        if os.path.exists(c):
            return os.path.normpath(c)
    return None


class PersonaError(Exception):
    """A file that cannot be read; the message says what to do about it."""


@dataclass
class PersonaFile:
    path: str
    lines: list
    frontmatter: dict = field(default_factory=dict)
    unparsed: list = field(default_factory=list)
    body: list = field(default_factory=list)  # (line number, text) pairs
    fmt: str = "markdown"
    folder: str = "."

    @property
    def empty(self):
        return not any(line.strip() for line in self.lines)

    @property
    def bound_parts(self):
        """The bound-part fields present, in the order the file gives them."""
        return [k for k in self.frontmatter if k in BOUND_PART_FIELDS] + [
            k for k in self.unparsed if k in BOUND_PART_FIELDS and k not in self.frontmatter
        ]

    def field_line(self, name):
        """The number of the line where a frontmatter or TOML field is set, or None."""
        key = re.compile(rf"^{re.escape(name)}\s*[:=]")
        for n, text in enumerate(self.lines, start=1):
            if key.match(text):
                return n
            if self.fmt == "markdown" and n > 1 and text.strip() in ("---", "..."):
                return None
        return None

    def field_text(self, name):
        """A field's value as one string (lists joined with ', '), or None when absent or empty."""
        if name not in self.frontmatter:
            return None
        value = self.frontmatter[name]
        if isinstance(value, list):
            value = ", ".join(str(v) for v in value)
        elif isinstance(value, dict):
            value = ", ".join(str(k) for k in value)
        value = "" if value is None else str(value)
        return value if value.strip() else None


def _unquote(value):
    value = value.strip()
    if len(value) >= 2 and value[0] == value[-1] and value[0] in "'\"":
        inner = value[1:-1]
        return inner.replace("''", "'") if value[0] == "'" else inner.replace('\\"', '"')
    return value


def _inline_list(value):
    inner = value.strip()[1:-1].strip()
    if not inner:
        return []
    return [_unquote(part) for part in re.split(r",(?=(?:[^'\"]|'[^']*'|\"[^\"]*\")*$)", inner)]


def _strip_comment(value):
    """Drop a trailing ' # comment' from an unquoted scalar."""
    if value[:1] in "'\"":
        return value
    return re.sub(r"\s+#.*$", "", value)


def parse_frontmatter(lines):
    """Read top-level keys from frontmatter lines; return (fields, unparsed keys)."""
    fields, unparsed = {}, []
    i = 0
    key_re = re.compile(r"^([A-Za-z_][\w.-]*)\s*:(.*)$")
    while i < len(lines):
        line = lines[i]
        if not line.strip() or line.lstrip().startswith("#"):
            i += 1
            continue
        m = key_re.match(line)
        if not m:
            i += 1
            continue
        key, rest = m.group(1), _strip_comment(m.group(2).strip())
        # Indented lines that belong to this key.
        j = i + 1
        block = []
        while j < len(lines) and (not lines[j].strip() or lines[j][:1] in (" ", "\t", "-")):
            if lines[j][:1] == "-" and not lines[j].startswith("- ") and lines[j].strip() != "-":
                break
            block.append(lines[j])
            j += 1
        while block and not block[-1].strip():
            block.pop()
        if rest in (">", ">-", ">+", "|", "|-", "|+"):
            parts = [b.strip() for b in block]
            if rest.startswith(">"):
                fields[key] = " ".join(p for p in parts if p)
            else:
                fields[key] = "\n".join(parts)
        elif rest.startswith("[") and rest.endswith("]"):
            fields[key] = _inline_list(rest)
        elif rest == "" and block and all(b.strip().startswith("- ") or not b.strip() for b in block):
            items = [b.strip()[2:].strip() for b in block if b.strip()]
            if any(re.match(r"^[\w.-]+\s*:", item) for item in items):
                unparsed.append(key)
            else:
                fields[key] = [_unquote(item) for item in items]
        elif rest == "" and block:
            unparsed.append(key)
        elif rest.startswith("{"):
            unparsed.append(key)
        else:
            value = _unquote(rest)
            # A plain scalar continued on indented lines.
            if block and rest[:1] not in "'\"":
                value = " ".join([value] + [b.strip() for b in block if b.strip()])
            fields[key] = value
        i = j
    return fields, unparsed


def _from_markdown(path, text, folder):
    lines = text.splitlines()
    pf = PersonaFile(path=path, lines=lines, folder=folder)
    start = 0
    if lines and lines[0].strip() == "---":
        for n in range(1, len(lines)):
            if lines[n].strip() in ("---", "..."):
                pf.frontmatter, pf.unparsed = parse_frontmatter(lines[1:n])
                start = n + 1
                break
    pf.body = [(n + 1, lines[n]) for n in range(start, len(lines))]
    return pf


def _from_toml(path, text, folder):
    lines = text.splitlines()
    pf = PersonaFile(path=path, lines=lines, fmt="toml", folder=folder)
    try:
        data = tomllib.loads(text)
    except tomllib.TOMLDecodeError as exc:
        raise PersonaError(f"cannot read {path}: the TOML does not parse ({exc}); check the file's syntax")
    pf.frontmatter = {k: v for k, v in data.items() if k != TOML_PROSE_FIELD}
    prose = data.get(TOML_PROSE_FIELD, "")
    if isinstance(prose, str):
        # Map each prose line to the file line that holds it, searching forward in order.
        cursor = 0
        for raw in prose.splitlines():
            for n in range(cursor, len(lines)):
                if raw.strip() and raw.strip() in lines[n]:
                    pf.body.append((n + 1, lines[n]))
                    cursor = n + 1
                    break
    return pf


def read_text(text, label=SESSION_TEXT, folder=None):
    """Read persona text given directly, such as text pasted into a session."""
    folder = folder or os.getcwd()
    stripped = text.lstrip()
    if re.match(r'^[A-Za-z_][\w-]*\s*=\s*["\'\[{0-9tf]', stripped) and TOML_PROSE_FIELD in text:
        return _from_toml(label, text, folder)
    return _from_markdown(label, text, folder)


def read_path(path, display=None):
    """Read a persona file from disk; raise PersonaError with a message saying what to do."""
    path = os.fspath(path)
    display = display or path.replace(os.sep, "/")
    try:
        with open(path, "rb") as fh:
            raw = fh.read()
    except FileNotFoundError:
        raise PersonaError(f"cannot read {display}: no such file; check the path")
    except IsADirectoryError:
        raise PersonaError(f"cannot read {display}: it is a folder; name a file, or let find.py search it")
    except PermissionError:
        raise PersonaError(f"cannot read {display}: permission denied; check the path or its permissions")
    except OSError as exc:
        raise PersonaError(f"cannot read {display}: {exc.strerror}; check the path or its permissions")
    try:
        text = raw.decode("utf-8-sig")
    except UnicodeDecodeError:
        raise PersonaError(f"cannot read {display}: it is not UTF-8 text; a persona file is text")
    folder = os.path.dirname(os.path.abspath(path))
    if path.endswith(".toml"):
        return _from_toml(display, text, folder)
    return _from_markdown(display, text, folder)
