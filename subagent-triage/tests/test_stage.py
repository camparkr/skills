"""Tests for stage.py: the task's stage, read exactly from named files only (R-5, K-2a; TC-4).

A build specification exists for a task when a file named `*-build-spec.md` under a build folder carries the task's
id. A ratified specification exists when a file named `*-surviving-spec.md` or `*-architectural-spec*.md` under a
ratified folder carries the task's id and status `ratified`. Nothing else counts. The folders are arguments; the
fixtures keep their task id and status under `meta.`, so the key options are exercised too.

Run from the skill's folder:  python3 -m unittest discover -s tests
"""

import json
import subprocess
import sys
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
SCRIPTS = HERE.parent / 'skill' / 'scripts'
SCRIPT = SCRIPTS / 'stage.py'
TREE = HERE / 'fixtures' / 'stage'
KEYS = ['--task-key', 'meta.task_id', '--status-key', 'meta.status']
ROOTS = ['--build-root', str(TREE / 'build-specs'), '--ratified-root', str(TREE / 'specs'),
         '--ratified-root', str(TREE / 'projects' / '*' / 'docs'),
         '--ratified-root', str(TREE / 'projects' / '*' / 'specs')]
BUILD = 'build specification'
RATIFIED = 'ratified specification'


class StageTests(unittest.TestCase):

    def read(self, task, roots=ROOTS, keys=KEYS):
        arguments = (['--task', task] if task is not None else []) + list(roots) + list(keys)
        done = subprocess.run([sys.executable, str(SCRIPT)] + arguments, capture_output=True, text=True, timeout=60)
        try:
            out = json.loads(done.stdout)
        except ValueError:
            self.fail('no JSON on stdout (exit %s): %s %s' % (done.returncode, done.stdout, done.stderr))
        self.assertEqual(done.returncode, 0, out)
        return out

    def names(self, paths):
        return sorted(Path(path).name for path in paths)

    def test_tc4_empty_a_task_with_no_specification_reads_unrecorded(self):
        out = self.read('zeta')
        self.assertEqual(out['stage'], 'unrecorded (no specification found for zeta)')
        self.assertEqual(out['found'], {'build': [], 'ratified': []})

    def test_tc4_likeness_a_findings_file_and_a_proposal_marked_ratified_are_not_counted(self):
        out = self.read('epsilon')
        self.assertEqual(out['stage'], 'unrecorded (no specification found for epsilon)')
        self.assertEqual(out['found'], {'build': [], 'ratified': []})

    def test_a_build_specification_gives_the_build_stage(self):
        out = self.read('alpha')
        self.assertEqual(out['stage'], BUILD)
        self.assertEqual(self.names(out['found']['build']), ['2026-01-02-alpha-build-spec.md'])
        self.assertEqual(self.names(out['found']['ratified']), ['2026-01-01-alpha-surviving-spec.md'])

    def test_a_ratified_surviving_specification_gives_the_ratified_stage(self):
        self.assertEqual(self.read('beta')['stage'], RATIFIED)

    def test_a_surviving_specification_not_ratified_is_not_counted(self):
        self.assertEqual(self.read('gamma')['stage'], 'unrecorded (no specification found for gamma)')

    def test_an_architectural_specification_one_folder_down_is_counted(self):
        out = self.read('delta')
        self.assertEqual(out['stage'], RATIFIED)
        self.assertEqual(self.names(out['found']['ratified']), ['2026-01-01-delta-architectural-specification.md'])

    def test_a_folder_named_by_a_pattern_is_read(self):
        self.assertEqual(self.read('eta')['stage'], RATIFIED)
        self.assertEqual(self.read('kappa')['stage'], RATIFIED)

    def test_a_build_specification_outside_the_build_folders_is_not_counted(self):
        self.assertEqual(self.read('theta')['stage'], 'unrecorded (no specification found for theta)')

    def test_an_amendment_is_not_counted(self):
        self.assertEqual(self.read('iota')['stage'], 'unrecorded (no specification found for iota)')

    def test_an_architectural_amendment_matching_the_pattern_is_not_counted(self):
        # `*-architectural-spec*.md` matches `...-architectural-spec-amendment.md`; an amendment never counts.
        out = self.read('mu')
        self.assertEqual(out['stage'], 'unrecorded (no specification found for mu)')
        self.assertEqual(out['found'], {'build': [], 'ratified': []})

    def test_a_file_whose_front_matter_cannot_be_read_is_named_and_not_counted(self):
        out = self.read('lambda')
        self.assertEqual(out['stage'], 'unrecorded (no specification found for lambda)')
        self.assertEqual(self.names(out['unreadable']), ['2026-01-06-lambda-surviving-spec.md'])

    def test_the_keys_decide_where_the_task_and_status_are_read(self):
        # With the default keys the fixtures carry no task id, so nothing is found.
        self.assertEqual(self.read('beta', keys=[])['stage'], 'unrecorded (no specification found for beta)')

    def test_no_task_and_no_folder_each_read_unrecorded_with_the_reason(self):
        self.assertEqual(self.read(None)['stage'], 'unrecorded (no task id was given)')
        self.assertEqual(self.read('beta', roots=[])['stage'],
                         'unrecorded (no folder is named for the stage read)')

    def test_the_read_as_a_module(self):
        sys.path.insert(0, str(SCRIPTS))
        import stage
        reading = stage.read('beta', [], [str(TREE / 'specs')], 'meta.task_id', 'meta.status')
        self.assertEqual(reading['stage'], RATIFIED)


if __name__ == '__main__':
    unittest.main()
