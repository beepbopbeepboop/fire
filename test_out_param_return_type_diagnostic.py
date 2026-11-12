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
  must have type 'Self'; use a 'where' clause ...`.
* `f(y)` where `def f(out x: Int)`: `invalid call to 'f': unexpected
  argument`.
* `fn f(...)`: `'fn' has been removed; use 'def' instead` (a warning now; the
  refusal is a separate, decided-against stage, see
  bugs/DIAGNOSTICS_fn_keyword_is_accepted_should_warn_then_refuse.md).

Every measured case is now a plain assertion: the compiler refuses each shape
at the real compiler's primary message and location.

`FixtureCorpusValidity` closes the other half of the same bug. An invalid
fixture is only refused if something COMPILES it, and a fixture is not built on
every path its test takes (the parity harness treated the refusal as a backend
red, and the CPython oracle accepted `out self` as an ordinary parameter).
That class compiles every fixture string in the suite that spells `out self`
and fails on an out-declaration refusal, so an invalid fixture is an error in
the test before it reaches a backend.
"""

import ast
import contextlib
import glob
import io
import os
import re
import sys
import unittest
import warnings

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

from gimple_codegen import compile_to_gimple

RETURN_OUT_MSG = "functions must not declare both an 'out' argument and a return type"

# The declaration refusals real Mojo gives for the shapes above. A fixture that
# provokes one of these is invalid Mojo, whatever its own test asserts.
OUT_DECLARATION_REFUSALS = (
    RETURN_OUT_MSG,
    "self argument must be present in instance method",
    "'self' argument must have type 'Self'",
)

# A cheap FILTER over fixture strings, not the check: the compiler answers
# whether the declaration is valid. `out` as an ordinary word never matches,
# and a string this lets through is still compiled.
OUT_DECLARATION_HINT = re.compile(r'^\s*(?:async\s+)?(?:def|fn)\b[^\n]*\bout\b', re.M)


def _compile(src, filename='t.mojo'):
    return compile_to_gimple(src, do_imports=False, filename=filename)


def _location(err):
    m = re.search(r":(\d+):(\d+): error", str(err))
    assert m, f"no line:col in diagnostic: {err}"
    return int(m.group(1)), int(m.group(2))


def _out_declaration_refusal(src):
    """The first line of the out-declaration refusal `src` provokes, or None.

    Compiles with this tree's front end, which now answers the measured shapes
    with the real compiler's primary message (the cases pinned above). A
    failure for any OTHER reason is not this gate's subject and returns None.
    """
    try:
        with contextlib.redirect_stderr(io.StringIO()):
            _compile(src)
    except Exception as exc:
        message = str(exc)
        for refusal in OUT_DECLARATION_REFUSALS:
            if refusal in message:
                return message.splitlines()[0]
    return None


def _fixture_strings_with_out_declaration():
    """(path, line, source) for every fixture string that declares an `out` param.

    A fixture is a Python string constant holding Mojo source. The sweep is
    over the whole suite rather than the five files the campaign measured: the
    next invalid fixture will be written wherever its author was working.
    This file is skipped because its string constants ARE the measured
    refusals it must keep.
    """
    here = os.path.abspath(__file__)
    for path in sorted(glob.glob(os.path.join(HERE, 'test_*.py'))):
        if os.path.abspath(path) == here:
            continue
        with open(path, encoding='utf-8') as f:
            # Other test files carry Python-isms that warn at parse time (an
            # invalid escape in a docstring, for one); that is not this sweep's
            # subject and must not clutter its output.
            with warnings.catch_warnings():
                warnings.simplefilter('ignore', SyntaxWarning)
                tree = ast.parse(f.read(), path)
        for node in ast.walk(tree):
            if (isinstance(node, ast.Constant) and isinstance(node.value, str)
                    and OUT_DECLARATION_HINT.search(node.value)):
                yield path, node.lineno, node.value


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


class FixtureCorpusValidity(unittest.TestCase):
    """No fixture in the suite declares an `out` form real Mojo refuses.

    The bug this class exists for: `test_formal_x86_64_parity.py` reported
    three backend failures whose fixtures all declared
    `def put(out self, v: Int) -> Int:`. The declaration was invalid Mojo, and
    nothing looked: the parity harness called the build failure a backend red
    and the CPython oracle accepted `out self` as an ordinary parameter. The
    42 fixtures in five files were converted to `mut self`; this sweep is what
    keeps the invalid spelling from returning unseen.
    """

    def test_no_fixture_string_declares_a_refused_out_param(self):
        offenders = []
        for path, line, src in _fixture_strings_with_out_declaration():
            refusal = _out_declaration_refusal(src)
            if refusal is not None:
                offenders.append(f'{os.path.basename(path)}:{line}: {refusal}')
        self.assertEqual(
            offenders, [],
            'fixture strings declare an `out` form real Mojo refuses; use '
            '`mut self` (or `__init__` for a constructor):\n  '
            + '\n  '.join(offenders))

    def test_the_corpus_gate_catches_a_reintroduced_return_typed_out_self(self):
        # The shape in the parity fixtures, and the first row of the module
        # docstring's table: this is exactly what the sweep must refuse.
        self.assertIsNotNone(_out_declaration_refusal(
            'struct A:\n'
            '    var n: Int\n'
            '    def put(out self, v: Int) -> Int:\n'
            '        return v\n'))

    def test_the_corpus_gate_catches_a_non_self_out_parameter(self):
        self.assertIsNotNone(_out_declaration_refusal(
            'struct R:\n'
            '    var a: Int\n'
            '    def set(out self, v: Int):\n'
            '        self.a = v\n'))

    def test_the_corpus_gate_accepts_a_constructor_receiver(self):
        self.assertIsNone(_out_declaration_refusal(
            'struct R:\n'
            '    var a: Int\n'
            '    def __init__(out self, v: Int):\n'
            '        self.a = v\n'))

    def test_the_corpus_gate_accepts_an_ordinary_mut_receiver(self):
        self.assertIsNone(_out_declaration_refusal(
            'struct R:\n'
            '    var a: Int\n'
            '    def set(mut self, v: Int) -> Int:\n'
            '        self.a = v\n'
            '        return v\n'))


if __name__ == '__main__':
    unittest.main()
