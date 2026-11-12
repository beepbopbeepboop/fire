#!/usr/bin/env python3
"""A dead worker is found by sync until it is restarted or superseded, whatever its registry state says.

2026-11-10: a killed worker stayed "running" in the registry for hours, and a restart skipped for want of a slot was
never retried, because dead detection looked only at "running". Pins: running and exited-err with a dead pid and no
exitcode are dead; a live pid, an exitcode, or a superseded/abandoned state is not.

Run: python3 tools/test_dead_worker_state.py
"""
import os, sys, tempfile, unittest
from unittest import mock
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import control as C

DEAD = 2 ** 22 - 3


def task(state, wt, pid=DEAD):
    return {"state": state, "worktree": wt, "pid": pid, "claims": [], "branch": "b", "model": "m"}


class DeadWorkerState(unittest.TestCase):
    def setUp(self):
        self.root = tempfile.mkdtemp()

    def wt(self, name, exitcode=False):
        d = os.path.join(self.root, name)
        os.makedirs(d, exist_ok=True)
        if exitcode:
            open(os.path.join(d, "exitcode"), "w").write("0")
        return d

    def dead(self, tasks):
        with mock.patch.object(C, "alive", return_value=False):
            return C.dead_running_tasks(tasks)

    def test_running_with_dead_pid_is_dead(self):
        self.assertEqual(self.dead({"a": task("running", self.wt("a"))}), {"a"})

    def test_exited_err_with_dead_pid_is_still_dead_so_a_skipped_restart_is_retried(self):
        self.assertEqual(self.dead({"b": task("exited-err", self.wt("b"))}), {"b"})

    def test_an_exitcode_means_finished_not_dead(self):
        self.assertEqual(self.dead({"c": task("running", self.wt("c", exitcode=True))}), set())

    def test_superseded_and_abandoned_are_not_dead(self):
        self.assertEqual(self.dead({"d": task("superseded", self.wt("d")),
                                    "e": task("abandoned", self.wt("e"))}), set())

    def test_a_live_pid_is_not_dead(self):
        with mock.patch.object(C, "alive", return_value=True):
            self.assertEqual(C.dead_running_tasks({"f": task("running", self.wt("f"))}), set())


if __name__ == "__main__":
    unittest.main()
