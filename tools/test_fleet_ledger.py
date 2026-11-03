#!/usr/bin/env python3
"""The fleet signals only processes it recorded at spawn. Run: python3 tools/test_fleet_ledger.py

Uses real processes. Each test kills what it started, in `finally`.
"""
import os, subprocess, sys, tempfile, time, unittest
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import fleet_ledger as L


def sleeper(cwd, start_new_session=True):
    return subprocess.Popen(["sleep", "600"], cwd=cwd, start_new_session=start_new_session)


class Ledger(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp()
        self.procs = []

    def tearDown(self):
        for p in self.procs:
            if p.poll() is None:
                p.kill()
                p.wait()

    def test_recorded_group_is_stopped_with_term_and_logged(self):
        p = sleeper(self.dir); self.procs.append(p)
        L.record_spawn(self.dir, "t1", p.pid, self.dir, ["sleep", "600"])
        L.kill_group(self.dir, "t1", "test", grace=5)
        self.assertIsNotNone(p.wait(timeout=10))
        log = open(os.path.join(self.dir, L.KILL_LOG)).read()
        self.assertIn("TERM task=t1", log)
        self.assertIn("EXITED task=t1", log)

    def test_unrecorded_process_in_the_same_directory_is_never_signalled(self):
        mine = sleeper(self.dir); self.procs.append(mine)
        theirs = sleeper(self.dir); self.procs.append(theirs)      # same cwd, not recorded: a user's session
        L.record_spawn(self.dir, "t1", mine.pid, self.dir, ["sleep", "600"])
        L.kill_group(self.dir, "t1", "test", grace=5)
        mine.wait(timeout=10)
        self.assertIsNone(theirs.poll(), "an unrecorded process was signalled")

    def test_recycled_pid_is_refused(self):
        p = sleeper(self.dir); self.procs.append(p)
        e = L.record_spawn(self.dir, "t1", p.pid, self.dir, ["sleep", "600"])
        # Simulate pid reuse: the ledger says the leader started at another time.
        rows = [dict(r, lstart="Thu Jan  1 00:00:00 1970") if r["task"] == "t1" else r
                for r in map(__import__("json").loads, open(os.path.join(self.dir, L.SPAWN_LEDGER)))]
        open(os.path.join(self.dir, L.SPAWN_LEDGER), "w").write("".join(__import__("json").dumps(r) + "\n" for r in rows))
        L.kill_group(self.dir, "t1", "test", grace=2)
        self.assertIsNone(p.poll(), "a process whose start time did not match was signalled")
        self.assertIn("REFUSED task=t1", open(os.path.join(self.dir, L.KILL_LOG)).read())

    def test_task_with_no_record_signals_nothing(self):
        p = sleeper(self.dir); self.procs.append(p)
        self.assertEqual(L.kill_group(self.dir, "nobody", "test", grace=2), [])
        self.assertIsNone(p.poll())


if __name__ == "__main__":
    unittest.main()
