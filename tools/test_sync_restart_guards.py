#!/usr/bin/env python3
"""A dead worker must not be restarted into another guaranteed failure.

Three guards, all added 2026-11-10 after one doc (`recover-apply-haiku`) was restarted 335 times on
a model whose OAuth session had expired, and after a DONE task was superseded by a restart:

1. `dead_running_tasks` — a task that wrote an exitcode has finished; restarting it supersedes
   finished work (r329 said DONE, exited 0, and sync restarted it anyway).
2. `no_restart_reason` — a slot that is disabled (count 0) or full, or a banned model, can only
   fail again. The old check was `if cap and ...`, so a count-0 slot was treated as unlimited.
3. `auth_failed` — an authentication failure is neither a usage limit nor a network error, so it
   matched nothing and the model was never banned.
4. `restart` budget — a chain past MAX_RESTARTS is abandoned so its claim is released and the doc
   is re-fed, instead of round 300 of the same failure.

Run: python3 tools/test_sync_restart_guards.py
"""
import os, shutil, sys, tempfile, unittest
from unittest import mock
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import control as C

DEAD_PID = 2 ** 22 - 3          # no such process


def task(name, wt, state="running", pid=DEAD_PID, model="m/x", exitcode=None):
    os.makedirs(wt, exist_ok=True)
    if exitcode is not None:
        open(os.path.join(wt, "exitcode"), "w").write(str(exitcode))
    return {"name": name, "state": state, "pid": pid, "worktree": wt, "model": model,
            "branch": "work/" + name, "claims": ["bug:" + name], "summary": name,
            "started": "2026-11-10 00:00:00"}


class DeadRunning(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_a_task_that_wrote_an_exitcode_is_not_a_dead_worker(self):
        wt = os.path.join(self.tmp, "a")
        tasks = {"bug-x": task("bug-x", wt, exitcode=0)}
        self.assertEqual(C.dead_running_tasks(tasks), set(),
                         "a finished task (state_of says exited-ok) must not be restarted")

    def test_a_killed_task_with_no_exitcode_is_a_dead_worker(self):
        wt = os.path.join(self.tmp, "b")
        tasks = {"bug-y": task("bug-y", wt)}
        self.assertEqual(C.dead_running_tasks(tasks), {"bug-y"})

    def test_a_live_task_is_not_a_dead_worker(self):
        wt = os.path.join(self.tmp, "c")
        tasks = {"bug-z": task("bug-z", wt, pid=os.getpid())}
        self.assertEqual(C.dead_running_tasks(tasks), set())

    def test_a_terminal_task_is_not_a_dead_worker(self):
        wt = os.path.join(self.tmp, "d")
        tasks = {"bug-w": task("bug-w", wt, state="superseded")}
        self.assertEqual(C.dead_running_tasks(tasks), set())


class RestartGuards(unittest.TestCase):
    POOL = {"slots": [{"name": "haiku", "model": "claude-haiku-5-5", "count": 0},
                       {"name": "iceman", "model": "opencode-go/iceman-contributor-free", "count": 1}]}

    def test_a_disabled_slot_is_never_restarted(self):
        reason = C.no_restart_reason({"model": "claude-haiku-5-5"}, self.POOL, {})
        self.assertIsNotNone(reason)
        self.assertIn("0/0", reason, "count 0 means the slot is off: nothing may restart on it")

    def test_a_full_slot_is_not_restarted(self):
        counts = {"opencode-go/iceman-contributor-free": 1}
        reason = C.no_restart_reason({"model": "opencode-go/iceman-contributor-free"}, self.POOL, counts)
        self.assertIsNotNone(reason)
        self.assertIn("1/1", reason)

    def test_a_free_slot_may_restart(self):
        self.assertIsNone(C.no_restart_reason({"model": "opencode-go/iceman-contributor-free"}, self.POOL, {}))

    def test_a_banned_model_is_not_restarted(self):
        reason = C.no_restart_reason({"model": "m/x"}, {"slots": []}, {}, banned={"m/x": 1})
        self.assertIsNotNone(reason)
        self.assertIn("banned", reason)

    def test_an_unknown_model_with_no_ban_may_restart(self):
        self.assertIsNone(C.no_restart_reason({"model": "m/x"}, {"slots": []}, {}))


class AuthFailure(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def write_log(self, body):
        wt = os.path.join(self.tmp, "wt")
        os.makedirs(wt, exist_ok=True)
        open(os.path.join(wt, "work.log"), "w").write(body)
        return {"worktree": wt}

    def test_an_expired_oauth_session_is_an_auth_failure(self):
        t = self.write_log("=== control: spawned x ===\nFailed to authenticate: OAuth session expired and could not be refreshed\n")
        self.assertTrue(C.auth_failed(t))

    def test_a_benign_log_is_not_an_auth_failure(self):
        t = self.write_log("working\nCONTROL-STATUS: DONE\n")
        self.assertFalse(C.auth_failed(t))

    def test_no_log_is_not_an_auth_failure(self):
        self.assertFalse(C.auth_failed({"worktree": self.tmp}))


class RestartBudget(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.wt = os.path.join(self.tmp, "wt")
        os.makedirs(self.wt)

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_a_chain_past_the_budget_is_abandoned_not_restarted(self):
        # the whole chain must exist, or restart() finds a free low -rN and starts there
        names = ["bug-x-r%d" % i for i in range(2, C.MAX_RESTARTS + 1)]
        reg = {n: task(n, self.wt) for n in names}
        with mock.patch.object(C, "load", return_value=reg), \
             mock.patch.object(C, "git", return_value=""), \
             mock.patch.object(C.fleet_ledger, "kill_group", return_value=None), \
             mock.patch.object(C, "registry", return_value=_Reg(reg)), \
             mock.patch.object(C, "cmd_spawn", side_effect=AssertionError("must not spawn")):
            new = C.restart(names[-1], "test")
        self.assertIsNone(new, "over budget: restart must refuse and abandon the task")
        self.assertEqual(reg[names[-1]]["state"], "abandoned", "abandoned releases the claim")

    def test_a_chain_under_the_budget_still_restarts(self):
        reg = {"bug-y": task("bug-y", self.wt)}
        spawned = []
        with mock.patch.object(C, "load", return_value=reg), \
             mock.patch.object(C, "git", return_value=""), \
             mock.patch.object(C.fleet_ledger, "kill_group", return_value=None), \
             mock.patch.object(C, "registry", return_value=_Reg(reg)), \
             mock.patch.object(C, "cmd_spawn", side_effect=lambda ns: spawned.append(ns.name)):
            new = C.restart("bug-y", "test")
        self.assertEqual(new, "bug-y-r2")
        self.assertEqual(spawned, ["bug-y-r2"])
        self.assertEqual(reg["bug-y"]["state"], "superseded")


class _Reg:
    def __init__(self, d): self.d = d
    def __enter__(self): return self.d
    def __exit__(self, *a): return False


if __name__ == "__main__":
    unittest.main()
