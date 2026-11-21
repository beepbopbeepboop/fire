#!/usr/bin/env python3
"""Phase 1 of the orchestration redesign (doc/ORCHESTRATION_REDESIGN.md §3):
  1. a child that runs past the round's deadline is stopped, its own grandchildren with it, and the round ends;
  2. the holder record written into integrator.lock is what control.integrator_holder() reads back, and it reads
     None once the lock is free;
  3. a losing lock attempt does not truncate the holder's record (the old "w" open did)."""
import fcntl, json, os, subprocess, sys, tempfile, time, unittest
from unittest import mock

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import control as C
import integrate as I


class DeadlineStopsGroup(unittest.TestCase):
    def test_overrun_stops_child_and_grandchild_and_ends_round(self):
        with tempfile.TemporaryDirectory() as d:
            pidfile = os.path.join(d, "grandchild.pid")
            # The child starts a grandchild, records its pid, then sleeps far past the deadline.
            child = ("import subprocess, time, sys\n"
                     "g = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(120)'])\n"
                     "open(%r, 'w').write(str(g.pid))\n"
                     "time.sleep(120)\n" % pidfile)
            saved = dict(I.ROUND)
            I.ROUND.update(deadline=time.time() + 2, probe=True, merged=[], lock=None)
            t0 = time.time()
            try:
                with self.assertRaises(SystemExit) as cm:
                    I.run([sys.executable, "-c", child], d, step="gate")
            finally:
                I.ROUND.clear(); I.ROUND.update(saved)
            elapsed = time.time() - t0
            self.assertEqual(cm.exception.code, 1, "the round must end with exit 1")
            self.assertLess(elapsed, 30, "the deadline must stop the child, not wait for it")
            gpid = int(open(pidfile).read())
            time.sleep(0.5)
            with self.assertRaises(ProcessLookupError):
                os.kill(gpid, 0)   # the grandchild is gone too: the whole group was stopped


class HolderRecord(unittest.TestCase):
    def setUp(self):
        self.d = tempfile.mkdtemp()
        self.patch = mock.patch.object(C, "ctl_dir", lambda: self.d)
        self.patch.start()

    def tearDown(self):
        self.patch.stop()

    def test_record_round_trips_and_free_lock_reads_none(self):
        path = os.path.join(self.d, "integrator.lock")
        lock = open(path, "a+")
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        saved = dict(I.ROUND)
        I.ROUND.update(id="t-1", started=time.time(), deadline=time.time() + 600, lock=lock,
                       merged=["bug-a", "bug-b"])
        try:
            I.holder("gate")
            rec = C.integrator_holder()          # the lock is held by `lock`, a different open file
            self.assertEqual(rec["round"], "t-1")
            self.assertEqual(rec["step"], "gate")
            self.assertEqual(rec["merged"], ["bug-a", "bug-b"])
            self.assertIn("round t-1, step gate", C.describe_holder(rec))
            fcntl.flock(lock, fcntl.LOCK_UN)
            lock.close()
            self.assertIsNone(C.integrator_holder(), "a free lock reads as None")
        finally:
            I.ROUND.clear(); I.ROUND.update(saved)

    def test_losing_attempt_does_not_truncate_record(self):
        path = os.path.join(self.d, "integrator.lock")
        with open(path, "w") as f:
            f.write(json.dumps({"pid": 1, "round": "held", "step": "gate"}) + "\n")
        winner = open(path, "a+")
        fcntl.flock(winner, fcntl.LOCK_EX | fcntl.LOCK_NB)
        try:
            self.assertEqual(C.integrator_holder()["round"], "held")   # the reader does not truncate
            # A losing integrator opens the file the way main() does now; the record must survive it.
            loser = open(path, "a+")
            with self.assertRaises(OSError):
                fcntl.flock(loser, fcntl.LOCK_EX | fcntl.LOCK_NB)
            loser.close()
            self.assertIn('"round": "held"', open(path).read())
        finally:
            winner.close()


class ProbeLocking(unittest.TestCase):
    """Phase 2: a probe takes no integrator lock and gates in its own tree; a landing still takes the lock."""
    def setUp(self):
        self.d = tempfile.mkdtemp()
        self.patch = mock.patch.object(C, "ctl_dir", lambda: self.d)
        self.patch.start()
        self.held = open(os.path.join(self.d, "integrator.lock"), "a+")
        fcntl.flock(self.held, fcntl.LOCK_EX | fcntl.LOCK_NB)   # another integrator holds the lock

    def tearDown(self):
        self.held.close()
        self.patch.stop()

    def test_probe_takes_no_lock_while_a_landing_holds_it(self):
        self.assertIsNone(I.take_integrator_lock(probe=True))

    def test_landing_refuses_while_the_lock_is_held(self):
        with self.assertRaises(SystemExit):
            I.take_integrator_lock(probe=False)

    def test_probe_tree_is_removed_from_the_repo(self):
        repo = os.path.join(self.d, "repo")
        os.mkdir(repo)
        env = dict(os.environ, GIT_AUTHOR_NAME="t", GIT_AUTHOR_EMAIL="t@t", GIT_COMMITTER_NAME="t",
                   GIT_COMMITTER_EMAIL="t@t")
        subprocess.run(["git", "init", "-q", repo], check=True)
        subprocess.run(["git", "-C", repo, "commit", "-q", "--allow-empty", "-m", "root"], check=True, env=env)
        tree = os.path.join(self.d, "work-probe-test")
        subprocess.run(["git", "-C", repo, "worktree", "add", "-q", "--detach", tree, "HEAD"], check=True)
        self.assertTrue(os.path.isdir(tree))
        with mock.patch.object(C, "MAIN", repo):
            I.remove_probe_tree(tree)
        self.assertFalse(os.path.exists(tree))
        wl = subprocess.run(["git", "-C", repo, "worktree", "list"], capture_output=True, text=True).stdout
        self.assertNotIn("work-probe-test", wl)


if __name__ == "__main__":
    unittest.main()
