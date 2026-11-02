#!/usr/bin/env python3
"""reap must not kill inside a worktree that an opencode session is still driving.

Run: python3 tools/test_reap_live.py
"""
import os, sys, time, unittest
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import control as C


class LiveSessions(unittest.TestCase):
    def test_recent_session_is_live_old_is_not(self):
        now = int(time.time() * 1000)
        listing = [
            {"directory": "/w/work-1", "updated": now - 10_000},          # 10 s ago: live
            {"directory": "/w/work-2", "updated": now - 3_600_000},       # an hour ago: not
            {"directory": "/w/work-3"},                                    # no timestamp: not live
        ]
        dirs = C.live_session_dirs(window_s=900, listing=listing)
        self.assertIn(os.path.realpath("/w/work-1"), dirs)
        self.assertNotIn(os.path.realpath("/w/work-2"), dirs)
        self.assertNotIn(os.path.realpath("/w/work-3"), dirs)

    def test_busy_task_matches_its_tree_not_a_sibling_prefix(self):
        tasks = {
            "a": {"worktree": "/w/work-3898"},
            "b": {"worktree": "/w/work-38981"},   # a sibling whose name starts the same way
        }
        dirs = {os.path.realpath("/w/work-3898/stage1")}
        self.assertEqual(C.busy_task_names(dirs, tasks), {"a"})

    def test_session_in_the_tree_root_is_busy(self):
        tasks = {"a": {"worktree": "/w/work-9"}}
        self.assertEqual(C.busy_task_names({os.path.realpath("/w/work-9")}, tasks), {"a"})


if __name__ == "__main__":
    unittest.main()
