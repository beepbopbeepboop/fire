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


class ConflictBecomesLandDoc(unittest.TestCase):
    """A conflicting branch is capped (never re-probed) and gets a LAND doc, however many fixer rounds it had before."""
    def _hand(self, name, claims=()):
        reg = {name: {"state": "exited-ok"}}
        t = {"branch": "work/x", "summary": "s", "claims": list(claims), "cls": "easy"}
        with mock.patch.object(I.C, "registry") as reg_cm, \
             mock.patch.object(I, "land_doc") as ld, \
             mock.patch.object(I.C, "cmd_enqueue") as enq:
            reg_cm.return_value.__enter__.return_value = reg
            reg_cm.return_value.__exit__.return_value = False
            I.hand_to_land_doc(name, t, "CONFLICT (content): Merge conflict in a/b.py\n")
        enq.assert_not_called()                                # no fixer task is queued any more
        return reg, ld

    def test_conflict_caps_the_branch_and_files_a_land_doc(self):
        reg, ld = self._hand("bug-x", ["bug:X"])
        self.assertEqual(reg["bug-x"]["state"], "abandoned")
        self.assertTrue(reg["bug-x"]["merge_capped"])          # pick_candidates skips it: no re-probe every pass
        ld.assert_called_once()
        self.assertIn("a/b.py", ld.call_args[0][3])            # the doc names the conflicting files

    def test_a_deep_old_fixer_name_is_no_special_case(self):
        reg, ld = self._hand("fix-merge-fix-merge-fix-merge-fix-x")
        self.assertTrue(reg["fix-merge-fix-merge-fix-merge-fix-x"]["merge_capped"])
        ld.assert_called_once()

    def test_a_not_done_branch_with_no_doc_is_reported_stuck(self):
        t = {"slot": 1, "state": "exited-ok", "branch": "b", "worktree": "/w", "claims": ["bug:GONE"]}
        stuck = []
        with mock.patch.object(I.C, "load", return_value={"n": t}), \
             mock.patch.object(I.C, "state_of", return_value="exited-ok"), \
             mock.patch.object(I.C, "verdict", return_value="BLOCKED"), \
             mock.patch.object(I.C, "ahead", return_value=2), \
             mock.patch.object(I.C, "doc_exists_for", return_value=False):
            self.assertEqual(I.pick_candidates(quiet=True, stuck_out=stuck), [])
        self.assertEqual([n for n, _, _ in stuck], ["n"])

    def test_a_done_branch_with_a_dirty_tree_is_reported_stuck(self):
        t = {"slot": 1, "state": "exited-ok", "branch": "b", "worktree": "/w", "claims": ["bug:X"]}
        stuck = []
        with mock.patch.object(I.C, "load", return_value={"n": t}), \
             mock.patch.object(I.C, "state_of", return_value="exited-ok"), \
             mock.patch.object(I.C, "verdict", return_value="DONE"), \
             mock.patch.object(I.C, "ahead", return_value=1), \
             mock.patch.object(I.C, "tree_extras", return_value=["a.py"]):
            self.assertEqual(I.pick_candidates(quiet=True, stuck_out=stuck), [])
        self.assertIn("a.py", stuck[0][2])

    def test_pick_candidates_skips_a_capped_branch(self):
        t = {"slot": 1, "state": "exited-ok", "merge_capped": "x", "branch": "b", "worktree": "/w", "claims": []}
        with mock.patch.object(I.C, "load", return_value={"n": t}), \
             mock.patch.object(I.C, "state_of", return_value="exited-ok"), \
             mock.patch.object(I.C, "verdict", side_effect=AssertionError("a capped branch is not even probed")):
            self.assertEqual(I.pick_candidates(quiet=True), [])


class ConflictTextIsPerBranch(unittest.TestCase):
    """A probe prints every branch in turn; a branch's LAND doc must name only its own files."""
    def test_section_stops_at_the_next_branch(self):
        out = ("merged a\nCONFLICT b:\nCONFLICT (content): Merge conflict in x.py\n(probe) b conflicts: left out\n"
               "CONFLICT c:\nCONFLICT (content): Merge conflict in y.py\nMERGED: a\n")
        self.assertEqual(I.conflict_section(out, "b"), "CONFLICT (content): Merge conflict in x.py")
        self.assertEqual(I.conflict_section(out, "c"), "CONFLICT (content): Merge conflict in y.py")

    def test_conflict_lines_keeps_every_file(self):
        out = "Auto-merging q\n" + "".join("CONFLICT (content): Merge conflict in f%d.py\n" % i for i in range(40))
        self.assertEqual(len(I.conflict_lines(out).splitlines()), 40)


class AppendOnlyTestConflictsMerge(unittest.TestCase):
    """Two branches that each append a test at the same place in test_gimple.py both land; an edit of the same
    existing line is still a conflict."""
    def _repo(self, base, ours, theirs, fname="test_gimple.py"):
        import tempfile, subprocess, os
        d = tempfile.mkdtemp()
        def g(*a):
            return subprocess.run(["git", "-c", "user.name=t", "-c", "user.email=t@t"] + list(a), cwd=d,
                                  capture_output=True, text=True)
        g("init", "-q", "-b", "master")
        def put(text, msg):
            with open(os.path.join(d, fname), "w") as fh:
                fh.write(text)
            g("add", fname); g("commit", "-q", "-m", msg)
        put(base, "base")
        g("switch", "-q", "-c", "side"); put(theirs, "theirs")
        g("switch", "-q", "master"); put(ours, "ours")
        r = g("merge", "--no-ff", "-m", "m", "side")
        self.assertTrue(r.returncode)
        return d, fname

    def test_both_added_blocks_are_kept(self):
        import os
        d, f = self._repo("a = 1\n\nz = 9\n", "a = 1\n\nb = 2\n\nz = 9\n", "a = 1\n\nc = 3\n\nz = 9\n")
        self.assertTrue(I.union_resolve(d))
        text = open(os.path.join(d, f)).read()
        self.assertIn("b = 2", text); self.assertIn("c = 3", text); self.assertNotIn("<<<<<<<", text)

    def test_an_edit_of_the_same_line_is_left_alone(self):
        d, f = self._repo("a = 1\n", "a = 2\n", "a = 3\n")
        self.assertFalse(I.union_resolve(d))

    def test_other_files_are_never_resolved(self):
        d, f = self._repo("a = 1\n\nz = 9\n", "a = 1\n\nb = 2\n\nz = 9\n", "a = 1\n\nc = 3\n\nz = 9\n",
                          fname="emit_calls.py")
        self.assertFalse(I.union_resolve(d))


if __name__ == "__main__":
    unittest.main()
