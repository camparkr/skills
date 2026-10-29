#!/usr/bin/env python3
"""A stand-in front-matter validator for the tests, with the exits and texts a real one gives.

    python3 validator.py <path>

Exit 0 and 'Validated 1 files: 1 pass, 0 fail' for a file whose front matter opens the file and carries `type`.
Exit 1 for every other case, as the validator dry run 10 read does, each with its own first line on standard error:
a path that does not exist ('Path not found'), a path under an `excluded/` folder ('0 files examined'), a run with
STAND_IN_VALIDATOR_BROKEN set ('VISIBLE ERROR', the validator's own inputs missing), a file with no front matter, and
front matter with no `type`.
"""

import os
import sys

path = sys.argv[-1] if len(sys.argv) > 1 else ''
if os.environ.get('STAND_IN_VALIDATOR_BROKEN'):
    sys.stderr.write('VISIBLE ERROR: cannot read the profile at /nowhere/profile.md\n')
    sys.exit(1)
if not os.path.exists(path):
    sys.stderr.write('ERROR: Path not found: %s\n' % path)
    sys.exit(1)
if '%sexcluded%s' % (os.sep, os.sep) in path:
    sys.stderr.write('ERROR: 0 files examined; a clean result over zero items is an error (1 skipped)\n')
    sys.exit(1)
with open(path, encoding='utf-8', errors='replace') as handle:
    text = handle.read()
if not text.startswith('---'):
    sys.stderr.write("ERROR: File does not start with '---' (no frontmatter)\n")
    sys.exit(1)
front = text.split('---', 2)[1] if text.count('---') >= 2 else ''
if 'type:' not in front:
    sys.stderr.write("ERROR: Missing required field: 'type'\n")
    sys.exit(1)
print('Validated 1 files: 1 pass, 0 fail')
sys.exit(0)
