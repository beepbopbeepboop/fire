#!/usr/bin/env python3
"""The proof-gap ledger: scaffold holes live only in lib/Scaffold.lean.

Every `by sorry` in `lib/Scaffold.lean` must appear in
`formal.proof_gaps.SCAFFOLD_HOLES`. No other library module may contain
sorries. The census is obtained via `formal.lean.library_census` (elaborated
measurement), never a text scan.
"""
import os
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = HERE
sys.path.insert(0, ROOT)

from formal import lean as L
from formal import proof_gaps


class TestDiffHolesPure(unittest.TestCase):
    def test_empty_match(self):
        census = {"Scaffold": (1, ("scaffold_canary",)), "ProofLib": (0, ())}
        ledger = {"scaffold_canary": proof_gaps.Hole("step-01a", "x", "control")}
        self.assertEqual(proof_gaps.diff_holes(census, ledger), [])

    def test_unledgered_hole(self):
        census = {"Scaffold": (2, ("scaffold_canary", "probe_x")), "ProofLib": (0, ())}
        ledger = {"scaffold_canary": proof_gaps.Hole("step-01a", "x", "control")}
        problems = proof_gaps.diff_holes(census, ledger)
        self.assertTrue(any("unledgered" in p and "probe_x" in p for p in problems))

    def test_stale_ledger_row(self):
        census = {"Scaffold": (0, ()), "ProofLib": (0, ())}
        ledger = {"stale_hole": proof_gaps.Hole("step-01a", "x", "scaffold")}
        problems = proof_gaps.diff_holes(census, ledger)
        self.assertTrue(any("stale" in p and "stale_hole" in p for p in problems))

    def test_hole_in_non_scaffold_module(self):
        census = {"Scaffold": (1, ("scaffold_canary",)), "ProofLib": (1, ("bad_hole",))}
        ledger = {"scaffold_canary": proof_gaps.Hole("step-01a", "x", "control")}
        problems = proof_gaps.diff_holes(census, ledger)
        self.assertTrue(any("non-Scaffold" in p and "ProofLib" in p for p in problems))


class TestProofGapsCensus(unittest.TestCase):
    def test_scaffold_holes_match_census(self):
        lean = L.find_lean(ROOT)
        if not lean:
            self.skipTest("lean not found")
        lib_dir = os.path.join(ROOT, "lib")
        census = L.library_census(lean, lib_dir)
        problems = proof_gaps.diff_holes(census, proof_gaps.SCAFFOLD_HOLES)
        if problems:
            self.fail("proof gap ledger mismatch:\n" + "\n".join(problems))


if __name__ == "__main__":
    unittest.main()
