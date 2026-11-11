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


class NoEscalationIntoAVoid(unittest.TestCase):
    def test_a_doc_does_not_escalate_into_an_unserved_class(self):
        st = {"fails": {"CODEGEN_x": S.ESCALATE_AFTER}}
        with mock.patch.object(S, "unserved_classes", return_value={"hard": ["opus"]}), \
             mock.patch.object(S, "doc_class", return_value="mid"):
            S.reclass_on_failure(st, "CODEGEN_x", "mid/CODEGEN_x")
        self.assertNotIn("CODEGEN_x", st.get("pending", {}),
                         "escalating into a class with no slot would strand the doc there")

    def test_a_doc_still_escalates_to_a_served_class(self):
        st = {"fails": {"CODEGEN_x": S.ESCALATE_AFTER}}
        with mock.patch.object(S, "unserved_classes", return_value={}), \
             mock.patch.object(S, "doc_class", return_value="mid"):
            S.reclass_on_failure(st, "CODEGEN_x", "mid/CODEGEN_x")
        self.assertEqual(st["pending"]["CODEGEN_x"], "hard")


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
        self.write("hard/X.md", "# X\nSPLIT: X-part1, X-part2\n")
        with mock.patch.object(C, "MAIN", self.tmp):
            self.assertEqual(S.split_reason("hard/X"), "X-part1, X-part2")

    def test_a_doc_without_the_line_has_no_split(self):
        self.write("hard/Y.md", "# Y\nno split here\n")
        with mock.patch.object(C, "MAIN", self.tmp):
            self.assertIsNone(S.split_reason("hard/Y"))

    def test_why_reports_a_split(self):
        self.write("hard/X.md", "# X\nSPLIT: X-part1\n")
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
            self.assertIn("SPLIT", S.why("hard/X"))


class QueuedClass(unittest.TestCase):
    def test_a_doc_task_follows_its_doc(self):
        item = {"name": "bug-suite-silentnoop", "claims": ["bug:SUITE_silentnoop"], "cls": "easy"}
        self.assertEqual(C.doc_class_now(item), "mid", "a bug- task's class follows its doc")

    def test_controller_work_keeps_its_own_class(self):
        item = {"name": "fix-replan-diagnostics-align-decorator",
                "claims": ["bug:DIAGNOSTICS_align_decorator"], "cls": "easy"}
        self.assertEqual(C.doc_class_now(item), "easy",
                         "a replan runs at the class with a slot, not the doc's unserved class")


if __name__ == "__main__":
    unittest.main()
