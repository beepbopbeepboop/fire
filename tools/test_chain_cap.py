#!/usr/bin/env python3
"""A restart chain and a merge-fixer chain stop: the budget counts the chain's depth, not the next free name.

2026-11-10: fix-gate-formal-doc-truth-r2-...-r134 (178 tasks) restarted against a master that moved every pass.
`restart()` stripped one "-rN" and searched for a free "-rN" under the nested base, so the first free name always
looked like round 2 and the MAX_RESTARTS budget never fired. Pins: depth counts every "-rN", a deep chain is
abandoned by restart(), and a merge-fixer chain past MERGE_FIX_DEPTH is not nested again.

Run: python3 tools/test_chain_cap.py
"""
import os, sys, unittest
from unittest import mock
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import control as C
import integrate as I


class ChainDepth(unittest.TestCase):
    def test_each_r_suffix_is_one_restart(self):
        self.assertEqual(C.chain_depth("fix-gate-formal-doc-truth"), 0)
        self.assertEqual(C.chain_depth("fix-gate-formal-doc-truth-r2"), 1)
        self.assertEqual(C.chain_depth("fix-gate-formal-doc-truth-r2-r2-r2-r2-r2-r2-r134"), 7)

    def test_a_deep_chain_is_abandoned_by_restart(self):
        name = "fix-gate-x-r2-r2-r2-r2-r2-r2-r2-r2-r2-r2-r2"          # depth 11 = past MAX_RESTARTS
        reg = {name: {"state": "exited-err"}}
        t = {"name": name, "worktree": "/nonexistent", "branch": "b", "claims": [], "pid": 0, "model": "m"}
        with mock.patch.object(C, "load", return_value={name: t}), \
             mock.patch.object(C, "git", return_value=""), \
             mock.patch.object(C, "fleet_ledger", create=True), \
             mock.patch.object(C, "registry") as reg_cm, \
             mock.patch.object(C, "cmd_spawn") as spawn:
            reg_cm.return_value.__enter__.return_value = reg
            reg_cm.return_value.__exit__.return_value = False
            self.assertIsNone(C.restart(name, "test"))
            spawn.assert_not_called()
            self.assertEqual(reg[name]["state"], "abandoned")


class MergeFixDepth(unittest.TestCase):
    def test_a_fixer_of_a_fixer_past_the_cap_is_abandoned_not_queued(self):
        name = "fix-merge-fix-merge-fix-merge-fix-x"                   # three levels: at the cap
        reg = {name: {"state": "exited-ok"}}
        with mock.patch.object(I.C, "registry") as reg_cm, \
             mock.patch.object(I.C, "cmd_enqueue") as enq:
            reg_cm.return_value.__enter__.return_value = reg
            reg_cm.return_value.__exit__.return_value = False
            I.enqueue_merge_fix(name, {"branch": "work/x", "summary": "s", "claims": [], "cls": "easy"}, "")
            enq.assert_not_called()
            self.assertEqual(reg[name]["state"], "abandoned")


if __name__ == "__main__":
    unittest.main()
