#!/usr/bin/env python3
"""swarm.log prints a status line once per quiet window, and kills.log records a refusal once.

Run: python3 tools/test_swarm_log_quiet.py
"""
import contextlib, io, json, os, sys, tempfile, unittest
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import swarm as S
import fleet_ledger as F


def emitted(*msgs):
    S._SEEN.clear()
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        for m in msgs:
            S.log(m)
    return buf.getvalue().splitlines()


class Quiet(unittest.TestCase):
    def test_an_identical_line_prints_once(self):
        self.assertEqual(len(emitted("holding x: dirty", "holding x: dirty", "holding x: dirty")), 1)

    def test_alternating_lines_each_print_once(self):
        self.assertEqual(len(emitted("holding a", "holding b", "holding a", "holding b")), 2)

    def test_a_moving_count_is_not_news(self):
        self.assertEqual(len(emitted("guard: 5 task(s) live", "guard: 7 task(s) live")), 1)

    def test_events_with_different_pids_all_print(self):
        self.assertEqual(len(emitted("refill: spawned a (pid 1)", "refill: spawned a (pid 2)")), 2)

    def test_it_prints_again_after_the_window(self):
        S._SEEN.clear()
        with contextlib.redirect_stdout(io.StringIO()):
            S.log("holding x")
        S._SEEN["holding x"] -= S.REPEAT_QUIET_S + 1
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            S.log("holding x")
        self.assertEqual(len(buf.getvalue().splitlines()), 1)


class Refusal(unittest.TestCase):
    def test_a_refusal_is_recorded_once_per_task_pgid_pid(self):
        d = tempfile.mkdtemp(prefix="refused_")
        self.assertTrue(F._first_refusal(d, "t", 10, 11))
        self.assertFalse(F._first_refusal(d, "t", 10, 11))
        self.assertTrue(F._first_refusal(d, "t", 12, 11))      # another group is news


if __name__ == "__main__":
    unittest.main()
