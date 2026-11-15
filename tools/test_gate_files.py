#!/usr/bin/env python3
"""A job that is red on master is forgiven only for the files master also fails.

2026-11-15: stdlib-syntax was red on master for 7 files, so a batch that broke 208 more files was judged "pre-existing"
(per-job comparison) and landed. is_preexisting compares file sets.

Run: python3 tools/test_gate_files.py
"""
import os, sys, tempfile, unittest
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import integrate as I

LOG = """PASSED: 402
FAILED: 3 (0 expected, 3 unexpected)

UNEXPECTED failed files:
  a/one.mojo
    → gcc: error: too many arguments
  b/two.mojo
    → codegen: invalid bindings
  c/three.mojo
    → gcc: implicit declaration

Next section
  not/a/file.mojo
"""


class GateFiles(unittest.TestCase):
    def test_parses_the_failing_files_only(self):
        with tempfile.NamedTemporaryFile("w", suffix=".log", delete=False) as f:
            f.write(LOG)
        try:
            self.assertEqual(I.failing_files(f.name), ["a/one.mojo", "b/two.mojo", "c/three.mojo"])
        finally:
            os.unlink(f.name)
        self.assertEqual(I.failing_files("/nonexistent/suite.log"), [])

    def test_green_on_master_is_never_preexisting(self):
        self.assertFalse(I.is_preexisting("stdlib-syntax", ["a"], None))

    def test_a_subset_of_masters_files_is_preexisting(self):
        self.assertTrue(I.is_preexisting("stdlib-syntax", ["a"], ["a", "b"]))

    def test_a_new_file_makes_the_job_this_rounds(self):
        self.assertFalse(I.is_preexisting("stdlib-syntax", ["a", "new"], ["a", "b"]))

    def test_a_job_with_no_file_list_keeps_the_job_level_rule(self):
        self.assertTrue(I.is_preexisting("gimple-lint", [], []))


if __name__ == "__main__":
    unittest.main()
