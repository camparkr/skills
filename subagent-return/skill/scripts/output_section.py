#!/usr/bin/env python3
"""The output section's parser: the files a member's report claims as its output, and nothing else.

    python3 output_section.py < report.txt      (prints the reading as one JSON object)

A report ends with an output section. The section is the text after the last line of the report that reads exactly
`## Output`, up to the next line that begins with `#`, or to the end of the report. Each non-blank line in it is one
claim: a path, absolute or relative to the member's working root, or the single word `none`. A line may open with
`- ` or `* `, and the path may be wrapped in one pair of backticks; the parser removes the marker, then the backticks,
then the spaces around what is left. `none` is read only in lower case. A line is blank when it holds only spaces or
tabs. A path named anywhere else in the report is not a claim. `references/output-section.md` states the grammar in
prose; where the two differ, one of them is wrong, and the difference is reported.

parse() returns a Section, whose `state` is one of:

  * `missing`: no line reads exactly `## Output`;
  * `malformed`: the section has no non-blank line, or holds `none` beside a path (`reason` says which);
  * `none`: the section reads `none` and nothing else;
  * `claims`: one or more paths, in `claims`, in order, each once.

The parser asks no semantic question, reads no file and judges no path. The triage skill imports it to check a brief's
instruction against the grammar; the return check imports it to read a report. Standard library only.
"""

import json
import sys

HEADING = '## Output'
NONE = 'none'
MARKERS = ('- ', '* ')
MISSING = 'missing'
MALFORMED = 'malformed'
NONE_STATE = 'none'
CLAIMS = 'claims'
NO_LINE = 'no non-blank line'
NONE_BESIDE_PATH = '`none` beside a path'


class Section(object):
    """One report's output section, as parse() read it."""

    def __init__(self, state, claims=None, reason=None):
        self.state = state
        self.claims = list(claims or [])
        self.reason = reason

    def as_dict(self):
        return {'state': self.state, 'claims': self.claims, 'reason': self.reason}


def is_blank(line):
    return line.strip(' \t') == ''


def claim_of(line):
    """The claim one non-blank line of the section holds: the marker, then one pair of backticks, then the spaces
    around what is left, removed."""
    item = line.strip(' \t')
    for marker in MARKERS:
        if item.startswith(marker):
            item = item[len(marker):]
            break
    if len(item) >= 2 and item.startswith('`') and item.endswith('`'):
        item = item[1:-1]
    return item.strip(' \t')


def section_lines(text):
    """The lines of the section, or None where the report has none."""
    lines = (text or '').splitlines()
    starts = [at for at, line in enumerate(lines) if line == HEADING]
    if not starts:
        return None
    out = []
    for line in lines[starts[-1] + 1:]:
        if line.startswith('#'):
            break
        out.append(line)
    return out


def parse(text):
    """Read the output section of the report `text`. Never raises on text; a value that is not text has no section."""
    if not isinstance(text, str):
        return Section(MISSING)
    lines = section_lines(text)
    if lines is None:
        return Section(MISSING)
    claims = [claim_of(line) for line in lines if not is_blank(line)]
    claims = [claim for claim in claims if claim]
    if not claims:
        return Section(MALFORMED, reason=NO_LINE)
    if any(claim == NONE for claim in claims) and any(claim != NONE for claim in claims):
        return Section(MALFORMED, reason=NONE_BESIDE_PATH)
    paths = []
    for claim in claims:
        if claim != NONE and claim not in paths:
            paths.append(claim)
    if not paths:
        return Section(NONE_STATE)
    return Section(CLAIMS, claims=paths)


def main(argv=None):
    text = sys.stdin.read()
    print(json.dumps(parse(text).as_dict(), ensure_ascii=False))
    return 0


if __name__ == '__main__':
    sys.exit(main())
