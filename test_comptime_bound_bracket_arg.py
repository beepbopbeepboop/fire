#!/usr/bin/env python3
"""Regression: a bracket argument that is a `comptime`-bound NAME resolves to
its value, not to its own identifier.

`_type_expr_to_ann` rendered `compare[dtype]` as the literal text `dtype`, so
every `comptime dtype = DType.<x>` call site of one generic got the SAME
mangled symbol (`compare_5_dtype_5_dtype_...`) while their return types
differed (float vs double). gcc saw one symbol declared with two types:
"conflicting types". That is the stdlib-syntax red `test/math/test_tanh.mojo`
pins end-to-end; this test pins the root cause directly and without gcc, on a
minimal two-instantiation source.

Pure codegen (no gcc, no build), so it stays a quick test.
"""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import gimple_codegen  # noqa: E402

SRC = '''def ident[dtype: DType](x: Scalar[dtype]) -> Scalar[dtype]:
    return x


def f32() -> Float32:
    comptime dtype = DType.float32
    return ident[dtype](1.0)


def f64() -> Float64:
    comptime dtype = DType.float64
    return ident[dtype](1.0)
'''


def test_bound_dtype_arguments_are_distinct_instantiations():
    c = gimple_codegen.compile_to_gimple(SRC, do_imports=False,
                                         filename='m.mojo')
    assert 'ident_5_dtype_18_DType_x002Efloat32' in c, (
        'the Float32 call site was not instantiated with its dtype value:\n'
        + c)
    assert 'ident_5_dtype_18_DType_x002Efloat64' in c, (
        'the Float64 call site was not instantiated with its dtype value:\n'
        + c)
    # The old rendering: the callee's own parameter NAME used as the argument,
    # so both call sites collide on one symbol.
    assert 'ident_5_dtype_5_dtype' not in c, (
        'a bound dtype argument was rendered as its own name:\n' + c)
    # The two instantiations must carry the dtype's scalar C return type.
    assert 'extern float ident_5_dtype_18_DType_x002Efloat32' in c
    assert 'extern double ident_5_dtype_18_DType_x002Efloat64' in c


if __name__ == '__main__':
    test_bound_dtype_arguments_are_distinct_instantiations()
    print('PASS test_comptime_bound_bracket_arg')
