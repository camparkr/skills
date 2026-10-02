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
