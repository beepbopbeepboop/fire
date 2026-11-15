#!/usr/bin/env python3
"""Regression: `error: invalid bindings in signature: lacking evidence` raised
for VALID declarations (bugs/gate-mojoc.md).

Commit 43bd3dcba extended `_check_fn_signature_binding_violations` to the
RETURN type, exposing three false positives in the trait-bound evidence check
(`elaborate.check_signature_param_bound_evidence`):

  * a bounded bracket parameter's DECLARED DEFAULT was kept inside the
    annotation text the check read from `comptime_param_annotations`
    (`'DType = Self . dtype'`), so a required `DType` could never be found in
    the bound list — std/simd.mojo's `_refine`, std/ffi's `get_function` and
    std/compile's `compile_info` all carried such parameters;
  * a bracket parameter constrained by a non-trait TYPE (a value or function
    type, `mapFn: fn(Strat.Value) -> Dest`) was treated as a trait list and
    tested for membership — a type constraint is not a conformance
    requirement, so nothing can be "unproven" about it;
  * a bracket parameter constrained by a concrete TYPE (`length: SIMDLength`)
    had its argument tested for TRAIT membership, even though the required
    name is a type, not a trait, that this module cannot decide conformance
    for — std/simd.mojo's `_shuffle_variadic` returns
    `SIMD[Self.dtype, output_size]` with `output_size: Int`.
"""

import os
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

from gimple_codegen import compile_to_gimple


def _compile(src):
    with tempfile.TemporaryDirectory(prefix='sig_bound_ev_') as d:
        p = os.path.join(d, 't.mojo')
        with open(p, 'w') as fh:
            fh.write(src)
        try:
            compile_to_gimple(src, do_imports=False, filename=p)
        except Exception as e:
            return f'{type(e).__name__}: {e}'
    return None


def _assert_err(src, *frags):
    err = _compile(src)
    assert err is not None, 'expected compile error, got success'
    for frag in frags:
        assert frag in err, err
    return err


def _assert_ok(src):
    err = _compile(src)
    assert err is None, f'expected success, got: {err}'


# simd shape: std/simd.mojo's `SIMD._refine[new_dtype: DType = Self.dtype,
# new_size: SIMDLength = Self.length] -> SIMD[new_dtype, new_size]`. A bounded
# type parameter carrying a DEFAULT, used in the return type: the default used
# to ride along inside the annotation text, so the bound list read as
# `['DType = Self . dtype']` and the required `DType` was never found in it.
POS_DEFAULTED_BOUND = r'''
trait DType:
    pass

trait VLen:
    pass

struct Vec[dtype: DType, length: VLen]:
    def __init__(out self):
        pass
    def refine[
        new_dtype: DType = Self.dtype,
        new_length: VLen = Self.length,
    ](self) -> Vec[new_dtype, new_length]:
        return Vec[new_dtype, new_length]()

def main():
    pass
'''


def test_positive_defaulted_bound_used_in_return_type():
    _assert_ok(POS_DEFAULTED_BOUND)


# callable-bound shape: a bracket parameter constrained by a FUNCTION TYPE is
# a type constraint, not a trait list — `fn(Strat.Value) -> Dest` must be
# skipped by the evidence check, not tested for membership. This is the
# positive half of `test_defaulted_trait_method_conformance_diagnostic.py`'s
# `Map[Self, Dest, mapFn]` override, which the check used to reject.
POS_FUNCTION_TYPE_BOUND = r'''
trait Strategy:
    comptime Value: AnyType
    def value(self) -> Self.Value: ...

struct Map[Strat: Strategy, Dest: Copyable, mapFn: fn(Strat.Value) -> Dest](Strategy):
    comptime Value = Dest
    def __init__(out self):
        pass
    def value(self) -> Self.Value:
        var x: Self.Value
        return x
    def map[Dest: Copyable, mapFn: fn(Self.Value) -> Dest](self) -> Map[Self, Dest, mapFn]:
        return Map[Self, Dest, mapFn]()

def main():
    pass
'''


def test_positive_function_type_bound_not_a_trait():
    _assert_ok(POS_FUNCTION_TYPE_BOUND)


# compile_info shape: std/compile/compile.mojo's
# `CompiledFunctionInfo[func_type: TrivialRegisterPassable, func: func_type,
# ...]` — a bracket parameter BOUNDED BY ANOTHER type parameter of the same
# signature (`func: func_type`). The bound names a type parameter, not a
# trait, and the enclosing signature's own declaration for `func`
# (`func: func_type`) must read back as that parameter, not as a trait list
# lacking the bound.
POS_BOUND_REFERRING_TO_PARAM = r'''
trait TrivialPassable:
    pass

struct Info[
    func_type: TrivialPassable,
    func: func_type,
]:
    def __init__(out self):
        pass

def info[
    func_type: TrivialPassable,
    func: func_type,
]() -> Info[func_type, func]:
    return Info[func_type, func]()

def main():
    pass
'''


def test_positive_bound_referring_to_type_parameter():
    _assert_ok(POS_BOUND_REFERRING_TO_PARAM)


# type-constraint shape: std/simd.mojo's `_shuffle_variadic[output_size: Int =
# Self.length] -> SIMD[Self.dtype, output_size]`, where `SIMD`'s `length`
# parameter is constrained by the concrete TYPE `SIMDLength` and the
# argument's own bound is a different concrete type (`Int`). A type constraint
# is not a conformance requirement: the required "trait" names a type the
# checker cannot resolve as a trait here, so it must be accepted, not tested
# for membership. (The names below are stand-ins for `SIMDLength`/`Int` — what
# matters is two distinct names that are not traits in this module.)
POS_TYPE_CONSTRAINT_BOUND = r'''
struct Vec[length: Int]:
    def __init__(out self):
        pass
    def resize[new_length: Float64 = 1.0](self) -> Vec[new_length]:
        return Vec[new_length]()

def main():
    pass
'''


def test_positive_type_constraint_bound_not_a_trait():
    _assert_ok(POS_TYPE_CONSTRAINT_BOUND)


# Negative control: the check must still reject a bound argument that is a
# signature type parameter whose OWN bound list genuinely lacks the required
# trait (`U: MovableT` cannot be shown to satisfy `Box[T: CopyableT]`). This
# pins that the default-strip and the non-trait-bound skip do not widen the
# check into blanket acceptance.
NEG_GENUINELY_UNPROVEN = r'''
trait CopyableT:
    def copy(self) -> Self: ...

trait MovableT:
    pass

struct Box[T: CopyableT]:
    def __init__(out self):
        pass

def bad[U: MovableT](x: U) -> Box[U]: ...

def main():
    pass
'''


def test_negative_unproven_trait_still_rejected():
    _assert_err(
        NEG_GENUINELY_UNPROVEN,
        'invalid bindings in signature: lacking evidence',
    )


if __name__ == '__main__':
    tests = [v for k, v in sorted(globals().items()) if k.startswith('test_') and callable(v)]
    for fn in tests:
        try:
            fn()
            print('ok', fn.__name__)
        except Exception as e:
            import traceback
            print('FAIL', fn.__name__, e)
            traceback.print_exc()
            sys.exit(1)
    print('all tests passed')
