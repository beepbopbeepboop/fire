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


def test_unrecorded_call_is_erased_not_int():
    # The gate regression this pins: the estimator's int64_t FALLBACK for a
    # call whose return was never recorded is a type-erased box (it may hold
    # a container), not a proven Int. `content in String(self)` in
    # std/compile/compile.mojo was rejected as Int on that default, and six
    # stdlib modules fell back to source on it.
    _expect_ok('def f(x):\n    _ = "a" in String(x)\n')
    _expect_ok('def f(x):\n    _ = 1 in x.get_value()\n')


def test_erased_operand_binaryop_still_compiles():
    # `+`/`*`/`|`/`&`/`^`/`-`/`%`/`and`/`or` can yield a CONTAINER from a
    # type-erased operand (list+list, int*list, dict|dict, set&set, str%s,
    # `or` selecting the container arm); unproven operands must stay
    # conservative, and annotated scalars must still be rejected.
    _expect_ok('def f(a, b):\n    _ = 1 in (a + b)\n')
    _expect_ok('def f(a, b):\n    _ = 1 in (a or b)\n')
    _expect_ok('def f(a, b):\n    _ = 1 in (a * b)\n')
    _expect_contains_error(
        'def f(a: Int, b: Int):\n    _ = 1 in (a + b)\n', 'Int')
    _expect_contains_error(
        'def f(a: Int, b: Int):\n    _ = 1 in (a or b)\n', 'Int')


def test_known_int_return_call_still_rejected():
    # The estimator's SPECIFIC int-return rows (scalar builtins, a recorded
    # `-> Int`) are proofs and must keep rejecting.
    _expect_contains_error(
        'def f(s: String):\n    _ = 1 in len(s)\n', 'Int')
    _expect_contains_error(
        'def f(s: String):\n    _ = 1 in int(s)\n', 'Int')
    _expect_contains_error(
        'def n() -> Int:\n    return 1\ndef f():\n    _ = 1 in n()\n', 'Int')


def test_unannotated_call_result_is_not_provably_int():
    # A call whose return type is unannotated lowers its result as the
    # int64_t box default, which is "unknown", not "Int". The container
    # here is a list, so the membership must compile (this is the shape of
    # `item in self.resolve()` in myinterpreter.LazyImportType.__contains__,
    # which rejected the whole self-host closure).
    _expect_ok('def g():\n'
               '    return [1, 2]\n'
               'def f(x: Int):\n'
               '    _ = x in g()\n')


def test_unannotated_method_call_result_is_not_provably_int():
    _expect_ok('class C:\n'
               '    def __init__(self):\n'
               '        self._value = [1, 2]\n'
               '    def resolve(self):\n'
               '        return self._value\n'
               '    def has(self, item: Int):\n'
               '        return item in self.resolve()\n')


def test_unannotated_arithmetic_operand_is_not_provably_int():
    _expect_ok('def f(x: Int, a):\n    _ = x in (a + 1)\n')


def test_annotated_arithmetic_is_still_provably_int():
    _expect_contains_error(
        'def f(x: Int, a: Int):\n    _ = x in (a + 1)\n', 'Int')


if __name__ == '__main__':
    test_int_operands_in()
    test_int_operands_not_in()
    test_int_operands_build_refusal()
    test_float64_reports_type_name()
    test_bool_reports_type_name()
    test_positive_membership_still_compiles()
    test_module_global_container_still_compiles()
    test_unresolved_generic_param_conservative()
    test_unrecorded_call_is_erased_not_int()
    test_erased_operand_binaryop_still_compiles()
    test_known_int_return_call_still_rejected()
    test_unannotated_call_result_is_not_provably_int()
    test_unannotated_method_call_result_is_not_provably_int()
    test_unannotated_arithmetic_operand_is_not_provably_int()
    test_annotated_arithmetic_is_still_provably_int()
    print('ok')
