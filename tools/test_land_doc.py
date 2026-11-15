#!/usr/bin/env python3
"""land_doc: a finished branch that cannot land becomes bugs/LAND-<root>.md, and a second failure appends a Status entry.

Run: python3 tools/test_land_doc.py
"""
import os, sys, tempfile, unittest
from unittest import mock
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import control as C
import integrate as I

T = {"branch": "work/bug-x", "summary": "fix x", "claims": ["bug:X"]}


class LandDoc(unittest.TestCase):
    def test_creates_then_appends(self):
        with tempfile.TemporaryDirectory() as d:
            os.makedirs(os.path.join(d, "bugs"))
            with mock.patch.object(C, "MAIN", d), mock.patch.object(I, "commit_doc") as cd:
                p = I.land_doc("fix-merge-fix-merge-bug-x", T, "merge-fix depth cap", "conflicts in a.py")
                self.assertEqual(os.path.basename(p), "LAND-x.md")      # the fix-merge- chain collapses to the root name
                body = open(p).read()
                self.assertIn("`work/bug-x`", body); self.assertIn("conflicts in a.py", body)
                I.land_doc("bug-x", T, "second attempt")
                body = open(p).read()
                self.assertEqual(body.count("# Land:"), 1)               # one doc, not two
                self.assertIn("second attempt", body); self.assertIn("merge-fix depth cap", body)
                self.assertEqual(cd.call_count, 2)


if __name__ == "__main__":
    unittest.main()
