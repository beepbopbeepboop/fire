"""Regression pin for CODEGEN_dict_comprehension_repr_is_separately_broken
Defects 1 (int key stringified) and 2 (0 value as None) are fixed on master.
This test pins the correct compiled repr behavior.
"""
import unittest
import subprocess
import sys


def run_case(name):
    out = subprocess.run(
        [sys.executable, "test_runtime_diff.py", "--case", name],
        capture_output=True, text=True
    )
    assert out.returncode == 0, out.stderr
    assert "PASS" in out.stdout, f"Case {name} failed: {out.stdout}\n{out.stderr}"


class TestDictComprehensionReprRegression(unittest.TestCase):
    def test_dict_comprehension_repr_fixed(self):
        # Int keys render as ints (not quoted strings)
        run_case("dict_int_key_spelling_repr_matches_cpython")
        # Zero value renders as 0 (not None)
        run_case("dict_repr_zero_value_is_not_the_none_sentinel")
