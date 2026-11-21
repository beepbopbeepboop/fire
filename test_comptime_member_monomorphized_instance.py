#!/usr/bin/env python3
"""Pin for the stdlib-syntax red in the `_ldexp_impl` family (four files:
std/math/math.mojo, test/math/test_exp.mojo, test/math/test_ldexp.mojo,
test/math/test_math.mojo), whose monomorphized instances stopped at

    error: invalid operands to binary << (have 'float' and 'float')

A comptime reference to ANOTHER struct's members inside a monomorphized
FUNCTION instance (`FPUtils[dtype].integral_type`, `FPUtils[dtype].
exponent_bias()`, `FPUtils[dtype].mantissa_width()` in the stdlib's
_ldexp_impl) must be folded to its concrete value at elaboration: the
instance is its own translation unit with no definition of a struct the home
module merely imports, so a reference left in the source reads as a zero
word and the type derived from it erases to the wrong dtype.

Two guards:

  * the small module reproduces the shape in one file — a generic function
    reads a comptime member of a parameterized struct, and a local is built
    from it through `cast[it]()` and the `SIMD[it, 1](...)` constructor.
    Before the fix the local was declared `double` (the receiver's type,
    the cast echoing the receiver) and the constructor emitted the int64_t
    word; after the fix it is `int32_t`. The small module compiles "cleanly"
    both ways, so the guard asserts the DECLARED TYPE, not a compile error.
  * the four stdlib files failed with a hard gcc error before the fix, so
    their pinning transpile is the direct guard for the symptom.
"""

import glob
import os
import shutil
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

from compile_stdlib import get_stdlib_path, transpile_file
from build_stdlib_dylib import compile_module_to_c_cached


_SMALL_SRC = '''\
def _it_of[dtype: DType]() -> DType:
    comptime if dtype == DType.float32:
        return DType.int32
    elif dtype == DType.float64:
        return DType.int64
    else:
        comptime assert False, "unexpected dtype"

struct FPU[dtype: DType]:
    comptime integral = _it_of[dtype]()

def inner[dtype: DType](x: float) -> float:
    comptime it = FPU[dtype].integral
    var m = x.cast[it]() + SIMD[it, 1](7)
    return m

def main() -> None:
    var r: float = inner[Float32](1.0)
    print("ok", r)
'''


class TestComptimeMemberMonomorphizedInstance(unittest.TestCase):
    def test_comptime_member_folds_in_function_instance(self):
        # The monomorphized instance TU is written by monomorphize.instantiate
        # under tempfile.gettempdir(); point it at a private directory for the
        # duration of the compile so another worker's mojo_inst_* directories
        # in the shared temp cannot be mistaken for this instance.
        home = tempfile.mkdtemp(prefix='ctm_member_')
        old = tempfile.tempdir
        tempfile.tempdir = home
        try:
            path = os.path.join(home, 'ctm_member_instance.mojo')
            with open(path, 'w') as f:
                f.write(_SMALL_SRC)
            compile_module_to_c_cached(
                _SMALL_SRC, path, 'ctm_member_instance', linkable=False)
            insts = [f for d in glob.glob(os.path.join(home, 'mojo_inst_*'))
                     for f in glob.glob(os.path.join(d, 'inner_*.c'))]
            self.assertTrue(insts,
                            'the monomorphized instance TU was not produced')
            c = max(insts, key=os.path.getmtime)
            text = open(c).read()
            # Pre-fix the local came out `double m;` (the receiver's type)
            # and the SIMD constructor emitted the int64 word; the folded
            # comptime member makes both sides int32.
            self.assertIn('int32_t m;', text,
                          'the comptime member was not folded: the instance '
                          'local is not int32_t (the cast/constructor read '
                          'the reference as a zero word)')
        finally:
            tempfile.tempdir = old
            shutil.rmtree(home, ignore_errors=True)

    def test_stdlib_math_transpiles(self):
        path = get_stdlib_path() / "std" / "math" / "math.mojo"
        ok, msg, _cg, _gcc, _ref = transpile_file(str(path))
        self.assertTrue(ok, f"std/math/math.mojo failed to transpile: {msg}")

    def test_stdlib_test_exp_transpiles(self):
        path = get_stdlib_path() / "test" / "math" / "test_exp.mojo"
        ok, msg, _cg, _gcc, _ref = transpile_file(str(path))
        self.assertTrue(ok, f"test/math/test_exp.mojo failed to transpile: {msg}")

    def test_stdlib_test_ldexp_transpiles(self):
        path = get_stdlib_path() / "test" / "math" / "test_ldexp.mojo"
        ok, msg, _cg, _gcc, _ref = transpile_file(str(path))
        self.assertTrue(ok, f"test/math/test_ldexp.mojo failed to transpile: {msg}")

    def test_stdlib_test_math_transpiles(self):
        path = get_stdlib_path() / "test" / "math" / "test_math.mojo"
        ok, msg, _cg, _gcc, _ref = transpile_file(str(path))
        self.assertTrue(ok, f"test/math/test_math.mojo failed to transpile: {msg}")


if __name__ == "__main__":
    unittest.main()
