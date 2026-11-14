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


class DeadOnArrivalSinceBase(unittest.TestCase):
    """A fixer/continuation starts from a branch that already has commits master lacks. `ahead()` counts those
    inherited commits, so a fixer that died in its first second looked busy and was never bounced or banned
    (2026-11-13: the wal-2 fixer died on the free-tier rate limit and stayed an exited-err entry with 5 inherited
    commits, while its model kept getting restarted). `ahead_since_base` is the worker's own contribution."""

    def setUp(self):
        import subprocess
        self.root = tempfile.mkdtemp()
        self.repo = os.path.join(self.root, "repo")
        os.makedirs(self.repo)
        self.wt = os.path.join(self.root, "wt")
        os.makedirs(self.wt)
        open(os.path.join(self.wt, "work.log"), "w").write(
            "Error: Rate limit exceeded: free-models-per-day-high-balance.\n")
        g = lambda *a: subprocess.run(["git", "-C", self.repo, *a], check=True, capture_output=True)
        g("init", "-q", "-b", "master")
        g("-c", "user.name=t", "-c", "user.email=t@t", "commit", "-q", "--allow-empty", "-m", "root")
        g("branch", "work/base")
        g("checkout", "-q", "work/base")
        g("-c", "user.name=t", "-c", "user.email=t@t", "commit", "-q", "--allow-empty", "-m", "base work")
        g("branch", "work/fixer", "work/base")
        self.saved = C.MAIN
        C.MAIN = self.repo

    def tearDown(self):
        C.MAIN = self.saved

    def task(self, branch, base):
        return {"state": "exited-err", "worktree": self.wt, "pid": 0, "claims": [],
                "branch": branch, "base": base, "model": "m", "pool": "p"}

    def test_a_fixer_that_added_nothing_is_dead_on_arrival(self):
        t = self.task("work/fixer", "work/base")
        self.assertEqual(C.ahead(t), 1)              # the base commit master lacks
        self.assertEqual(C.ahead_since_base(t), 0)
        self.assertTrue(C.dead_on_arrival(t))

    def test_a_fixer_with_its_own_commit_is_not_dead_on_arrival(self):
        import subprocess
        subprocess.run(["git", "-C", self.repo, "checkout", "-q", "work/fixer"], check=True)
        subprocess.run(["git", "-C", self.repo, "-c", "user.name=t", "-c", "user.email=t@t",
                        "commit", "-q", "--allow-empty", "-m", "own work"], check=True)
        self.assertEqual(C.ahead_since_base(self.task("work/fixer", "work/base")), 1)
        self.assertFalse(C.dead_on_arrival(self.task("work/fixer", "work/base")))


if __name__ == "__main__":
    unittest.main()
