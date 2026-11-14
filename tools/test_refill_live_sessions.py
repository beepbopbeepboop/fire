#!/usr/bin/env python3
"""Refill counts a worker as running while its opencode session is live, even when its recorded pid is dead, and
reap never signals a live worker's process group.

2026-11-03: 31 of 52 registry-'running' tasks had dead pids while their sessions kept going. state_of() said
exited-err, so refill saw free slots and over-filled iceman to 43 of 20. This pins the count, the cap, the fail-closed
path when the session listing cannot be read, and the reap guard.

Run: python3 tools/test_refill_live_sessions.py
"""
import os, shutil, sys, tempfile, unittest
from unittest import mock
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import control as C

POOL = {"slots": [{"name": "iceman", "model": "opencode-go/iceman-contributor-free", "count": 2, "class": "mid",
                   "also": ["easy"]}]}
DEAD_PID = 2 ** 22 - 3          # no such process


def worker(name, wt):
    return {"slot": 1, "branch": "work/" + name, "worktree": wt, "claims": ["bug:" + name], "state": None,
            "pid": DEAD_PID, "summary": name, "started": "2026-11-03 10:00:00",
            "model": POOL["slots"][0]["model"], "pool": "iceman"}


class RefillCountsLiveSessions(unittest.TestCase):
    def setUp(self):
        self.root = tempfile.mkdtemp()
        self.wts = {n: os.path.join(self.root, n) for n in ("a", "b", "c")}
        for wt in self.wts.values():
            os.makedirs(wt)
        self.tasks = {n: worker(n, wt) for n, wt in self.wts.items()}
        self.patches = [mock.patch.object(C, "load_pool", return_value=POOL)]
        for p in self.patches:
            p.start()

    def tearDown(self):
        for p in self.patches:
            p.stop()
        shutil.rmtree(self.root, ignore_errors=True)

    def test_dead_pid_with_live_session_still_counts_as_running(self):
        self.assertEqual(C.state_of(self.tasks["a"]), "exited-err")          # the bug's view of it
        live = C.busy_task_names({os.path.realpath(self.wts["a"])}, self.tasks)
        self.assertEqual(C.running_by_slot(self.tasks, live), {"iceman": 1})
        self.assertEqual(C.running_by_slot(self.tasks, frozenset()), {})   # without the sessions, it is not

    def test_slot_cap_holds_when_every_worker_has_a_live_session(self):
        live = C.busy_task_names({os.path.realpath(wt) for wt in self.wts.values()}, self.tasks)
        busy = C.running_by_slot(self.tasks, live)
        self.assertEqual(busy, {"iceman": 3})
        self.assertFalse(C.slot_free(POOL["slots"][0], busy), "3 live workers on a count-2 slot: no room")

    def test_unreadable_session_listing_is_unknown_not_empty(self):
        with mock.patch.object(C, "live_session_dirs", side_effect=RuntimeError("opencode down")):
            self.assertIsNone(C.live_names(self.tasks))

    def test_readable_listing_with_nothing_live_is_empty(self):
        with mock.patch.object(C, "live_session_dirs", return_value=set()):
            self.assertEqual(C.live_names(self.tasks), set())


class ReapNeverSignalsALiveWorker(unittest.TestCase):
    def setUp(self):
        self.root = tempfile.mkdtemp()
        self.wt = os.path.join(self.root, "a")
        os.makedirs(self.wt)
        self.tasks = {"a": worker("a", self.wt)}

    def tearDown(self):
        shutil.rmtree(self.root, ignore_errors=True)

    def _reap_with(self, live_dirs):
        touched = []      # the tasks reap would signal; kill_group is stubbed so nothing real is touched
        patches = [mock.patch.object(C, "load", return_value=self.tasks),
                   mock.patch.object(C, "live_session_dirs", side_effect=live_dirs),
                   mock.patch.object(C.fleet_ledger, "kill_group",
                                     side_effect=lambda d, n, reason, **k: touched.append(n) or []),
                   mock.patch.object(C.fleet_ledger, "entries", return_value=[]),
                   mock.patch.object(C.fleet_ledger, "group_members", return_value=[])]
        for p in patches:
            p.start()
        try:
            C.cmd_reap(type("A", (), {"dry_run": False})())
        finally:
            for p in patches:
                p.stop()
        return touched

    def test_live_session_is_left_alone(self):
        self.assertEqual(self._reap_with(lambda: {os.path.realpath(self.wt)}), [])

    def test_no_live_session_means_it_is_a_candidate(self):
        self.assertEqual(self._reap_with(lambda: set()), ["a"])

    def test_unreadable_listing_reaps_nothing(self):
        self.assertEqual(self._reap_with(RuntimeError("opencode down")), [])


if __name__ == "__main__":
    unittest.main()
