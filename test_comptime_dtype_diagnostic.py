#!/usr/bin/env python3
"""Regression test: DType predicate evaluation in comptime diagnostics.

`bugs/DIAGNOSTICS_missing_validation_modular.md`: comptime validation must
catch provably-false conditions involving DType predicates such as
`dtype.is_integral()`. The comptime evaluator now folds DType member access
(`DType.int32`) and DType predicate methods, so `comptime assert` and
`constrained` reject provably-false DType conditions instead of silently
accepting them.
"""

from gimple_codegen import compile_to_gimple


def _compile(src, filename='t.mojo'):
    return compile_to_gimple(src, do_imports=False, filename=filename)


def test_comptime_assert_dtype_is_integral_false():
    try:
        _compile('fn f():\n    comptime assert DType.float32.is_integral(), "nope"\n')
    except RuntimeError as e:
        assert 'comptime assertion failed' in str(e), e
        assert 'nope' in str(e), e
        return
    raise AssertionError('provably-false DType.is_integral() comptime assert compiled')


def test_comptime_assert_dtype_is_integral_true():
    _compile('fn f():\n    comptime assert DType.int32.is_integral(), "ok"\n')


def test_comptime_assert_dtype_is_floating_point_false():
    try:
        _compile('fn f():\n    comptime assert DType.int64.is_floating_point(), "fp"\n')
    except RuntimeError as e:
        assert 'comptime assertion failed' in str(e), e
        return
    raise AssertionError('provably-false DType.is_floating_point() compiled')


def test_comptime_assert_dtype_is_floating_point_true():
    _compile('fn f():\n    comptime assert DType.float64.is_floating_point(), "ok"\n')


def test_comptime_assert_dtype_signedness():
    try:
        _compile('fn f():\n    comptime assert DType.uint8.is_signed(), "signed"\n')
    except RuntimeError as e:
        assert 'comptime assertion failed' in str(e), e
        return
    raise AssertionError('provably-false DType.is_signed() compiled')


def test_constrained_dtype_predicate_false():
    try:
        _compile('fn f():\n    constrained[DType.float32.is_integral(), "nope"]()\n')
    except RuntimeError as e:
        assert 'constraint failed' in str(e), e
        assert 'nope' in str(e), e
        return
    raise AssertionError('provably-false constrained DType predicate compiled')


def test_constrained_dtype_predicate_true():
    _compile('fn f():\n    constrained[DType.int32.is_integral(), "ok"]()\n')


if __name__ == '__main__':
    test_comptime_assert_dtype_is_integral_false()
    test_comptime_assert_dtype_is_integral_true()
    test_comptime_assert_dtype_is_floating_point_false()
    test_comptime_assert_dtype_is_floating_point_true()
    test_comptime_assert_dtype_signedness()
    test_constrained_dtype_predicate_false()
    test_constrained_dtype_predicate_true()
    print('ok')
