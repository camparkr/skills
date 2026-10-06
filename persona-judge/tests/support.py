"""Helpers the tests share: run a script, build a scratch project, take a manifest.

The tests import the skill's scripts in their own process, so this module switches bytecode off before any test can:
otherwise the imports would leave __pycache__ in skill/scripts/, a file the skill must never write.
"""

import sys

sys.dont_write_bytecode = True

import shutil  # noqa: E402
import subprocess  # noqa: E402
import tempfile  # noqa: E402
import unittest  # noqa: E402
from pathlib import Path  # noqa: E402

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
SKILL = ROOT / "skill"
# The files only the Claude Code plugin uses: its agents, its hook and the other harnesses' agent files.
PLUGIN = ROOT / "plugin"
SCRIPTS = SKILL / "scripts"
REFERENCES = SKILL / "references"
STEPS = SKILL / "steps"
# The review questions, in parts: joined in the order questions.py's list gives, they make the one text it reads.
QUESTIONS = REFERENCES / "questions"
# sample-review.md, pinned by its SHA-256 hash (141 lines); every test that reads its content checks the hash
# first, so an edit to the sample shows as a moved file rather than as a wrong comparison.
SAMPLE = REFERENCES / "sample-review.md"
SAMPLE_SHA256 = "21190275a39429b967c1179af4b0847073989f6728e52dfe9f8c0c5cea81d69c"


def sample_text():
    """The sample's text, after checking its hash: a moved sample stops the test instead of being compared."""
    import hashlib

    data = SAMPLE.read_bytes()
    got = hashlib.sha256(data).hexdigest()
    if got != SAMPLE_SHA256:
        raise AssertionError(f"sample-review.md has moved: SHA-256 {got}, expected {SAMPLE_SHA256}")
    return data.decode("utf-8")



def part_names():
    """The names of the review questions' parts, in order, from questions.py's one list of them."""
    sys.path.insert(0, str(SCRIPTS))
    import questions

    return list(questions.PARTS)


def question_parts(folder=QUESTIONS):
    """The part files of the review questions in folder, in the order questions.py's list gives."""
    return [Path(folder) / name for name in part_names()]


def questions_text(folder=QUESTIONS):
    """The review questions as one text, joined here and not by questions.py: each part stripped of leading and
    trailing newlines, one blank line between them, a newline at the end."""
    return "\n\n".join(p.read_text(encoding="utf-8").strip("\n") for p in question_parts(folder)) + "\n"


def part_holding(folder, old):
    """The one part file in folder that holds old; a test that plants a fault edits that part alone."""
    holding = [p for p in question_parts(folder) if old in p.read_text(encoding="utf-8")]
    if len(holding) != 1:
        raise AssertionError(f"{len(holding)} parts hold {old!r}; expected exactly one")
    return holding[0]


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
