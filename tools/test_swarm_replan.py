#!/usr/bin/env python3
"""A doc at a class the pool cannot serve must not be stranded.

Root cause (2026-11-10): pool.json documents `hard` as "bugs/hard/*.md (Opus 5.5)" while the opus
slot has count 0 and has never run a task. 25 hard docs sat at the one class with no slot, and the
escalation ladder had no way out of it. The ladder is one-way and easy models are not used for
higher-class work, so the fix is to decompose such a doc: a replan task at a servable class splits
it into parts filed at classes that DO have capacity, and the original is marked SPLIT.

Run: python3 tools/test_swarm_replan.py
"""
import json, os, shutil, sys, tempfile, unittest
from unittest import mock
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import control as C
import swarm as S

REAL_POOL = {"slots": [
    {"name": "qwen", "model": "m/qwen", "count": 1, "class": "easy"},
    {"name": "iceman", "model": "m/iceman", "count": 1, "class": "mid"},
    {"name": "opus", "model": "m/opus", "count": 0, "class": "hard"},
]}


class Unserved(unittest.TestCase):
    def test_a_class_with_no_slot_is_unserved(self):
        self.assertEqual(S.unserved_classes(REAL_POOL), {"hard": ["opus"]})

    def test_a_fully_served_pool_has_none(self):
        pool = {"slots": REAL_POOL["slots"][:2] + [{"name": "opus", "model": "m/opus", "count": 1, "class": "hard"}]}
        self.assertEqual(S.unserved_classes(pool), {})

    def test_a_slot_with_also_still_serves_its_extra_classes(self):
        pool = {"slots": [{"name": "iceman", "model": "m/i", "count": 1, "class": "mid", "also": ["easy"]},
                          {"name": "opus", "model": "m/o", "count": 0, "class": "hard"}]}
        self.assertEqual(S.unserved_classes(pool), {"hard": ["opus"]})

    def test_an_accepted_unserved_policy_is_still_unserved_for_replan(self):
        pool = {**REAL_POOL, "classes": {"unserved_policy": {"hard": "replan"}}}
        self.assertEqual(S.unserved_classes(pool), {"hard": ["opus"]})

    def test_an_accepted_unserved_policy_is_not_warned_about(self):
        pool = {**REAL_POOL, "classes": {"unserved_policy": {"hard": "replan"}}}
        self.assertEqual(S.unserved_classes(pool, warn_only=True), {})


class Split(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def write(self, rel, body):
        path = os.path.join(self.tmp, "bugs", rel)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        open(path, "w").write(body)
        return path

    def test_a_split_doc_reports_its_parts(self):
        self.write("hard/Xcase.md", "# X\nSPLIT: X-part1, X-part2\n")
        self.write("mid/X-part1.md", "# part 1\n")
        self.write("mid/X-part2.md", "# part 2\n")
        with mock.patch.object(C, "MAIN", self.tmp):
            self.assertEqual(S.split_reason("hard/Xcase"), "X-part1, X-part2")

    def test_a_marker_written_as_markdown_still_counts(self):
        # 2026-11-12: a replan wrote `# SPLIT: ...` (a heading); the parser needed column 0, so the decomposition was
        # ignored and the replan ran a second time.
        for i, line in enumerate(("# SPLIT: X-part1, X-part2", "## SPLIT: X-part1, X-part2", "> SPLIT: X-part1, X-part2",
                                  "- SPLIT: X-part1, X-part2", "**SPLIT:** X-part1, X-part2", "`SPLIT: X-part1, X-part2`")):
            self.write("hard/Xmd%d.md" % i, "%s\n\n# X\n" % line)
            self.write("mid/X-part1.md", "# part 1\n")
            self.write("mid/X-part2.md", "# part 2\n")
            with mock.patch.object(C, "MAIN", self.tmp):
                self.assertEqual(S.split_reason("hard/Xmd%d" % i), "X-part1, X-part2", line)

    def test_prose_mentioning_split_is_not_a_marker(self):
        self.write("hard/Z.md", "# Z\nWe SPLIT: this is prose in the middle of a line.\nthe doc says SPLIT: a, b here\n")
        with mock.patch.object(C, "MAIN", self.tmp):
            self.assertIsNone(S.split_reason("hard/Z"))
        self.assertIsNone(S.STOP.search("we should STOP: now"))
        self.assertEqual(S.STOP.search("## STOP: needs the owner").group(1), "needs the owner")

    def test_notes_in_the_line_are_not_part_names(self):
        # 2026-11-12: `(part1 landed: the where-clause text, wording)` made fragments look like missing parts
        self.write("hard/N.md", "SPLIT: N-part1 (fixed, deleted 2026-11-12), N-part2, N-part3 (part 3: a note, with commas)\n")
        self.write("mid/N-part2.md", "# p2\n"); self.write("mid/N-part3.md", "# p3\n")
        with mock.patch.object(C, "MAIN", self.tmp), mock.patch.object(S, "deleted_on_a_branch", lambda b: b == "N-part1"):
            self.assertEqual(S.split_parts("N-part1 (fixed, deleted 2026-11-12), N-part2, N-part3 (a, b)"),
                             ["N-part1", "N-part2", "N-part3"])
            self.assertIsNotNone(S.split_reason("hard/N"))

    def test_a_part_that_landed_is_not_an_orphan(self):
        # a part's doc is deleted by the fix that closes it: that must not make the parent look orphaned
        self.write("hard/L.md", "SPLIT: L-part1, L-part2\n"); self.write("mid/L-part2.md", "# p2\n")
        with mock.patch.object(C, "MAIN", self.tmp), mock.patch.object(S, "deleted_on_a_branch", lambda b: b == "L-part1"):
            self.assertEqual(S.split_reason("hard/L"), "L-part1, L-part2")
            self.assertFalse(S.split_all_landed("hard/L"))
        with mock.patch.object(C, "MAIN", self.tmp), mock.patch.object(S, "deleted_on_a_branch", lambda b: False):
            self.assertIsNone(S.split_reason("hard/L"), "a part never filed IS an orphan")

    def test_all_parts_landed_says_so_instead_of_replanning(self):
        self.write("hard/D.md", "SPLIT: D-part1, D-part2\n")
        with mock.patch.object(C, "MAIN", self.tmp), mock.patch.object(S, "deleted_on_a_branch", lambda b: True):
            self.assertTrue(S.split_all_landed("hard/D"))
            self.assertIn("every part has landed", S.block_reason("hard/D", S.load_state(), {"slots": [], "skip": []}, {}, set()))

    def test_a_doc_listing_itself_among_its_parts_is_not_its_own_orphan(self):
        self.write("hard/Self.md", "SPLIT: Self-part1, Self\n"); self.write("mid/Self-part1.md", "# p\n")
        with mock.patch.object(C, "MAIN", self.tmp):
            self.assertIsNotNone(S.split_reason("hard/Self"))

    def test_a_doc_without_the_line_has_no_split(self):
        self.write("hard/Y.md", "# Y\nno split here\n")
        with mock.patch.object(C, "MAIN", self.tmp):
            self.assertIsNone(S.split_reason("hard/Y"))

    def test_a_split_whose_parts_are_all_on_disk_counts(self):
        self.write("hard/Xcase.md", "# X\nSPLIT: X-part1, X-part2\n")
        self.write("mid/X-part1.md", "# part 1\n")
        self.write("X-part2.md", "# part 2\n")       # a part may be filed at any class directory
        with mock.patch.object(C, "MAIN", self.tmp):
            self.assertEqual(S.split_reason("hard/Xcase"), "X-part1, X-part2")

    def test_a_split_naming_a_missing_part_is_an_orphan_and_does_not_count(self):
        # 2026-11-11: an orphan SPLIT would park the original forever; None lets the replan run again
        self.write("hard/Xcase.md", "# X\nSPLIT: X-part1, X-part2\n")
        self.write("mid/X-part1.md", "# part 1\n")   # part2 was never filed
        with mock.patch.object(C, "MAIN", self.tmp):
            self.assertIsNone(S.split_reason("hard/Xcase"))

    def test_the_replan_prompt_asks_each_part_for_a_done_when_test(self):
        text = S.REPLAN_TASK % {"doc": "bugs/hard/Xcase.md", "cls": "hard", "slots": "opus",
                                "servable": "easy, mid"}
        self.assertIn("## Done when", text)
        self.assertIn("ONE quick test", text)
        self.assertIn("SPLIT: <base>-part1", text)

    def test_why_reports_a_split(self):
        self.write("hard/Xcase.md", "# X\nSPLIT: X-part1\n")
        self.write("mid/X-part1.md", "# part 1\n")
        with mock.patch.object(C, "MAIN", self.tmp), \
             mock.patch.object(C, "load", return_value={}), \
             mock.patch.object(C, "load_pool", return_value={"slots": [], "skip": []}), \
             mock.patch.object(C, "running_by_slot", return_value={}), \
             mock.patch.object(C, "qdir", return_value=self.tmp), \
             mock.patch.object(C, "external", return_value={}), \
             mock.patch.object(C, "dead_models", return_value={}), \
             mock.patch.object(S, "BUSY", {"names": set(), "claims": set()}), \
             mock.patch.object(S, "load_state", return_value={}), \
             mock.patch.object(S.subprocess, "run", return_value=mock.Mock(stdout="", returncode=0)):
            self.assertIn("SPLIT", S.why("hard/Xcase"))


class QueuedClass(unittest.TestCase):
    def test_a_doc_task_follows_its_doc(self):
        # a temp bugs/ tree, not the repo's: the real doc moves between classes, and this test pins the rule, not a file
        import tempfile, shutil
        root = tempfile.mkdtemp()
        try:
            os.makedirs(os.path.join(root, 'bugs', 'mid'))
            open(os.path.join(root, 'bugs', 'mid', 'SUITE_silentnoop.md'), 'w').close()
            item = {"name": "bug-suite-silentnoop", "claims": ["bug:SUITE_silentnoop"], "cls": "easy"}
            with mock.patch.object(C, 'MAIN', root):
                self.assertEqual(C.doc_class_now(item), "mid", "a bug- task's class follows its doc")
        finally:
            shutil.rmtree(root, ignore_errors=True)

    def test_controller_work_keeps_its_own_class(self):
        item = {"name": "fix-replan-diagnostics-align-decorator",
                "claims": ["bug:DIAGNOSTICS_align_decorator"], "cls": "easy"}
        self.assertEqual(C.doc_class_now(item), "easy",
                         "a replan runs at the class with a slot, not the doc's unserved class")


class QueuedUnserved(unittest.TestCase):
    def test_a_queued_task_for_an_unserved_class_is_dropped_so_the_doc_can_be_replanned(self):
        tmp = tempfile.mkdtemp()
        q = os.path.join(tmp, "queue"); os.makedirs(q)
        for name, cls in (("hard-one", "hard"), ("mid-one", "mid")):
            with open(os.path.join(q, name + ".json"), "w") as f:
                json.dump({"name": name, "cls": cls, "claims": ["bug:" + name]}, f)
        with mock.patch.object(C, "qdir", lambda: q):
            self.assertEqual(S.drop_queued_unserved({"hard": ["opus"]}), 1)
        self.assertEqual(sorted(os.listdir(q)), ["mid-one.json"], "only the unserved class's entry goes")


if __name__ == "__main__":
    unittest.main()
