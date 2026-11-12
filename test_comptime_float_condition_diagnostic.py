#!/usr/bin/env python3
"""Regression test: float comparisons in comptime conditions are decided.

Every float comparison was left unfolded, so a provably-false condition over
float literals (or a Float64 parameter) was silently accepted by
`comptime assert`, `constrained`, and `where` clauses. The shared constant
folder now treats a FloatLiteral as a constant, and a float type argument
binds into the `where` clause table.
"""

from gimple_codegen import compile_to_gimple
from diagnostic_build import build_refusal


def _compile(src, filename='t.mojo'):
    return compile_to_gimple(src, do_imports=False, filename=filename)


def _expect_rejected(src, needle, msg_needle):
    try:
        _compile(src)
    except RuntimeError as e:
        assert needle in str(e), e
        assert msg_needle in str(e), e
        return
    raise AssertionError(f'provably-false float condition compiled: {src!r}')


def test_comptime_assert_float_less_false():
    _expect_rejected('fn f():\n    comptime assert 0.5 > 1.0, "small"\n',
                     'comptime assertion failed', 'small')


def test_comptime_assert_float_not_equal_false():
    _expect_rejected('fn f():\n    comptime assert 1.5 != 1.5, "neq"\n',
                     'comptime assertion failed', 'neq')


def test_constrained_float_false():
    _expect_rejected('fn f():\n    constrained[0.5 > 1.0, "small"]()\n',
                     'constraint failed', 'small')


def test_comptime_assert_float_true_compiles():
    _compile('fn f():\n    comptime assert 0.5 < 1.0, "ok"\n')


def test_comptime_assert_float_equal_true_compiles():
    _compile('fn f():\n    comptime assert 1.5 == 1.5, "ok"\n')


def test_constrained_float_true_compiles():
    _compile('fn f():\n    constrained[0.5 < 1.0, "ok"]()\n')


def test_runtime_float_condition_stays_undecided():
    # A float known only at run time must not be folded, so it compiles.
    _compile('fn f(x: Float64) -> Bool:\n    return x > 0.5\n')


def test_where_float_param_rejects_false_instantiation():
    src = '''
def g[x: Float64]() where x > 1.0:
    pass

def main():
    g[0.5]()
'''
    rc, out = build_refusal(src)
    assert rc != 0, out
    assert 'not satisfied' in out, out


def test_where_float_param_accepts_true_instantiation():
    src = '''
def g[x: Float64]() where x > 1.0:
    pass

def main():
    g[2.5]()
'''
    rc, out = build_refusal(src)
    assert rc == 0, out


if __name__ == '__main__':
    test_comptime_assert_float_less_false()
    test_comptime_assert_float_not_equal_false()
    test_constrained_float_false()
    test_comptime_assert_float_true_compiles()
    test_comptime_assert_float_equal_true_compiles()
    test_constrained_float_true_compiles()
    test_runtime_float_condition_stays_undecided()
    test_where_float_param_rejects_false_instantiation()
    test_where_float_param_accepts_true_instantiation()
    print('ok')
