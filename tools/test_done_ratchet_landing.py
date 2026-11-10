#!/usr/bin/env python3
"""The DONE ratchet's premise — "deleted on a branch means fixed" — must actually be true.

The feed skips a doc that any branch has deleted. When the branch's task was later superseded or
abandoned, nothing ever landed it: the doc stayed on master, the ratchet skipped it, and no worker
touched it again (1030 such branches, 5 docs visible in swarm.out). `pick_candidates` is what lands
a branch, so a DONE task with commits must be landable whatever a restart did to its state.

Run: python3 tools/test_done_ratchet_landing.py
"""
import os, shutil, sys, tempfile, unittest
from unittest import mock
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import control as C
import integrate as I

LIVE_PID = os.getpid()


def pick(tasks, **kw):
    """Run pick_candidates against `tasks`, with the registry, liveness and git mocked out."""
    for t in tasks.values():
        t["_verdict"], t["_ahead"] = t.get("_verdict", ""), t.get("_ahead", 0)
    with mock.patch.object(C, "load", return_value=tasks), \
         mock.patch.object(C, "verdict", side_effect=lambda t: t["_verdict"]), \
         mock.patch.object(C, "state_of", side_effect=lambda t: t["state"]), \
         mock.patch.object(C, "ahead", side_effect=lambda t: t["_ahead"]), \
         mock.patch.object(C, "git", return_value=""):
        return I.pick_candidates(quiet=True, **kw)


class Candidates(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.wt = os.path.join(self.tmp, "wt")
        os.makedirs(self.wt)

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def task(self, name, state, verdict, ahead, pid=0):
        return {"name": name, "slot": 1, "state": state, "pid": pid, "worktree": self.wt,
                "branch": "work/" + name, "claims": ["bug:" + name], "summary": name,
                "started": "2026-11-10 00:00:00", "_verdict": verdict, "_ahead": ahead}

    def test_a_superseded_done_task_is_landable(self):
        tasks = {"bug-done": self.task("bug-done", "superseded", "DONE", 3)}
        self.assertIn("bug-done", pick(tasks),
                      "a DONE task a restart superseded is still finished work: land it")

    def test_an_abandoned_done_task_is_landable(self):
        tasks = {"bug-abandoned": self.task("bug-abandoned", "abandoned", "DONE", 2)}
        self.assertIn("bug-abandoned", pick(tasks))

    def test_a_plain_exited_task_is_still_landable(self):
        tasks = {"bug-plain": self.task("bug-plain", "exited-ok", "DONE", 2)}
        self.assertIn("bug-plain", pick(tasks))

    def test_a_superseded_task_without_a_done_verdict_is_not_landed(self):
        tasks = {"bug-partial": self.task("bug-partial", "superseded", "", 2)}
        self.assertNotIn("bug-partial", pick(tasks), "no DONE verdict: the worker never finished")

    def test_a_done_task_with_no_commits_is_not_landed(self):
        tasks = {"bug-empty": self.task("bug-empty", "superseded", "DONE", 0)}
        self.assertNotIn("bug-empty", pick(tasks), "nothing to land")

    def test_a_live_done_task_is_not_landed(self):
        tasks = {"bug-live": self.task("bug-live", "running", "DONE", 2, pid=LIVE_PID)}
        self.assertNotIn("bug-live", pick(tasks), "a DONE-but-alive worker is finishing cleanup")

    def test_an_integration_failed_task_is_landable(self):
        tasks = {"bug-red": self.task("bug-red", "integration-failed", "DONE", 2)}
        self.assertIn("bug-red", pick(tasks))

    def test_a_task_handed_to_a_fixer_is_not_landed_again(self):
        tasks = {"bug-fixed": self.task("bug-fixed", "superseded", "DONE", 2)}
        tasks["bug-fixed"]["fixer"] = "fix-merge-bug-fixed"
        self.assertNotIn("bug-fixed", pick(tasks),
                         "re-probing a conflicting branch queues a second fixer for it every pass")


if __name__ == "__main__":
    unittest.main()
