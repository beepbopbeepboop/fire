#!/usr/bin/env python3
"""Regression test for compile-time `constrained` diagnostics.

`bugs/DIAGNOSTICS_missing_validation_modular.md`: the compiler accepted
`constrained[False, "msg"]()` (and related forms) whose conditions are
provably false at compile time.  `constrained` is a compile-time check; a
provably-false condition must fail compilation with a diagnostic.
"""

from gimple_codegen import compile_to_gimple


def _compile(src, filename='t.mojo'):
    return compile_to_gimple(src, do_imports=False, filename=filename)


def test_constrained_bracket_false_fails():
    try:
        _compile('fn f():\n    constrained[False, "nope"]()\n')
    except RuntimeError as e:
        assert 'constraint failed' in str(e), e
        assert 'nope' in str(e), e
        return
    raise AssertionError('provably-false constrained compiled without error')


def test_constrained_bracket_false_no_msg():
    try:
        _compile('fn f():\n    constrained[False]()\n')
    except RuntimeError as e:
        assert 'constraint failed' in str(e), e
        return
    raise AssertionError('provably-false constrained compiled without error')


def test_constrained_bracket_true_passes():
    _compile('fn f():\n    constrained[True, "ok"]()\n')


def test_constrained_comparison_fails():
    try:
        _compile('fn f():\n    constrained[1 == 2, "math"]()\n')
    except RuntimeError as e:
        assert 'constraint failed' in str(e), e
        assert 'math' in str(e), e
        return
    raise AssertionError('provably-false constrained compiled without error')


def test_constrained_unknown_passes():
    # Unknown condition: must not produce a false diagnostic.
    _compile('fn f[x: Int]():\n    constrained[x > 0, "pos"]()\n')


if __name__ == '__main__':
    test_constrained_bracket_false_fails()
    test_constrained_bracket_false_no_msg()
    test_constrained_bracket_true_passes()
    test_constrained_comparison_fails()
    test_constrained_unknown_passes()
    print('ok')
