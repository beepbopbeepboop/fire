#!/usr/bin/env python3
"""A wedged bug doc must say why, and the DONE ratchet must only skip FINISHED fixes.

Two defects, both 2026-11-10:

1. The feeder skipped docs silently. A hard doc with no hard slot, a doc held by a live task, a doc
   matching the skip pattern — all skipped every pass with no log line, so "why is this bug not
   moving?" had no answer. Every skip is now logged, and `swarm.py --why DOC` answers on demand.
2. The DONE ratchet skipped a doc that ANY branch deleted. A deletion by a worker that never
   finished (no DONE verdict, no commits) is not a fix, and skipping on it stranded the doc
   forever. The ratchet now requires a finished fix: a DONE task with commits, not yet landed.

Run: python3 tools/test_swarm_why.py
"""
import os, shutil, sys, tempfile, unittest
from unittest import mock
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import control as C
import swarm as S


def task(name, verdict, ahead, fixer=None, base="BASE"):
    return {"name": name, "state": "superseded", "pid": 0, "worktree": "/nonexistent",
            "branch": "work/" + name, "claims": ["bug:" + base], "summary": name,
            "started": "2026-11-10 00:00:00", "_verdict": verdict, "_ahead": ahead, "fixer": fixer}


class Landable(unittest.TestCase):
    def test_only_a_finished_fix_counts(self):
        tasks = {"a": task("a", "DONE", 2), "b": task("b", "", 2), "c": task("c", "DONE", 0),
                 "d": task("d", "DONE", 2, fixer="fix-merge-d")}
        with mock.patch.object(C, "load", return_value=tasks), \
             mock.patch.object(C, "verdict", side_effect=lambda t: t["_verdict"]), \
             mock.patch.object(C, "ahead", side_effect=lambda t: t["_ahead"]):
            self.assertEqual(S.landable("BASE"), ["a"],
                             "only a DONE task with commits and no fixer is a finished fix")

    def test_a_fixer_owned_branch_is_not_re_landed(self):
        tasks = {"d": task("d", "DONE", 2, fixer="fix-merge-d")}
        with mock.patch.object(C, "load", return_value=tasks), \
             mock.patch.object(C, "verdict", side_effect=lambda t: t["_verdict"]), \
             mock.patch.object(C, "ahead", side_effect=lambda t: t["_ahead"]):
            self.assertEqual(S.landable("BASE"), [])


class Why(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.doc = os.path.join(self.tmp, "bugs", "X.md")
        os.makedirs(os.path.dirname(self.doc))
        open(self.tmp and self.doc, "w").write("# X\n")

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def why(self, doc, deletion, tasks=None, pool=None, held=None):
        tasks = tasks or {}
        pool = pool or {"slots": [{"name": "opus", "model": "claude-opus-5-5", "count": 0, "class": "hard"}],
                        "skip": []}
        with mock.patch.object(C, "MAIN", self.tmp), \
             mock.patch.object(C, "load", return_value=tasks), \
             mock.patch.object(C, "verdict", side_effect=lambda t: t.get("_verdict", "")), \
             mock.patch.object(C, "ahead", side_effect=lambda t: t.get("_ahead", 0)), \
             mock.patch.object(C, "load_pool", return_value=pool), \
             mock.patch.object(C, "running_by_slot", return_value={}), \
             mock.patch.object(C, "qdir", return_value=self.tmp), \
             mock.patch.object(C, "external", return_value={}), \
             mock.patch.object(C, "dead_models", return_value={}), \
             mock.patch.object(S, "BUSY", {"names": set(), "claims": set()}), \
             mock.patch.object(S, "load_state", return_value={}), \
             mock.patch.object(S, "stop_reason", return_value=None), \
             mock.patch.object(S.subprocess, "run",
                               return_value=mock.Mock(stdout=deletion, returncode=0)):
            return S.why(doc)

    def test_no_free_slot_names_the_slot(self):
        w = self.why("bugs/hard/X.md", deletion="")
        self.assertIn("no free hard slot", w)
        self.assertIn("opus", w, "the answer names the slot and why it cannot take the doc")

    def test_skip_pattern_is_reported(self):
        w = self.why("bugs/OPEN_WORK.md", deletion="", pool={
            "slots": [{"name": "s", "model": "m", "count": 1, "class": "easy"}], "skip": ["OPEN_WORK"]})
        self.assertIn("skip pattern", w)

    def test_a_finished_fix_is_the_ratchet(self):
        w = self.why("bugs/X.md", deletion="abc Deleted bugs/X.md\n",
                     tasks={"bug-x": task("bug-x", "DONE", 2, base="X")})
        self.assertIn("DONE ratchet", w)

    def test_an_unfinished_deletion_is_not_a_ratchet(self):
        """A branch deleted the doc but no DONE task holds it: the doc is NOT skipped, so the answer
        must fall through to whatever actually blocks it (here, the hard slot)."""
        w = self.why("bugs/hard/X.md", deletion="abc Deleted bugs/X.md\n",
                     tasks={"bug-x": task("bug-x", "", 2, base="X")})
        self.assertNotIn("DONE ratchet", w)
        self.assertIn("no free hard slot", w)


if __name__ == "__main__":
    unittest.main()
