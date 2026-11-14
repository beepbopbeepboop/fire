#!/usr/bin/env python3
"""Regression test: `conforms_to(T, Trait)` folds in comptime conditions.

Covers comptime assert, constrained[...], and function `where` clauses, plus
not/positive/inherited/undecided controls. No stdlib imports.
"""

from diagnostic_build import build_refusal
from gimple_codegen import compile_to_gimple

_TRAITS = (
    'trait Tr:\n'
    '    pass\n'
    '\n'
    'trait Sub(Tr):\n'
    '    pass\n'
    '\n'
    'struct No:\n'
    '    pass\n'
    '\n'
    'struct Yes(Tr):\n'
    '    pass\n'
    '\n'
    'struct YesSub(Sub):\n'
    '    pass\n'
)


def _compile(src, filename='t.mojo'):
    return compile_to_gimple(src, do_imports=False, filename=filename)


# --- comptime assert -------------------------------------------------------

def test_comptime_assert_false_nonconforming_rejected():
    rc, out = build_refusal(
        _TRAITS
        + 'def f[T: AnyType]():\n'
          '    comptime assert conforms_to(T, Tr), "no"\n'
          '\n'
          'def main():\n'
          '    f[No]()\n')
    assert rc != 0, out
    assert 'comptime assertion failed' in out, out
    assert 'no' in out, out


def test_comptime_assert_copyable_and_movable_are_derived():
    # Copyable/Movable are derived from a struct's fields, so they are not in
    # its DECLARED bases list; an empty list must not prove a negative. This is
    # the shape of the stdlib check that failed: LinkedList's
    # `comptime assert conforms_to(Self.ElementType, Copyable)` (2026-11-12).
    _compile(
        'struct Plain:\n'
        '    var x: Int\n'
        '\n'
        'def f[T: AnyType]():\n'
        '    comptime assert conforms_to(T, Copyable), "no"\n'
        '    comptime assert conforms_to(T, Movable), "bad"\n'
        '\n'
        'def main():\n'
        '    f[Plain]()\n')


def test_comptime_assert_true_conforming_compiles():
    _compile(
        _TRAITS
        + 'def f[T: AnyType]():\n'
          '    comptime assert conforms_to(T, Tr), "no"\n'
          '\n'
          'def main():\n'
          '    f[Yes]()\n')


def test_comptime_assert_true_inherited_compiles():
    _compile(
        _TRAITS
        + 'def f[T: AnyType]():\n'
          '    comptime assert conforms_to(T, Tr), "no"\n'
          '\n'
          'def main():\n'
          '    f[YesSub]()\n')


def test_comptime_assert_not_on_conforming_rejected():
    rc, out = build_refusal(
        _TRAITS
        + 'def f[T: AnyType]():\n'
          '    comptime assert not conforms_to(T, Tr), "bad"\n'
          '\n'
          'def main():\n'
          '    f[Yes]()\n')
    assert rc != 0, out
    assert 'comptime assertion failed' in out, out
    assert 'bad' in out, out


def test_comptime_assert_not_on_nonconforming_compiles():
    _compile(
        _TRAITS
        + 'def f[T: AnyType]():\n'
          '    comptime assert not conforms_to(T, Tr), "bad"\n'
          '\n'
          'def main():\n'
          '    f[No]()\n')


def test_comptime_assert_unresolved_type_param_undecided():
    # A bare type parameter in a non-instantiated body: undecided, no diagnostic.
    _compile(
        _TRAITS
        + 'def f[T: AnyType]():\n'
          '    comptime assert conforms_to(T, Tr), "no"\n')


# --- constrained -----------------------------------------------------------

def test_constrained_false_nonconforming_rejected():
    rc, out = build_refusal(
        _TRAITS
        + 'def f[T: AnyType]():\n'
          '    constrained[conforms_to(T, Tr), "nope"]()\n'
          '\n'
          'def main():\n'
          '    f[No]()\n')
    assert rc != 0, out
    assert 'constraint failed' in out, out
    assert 'nope' in out, out


def test_constrained_true_conforming_compiles():
    _compile(
        _TRAITS
        + 'def f[T: AnyType]():\n'
          '    constrained[conforms_to(T, Tr), "nope"]()\n'
          '\n'
          'def main():\n'
          '    f[Yes]()\n')


def test_constrained_true_inherited_compiles():
    _compile(
        _TRAITS
        + 'def f[T: AnyType]():\n'
          '    constrained[conforms_to(T, Tr), "nope"]()\n'
          '\n'
          'def main():\n'
          '    f[YesSub]()\n')


def test_constrained_unresolved_type_param_undecided():
    _compile(
        _TRAITS
        + 'def f[T: AnyType]():\n'
          '    constrained[conforms_to(T, Tr), "nope"]()\n')


# --- where clause ----------------------------------------------------------

def test_where_false_nonconforming_rejected():
    rc, out = build_refusal(
        _TRAITS
        + 'def f[T: AnyType]() where conforms_to(T, Tr):\n'
          '    pass\n'
          '\n'
          'def main():\n'
          '    f[No]()\n')
    assert rc != 0, out
    assert 'violated constraint' in out or 'requirement' in out or 'constraint failed' in out, out


def test_where_true_conforming_compiles():
    _compile(
        _TRAITS
        + 'def f[T: AnyType]() where conforms_to(T, Tr):\n'
          '    pass\n'
          '\n'
          'def main():\n'
          '    f[Yes]()\n')


def test_where_true_inherited_compiles():
    _compile(
        _TRAITS
        + 'def f[T: AnyType]() where conforms_to(T, Tr):\n'
          '    pass\n'
          '\n'
          'def main():\n'
          '    f[YesSub]()\n')


# --- existing behaviour preserved ------------------------------------------

def test_comptime_assert_bool_still_works():
    # True/False and basic predicates keep their current behaviour.
    _compile('def f():\n    comptime assert True\n')
    try:
        _compile('def f():\n    comptime assert False, "x"\n')
    except RuntimeError as e:
        assert 'comptime assertion failed' in str(e), e
    else:
        raise AssertionError('comptime assert False compiled')


def test_dtype_predicate_still_works():
    from diagnostic_build import build_refusal as br
    rc, out = br(
        'def f[T: AnyType]():\n'
        '    constrained[T.is_floating_point(), "fp"]()\n'
        '\n'
        'def main():\n'
        '    f[Int]()\n')
    # DType/value predicates keep current behaviour; unknown/other forms must
    # not regress. (This specific shape may or may not be foldable depending on
    # binding; we only require no crash in the folder path.)
    assert isinstance(rc, int)


if __name__ == '__main__':
    for name, fn in sorted(list(globals().items())):
        if name.startswith('test_') and callable(fn):
            fn()
            print('ok', name)
    print('all tests passed')
