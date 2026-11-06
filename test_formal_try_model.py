#!/usr/bin/env python3
"""TryStmt translation in the arm64 proof model (step-27b)."""

import os
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

import fire_compiler as F
import formal.arm64_proof_gen as G


class TestTryModel(unittest.TestCase):
    def _get_fn(self, source, name="main"):
        mod = F.Parser(F.py_tokenize(source)).parse_module()
        for s in mod:
            if getattr(s, "name", None) == name:
                return s
        raise AssertionError(f"function {name} not found")

    def test_a_try_finally_flattened(self):
        source = (
            "def main(n):\n"
            "    try:\n"
            "        x = 1\n"
            "    finally:\n"
            "        y = 2\n"
            "    return x + y\n"
        )
        fn = self._get_fn(source)
        helpers = []
        out = G._stmts_go(fn.body, "n", {"n": "n"}, "main", [0], helpers,
                          {}, {}, G._Scope())
        # Translation succeeds; both bindings processed in order
        self.assertIn("(UInt64.ofNat 1)", out)
        self.assertIn("(UInt64.ofNat 2)", out)
        self.assertLess(out.index("(UInt64.ofNat 1)"), out.index("(UInt64.ofNat 2)"))

    def test_b_try_except_pass_over_nonraising_body(self):
        source = (
            "def main(n):\n"
            "    try:\n"
            "        x = 1\n"
            "    except ValueError:\n"
            "        pass\n"
            "    return x\n"
        )
        fn = self._get_fn(source)
        helpers = []
        out = G._stmts_go(fn.body, "n", {"n": "n"}, "main", [0], helpers,
                          {}, {}, G._Scope())
        self.assertIn("(UInt64.ofNat 1)", out)

    def test_c_except_as_e_raises(self):
        source = (
            "def main(n):\n"
            "    try:\n"
            "        x = 1\n"
            "    except ValueError as e:\n"
            "        pass\n"
            "    return x\n"
        )
        fn = self._get_fn(source)
        helpers = []
        with self.assertRaises(NotImplementedError) as cm:
            G._stmts_go(fn.body, "n", {"n": "n"}, "main", [0], helpers,
                        {}, {}, G._Scope())
        self.assertIn("as e", str(cm.exception))

    def test_d_return_inside_body_raises(self):
        source = (
            "def main(n):\n"
            "    try:\n"
            "        return 1\n"
            "    finally:\n"
            "        y = 2\n"
            "    return y\n"
        )
        fn = self._get_fn(source)
        helpers = []
        with self.assertRaises(NotImplementedError) as cm:
            G._stmts_go(fn.body, "n", {"n": "n"}, "main", [0], helpers,
                        {}, {}, G._Scope())
        self.assertIn("return", str(cm.exception).lower())

    def test_e_python_oracle_matches(self):
        source = (
            "def main(n):\n"
            "    try:\n"
            "        x = 1\n"
            "    finally:\n"
            "        y = 2\n"
            "    return x + y\n"
        )
        ns = {}
        exec(source, ns)
        self.assertEqual(ns["main"](0), 3)


if __name__ == "__main__":
    unittest.main()
