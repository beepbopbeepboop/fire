#!/usr/bin/env python3
"""Regression: trait comptime member type/where requirements (part 5).

A trait may require a `comptime` member (`trait EnumLike: comptime
_enum_is_exhaustive: Bool`).  A conforming struct's own member must have a
conforming declared type, and a member constrained by a `where` clause must be
implied by the conformance constraint.  The check must stay conservative:
members the compiler synthesises, defaulted trait members, value-typed aliases
(`comptime Element = Self.T`), and opaque conditions are all accepted.
"""

import os
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

from gimple_codegen import compile_to_gimple


def _compile(src):
    d = tempfile.mkdtemp(prefix='trait_cmpt_p5_')
    p = os.path.join(d, 't.mojo')
    with open(p, 'w') as fh:
        fh.write(src)
    try:
        compile_to_gimple(src, do_imports=False, filename=p)
    except Exception as e:
        return f'{type(e).__name__}: {e}'
    return None


def _assert_err(src, *msgs):
    text = _compile(src)
    assert text is not None, 'expected compile error, got success'
    for msg in msgs:
        assert msg in text, (msg, text)
    return text


def _assert_ok(src):
    text = _compile(src)
    assert text is None, f'expected success, got: {text}'


def test_enum_exhaustive_mistyped():
    # The doc's enum surface: `__enum` is parsed as a struct, so the base list
    # is real conformance and the unannotated literal's type is `IntLiteral`.
    src = (
        'trait EnumLike:\n'
        '    comptime _enum_is_exhaustive: Bool\n'
        '\n'
        '__enum Mistyped(EnumLike):\n'
        '    A = 0\n'
        '    comptime _enum_is_exhaustive = 5\n'
    )
    _assert_err(
        src,
        "error: 'Mistyped' does not implement all requirements for 'EnumLike'",
        "comptime member '_enum_is_exhaustive' type 'IntLiteral[5]'",
        "does not conform to trait's required type 'Bool'",
        "note: trait 'EnumLike' declared here",
    )


def test_annotated_type_mismatch():
    # An explicit annotation does not get a free pass: `Int` is not `Bool`.
    src = (
        'trait EnumLike:\n'
        '    comptime _enum_is_exhaustive: Bool\n'
        '\n'
        'struct Annotated(EnumLike):\n'
        '    comptime _enum_is_exhaustive: Int = 5\n'
        '    def __init__(out self):\n'
        '        pass\n'
    )
    _assert_err(
        src,
        "does not implement all requirements for 'EnumLike'",
        "comptime member '_enum_is_exhaustive' type 'Int'",
    )


def test_cond_alias_not_implied_struct():
    src = (
        'trait CondAliasNotImplied:\n'
        '    comptime SIZE: Int\n'
        '\n'
        'struct CondAliasNotImpliedStruct[n: Int](CondAliasNotImplied):\n'
        '    comptime SIZE: Int where Self.n >= 10 = Self.n\n'
        '    def __init__(out self):\n'
        '        pass\n'
    )
    _assert_err(
        src,
        "does not implement all requirements for 'CondAliasNotImplied'",
        "comptime member 'SIZE'",
    )


def test_positive_enum_bool():
    src = (
        'trait EnumLike:\n'
        '    comptime _enum_is_exhaustive: Bool\n'
        '\n'
        '__enum Good(EnumLike):\n'
        '    A = 0\n'
        '    comptime _enum_is_exhaustive = True\n'
    )
    _assert_ok(src)


def test_positive_cond_alias_implied():
    src = (
        'trait CondAliasNotImplied:\n'
        '    comptime SIZE: Int\n'
        '\n'
        'struct CondAliasImpliedStruct[n: Int](CondAliasNotImplied) where n >= 0:\n'
        '    comptime SIZE: Int where Self.n >= 0 = Self.n\n'
        '    def __init__(out self):\n'
        '        pass\n'
    )
    _assert_ok(src)


def test_unknown_value_type_is_accepted():
    # The stdlib's `.Iterator`/`.Iterable` spelling: the member's type is a
    # type expression, so its conformance to a trait requirement (`Movable`)
    # is outside this checker's model.  Accepting it is required; rejecting it
    # would fail nearly every iterator struct.
    src = (
        'trait Iterator:\n'
        '    comptime Element: Movable\n'
        '\n'
        'struct Counter[T: Int](Iterator):\n'
        '    comptime Element = Self.T\n'
        '    def __init__(out self):\n'
        '        pass\n'
    )
    _assert_ok(src)


def test_unannotated_int_literal_satisfies_int():
    src = (
        'trait HasSize:\n'
        '    comptime SIZE: Int\n'
        '\n'
        'struct HasSizeImpl(HasSize):\n'
        '    comptime SIZE = 5\n'
        '    def __init__(out self):\n'
        '        pass\n'
    )
    _assert_ok(src)


def test_synthesised_member_may_be_absent():
    # `__copy_ctor_is_trivial` and friends are compiler-synthesised; a struct
    # that relies on the synthesis does not declare them.
    src = (
        'trait Copyable:\n'
        '    comptime __copy_ctor_is_trivial: Bool\n'
        '\n'
        'struct Plain(Copyable):\n'
        '    def __init__(out self):\n'
        '        pass\n'
    )
    _assert_ok(src)


def test_defaulted_trait_member_is_not_required():
    # `comptime X: Bool = True` supplies a default; conforming types need not
    # repeat it (EnumLike's `_enum_elt_type_for_case` has this shape).
    src = (
        'trait WithDefault:\n'
        '    comptime X: Bool = True\n'
        '\n'
        'struct UsesDefault(WithDefault):\n'
        '    def __init__(out self):\n'
        '        pass\n'
    )
    _assert_ok(src)


def test_opaque_where_clause_is_accepted():
    # An unparseable/undecidable condition is not a proven violation.
    src = (
        'trait Weird:\n'
        '    comptime SIZE: Int\n'
        '\n'
        'struct Opaque[n: Int](Weird):\n'
        '    comptime SIZE: Int where some_predicate(Self.n) = Self.n\n'
        '    def __init__(out self):\n'
        '        pass\n'
    )
    _assert_ok(src)


def main():
    test_enum_exhaustive_mistyped()
    test_annotated_type_mismatch()
    test_cond_alias_not_implied_struct()
    test_positive_enum_bool()
    test_positive_cond_alias_implied()
    test_unknown_value_type_is_accepted()
    test_unannotated_int_literal_satisfies_int()
    test_synthesised_member_may_be_absent()
    test_defaulted_trait_member_is_not_required()
    test_opaque_where_clause_is_accepted()
    print('PASS')


if __name__ == '__main__':
    main()
