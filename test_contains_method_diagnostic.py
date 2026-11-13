#!/usr/bin/env python3
"""Regression test: `in` / `not in` on a type with no `__contains__`.

DIAGNOSTICS_missing_validation_modular-part3: membership against a provably
scalar container must be a compile error with
  '<Type>' does not implement the '__contains__' method
while positive membership and erased/unknown cases keep compiling.
"""

import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

from gimple_codegen import compile_to_gimple
import diagnostic_build


def _expect_contains_error(src, type_name, use_build=False):
    needle = f"'{type_name}' does not implement the '__contains__' method"
    if use_build:
        rc, out = diagnostic_build.build_refusal(src)
        assert rc != 0, ('expected build failure, got success', src)
        assert needle in out, (needle, out)
        return
    try:
        compile_to_gimple(src, do_imports=False)
    except RuntimeError as e:
        text = str(e)
        assert needle in text, (needle, text)
        return
    raise AssertionError('membership on scalar container compiled without error: ' + src)


def _expect_ok(src):
    compile_to_gimple(src, do_imports=False)


def test_int_operands_in():
    _expect_contains_error(
        'def f(x: Int, y: Int):\n    _ = x in y\n', 'Int')


def test_int_operands_not_in():
    _expect_contains_error(
        'def f(x: Int, y: Int):\n    _ = x not in y\n', 'Int')


def test_int_operands_build_refusal():
    _expect_contains_error(
        'def f(x: Int, y: Int):\n    _ = x in y\n', 'Int', use_build=True)


def test_float64_reports_type_name():
    _expect_contains_error(
        'def f(x: Int, y: Float64):\n    _ = x in y\n', 'Float64')
    _expect_contains_error(
        'def f(x: Int):\n    _ = x in 1.0\n', 'Float64')


def test_bool_reports_type_name():
    _expect_contains_error(
        'def f(x: Int, y: Bool):\n    _ = x in y\n', 'Bool')
    _expect_contains_error(
        'def f(x: Int):\n    _ = x in True\n', 'Bool')


def test_positive_membership_still_compiles():
    _expect_ok('def f():\n    _ = 1 in (1, 2)\n')
    _expect_ok('def f(s: String):\n    _ = "a" in s\n')
    _expect_ok('def f(lst: List[Int]):\n    _ = 1 in lst\n')


def test_module_global_container_still_compiles():
    _expect_ok('var g = [1, 2, 3]\ndef f(x: Int):\n    _ = x in g\n')


def test_unresolved_generic_param_conservative():
    _expect_ok('def f[T](x: T):\n    _ = 1 in x\n')


if __name__ == '__main__':
    test_int_operands_in()
    test_int_operands_not_in()
    test_int_operands_build_refusal()
    test_float64_reports_type_name()
    test_bool_reports_type_name()
    test_positive_membership_still_compiles()
    test_module_global_container_still_compiles()
    test_unresolved_generic_param_conservative()
    print('ok')
