"""Helpers the tests share: run a script, build a scratch project, take a manifest."""

import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
SKILL = ROOT / "skill"
SCRIPTS = SKILL / "scripts"
REFERENCES = SKILL / "references"

sys.path.insert(0, str(HERE))
import make_fixtures  # noqa: E402


def run(script, *args, cwd=None, stdin=None):
    """Run one of the skill's scripts; return the finished process, text decoded.

    A missing script fails the test outright. Python's own exit code for a missing file is 2, the
    same as a usage error, so without this a test of a refusal would hold on an empty implementation.
    """
    if not (SCRIPTS / script).is_file():
        raise AssertionError(f"{script} is not built: {SCRIPTS / script}")
    return subprocess.run(
        [sys.executable, str(SCRIPTS / script), *map(str, args)],
        cwd=cwd,
        input=stdin,
        capture_output=True,
        text=True,
        timeout=60,
    )


class ScratchCase(unittest.TestCase):
    """A test case that builds scratch projects in its own temporary folder."""

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="persona-judge-test-"))

    def tearDown(self):
        # Read-only copies need write permission back before removal.
        for path in sorted(self.tmp.rglob("*"), reverse=True):
            try:
                path.chmod(0o700 if path.is_dir() else 0o600)
            except OSError:
                pass
        shutil.rmtree(self.tmp, ignore_errors=True)

    def project(self, name):
        return make_fixtures.build(name, parent=self.tmp)

    def read_only(self, folder):
        """Make every file and folder under folder read-only; return folder."""
        for path in sorted(Path(folder).rglob("*"), reverse=True):
            path.chmod(0o500 if path.is_dir() else 0o400)
        Path(folder).chmod(0o500)
        return folder
