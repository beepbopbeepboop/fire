#!/usr/bin/env python3
"""A literal or a primitive-typed value passed to an `__mlir_type.*`
parameter is refused.

Measured with `tools/mojo build` (2026-11-12), the real compiler refuses every
LITERAL passed to a `__mlir_type.index` parameter, and says so at the
argument:

* `foo(1.5)`    -> `invalid call to 'foo': value passed to 'x' cannot be
  converted from 'FloatLiteral[1.5]' to '__mlir_type.index'` at the `1.5`.
* `foo(3)`      -> the same, from 'IntLiteral[3]' (an int literal is not an
  MLIR index value).
* `foo("s")`    -> the same, from 'StringLiteral["s"]'.
* `foo(True)`   -> the same, from 'Bool'.

It refuses a VARIABLE of primitive type the same way, at the argument:

* `var y = 2.5; foo(y)`   -> `cannot be converted from 'Float64'` at `y`
  (the type the compiler infers from the float-literal initialiser).
* `var y = 3; foo(y)`     -> `from 'Int'` (int-literal initialiser).
* `var y = "s"; foo(y)`   -> `from 'String'`.
* `var z = True; foo(z)`  -> `from 'Bool'`.
* `var y: Float64 = 2.5; foo(y)` -> `from 'Float64'` (declared type).
* `var y: Int64 = 3; foo(y)`     -> `from 'Int64'`.
* `def bar(y: Float64): foo(y)`  -> `from 'Float64'` (a parameter of a
  primitive type is a value of that type).

Our compiler accepted all of them and ran them. This file pins the refusals.
The `from '<type>'` half of the real message is not reproduced (our message
ends at `cannot be converted to '__mlir_type.index'`).

A name whose type this front end does not track is never refused: a variable
initialised from a non-literal expression, a non-primitive declaration, a
`for`-loop target, or an unannotated parameter. Such a name shadows an outer
primitive variable of the same name (the lookup stops at the inner binding).
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

    def _compiles(self, src):
        _compile(src)

    # --- literals ------------------------------------------------------------

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

    # --- variables and parameters of primitive type ----------------------------

    def test_variable_argument_is_refused_at_argument(self):
        # The doc's Done-when case: `var y = 2.5; foo(y)` is refused at `y`
        # (this was `test_variable_argument_is_not_checked`).
        msg = self._refused(
            f'def foo(x: {ANN}):\n'
            '    pass\n'
            '\n'
            'def main():\n'
            '    var y = 2.5\n'
            '    foo(y)\n')
        self.assertIn("error: invalid call to 'foo'", msg)
        self.assertEqual(_location(msg), (6, 9))

    def test_let_variable_argument_is_refused_at_argument(self):
        # `let` declares a constant exactly as `var` does; it must land as a
        # VarDecl so the same type table sees it (a `let` used to parse as an
        # identifier expression, so the table never saw the declaration).
        msg = self._refused(
            f'def foo(x: {ANN}):\n'
            '    pass\n'
            '\n'
            'def main():\n'
            '    let y = 2.5\n'
            '    foo(y)\n')
        self.assertIn("error: invalid call to 'foo'", msg)
        self.assertEqual(_location(msg), (6, 9))

    def test_int_variable_is_refused(self):
        msg = self._refused(
            f'def foo(x: {ANN}):\n'
            '    pass\n'
            '\n'
            'def main():\n'
            '    var y = 3\n'
            '    foo(y)\n')
        self.assertIn("error: invalid call to 'foo'", msg)
        self.assertEqual(_location(msg), (6, 9))

    def test_string_variable_is_refused(self):
        msg = self._refused(
            f'def foo(x: {ANN}):\n'
            '    pass\n'
            '\n'
            'def main():\n'
            '    var y = "s"\n'
            '    foo(y)\n')
        self.assertIn("error: invalid call to 'foo'", msg)

    def test_bool_variable_is_refused(self):
        msg = self._refused(
            f'def foo(x: {ANN}):\n'
            '    pass\n'
            '\n'
            'def main():\n'
            '    var y = True\n'
            '    foo(y)\n')
        self.assertIn("error: invalid call to 'foo'", msg)

    def test_declared_type_variable_is_refused(self):
        msg = self._refused(
            f'def foo(x: {ANN}):\n'
            '    pass\n'
            '\n'
            'def main():\n'
            '    var y: Float64 = 2.5\n'
            '    foo(y)\n')
        self.assertIn("error: invalid call to 'foo'", msg)
        self.assertEqual(_location(msg), (6, 9))

    def test_parameter_of_primitive_type_is_refused(self):
        msg = self._refused(
            f'def foo(x: {ANN}):\n'
            '    pass\n'
            '\n'
            'def bar(y: Float64):\n'
            '    foo(y)\n'
            '\n'
            'def main():\n'
            '    bar(1.5)\n')
        self.assertIn("error: invalid call to 'foo'", msg)
        self.assertEqual(_location(msg), (5, 9))

    def test_keyword_variable_is_refused_at_value(self):
        msg = self._refused(
            f'def foo(x: {ANN}):\n'
            '    pass\n'
            '\n'
            'def main():\n'
            '    var y = 2.5\n'
            '    foo(x=y)\n')
        self.assertIn("error: invalid call to 'foo'", msg)
        self.assertEqual(_location(msg), (6, 11))

    def test_second_parameter_variable_is_refused(self):
        msg = self._refused(
            f'def foo(a: Int, x: {ANN}):\n'
            '    pass\n'
            '\n'
            'def main():\n'
            '    var y = 2.5\n'
            '    foo(1, y)\n')
        self.assertIn("error: invalid call to 'foo'", msg)
        self.assertEqual(_location(msg), (6, 12))

    def test_module_variable_argument_is_refused(self):
        # The module scope is checked too: a top-level `var` and a top-level
        # call live in the same scope.
        msg = self._refused(
            f'def foo(x: {ANN}):\n'
            '    pass\n'
            '\n'
            'var y = 2.5\n'
            'foo(y)\n')
        self.assertIn("error: invalid call to 'foo'", msg)
        self.assertEqual(_location(msg), (5, 5))

    def test_nested_function_variable_is_refused(self):
        # The scope tables merge over nested scopes: `inner` sees `main`'s
        # `y` (a Float64 in the real compiler) and the call is refused there.
        msg = self._refused(
            f'def foo(x: {ANN}):\n'
            '    pass\n'
            '\n'
            'def main():\n'
            '    var y = 2.5\n'
            '    def inner():\n'
            '        foo(y)\n')
        self.assertIn("error: invalid call to 'foo'", msg)
        self.assertEqual(_location(msg), (7, 13))

    # --- not refused: the check must not guess a type it does not have --------

    def test_plain_annotation_is_not_checked(self):
        # Only `__mlir_type.*` annotations are checked by this rule.
        self._compiles('def foo(x: Int):\n'
                       '    pass\n'
                       '\n'
                       'def main():\n'
                       '    foo(1.5)\n')

    def test_plain_annotation_variable_argument_is_not_checked(self):
        # A non-MLIR parameter accepts a primitive-typed variable.
        self._compiles('def bar(x: Float):\n'
                       '    pass\n'
                       '\n'
                       'def main():\n'
                       '    var y = 2.5\n'
                       '    bar(y)\n')

    def test_variable_of_unknown_type_is_not_checked(self):
        # A non-literal initialiser has no type this front end can read;
        # no guess is made.
        self._compiles(f'def foo(x: {ANN}):\n'
                       '    pass\n'
                       '\n'
                       'def main():\n'
                       '    var y = 3 + 4\n'
                       '    foo(y)\n')

    def test_mlir_typed_variable_is_not_refused(self):
        # A variable declared `__mlir_type.index` HOLDS an MLIR value; passing
        # it to the parameter is the valid use.
        self._compiles(f'def foo(x: {ANN}):\n'
                       '    pass\n'
                       '\n'
                       'def main():\n'
                       '    var y: {ANN} = 0\n'
                       '    foo(y)\n')

    def test_local_variable_shadows_module_variable(self):
        # The inner binding wins even when its type is unknown: the lookup
        # stops there and does not fall through to the module's Float `y`.
        self._compiles(f'def foo(x: {ANN}):\n'
                       '    pass\n'
                       '\n'
                       'var y = 2.5\n'
                       '\n'
                       'def main():\n'
                       '    var y = 3 + 4\n'
                       '    foo(y)\n')

    def test_loop_target_shadows_variable(self):
        # A `for` target binds the name (the element type is not tracked); the
        # outer Float `y` must not leak into the loop body.
        self._compiles(f'def foo(x: {ANN}):\n'
                       '    pass\n'
                       '\n'
                       'def main():\n'
                       '    var y = 2.5\n'
                       '    for y in (1, 2):\n'
                       '        foo(y)\n')

    def test_star_argument_before_mlir_parameter_stops_the_check(self):
        # `*x` at the call site shifts positions; the check gives up there.
        self._compiles(f'def foo(a: Int, x: {ANN}):\n'
                       '    pass\n'
                       '\n'
                       'def main():\n'
                       '    var t = (1, 2.5)\n'
                       '    foo(*t)\n')


if __name__ == '__main__':
    unittest.main()
