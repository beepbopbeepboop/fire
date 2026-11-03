#!/usr/bin/env python3
"""A queued task follows its bug doc's CURRENT class, not the class it was queued in.

2026-11-03: a doc was reclassed mid -> hard while a `mid` task for it was still queued. Refill used the stored class,
so the task started on iceman (mid + easy only) and burned 46 attempts on hard docs. The fix re-reads the doc's
location at every refill (control.doc_class_now); this test pins both the bug and the fix.

Run: python3 tools/test_swarm_class_refresh.py
"""
import os, shutil, sys, tempfile, unittest
from unittest import mock
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import control as C

# Only iceman, as tools/pool.json has it: mid and easy, never hard.
ICEMAN_ONLY = {"slots": [{"name": "iceman", "model": "opencode-go/iceman-contributor-free", "count": 20,
                          "class": "mid", "also": ["easy"]}]}


def item(cls):
    return {"name": "bug-mid-x", "claims": ["bug:CODEGEN_x"], "cls": cls, "pool": "iceman"}


class ClassFollowsTheFile(unittest.TestCase):
    def setUp(self):
        self.root = tempfile.mkdtemp()
        for d in ("bugs/mid", "bugs/hard"):
            os.makedirs(os.path.join(self.root, d))
        self.patches = [mock.patch.object(C, "MAIN", self.root),
                        mock.patch.object(C, "load_pool", return_value=ICEMAN_ONLY)]
        for p in self.patches:
            p.start()

    def tearDown(self):
        for p in self.patches:
            p.stop()
        shutil.rmtree(self.root, ignore_errors=True)

    def _doc(self, where):
        path = os.path.join(self.root, "bugs", where, "CODEGEN_x.md")
        with open(path, "w") as f:
            f.write("# doc\n")
        return path

    def test_reclassed_doc_is_hard_even_though_queued_as_mid(self):
        mid = self._doc("mid")
        self.assertEqual(C.doc_class_now(item("mid")), "mid")
        os.rename(mid, os.path.join(self.root, "bugs/hard/CODEGEN_x.md"))   # the reclass
        self.assertEqual(C.doc_class_now(item("mid")), "hard")

    def test_stale_mid_queue_entry_no_longer_lands_on_iceman(self):
        # The bug: the queue entry still says mid, and iceman takes mid. This is what ran hard docs.
        os.rename(self._doc("mid"), os.path.join(self.root, "bugs/hard/CODEGEN_x.md"))
        stale = item("mid")
        self.assertEqual(C.pick_slot(stale, {})["name"], "iceman")       # the bug: the stored class picks iceman
        refreshed = dict(stale, cls=C.doc_class_now(stale))
        self.assertIsNone(C.pick_slot(refreshed, {}),
                          "a hard doc must wait for a hard slot; iceman has none, so the task must not start")

    def test_mid_doc_still_runs_on_iceman(self):
        self._doc("mid")
        it = item("mid")
        self.assertEqual(C.pick_slot(dict(it, cls=C.doc_class_now(it)), {})["name"], "iceman")

    def test_easy_doc_is_easy(self):
        path = os.path.join(self.root, "bugs", "CODEGEN_x.md")
        with open(path, "w") as f:
            f.write("# doc\n")
        self.assertEqual(C.doc_class_now(item("mid")), "easy")

    def test_missing_doc_keeps_the_queued_class(self):
        self.assertEqual(C.doc_class_now(item("mid")), "mid")

    def test_item_without_a_bug_claim_keeps_its_class(self):
        self.assertEqual(C.doc_class_now({"claims": ["module:os"], "cls": "hard"}), "hard")


if __name__ == "__main__":
    unittest.main()
