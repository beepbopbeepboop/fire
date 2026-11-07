#!/usr/bin/env python3
"""Regression test for comptime assert compile-time diagnostics.

`bugs/DIAGNOSTICS_missing_validation_modular.md`: the compiler accepted
`comptime assert` statements whose conditions are provably false at compile
time.  A `comptime assert` is a compile-time check; a provably-false
condition must fail compilation with a diagnostic, not be silently accepted
(or lowered to a runtime trap).
"""

from gimple_codegen import compile_to_gimple


def _compile(src, filename='t.mojo'):
    return compile_to_gimple(src, do_imports=False, filename=filename)


def test_comptime_assert_false_fails():
    try:
        _compile('fn f():\n    comptime assert False, "nope"\n')
    except RuntimeError as e:
        assert 'comptime assertion failed' in str(e), e
        assert 'nope' in str(e), e
        return
    raise AssertionError('provably-false comptime assert compiled without error')


def test_comptime_assert_false_no_msg():
    try:
        _compile('fn f():\n    comptime assert False\n')
    except RuntimeError as e:
        assert 'comptime assertion failed' in str(e), e
        return
    raise AssertionError('provably-false comptime assert compiled without error')


def test_comptime_assert_true_passes():
    _compile('fn f():\n    comptime assert True, "ok"\n    pass\n')


def test_comptime_assert_comparison_fails():
    try:
        _compile('fn f():\n    comptime assert 1 == 2, "math"\n')
    except RuntimeError as e:
        assert 'comptime assertion failed' in str(e), e
        assert 'math' in str(e), e
        return
    raise AssertionError('provably-false comptime assert compiled without error')


if __name__ == '__main__':
    test_comptime_assert_false_fails()
    test_comptime_assert_false_no_msg()
    test_comptime_assert_true_passes()
    test_comptime_assert_comparison_fails()
    print('ok')
