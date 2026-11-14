"""Regression: SIMD __pow__/exp elaboration must not be refused as
"advance without converging" due to misclassified fixed comptime bracket
args like `2 * Int(Self.length)` (bug:CODEGEN_simd_exp_staticTuple_refusal).
"""

import io
import os
import sys
import unittest
from contextlib import redirect_stderr, redirect_stdout


class TestSimdExpStaticTupleRefusal(unittest.TestCase):
    def test_std_simd_no_advance_without_converging(self):
        from module_loader import STDLIB_PATH
        import build_stdlib_dylib as bsd

        path = os.path.join(STDLIB_PATH, 'std', 'simd.mojo')
        self.assertTrue(os.path.exists(path), f'missing {path}')
        with open(path) as f:
            src = f.read()

        buf = io.StringIO()
        with redirect_stdout(buf), redirect_stderr(buf):
            bsd.compile_module_to_c_cached(src, path, 'std.simd')
        out = buf.getvalue()
        self.assertNotIn('advance without converging', out, out)
        self.assertNotIn('NOT being cached', out, out)


if __name__ == '__main__':
    unittest.main()
