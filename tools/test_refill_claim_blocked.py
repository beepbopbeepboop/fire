#!/usr/bin/env python3
"""A queued task whose claim is held elsewhere takes no slot.

2026-11-10: refill counted a slot as busy before spawn refused the task on its claim. Five claim-blocked fix-merge
tasks at the head of the queue took all five easy slots, so qwen-local (and every other slot) never got work, and the
rest of the queue was skipped with no log line. This pins: a blocked task is skipped, the next task still starts, and
a started task's claims block the rest of the same pass.

Run: python3 tools/test_refill_claim_blocked.py
"""
import argparse, json, os, shutil, sys, tempfile, unittest
from unittest import mock
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import control as C

POOL = {"default_slot": "a", "slots": [
    {"name": "a", "model": "m/a", "count": 1, "class": "easy"},
    {"name": "b", "model": "m/b", "count": 1, "class": "easy"},
]}


def item(name, claim, added):
    return {"name": name, "claims": [claim], "task": "t", "files": [], "base": "master", "needs": [],
            "added": added, "cls": "easy", "pool": None, "summary": name}


def held(name, claim):
    # a finished, unlanded task holding CLAIM: holds_claims() is True while it has commits
    return {"state": "exited-ok", "worktree": "/nonexistent", "branch": "work/" + name, "claims": [claim],
            "pid": 0, "model": "m/a", "pool": "a"}


class RefillClaimBlocked(unittest.TestCase):
    def setUp(self):
        self.qdir = tempfile.mkdtemp()
        self.items = [item("fix-merge-blocked-1", "bug:X", 1), item("fix-merge-blocked-2", "bug:X", 2),
                      item("fix-replan-ok", "bug:Y", 3)]
        for it in self.items:
            self._write(it)
        self.spawned = []
        self.patches = [
            mock.patch.object(C, "load_pool", return_value=POOL),
            mock.patch.object(C, "qdir", return_value=self.qdir),
            mock.patch.object(C, "live_names", return_value=frozenset()),
            mock.patch.object(C, "breaker_until", return_value=0),
            mock.patch.object(C, "dead_on_arrival", return_value=False),
            mock.patch.object(C, "dead_models", return_value={}),
            mock.patch.object(C, "load", return_value={"held": held("held", "bug:X")}),
            mock.patch.object(C, "state_of", side_effect=lambda t: t["state"]),
            mock.patch.object(C, "holds_claims", return_value=True),
            mock.patch.object(C, "external_conflicts", return_value=[]),
            mock.patch.object(C, "doc_class_now", side_effect=lambda it: it.get("cls")),
            mock.patch.object(C, "cmd_spawn", side_effect=lambda ns: self.spawned.append(ns.name)),
        ]
        for p in self.patches:
            p.start()

    def _write(self, it):
        with open(os.path.join(self.qdir, it["name"] + ".json"), "w") as fh:
            json.dump(it, fh)

    def tearDown(self):
        for p in self.patches:
            p.stop()
        shutil.rmtree(self.qdir, ignore_errors=True)

    def test_blocked_tasks_take_no_slot_and_the_next_one_starts(self):
        C.cmd_refill(argparse.Namespace(target=2, prefix="fix-"))
        self.assertEqual(self.spawned, ["fix-replan-ok"])
        self.assertTrue(os.path.exists(os.path.join(self.qdir, "fix-merge-blocked-1.json")), "blocked task stays queued")

    def test_started_task_claims_block_the_rest_of_the_pass(self):
        self.items.append(item("fix-second-on-y", "bug:Y", 4))
        self._write(self.items[-1])
        # fix-replan-ok starts and its claim bug:Y is then live; the second Y task must wait, not double-start
        def add_task(ns):
            self.spawned.append(ns.name)
            C.load.return_value["fix-replan-ok"] = dict(held("fix-replan-ok", "bug:Y"), state="running", pid=os.getpid())
        with mock.patch.object(C, "cmd_spawn", side_effect=add_task):
            C.cmd_refill(argparse.Namespace(target=2, prefix="fix-"))
        self.assertEqual(self.spawned, ["fix-replan-ok"])


if __name__ == "__main__":
    unittest.main()
