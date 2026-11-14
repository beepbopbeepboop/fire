#!/usr/bin/env python3
"""Pin for the stdlib-syntax red where `test/math/test_tanh.mojo` failed to transpile.

The gate job is green again; this keeps that stdlib test file transpiling
through gimple_codegen.
"""

import os
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

from compile_stdlib import get_stdlib_path, transpile_file


class TestStdlibSyntaxTanh(unittest.TestCase):
    def test_tanh_transpiles(self):
        path = get_stdlib_path() / "test" / "math" / "test_tanh.mojo"
        ok, msg, _cg, _gcc, _ref = transpile_file(str(path))
        self.assertTrue(ok, f"test/math/test_tanh.mojo failed to transpile: {msg}")


if __name__ == "__main__":
    unittest.main()
