#!/usr/bin/env python3
"""Pin for bugs/gate-stdlib-syntax.md: std/utils/variant.mojo must transpile."""

import os
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

from compile_stdlib import get_stdlib_path, transpile_file


class TestStdlibSyntaxVariant(unittest.TestCase):
    def test_variant_transpiles(self):
        path = get_stdlib_path() / "std" / "utils" / "variant.mojo"
        ok, msg, _cg, _gcc = transpile_file(str(path))
        self.assertTrue(ok, f"std/utils/variant.mojo failed to transpile: {msg}")


if __name__ == "__main__":
    unittest.main()
