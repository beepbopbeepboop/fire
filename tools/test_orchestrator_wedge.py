#!/usr/bin/env python3
"""Regression pins for the orchestrator wedge (2026-11-20): one stuck or crashing step held every slot idle.

    python3 tools/test_orchestrator_wedge.py

  - cleanup crashed when a candidate worker tree vanished mid-pass (FileNotFoundError out of the thread pool), and
    the swarm runs cleanup twice a pass, so every pass ended there and the feed never ran.
  - the swarm ran its control.py steps with no timeout: one that hung held the whole pass.
Temporary repositories only: the live registry and worktrees are never touched."""
import os
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import control as C
import swarm as S


class DirtyReason(unittest.TestCase):
    def test_vanished_tree_is_kept_not_raised(self):
        gone = os.path.join(tempfile.mkdtemp(), "work-gone")          # never created: the state a removed tree leaves
        self.assertEqual(C.tree_dirty_reason(gone), "tree vanished during the pass")

    def test_clean_tree_may_go(self):
        d = tempfile.mkdtemp()
        subprocess.run(["git", "init", "-q", d], check=True)
        self.assertIsNone(C.tree_dirty_reason(d))

    def test_dirty_tree_is_kept(self):
        d = tempfile.mkdtemp()
        subprocess.run(["git", "init", "-q", d], check=True)
        with open(os.path.join(d, "worker_edit.py"), "w") as f:
            f.write("x = 1\n")
        self.assertEqual(C.tree_dirty_reason(d), "dirty")

    def test_controller_files_alone_are_clean(self):
        d = tempfile.mkdtemp()
        subprocess.run(["git", "init", "-q", d], check=True)
        with open(os.path.join(d, "work.log"), "w") as f:
            f.write("log\n")
        self.assertIsNone(C.tree_dirty_reason(d))


class StepsAreBounded(unittest.TestCase):
    def test_hung_control_step_times_out_and_the_pass_goes_on(self):
        boom = subprocess.TimeoutExpired(cmd="control.py cleanup", timeout=900)
        with mock.patch.object(S.subprocess, "run", side_effect=boom):
            r = S.ctl(["cleanup"], timeout=1)
        self.assertEqual(r.returncode, 1)               # the caller reads an ordinary failed step, not an exception

    def test_hung_script_times_out_and_the_pass_goes_on(self):
        boom = subprocess.TimeoutExpired(cmd="cpu_cap.py", timeout=900)
        with mock.patch.object(S.subprocess, "run", side_effect=boom):
            r = S.ctl_script("cpu_cap.py", ["ratchet"], timeout=1)
        self.assertEqual(r.returncode, 1)


if __name__ == "__main__":
    unittest.main(verbosity=2)
