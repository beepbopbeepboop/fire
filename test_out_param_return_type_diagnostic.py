#!/usr/bin/env python3
"""The `out` declarations the real Mojo compiler refuses, and where it says so.

Measured with `tools/mojo build` (2026-11-11), each case below is the real
compiler's primary message and location:

* `def ten(out self) -> Int:` in a struct: `functions must not declare both an
  'out' argument and a return type`, at the RETURN TYPE (`Int`), and then `self
  argument must be present in instance method` at `self`.
* `def __init__(out self) -> A:`: the same primary message, at the return type.
* `def f(out x: Int) -> Int:`: the same primary message at the return type,
  then `'out' argument cannot be returned by name`.
* `def set(out self, v: Int):` (a method, no return type): `'self' argument
  must have type 'Self'; use a 'where' clause ...`. Our compiler accepts it.
* `f(y)` where `def f(out x: Int)`: `invalid call to 'f': unexpected
  argument`. Our compiler accepts it.
* `fn f(...)`: `'fn' has been removed; use 'def' instead`. Our compiler accepts it.

Cases we already match are plain assertions. Cases we do not yet match are
`expectedFailure` with the bug doc that owns them: an unexpected success is a
failure, so the marker must be removed in the commit that fixes the gap.

Umbrella: bugs/TEST_out_self_with_return_type_fixtures_are_invalid_mojo.md.
"""

import os
import re
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

from gimple_codegen import compile_to_gimple

RETURN_OUT_MSG = "functions must not declare both an 'out' argument and a return type"
BUG = "bugs/TEST_out_self_with_return_type_fixtures_are_invalid_mojo.md"


def _compile(src, filename='t.mojo'):
    return compile_to_gimple(src, do_imports=False, filename=filename)


def _location(err):
    m = re.search(r":(\d+):(\d+): error", str(err))
    assert m, f"no line:col in diagnostic: {err}"
    return int(m.group(1)), int(m.group(2))


class OutParamReturnTypeDiagnostic(unittest.TestCase):

    # --- refused, with the real primary message -------------------------------

    def test_method_out_self_with_return_type_is_refused(self):
        with self.assertRaises(RuntimeError) as cm:
            _compile('struct A:\n'
                     '    var n: Int\n'
                     '    def ten(out self) -> Int:\n'
                     '        return 10\n')
        self.assertIn(RETURN_OUT_MSG, str(cm.exception))

    def test_init_out_self_with_return_type_is_refused(self):
        with self.assertRaises(RuntimeError) as cm:
            _compile('struct A:\n'
                     '    def __init__(out self) -> A:\n'
                     '        pass\n')
        self.assertIn(RETURN_OUT_MSG, str(cm.exception))

    def test_function_out_param_with_return_type_is_refused(self):
        with self.assertRaises(RuntimeError) as cm:
            _compile('def f(out x: Int) -> Int:\n'
                     '    return 2\n')
        self.assertIn(RETURN_OUT_MSG, str(cm.exception))

    # --- refused, at the real location (the return type) -----------------------
    # Real Mojo: `    def ten(out self) -> Int:` reports 5:26, the `I` of `Int`.

    def test_method_return_type_error_is_at_the_return_type(self):
        with self.assertRaises(RuntimeError) as cm:
            _compile('struct A:\n'
                     '    var n: Int\n'
                     '    def ten(out self) -> Int:\n'
                     '        return 10\n')
        line, col = _location(cm.exception)
        self.assertEqual((line, col), (3, 26))

    def test_function_return_type_error_is_at_the_return_type(self):
        with self.assertRaises(RuntimeError) as cm:
            _compile('def f(out x: Int) -> Int:\n'
                     '    return 2\n')
        line, col = _location(cm.exception)
        self.assertEqual((line, col), (1, 22))

    # --- accepted, as real Mojo accepts them ----------------------------------

    def test_mut_self_with_return_type_passes(self):
        _compile('struct A:\n'
                 '    var n: Int\n'
                 '    def ten(mut self) -> Int:\n'
                 '        return self.n\n')

    def test_init_out_self_without_return_type_passes(self):
        _compile('struct A:\n'
                 '    var x: Int\n'
                 '    def __init__(out self):\n'
                 '        self.x = 1\n')

    def test_return_type_without_out_passes(self):
        _compile('def f(x: Int) -> Int:\n'
                 '    return x\n')

    # --- real Mojo refuses; we accept. Each is a gap, not a pass. -------------

    @unittest.expectedFailure  # gap: out self on a non-constructor method, no return type
    def test_method_out_self_without_return_type_is_refused(self):
        with self.assertRaises(RuntimeError) as cm:
            _compile('struct A:\n'
                     '    var n: Int\n'
                     '    def set(out self, v: Int):\n'
                     '        self.n = v\n')
        self.assertIn("'self' argument must have type 'Self'", str(cm.exception))

    @unittest.expectedFailure  # gap: an out argument passed as a call argument
    def test_out_argument_passed_positionally_is_refused(self):
        with self.assertRaises(RuntimeError) as cm:
            _compile('def f(out x: Int):\n'
                     '    x = 2\n'
                     'def main():\n'
                     '    var y: Int\n'
                     '    f(y)\n')
        self.assertIn("invalid call to 'f': unexpected argument", str(cm.exception))

    @unittest.expectedFailure  # gap: the removed `fn` keyword is accepted
    def test_fn_keyword_is_refused(self):
        with self.assertRaises(RuntimeError) as cm:
            _compile('fn f(x: Int) -> Int:\n'
                     '    return x\n')
        self.assertIn("'fn' has been removed; use 'def' instead", str(cm.exception))


    @unittest.expectedFailure  # gap: out self with a non-Self parameter (real Mojo refuses the declaration)
    def test_method_out_self_with_int_parameter_is_refused_at_the_parameter(self):
        with self.assertRaises(RuntimeError) as cm:
            _compile('struct R:\n'
                     '    var a: Int\n'
                     '    def set(out self, v: Int):\n'
                     '        self.a = v\n')
        self.assertIn("'self' argument must have type 'Self'", str(cm.exception))

    @unittest.expectedFailure  # gap: out self with no other parameters (real Mojo: self must be present)
    def test_method_out_self_without_parameters_is_refused(self):
        with self.assertRaises(RuntimeError) as cm:
            _compile('struct R:\n'
                     '    var a: Int\n'
                     '    def reset(out self):\n'
                     '        self.a = 0\n')
        self.assertIn("self argument must be present in instance method", str(cm.exception))


if __name__ == '__main__':
    unittest.main()
