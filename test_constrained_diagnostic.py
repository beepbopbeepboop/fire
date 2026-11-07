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


def test_constrained_tstring_message():
    # t-string messages must be evaluated in constrained diagnostics
    # (bugs/DIAGNOSTICS_missing_validation_modular.md).
    try:
        _compile('fn f():\n    comptime x = 7\n    constrained[False, t"val {x}"]()\n')
    except RuntimeError as e:
        s = str(e)
        assert 'constraint failed' in s, s
        assert 'val 7' in s, s
        assert '{x}' not in s, s
        return
    raise AssertionError('provably-false constrained with t-string compiled')


def test_constrained_short_circuit_and_false():
    # Short-circuit: provably-false `and` must diagnose even if rhs is unknown.
    try:
        _compile('fn f[x: Int]():\n    constrained[False and x > 0, "nope"]()\n')
    except RuntimeError as e:
        s = str(e)
        assert 'constraint failed' in s, s
        assert 'nope' in s, s
        return
    raise AssertionError('provably-false short-circuit constrained compiled')


def test_constrained_short_circuit_or_false_needs_rhs():
    # `False or <unknown>` depends on rhs; must not produce a false diagnostic.
    _compile('fn f[x: Int]():\n    constrained[False or x > 0, "ok"]()\n')


def test_constrained_in_comptime_for_range():
    # comptime for loop variables must be visible to constrained evaluation
    # (bugs/DIAGNOSTICS_missing_validation_modular.md).
    try:
        _compile('fn f():\n    comptime for i in range(4):\n        constrained[i != 2, "hit"]()\n')
    except RuntimeError as e:
        s = str(e)
        assert 'constraint failed' in s, s
        assert 'hit' in s, s
        return
    raise AssertionError('constrained in comptime for (false iteration) compiled')


def test_constrained_in_comptime_for_range_true():
    _compile('fn f():\n    comptime for i in range(3):\n        constrained[i < 3, "ok"]()\n')


def test_constrained_in_comptime_for_list_literal():
    # comptime for over constant list literals must unroll and bind the loop
    # variable for comptime diagnostics (bugs/DIAGNOSTICS_missing_validation_modular.md).
    try:
        _compile('fn f():\n    comptime for i in [0, 1, 2]:\n        constrained[i < 2, "nope"]()\n')
    except RuntimeError as e:
        s = str(e)
        assert 'constraint failed' in s, s
        assert 'nope' in s, s
        return
    raise AssertionError('constrained in comptime for over list literal compiled')


def test_constrained_in_comptime_for_list_literal_true():
    _compile('fn f():\n    comptime for i in [0, 1]:\n        constrained[i < 2, "ok"]()\n')


def test_constrained_in_comptime_for_tuple_unpack():
    # tuple-unpacking targets over constant collections must bind each target
    # (bugs/DIAGNOSTICS_missing_validation_modular.md).
    try:
        _compile('fn f():\n    comptime for i, j in [(0, 1), (1, 1)]:\n        constrained[i != j, "eq"]()\n')
    except RuntimeError as e:
        s = str(e)
        assert 'constraint failed' in s, s
        assert 'eq' in s, s
        return
    raise AssertionError('constrained in comptime for tuple unpack compiled')


def test_constrained_in_comptime_for_tuple_unpack_true():
    _compile('fn f():\n    comptime for i, j in [(0, 1), (1, 2)]:\n        constrained[i < j, "ok"]()\n')


def test_constrained_in_comptime_for_comptime_alias():
    # Iterating over a comptime (non-literal) iterable alias must unroll with
    # the loop variable bound so comptime diagnostics fire
    # (bugs/DIAGNOSTICS_missing_validation_modular.md).
    src = 'fn f():\n    comptime vals = [0, 1, 2]\n    comptime for i in vals:\n        constrained[i < 2, "bad"]()\n'
    try:
        _compile(src)
    except RuntimeError as e:
        s = str(e)
        assert 'constraint failed' in s, s
        assert 'bad' in s, s
        return
    raise AssertionError('constrained in comptime for over comptime alias compiled')


def test_constrained_in_comptime_for_comptime_alias_true():
    _compile('fn f():\n    comptime vals = [0, 1, 2]\n    comptime for i in vals:\n        constrained[i < 3, "ok"]()\n')


def test_constrained_in_comptime_for_comptime_alias_tuple_unpack():
    src = (
        'fn f():\n'
        '    comptime pairs = [(0, 1), (2, 0)]\n'
        '    comptime for i, j in pairs:\n'
        '        constrained[i + j < 2, "sum"]()\n'
    )
    try:
        _compile(src)
    except RuntimeError as e:
        s = str(e)
        assert 'constraint failed' in s, s
        assert 'sum' in s, s
        return
    raise AssertionError('constrained in comptime for over comptime alias unpack compiled')


if __name__ == '__main__':
    test_constrained_bracket_false_fails()
    test_constrained_bracket_false_no_msg()
    test_constrained_bracket_true_passes()
    test_constrained_comparison_fails()
    test_constrained_unknown_passes()
    test_constrained_tstring_message()
    test_constrained_short_circuit_and_false()
    test_constrained_short_circuit_or_false_needs_rhs()
    test_constrained_in_comptime_for_range()
    test_constrained_in_comptime_for_range_true()
    test_constrained_in_comptime_for_list_literal()
    test_constrained_in_comptime_for_list_literal_true()
    test_constrained_in_comptime_for_tuple_unpack()
    test_constrained_in_comptime_for_tuple_unpack_true()
    test_constrained_in_comptime_for_comptime_alias()
    test_constrained_in_comptime_for_comptime_alias_true()
    test_constrained_in_comptime_for_comptime_alias_tuple_unpack()
    print('ok')
