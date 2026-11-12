#!/usr/bin/env python3
"""A call that passes a literal to an `__mlir_type.*` parameter is refused.

Measured with `tools/mojo build` (2026-11-12), the real compiler refuses every
literal passed to a `__mlir_type.index` parameter, and says so at the argument:

* `foo(1.5)`    -> `invalid call to 'foo': value passed to 'x' cannot be
  converted from 'FloatLiteral[1.5]' to '__mlir_type.index'` at the `1.5`.
* `foo(3)`      -> the same, from 'IntLiteral[3]' (an int literal is not an
  MLIR index value).
* `foo("s")`    -> the same, from 'StringLiteral["s"]'.
* `foo(True)`   -> the same, from 'Bool'.

Our compiler accepted all four and ran them. This file pins the refusal.
Passing a VARIABLE of the wrong type is not checked here: that needs the
argument's static type, which this front end does not have (see
bugs/DIAGNOSTICS_mlir_annotations-part1.md).
"""

import os
import re
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

from gimple_codegen import compile_to_gimple

ANN = "__mlir_type.index"


def _compile(src, filename='t.mojo'):
    return compile_to_gimple(src, do_imports=False, filename=filename)


def _location(err):
    m = re.search(r":(\d+):(\d+): error", str(err))
    assert m, f"no line:col in diagnostic: {err}"
    return int(m.group(1)), int(m.group(2))


class MlirAnnotationCallDiagnostic(unittest.TestCase):

    def _refused(self, src):
        with self.assertRaises(RuntimeError) as cm:
            _compile(src)
        return str(cm.exception)

    def test_float_literal_to_mlir_type_is_refused_at_argument(self):
        msg = self._refused(
            f'def foo(x: {ANN}):\n'
            '    pass\n'
            '\n'
            'def main():\n'
            '    foo(1.5)\n')
        self.assertIn("error: invalid call to 'foo'", msg)
        self.assertEqual(_location(msg), (5, 9))

    def test_int_literal_to_mlir_type_is_refused(self):
        msg = self._refused(
            f'def foo(x: {ANN}):\n'
            '    pass\n'
            '\n'
            'def main():\n'
            '    foo(3)\n')
        self.assertIn("error: invalid call to 'foo'", msg)
        self.assertEqual(_location(msg), (5, 9))

    def test_string_literal_to_mlir_type_is_refused(self):
        msg = self._refused(
            f'def foo(x: {ANN}):\n'
            '    pass\n'
            '\n'
            'def main():\n'
            '    foo("s")\n')
        self.assertIn("error: invalid call to 'foo'", msg)

    def test_bool_literal_to_mlir_type_is_refused(self):
        msg = self._refused(
            f'def foo(x: {ANN}):\n'
            '    pass\n'
            '\n'
            'def main():\n'
            '    foo(True)\n')
        self.assertIn("error: invalid call to 'foo'", msg)

    def test_keyword_literal_to_mlir_type_is_refused_at_value(self):
        msg = self._refused(
            f'def foo(x: {ANN}):\n'
            '    pass\n'
            '\n'
            'def main():\n'
            '    foo(x=2.5)\n')
        self.assertIn("error: invalid call to 'foo'", msg)
        self.assertEqual(_location(msg), (5, 11))

    def test_second_parameter_is_checked_by_position(self):
        msg = self._refused(
            f'def foo(a: Int, x: {ANN}):\n'
            '    pass\n'
            '\n'
            'def main():\n'
            '    foo(1, 2.5)\n')
        self.assertIn("error: invalid call to 'foo'", msg)
        self.assertEqual(_location(msg), (5, 12))

    # --- not refused: the check must not reach past what it can see -----------

    def test_plain_annotation_is_not_checked(self):
        # Only `__mlir_type.*` annotations are checked by this rule.
        _compile('def foo(x: Int):\n'
                 '    pass\n'
                 '\n'
                 'def main():\n'
                 '    foo(1.5)\n')

    def test_variable_argument_is_not_checked(self):
        # A name's type is not known to this front end; no guess is made.
        _compile(f'def foo(x: {ANN}):\n'
                 '    pass\n'
                 '\n'
                 'def main():\n'
                 '    var y = 2.5\n'
                 '    foo(y)\n')

    def test_star_argument_before_mlir_parameter_stops_the_check(self):
        # `*args` at the call site shifts positions; the check gives up there.
        _compile(f'def foo(a: Int, x: {ANN}):\n'
                 '    pass\n'
                 '\n'
                 'def main():\n'
                 '    var t = (1, 2.5)\n'
                 '    foo(*t)\n')


if __name__ == '__main__':
    unittest.main()
