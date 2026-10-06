"""The skill's scripts write nothing into the skill folder, not even Python's bytecode cache.

A script that imports a sibling module, such as find.py importing questions.py, would leave __pycache__ in
skill/scripts/ unless it switches bytecode off first. Each script sets sys.dont_write_bytecode before such an import.
The test runs every script on a scratch copy of skill/, with nothing in the environment that switches bytecode off,
and checks the copy holds no __pycache__ afterwards. The control removes the setting from a second copy and expects
__pycache__ to appear, so the check can fail.
"""

import os
import re
import shutil
import subprocess
import sys
import unittest

from support import SKILL, ScratchCase

# Each script, with arguments that make it import its siblings and exit on its own.
RUNS = [
    ("find.py", "--help"),
    ("find.py", "-", "--format", "json"),
    ("check.py", "--help"),
    ("check.py", "-", "--format", "json"),
    ("report.py", "schema"),
    ("report.py", "--help"),
    ("questions.py",),
    ("guard.py", "--help"),
]
SETTING = "sys.dont_write_bytecode = True\n"


def scratch_skill(parent, name):
    """A copy of skill/ under parent, without any cache the real folder might hold."""
    copy = parent / name
    shutil.copytree(SKILL, copy, ignore=shutil.ignore_patterns("__pycache__"))
    return copy


def run_all(skill_dir, cwd):
    """Run every script in skill_dir/scripts with bytecode left on in the environment."""
    env = {k: v for k, v in os.environ.items() if k not in ("PYTHONDONTWRITEBYTECODE", "PYTHONPYCACHEPREFIX")}
    for script, *args in RUNS:
        subprocess.run([sys.executable, str(skill_dir / "scripts" / script), *args], input="You review code.\n",
                       capture_output=True, text=True, cwd=cwd, env=env, timeout=60)


def caches(skill_dir):
    return sorted(p.relative_to(skill_dir).as_posix() for p in skill_dir.rglob("__pycache__"))


class TestWritesNothing(ScratchCase):
    def test_every_script_sets_it_before_a_sibling_import(self):
        siblings = {p.stem for p in (SKILL / "scripts").glob("*.py")}
        for path in sorted((SKILL / "scripts").glob("*.py")):
            text = path.read_text(encoding="utf-8")
            # The first import of a sibling, at the top or inside a function.
            first = re.search(rf"(?m)^\s*import ({'|'.join(sorted(siblings))})\b", text)
            if first:
                with self.subTest(script=path.name):
                    self.assertTrue(SETTING in text[: first.start()], f"{path.name} imports a sibling first")

    def test_no_bytecode_in_the_skill(self):
        copy = scratch_skill(self.tmp, "skill")
        run_all(copy, self.tmp)
        self.assertEqual(caches(copy), [])

    def test_control_without_the_setting(self):
        copy = scratch_skill(self.tmp, "skill")
        for path in (copy / "scripts").glob("*.py"):
            path.write_text(path.read_text(encoding="utf-8").replace(SETTING, ""), encoding="utf-8")
        run_all(copy, self.tmp)
        self.assertEqual(caches(copy), ["scripts/__pycache__"])


if __name__ == "__main__":
    unittest.main()
