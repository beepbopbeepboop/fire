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
             mock.patch.object(I.C, "ahead_since_base", return_value=2), \
             mock.patch.object(I.C, "cmd_enqueue") as enq:
            reg_cm.return_value.__enter__.return_value = reg
            reg_cm.return_value.__exit__.return_value = False
            I.enqueue_merge_fix(name, {"branch": "work/x", "summary": "s", "claims": [], "cls": "easy"}, "")
            enq.assert_not_called()
            self.assertEqual(reg[name]["state"], "abandoned")
            self.assertTrue(reg[name]["merge_capped"])         # pick_candidates skips it: no re-probe every pass

    def _requeue(self, name, ahead, **extra):
        """Run enqueue_merge_fix for NAME whose own round added AHEAD commits; return (queued meta or None, reg)."""
        reg = {name: {"state": "exited-ok"}}
        t = {"branch": "work/x", "summary": "s", "claims": [], "cls": "easy", **extra}
        with mock.patch.object(I.C, "registry") as reg_cm, \
             mock.patch.object(I.C, "ahead_since_base", return_value=ahead), \
             mock.patch.object(I.C, "doc_exists_for", return_value=True), \
             mock.patch.object(I.C, "free_task_name", side_effect=lambda n: n), \
             mock.patch.object(I.C, "cmd_enqueue") as enq:
            reg_cm.return_value.__enter__.return_value = reg
            reg_cm.return_value.__exit__.return_value = False
            I.enqueue_merge_fix(name, t, "")
        return (enq.call_args[0][0].meta if enq.called else None), reg

    def test_a_fixer_that_committed_nothing_is_not_a_level(self):
        # 2026-11-13: the third fixer of bug-mid-codegen-simd-and-array reported DONE without merging master; the next
        # conflict hit the depth cap although the chain had not tried a third merge.
        name = "fix-merge-fix-merge-fix-merge-x"
        meta, reg = self._requeue(name, ahead=0)
        self.assertIsNotNone(meta, "an idle round must be retried, not capped")
        self.assertEqual(meta["merge_depth"], 3)               # the level the idle fixer held, not one deeper
        self.assertEqual(meta["merge_idle"], 1)
        self.assertNotIn("merge_capped", reg[name])

    def test_idle_rounds_are_forgiven_only_a_few_times_in_a_row(self):
        name = "fix-merge-fix-merge-fix-merge-x"
        meta, reg = self._requeue(name, ahead=0, merge_depth=3, merge_idle=I.MERGE_FIX_IDLE)
        self.assertIsNone(meta)
        self.assertTrue(reg[name]["merge_capped"])

    def test_a_fixer_that_committed_counts_and_resets_the_idle_run(self):
        meta, _ = self._requeue("fix-merge-x", ahead=1, merge_depth=1, merge_idle=1)
        self.assertEqual((meta["merge_depth"], meta["merge_idle"]), (2, 0))

    def test_a_branch_whose_doc_is_gone_gets_no_fixer(self):
        name = "bug-x"
        reg = {name: {"state": "exited-ok"}}
        with mock.patch.object(I.C, "registry") as reg_cm, \
             mock.patch.object(I.C, "doc_exists_for", return_value=False), \
             mock.patch.object(I.C, "cmd_enqueue") as enq:
            reg_cm.return_value.__enter__.return_value = reg
            reg_cm.return_value.__exit__.return_value = False
            I.enqueue_merge_fix(name, {"branch": "work/x", "summary": "s", "claims": ["bug:GONE"], "cls": "easy"}, "")
            enq.assert_not_called()
            self.assertTrue(reg[name]["merge_capped"])
            self.assertNotIn("fixer", reg[name])

    def test_pick_candidates_skips_a_capped_branch(self):
        t = {"slot": 1, "state": "exited-ok", "merge_capped": "x", "branch": "b", "worktree": "/w", "claims": []}
        with mock.patch.object(I.C, "load", return_value={"n": t}), \
             mock.patch.object(I.C, "state_of", return_value="exited-ok"), \
             mock.patch.object(I.C, "verdict", side_effect=AssertionError("a capped branch is not even probed")):
            self.assertEqual(I.pick_candidates(quiet=True), [])


if __name__ == "__main__":
    unittest.main()
