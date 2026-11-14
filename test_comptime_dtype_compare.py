#!/usr/bin/env python3
"""Regression test: comptime folding of DType comparisons.

An instantiated stdlib generic such as `isinf[dtype]` branches on the dtype
with `comptime if` / `elif` chains: `dtype == .float8_e5m2`,
`dtype in (.float8_e4m3fn, .float8_e5m2)`, `dtype.is_floating_point()`.
Three things kept those from folding, so the dead branch of every such chain
was emitted and gcc rejected it (`(val.to_bits() & 0x7F)` on a float):

1. `DottedLiteral` (the `.float8_e5m2` spelling) was read through a `name`
   attribute it does not have. Every dot-relative variant folded to None.
2. A bound `dtype` (`DType.float32` / `('DType', ...)`) and a dot-relative
   `.float32` are different Python values, so `==`/`in` between them was
   False even when they named the same dtype.
3. An elaborated instantiation substitutes the dtype textually, so its body
   spells the parameter as the scalar name `Float32`, which was unbound.

These tests pin the evaluator for every binding spelling the codegen uses.
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from fire_compiler import Parser, py_tokenize  # noqa: E402
from mojo.middle import comptime as ce  # noqa: E402


def _cond(src):
    """The condition of a one-line `comptime if` statement."""
    mod = Parser(py_tokenize('comptime if ' + src + ':\n    pass\n')).parse_module()
    return mod[0].condition


# Every spelling a bound DType parameter takes in this codebase.
_BINDINGS = ['DType.float32', ('.', 'float32'), ('DType', 'float32')]


def _fold(src, bindings):
    return ce.eval_const_bool(_cond(src), bindings, None, None)


def test_dot_relative_variant_folds():
    # The DottedLiteral branch: `.float8_e5m2` must produce its marker.
    assert ce.eval_const(_cond('x == .float8_e5m2').right, {}, None) == ('.', 'float8_e5m2')


def test_dtype_equality_folds_for_every_binding_spelling():
    cases = {
        'dtype == .float32': True,
        'dtype == .float8_e5m2': False,
        'dtype != .float32': False,
        'dtype == DType.float32': True,
        'dtype == DType.float64': False,
    }
    for src, want in cases.items():
        for b in _BINDINGS:
            got = _fold(src, {'dtype': b})
            assert got is want, (src, b, got, want)


def test_dtype_membership_folds_for_every_binding_spelling():
    cases = {
        'dtype in (.float8_e4m3fn, .float32)': True,
        'dtype in (.float8_e4m3fn, .float8_e5m2)': False,
        'dtype not in (.float8_e4m3fn, .float32)': False,
        'dtype not in (.float8_e4m3fn, .float8_e5m2)': True,
    }
    for src, want in cases.items():
        for b in _BINDINGS:
            got = _fold(src, {'dtype': b})
            assert got is want, (src, b, got, want)


def test_predicate_on_bound_dtype_folds():
    assert _fold('dtype.is_floating_point()', {'dtype': 'DType.float32'}) is True
    assert _fold('dtype.is_integral()', {'dtype': ('.', 'float32')}) is False


def test_scalar_dtype_spelling_folds_without_a_binding():
    # The elaborated isinf/frexp bodies spell the parameter as `Float32`.
    assert _fold('Float32.is_floating_point()', {}) is True
    assert _fold('Float32 == .float8_e5m2', {}) is False
    assert _fold('Float32 == .float32', {}) is True
    assert _fold('Float32 in (.float8_e4m3fn, .float32)', {}) is True
    assert _fold('Int8 == .int8', {}) is True


def test_isinf_branch_chain_is_decided_for_float32():
    # The exact `comptime if` / `elif` shape of std/math isinf: for Float32
    # every float8 branch is provably not taken, so none may be left to run.
    chain = ('not Float32.is_floating_point() or Float32 in (DType.float8_e4m3fn, '
             'DType.float8_e5m2fnuz)')
    assert _fold(chain, {}) is False
    assert _fold('Float32 == .float8_e5m2', {}) is False
    assert _fold('Float32 == .float8_e3m4', {}) is False


def test_non_dtype_enum_compare_is_unchanged():
    # A dot-relative marker compared with a plain value keeps its old meaning:
    # it is not a DType, so no name normalization applies to it.
    assert ce.compare_op('==', ('.', 'float32'), 'float32') is False
    assert ce.compare_op('==', 'abc', 'abc') is True


if __name__ == '__main__':
    failures = 0
    for name, fn in sorted(globals().items()):
        if name.startswith('test_') and callable(fn):
            try:
                fn()
                print('PASS ', name)
            except AssertionError as e:
                failures += 1
                print('FAIL ', name, e)
    print('FAILURES:', failures)
    sys.exit(1 if failures else 0)
