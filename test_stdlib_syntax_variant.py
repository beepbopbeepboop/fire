#!/usr/bin/env python3
"""Pin for the stdlib-syntax gate: std/utils/variant.mojo must transpile.

The `gate-stdlib-syntax` bug doc was removed in 478a03b82 ("stdlib-syntax: pin
variant.mojo and remove fixed gate doc") once the job was green; this pin keeps
the one case that gate was about — a stdlib file whose syntax the compiler must
accept — from silently regressing now that the doc is gone.
"""

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
