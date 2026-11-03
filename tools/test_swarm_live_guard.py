#!/usr/bin/env python3
"""The swarm must not retire, continue, feed, land or drop work that a live opencode session is driving.

Run: python3 tools/test_swarm_live_guard.py
"""
import json, os, shutil, sys, tempfile, unittest
from unittest import mock
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import control as C
import swarm as S


def task(name, wt, claims, state="exited-err"):
    return {"slot": 1, "branch": "work/" + name, "worktree": wt, "claims": claims, "state": state,
            "pid": 0, "summary": name, "started": "2026-11-02 15:00:00", "model": "m", "pool": None}


class Guard(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.saved = dict(BUSY=S.BUSY["names"].copy(), claims=S.BUSY["claims"].copy())
        S.BUSY["names"], S.BUSY["claims"] = set(), set()

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)
        S.BUSY["names"], S.BUSY["claims"] = self.saved["BUSY"], self.saved["claims"]

    def test_live_guard_marks_only_tasks_whose_tree_has_a_session(self):
        wt_busy, wt_idle = os.path.join(self.tmp, "work-1"), os.path.join(self.tmp, "work-2")
        tasks = {"busy": task("busy", wt_busy, ["bug:A"]), "idle": task("idle", wt_idle, ["bug:B"])}
        with mock.patch.object(C, "load", return_value=tasks), \
             mock.patch.object(C, "live_session_dirs", return_value={os.path.realpath(wt_busy + "/stage1")}):
            self.assertTrue(S.live_guard())
        self.assertEqual(S.BUSY["names"], {"busy"})
        self.assertEqual(S.BUSY["claims"], {"bug:A"})

    def test_live_guard_fails_safe_when_sessions_cannot_be_read(self):
        with mock.patch.object(C, "live_session_dirs", side_effect=RuntimeError("no listing")):
            self.assertFalse(S.live_guard())

    def test_held_claims_include_busy_tasks_claims(self):
        S.BUSY["claims"] = {"bug:A"}
        with mock.patch.object(C, "load", return_value={}), mock.patch.object(C, "external", return_value={}), \
             mock.patch.object(C, "qdir", return_value=self.tmp):
            self.assertIn("bug:A", S.held_claims())

    def test_drop_queued_busy_removes_only_clashing_items(self):
        for name, claims in [("clash", ["bug:A"]), ("free", ["bug:Z"])]:
            json.dump({"name": name, "claims": claims}, open(os.path.join(self.tmp, name + ".json"), "w"))
        S.BUSY["claims"] = {"bug:A"}
        with mock.patch.object(C, "qdir", return_value=self.tmp):
            S.drop_queued_busy()
        self.assertFalse(os.path.exists(os.path.join(self.tmp, "clash.json")))
        self.assertTrue(os.path.exists(os.path.join(self.tmp, "free.json")))

    def test_retire_dead_leaves_busy_tasks_alone(self):
        tasks = {"bug-busy": task("bug-busy", self.tmp, ["bug:A"]),
                 "bug-idle": task("bug-idle", self.tmp, ["bug:B"])}
        S.BUSY["names"] = {"bug-busy"}
        marks = []
        with mock.patch.object(C, "load", return_value=tasks), mock.patch.object(C, "holds_claims", return_value=False), \
             mock.patch.object(C, "state_of", return_value="exited-err"), mock.patch.object(C, "limit_hit", return_value=False), \
             mock.patch.object(S, "load_state", return_value={"retire_backfilled": True}), \
             mock.patch.object(S, "state_path", return_value=os.path.join(self.tmp, "swarm.json")), \
             mock.patch.object(S.subprocess, "run", side_effect=lambda cmd, **k: marks.append(cmd[-2:]) or None):
            S.retire_dead()
        self.assertEqual(marks, [["bug-idle", "abandoned"]])

    def test_moves_skip_docs_a_live_session_is_working_on(self):
        S.BUSY["claims"] = {"bug:CODEGEN_x", "bug:COMPILE_FAIL_y"}
        self.assertEqual(S.move_busy_bases(), {"CODEGEN_x", "COMPILE_FAIL_y"})
        S.BUSY["claims"] = {"fix:unrelated"}
        self.assertEqual(S.move_busy_bases(), set())

    def test_accepts_own_class_and_also_list(self):
        import control as C2
        iceman = {"name": "iceman", "class": "mid", "also": ["easy"]}
        easy = {"name": "free", "class": "easy"}
        self.assertTrue(C2.accepts(iceman, "mid"))
        self.assertTrue(C2.accepts(iceman, "easy"))
        self.assertFalse(C2.accepts(iceman, "hard"))
        self.assertTrue(C2.accepts(easy, "easy"))
        self.assertFalse(C2.accepts(easy, "mid"))

    def test_busy_counts_a_task_in_its_own_class_not_its_slot(self):
        tasks = {
            "f1": {"state": "running", "cls": "easy", "pool": "iceman"},   # a formal doc on iceman: easy load
            "m1": {"state": "running", "cls": "mid", "pool": "iceman"},
        }
        pool = {"slots": [{"name": "iceman", "class": "mid", "also": ["easy"], "count": 20}]}
        with mock.patch.object(C, "load", return_value=tasks), mock.patch.object(C, "load_pool", return_value=pool), \
             mock.patch.object(C, "state_of", side_effect=lambda t: t["state"]):
            self.assertEqual(S.busy_by_class(), {"easy": 1, "mid": 1, "hard": 0})


if __name__ == "__main__":
    unittest.main()
