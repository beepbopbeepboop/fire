#!/usr/bin/env python3
"""The reclass pass must survive a running worker, and the swarm must reload its own code.

Regression for bugs/SWARM_reclass_busy_set_crash.md: `apply_moves` used to build its busy set from
task *dicts* (`{t for t in C.load().values() ...}`), which raised `TypeError: cannot use 'dict' as a
set element` on every pass (157 times in swarm.out) whenever any worker was running. And because the
swarm is a long-lived process, a fix landed after it started (e2aca65eb) kept failing in memory until
a human restarted it.

Run: python3 tools/test_swarm_reclass_busy_set.py
"""
import json, os, shutil, sys, tempfile, unittest
from unittest import mock
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import control as C
import swarm as S


def running_task(name, claims):
    return {"state": "running", "pid": os.getpid(), "worktree": "/nonexistent", "branch": "work/" + name,
            "claims": claims, "model": "m", "pool": "iceman", "started": "2026-11-10 00:00:00"}


class ReclassBusySet(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.main = os.path.join(self.tmp, "main")
        self.ctl = os.path.join(self.tmp, "ctl")
        os.makedirs(os.path.join(self.main, "bugs"))
        os.makedirs(self.ctl)
        self.saved_hash, self.saved_fd = S._CODE_HASH, S._LOCK_FD

    def tearDown(self):
        S._CODE_HASH, S._LOCK_FD = self.saved_hash, self.saved_fd
        shutil.rmtree(self.tmp, ignore_errors=True)

    def write_doc(self, rel, body="# doc\n"):
        path = os.path.join(self.main, "bugs", rel)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        open(path, "w").write(body)
        return path

    def fake_git(self, main):
        """Just enough git for apply_moves: `mv` really moves, everything else succeeds."""
        def _git(*a):
            if a[:2] == ("mv",) or a[0] == "mv":
                os.rename(os.path.join(main, a[1]), os.path.join(main, a[2]))
            return 0, ""
        return _git

    def run_apply_moves(self, tasks, pending):
        st = {"pending": dict(pending)}
        with mock.patch.object(C, "load", return_value=tasks), \
             mock.patch.object(C, "MAIN", self.main), \
             mock.patch.object(C, "ctl_dir", return_value=self.ctl), \
             mock.patch.object(S, "state_path", return_value=os.path.join(self.ctl, "swarm.json")), \
             mock.patch.object(S, "_move_citations", return_value=[]), \
             mock.patch.object(S, "_git", side_effect=self.fake_git(self.main)):
            S.apply_moves(st)
        return json.load(open(os.path.join(self.ctl, "swarm.json")))

    def test_apply_moves_moves_a_doc_while_another_task_is_running(self):
        """The crash: a running worker made the busy set hold dicts. The doc must move anyway."""
        self.write_doc("SUITE_x.md")
        state = self.run_apply_moves({"bug-live": running_task("bug-live", ["bug:OTHER"])},
                                     {"SUITE_x": "mid"})
        self.assertTrue(os.path.exists(os.path.join(self.main, "bugs", "mid", "SUITE_x.md")),
                        "the escalated doc must reach its new class")
        self.assertNotIn("SUITE_x", state.get("pending", {}),
                         "a moved doc is no longer pending: the next pass must not move it again")

    def test_apply_moves_leaves_a_doc_a_running_task_holds(self):
        """The busy check still works: a doc a live worker holds is not moved out from under it."""
        self.write_doc("SUITE_y.md")
        tasks = {"bug-live": running_task("bug-live", ["bug:SUITE_y"])}
        self.run_apply_moves(tasks, {"SUITE_y": "mid"})
        self.assertTrue(os.path.exists(os.path.join(self.main, "bugs", "SUITE_y.md")),
                        "a held doc stays where it is")
        self.assertFalse(os.path.exists(os.path.join(self.main, "bugs", "mid", "SUITE_y.md")))

    def test_no_running_task_still_moves(self):
        self.write_doc("SUITE_z.md")
        self.run_apply_moves({}, {"SUITE_z": "hard"})
        self.assertTrue(os.path.exists(os.path.join(self.main, "bugs", "hard", "SUITE_z.md")))


class ReloadOwnCode(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.saved_hash, self.saved_fd, self.saved_here = S._CODE_HASH, S._LOCK_FD, S.HERE

    def tearDown(self):
        S._CODE_HASH, S._LOCK_FD, S.HERE = self.saved_hash, self.saved_fd, self.saved_here
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_code_hash_follows_contents_not_mtime(self):
        tool = os.path.join(self.tmp, "swarm.py")
        open(tool, "w").write("a = 1\n")
        with mock.patch.object(S, "HERE", self.tmp):
            h1 = S.code_hash()
            os.utime(tool, (0, 0))                      # touch only
            self.assertEqual(S.code_hash(), h1, "a touched file is not a code change")
            open(tool, "w").write("a = 2\n")
            self.assertNotEqual(S.code_hash(), h1, "an edited file is a code change")

    def test_stale_code_re_execs_with_the_same_pid_and_script(self):
        fd = os.open(os.path.join(self.tmp, "lock"), os.O_RDWR | os.O_CREAT)
        S._CODE_HASH, S._LOCK_FD = "deadbeef", fd
        calls = []
        with mock.patch.object(S.os, "execv", side_effect=lambda *a: calls.append(a)):
            self.assertFalse(S.stale_code())
        self.assertEqual(len(calls), 1, "a changed tools/*.py must re-exec the swarm")
        self.assertEqual(calls[0][0], sys.executable)
        self.assertEqual(calls[0][1], [sys.executable, S.SCRIPT] + sys.argv[1:])
        self.assertIsNone(S._LOCK_FD, "the lock fd must be closed, or the new image sees its own lock")

    def test_stale_code_is_a_noop_when_the_code_is_unchanged(self):
        with mock.patch.object(S, "HERE", self.tmp):
            S._CODE_HASH = S.code_hash()
        S._LOCK_FD = None
        with mock.patch.object(S.os, "execv", side_effect=AssertionError("must not re-exec")):
            self.assertFalse(S.stale_code())


if __name__ == "__main__":
    unittest.main()
