#!/usr/bin/env python3
"""Regression: defaulted trait method conformance (part 6)."""

import os
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

from gimple_codegen import compile_to_gimple


def _compile(src):
    with tempfile.TemporaryDirectory(prefix='def_trait_conf_') as d:
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


# Negative: defaulted map returns partially-applied struct Map[mapFn] (1 of 3),
# so Map cannot satisfy Strategy.
NEG = r'''
trait Strategy:
    comptime Value: AnyType
    def value(self) -> Self.Value: ...
    def map[Dest: Copyable, mapFn: fn(Self.Value) -> Dest](self) -> Map[mapFn]:
        return Map[mapFn]()

struct Map[Strat: Strategy, Dest: Copyable, mapFn: fn(Strat.Value) -> Dest](Strategy):
    comptime Value = Dest
    def __init__(out self):
        pass
    def value(self) -> Self.Value:
        var x: Self.Value
        return x

def main():
    pass
'''


def test_negative_partially_applied_default():
    _assert_err(
        NEG,
        "does not implement all requirements for 'Strategy'",
        "'Map[mapFn]'",
    )


# Negative: the same partial application in a default's PARAMETER type. The
# inherited signature is unformable for the struct there too, so the struct
# does not satisfy the trait; checking only the return type would miss it.
NEG_PARAM = r'''
trait Strategy:
    comptime Value: AnyType
    def value(self) -> Self.Value: ...
    def merge[Dest: Copyable, mapFn: fn(Self.Value) -> Dest](
            self, other: Map[mapFn]) -> Self:
        return self

struct Map[Strat: Strategy, Dest: Copyable, mapFn: fn(Strat.Value) -> Dest](Strategy):
    comptime Value = Dest
    def __init__(out self):
        pass
    def value(self) -> Self.Value:
        var x: Self.Value
        return x

def main():
    pass
'''


def test_negative_partially_applied_default_parameter():
    _assert_err(
        NEG_PARAM,
        "does not implement all requirements for 'Strategy'",
        "'Map[mapFn]'",
    )


# Negative, NON-COINCIDENTIAL spelling: the trait default method's own bracket
# parameter is `mapper` while the conforming struct declares the same value
# parameter as `mapFn`. The diagnostic must report the CONFORMING STRUCT's
# spelling -- `'Map[mapFn]'` -- not the trait method's `'Map[mapper]'`. Every
# other case here spells the parameter `mapFn` on BOTH sides, so it cannot
# catch a regression to the trait's spelling (which is what shipped before
# elaborate._respell_app_with_struct_value_params).
NEG_DIFFERENT_SPELLING = r"""
trait Strategy:
    comptime Value: AnyType
    def value(self) -> Self.Value: ...
    def map[To: Copyable, //, mapper: def (Self.Value) thin -> To](self) -> Map[mapper]:
        return Map[mapper]()

struct Map[Strat: Strategy, Dest: Copyable, //, mapFn: def (Strat.Value) thin -> Dest](Strategy):
    comptime Value = Dest
    def __init__(out self):
        pass
    def value(self) -> Self.Value:
        var x: Self.Value
        return x

def main():
    pass
"""


def test_negative_partially_applied_default_respelled_with_struct_parameter():
    _assert_err(
        NEG_DIFFERENT_SPELLING,
        "does not implement all requirements for 'Strategy'",
        "'Map[mapFn]'",
    )


# Positive: default returns Self.
POS_SELF = r'''
trait Strategy:
    comptime Value: AnyType
    def value(self) -> Self.Value: ...
    def clone(self) -> Self:
        return self

struct Good(Strategy):
    comptime Value = Int
    def __init__(out self):
        pass
    def value(self) -> Self.Value:
        return 0

def main():
    pass
'''


def test_positive_default_returns_self():
    _assert_ok(POS_SELF)


# Positive: default returns fully-applied struct type.
POS_FULL = r'''
trait Strategy:
    comptime Value: AnyType
    def value(self) -> Self.Value: ...
    def map[Dest: Copyable, mapFn: fn(Self.Value) -> Dest](self) -> Map[Self, Dest, mapFn]:
        return Map[Self, Dest, mapFn]()

struct Map[Strat: Strategy, Dest: Copyable, mapFn: fn(Strat.Value) -> Dest](Strategy):
    comptime Value = Dest
    def __init__(out self):
        pass
    def value(self) -> Self.Value:
        var x: Self.Value
        return x

def main():
    pass
'''


def test_positive_fully_applied_default():
    _assert_ok(POS_FULL)


# Positive: struct overrides the defaulted method itself.
POS_OVERRIDE = r'''
trait Strategy:
    comptime Value: AnyType
    def value(self) -> Self.Value: ...
    def map[Dest: Copyable, mapFn: fn(Self.Value) -> Dest](self) -> Map[mapFn]:
        return Map[mapFn]()

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


def test_positive_override_default():
    _assert_ok(POS_OVERRIDE)


# Positive: pin for the 2026-11-15 gate red. Commit 43bd3dcba extended the
# signature-binding check to RETURN types, and the trait-bound evidence
# check (elaborate.check_signature_param_bound_evidence) treated a template
# parameter constrained by a FUNCTION TYPE (`f: fn(Strat) -> Dest`) as a list
# of traits to prove conformance against. When the method's own same-named
# bound parameter is used as the instantiation argument in the return
# annotation, the two spellings differ (`fn(Strat) -> Dest` vs
# `fn(Self) -> Dest`), the membership test fails, and valid code was
# rejected with "invalid bindings in signature: lacking evidence" —
# `test_positive_override_default` above was the red case. The evidence
# check must skip non-trait bounds (785c1cf2e); this minimal case pins that
# guard without the trait machinery.
PIN_FN_TYPE_BOUND = r'''
struct Box[Strat: AnyType, Dest: Copyable, f: fn(Strat) -> Dest]:
    def __init__(out self):
        pass

struct S:
    def get[Dest: Copyable, f: fn(Self) -> Dest](self) -> Box[Self, Dest, f]:
        pass

def main():
    pass
'''


def test_positive_function_type_bound_bracket_param_in_return():
    _assert_ok(PIN_FN_TYPE_BOUND)


# Positive: a required trait method supplied by a non-trait base struct
# satisfies the trait. The declaration-time pre-pass runs before
# `_merge_struct_inheritance`, so it must resolve base-struct methods itself
# rather than report the struct as non-conforming.
POS_BASE_METHOD = r'''
trait T:
    def f(self) -> Int: ...

struct A:
    def __init__(out self):
        pass
    def f(self) -> Int:
        return 1

struct B(A, T):
    pass

def main():
    pass
'''


def test_positive_required_method_inherited_from_base_struct():
    _assert_ok(POS_BASE_METHOD)


# Positive: a trait's generic method may be implemented under its own
# type-parameter name. The requirement is renaming-invariant — `std/utils/
# variant.mojo`'s `_NicheStorage.as_uninit[T]` is implemented by
# `_DefaultNicheStorage.as_uninit[U]` — so a declaration-time check must not
# report the renamed parameter as a signature mismatch.
POS_RENAMED_GENERIC = r'''
trait First:
    def first[T: AnyType](self, x: List[T]) -> List[T]: ...

struct S(First):
    def first[U: AnyType](self, x: List[U]) -> List[U]:
        return x

def main():
    pass
'''


def test_positive_generic_parameter_renamed_in_implementation():
    _assert_ok(POS_RENAMED_GENERIC)


# Negative control for the same rule: renaming the parameter is free, using a
# different parameter in the same position is not.
NEG_RENAMED_GENERIC_WRONG_RETURN = r'''
trait First:
    def first[T: AnyType](self, x: List[T]) -> List[T]: ...

struct S(First):
    def first[U: AnyType](self, x: List[U]) -> U:
        return x

def main():
    pass
'''


def test_negative_renamed_generic_still_checks_the_signature():
    _assert_err(
        NEG_RENAMED_GENERIC_WRONG_RETURN,
        "does not implement all requirements for 'First'",
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
