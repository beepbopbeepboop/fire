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


_STATIC_METHOD_SRC = '''\
struct Lim[dtype: DType]:
    def bias[dtype: DType]() -> Int:
        comptime if dtype == DType.float32:
            return 127
        else:
            return 1023

def plus_bias[dtype: DType](x: Int) -> Int:
    comptime b = Lim[dtype].bias()
    return x + b

def use(x: Int) -> Int:
    return plus_bias[Float32](x)
'''


def _instance_c(src: str, stem: str, fn_prefix: str) -> str:
    """Compile SRC and return the C of the instance whose mangled name starts
    with FN_PREFIX.

    The monomorphized instance TU is written by monomorphize.instantiate under
    tempfile.gettempdir(); point it at a private directory for the duration of
    the compile so another worker's mojo_inst_* directories in the shared temp
    cannot be mistaken for this instance.
    """
    home = tempfile.mkdtemp(prefix='ctm_member_')
    old = tempfile.tempdir
    tempfile.tempdir = home
    try:
        path = os.path.join(home, stem + '.mojo')
        with open(path, 'w') as f:
            f.write(src)
        compile_module_to_c_cached(src, path, stem, linkable=False)
        insts = [f for d in glob.glob(os.path.join(home, 'mojo_inst_*'))
                 for f in glob.glob(os.path.join(d, fn_prefix + '*.c'))]
        assert insts, 'the monomorphized instance TU was not produced'
        with open(max(insts, key=os.path.getmtime)) as f:
            return f.read()
    finally:
        tempfile.tempdir = old
        shutil.rmtree(home, ignore_errors=True)


class TestComptimeMemberMonomorphizedInstance(unittest.TestCase):
    def test_comptime_member_folds_in_function_instance(self):
        text = _instance_c(_SMALL_SRC, 'ctm_member_instance', 'inner_')
        # Pre-fix the local came out `double m;` (the receiver's type)
        # and the SIMD constructor emitted the int64 word; the folded
        # comptime member makes both sides int32.
        self.assertIn('int32_t m;', text,
                      'the comptime member was not folded: the instance '
                      'local is not int32_t (the cast/constructor read '
                      'the reference as a zero word)')

    def test_static_method_folds_in_function_instance(self):
        """A zero-argument static method reached through the struct's own
        bracket args (`Lim[dtype].bias()`) folds in the instance.

        The instance TU carries only the template, not the struct's
        definition, so pre-fix `b` stayed the undeclared-name zero word (the
        `ct param or undeclared: b` comment) and `plus_bias[Float32]` added 0
        instead of 127. The static-method call is the half of the `_ldexp_impl`
        family (`FPUtils[dtype].exponent_bias()`) that the member-read guard
        above does not reach."""
        text = _instance_c(_STATIC_METHOD_SRC, 'ctm_static_instance',
                           'plus_bias_')
        self.assertIn('(int64_t)127', text,
                      'the static method was not folded: bias() is not 127 '
                      '(the instance read the call as a zero word)')
        self.assertNotIn('ct param or undeclared', text,
                         'the instance still carries an undeclared comptime '
                         'binding:\n' + text)
        self.assertNotIn('1023', text,
                         'the false arm of bias() leaked into the Float32 '
                         'instance:\n' + text)

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
