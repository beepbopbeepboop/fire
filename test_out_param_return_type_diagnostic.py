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

    def test_method_out_self_without_return_type_is_refused(self):
        with self.assertRaises(RuntimeError) as cm:
            _compile('struct A:\n'
                     '    var n: Int\n'
                     '    def set(out self, v: Int):\n'
                     '        self.n = v\n')
        self.assertIn("'self' argument must have type 'Self'", str(cm.exception))

    def test_out_argument_passed_positionally_is_refused(self):
        with self.assertRaises(RuntimeError) as cm:
            _compile('def f(out x: Int):\n'
                     '    x = 2\n'
                     'def main():\n'
                     '    var y: Int\n'
                     '    f(y)\n')
        self.assertIn("invalid call to 'f': unexpected argument", str(cm.exception))

    # --- the removed `fn` keyword: stage 1 warns (bugs/DIAGNOSTICS_fn_keyword_*) ---

    def test_fn_definition_compiles_with_the_real_warning_at_the_keyword(self):
        import contextlib
        import io
        err = io.StringIO()
        with contextlib.redirect_stderr(err):
            _compile('fn f(x: Int) -> Int:\n'
                     '    return x\n')
        self.assertIn("t.mojo:1:1: warning: 'fn' has been removed; use 'def' instead",
                      err.getvalue())

    def test_def_does_not_warn_about_fn(self):
        import contextlib
        import io
        err = io.StringIO()
        with contextlib.redirect_stderr(err):
            _compile('def f(x: Int) -> Int:\n'
                     '    return x\n')
        self.assertNotIn("'fn' has been removed", err.getvalue())

    def test_fn_as_an_identifier_does_not_warn(self):
        # CPython code uses `fn` as a name (logging's findCaller); that is not a definition.
        import contextlib
        import io
        err = io.StringIO()
        with contextlib.redirect_stderr(err):
            _compile('def g() -> Int:\n'
                     '    var fn = 3\n'
                     '    return fn\n')
        self.assertNotIn("'fn' has been removed", err.getvalue())


    def test_method_out_self_with_int_parameter_is_refused_at_the_parameter(self):
        with self.assertRaises(RuntimeError) as cm:
            _compile('struct R:\n'
                     '    var a: Int\n'
                     '    def set(out self, v: Int):\n'
                     '        self.a = v\n')
        self.assertIn("'self' argument must have type 'Self'", str(cm.exception))

    def test_method_out_self_without_parameters_is_refused(self):
        with self.assertRaises(RuntimeError) as cm:
            _compile('struct R:\n'
                     '    var a: Int\n'
                     '    def reset(out self):\n'
                     '        self.a = 0\n')
        self.assertIn("self argument must be present in instance method", str(cm.exception))


    def test_out_self_with_an_explicit_type_passes(self):
        # The standard library's nested `def default_init_func(out self: T, ...)`
        # (std/python/bindings.mojo:741): an explicitly typed `out self` is not
        # the method receiver, and real Mojo compiles it.
        _compile('struct R:\n'
                 '    var a: Int\n'
                 '    def make(args: Int):\n'
                 '        def init(out self: R, k: Int):\n'
                 '            self.a = k\n')


    def test_out_argument_passed_by_keyword_is_refused_at_the_value(self):
        # Measured with tools/mojo: `f(x=y)` is refused at the value, 6:9.
        with self.assertRaises(RuntimeError) as cm:
            _compile('def f(out x: Int):\n'
                     '    x = 2\n'
                     '\n'
                     'def main():\n'
                     '    var y: Int\n'
                     '    f(x=y)\n')
        self.assertIn("invalid call to 'f': unexpected keyword argument 'x'", str(cm.exception))
        self.assertEqual(_location(cm.exception), (6, 9))

    def test_mixed_signature_positional_extra_is_refused_at_the_argument(self):
        # Measured with tools/mojo: `f(1, y)` for `f(a: Int, out x: Int)` is refused at 6:10.
        with self.assertRaises(RuntimeError) as cm:
            _compile('def f(a: Int, out x: Int):\n'
                     '    x = a\n'
                     '\n'
                     'def main():\n'
                     '    var y: Int\n'
                     '    f(1, y)\n')
        self.assertIn("invalid call to 'f': unexpected argument", str(cm.exception))
        self.assertEqual(_location(cm.exception), (6, 10))

    def test_mixed_signature_omitting_the_out_argument_passes(self):
        # Measured with tools/mojo: `f(1)` is accepted (the out argument is returned, not passed).
        _compile('def f(a: Int, out x: Int):\n'
                 '    x = a\n'
                 'def main():\n'
                 '    var y: Int\n'
                 '    f(1)\n')

    def test_ordinary_keyword_arguments_still_pass(self):
        _compile('def f(a: Int, b: Int):\n'
                 '    pass\n'
                 'def main():\n'
                 '    f(a=1, b=2)\n')


if __name__ == '__main__':
    unittest.main()
