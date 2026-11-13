#!/usr/bin/env python3
"""Regression: conditional trait conformance declaration diagnostics (part 1)."""

from gimple_codegen import compile_to_gimple


def _compile(src, filename='t.mojo'):
    return compile_to_gimple(src, do_imports=False, filename=filename)


def _assert_raises(src, msg):
    try:
        _compile(src)
    except RuntimeError as e:
        out = str(e)
        assert msg in out, out
        return
    assert False, "expected RuntimeError"


# --- declaration cases -----------------------------------------------------

def test_diamond_missing_explicit_base():
    _assert_raises(
        'trait A:\n'
        '    pass\n'
        'trait B(A):\n'
        '    pass\n'
        'trait C(A):\n'
        '    pass\n'
        'struct S[T: AnyType](B where conforms_to(T, Copyable),\n'
        '                      C where conforms_to(T, Movable)):\n'
        '    pass\n',
        "ancestor trait 'A' is reached via multiple inheritance paths "
        "with different constraints; it must be explicitly listed in the "
        "conformance list with the desired constraint")


def test_derived_does_not_imply_ancestor():
    _assert_raises(
        'trait Base:\n'
        '    pass\n'
        'trait Derived(Base):\n'
        '    pass\n'
        'struct S[T: AnyType](Derived where conforms_to(T, Copyable),\n'
        '                      Base where conforms_to(T, Movable)):\n'
        '    pass\n',
        "constraint for 'Derived' does not imply constraint for "
        "ancestor trait 'Base'; strengthen the derived constraint "
        "by adding the ancestor's constraint with 'and'")


def test_unconditional_derived_conditional_ancestor():
    _assert_raises(
        'trait Base:\n'
        '    pass\n'
        'trait Derived(Base):\n'
        '    pass\n'
        'struct S[T: AnyType](Derived, Base where conforms_to(T, Copyable)):\n'
        '    pass\n',
        "constraint for 'Derived' does not imply constraint for "
        "ancestor trait 'Base'; strengthen the derived constraint "
        "by adding the ancestor's constraint with 'and'")


def test_conditional_trivial_register_passable():
    _assert_raises(
        'struct S[T: AnyType](TrivialRegisterPassable where conforms_to(T, Copyable)):\n'
        '    pass\n',
        "conditional conformance to 'TrivialRegisterPassable' is not supported")


def test_rp_trait_weaker_constraint():
    _assert_raises(
        'trait RP(RegisterPassable):\n'
        '    pass\n'
        'struct S[T: AnyType](RP where conforms_to(T, Copyable),\n'
        '                      RegisterPassable where conforms_to(T, Copyable) and conforms_to(T, Movable)):\n'
        '    pass\n',
        "constraint for 'RP' does not imply constraint for "
        "ancestor trait 'RegisterPassable'; strengthen the derived constraint "
        "by adding the ancestor's constraint with 'and'")


# --- conditional RP origin rule -------------------------------------------

def test_bad_conditional_rp_origin():
    _assert_raises(
        'struct Box[T: AnyType](RegisterPassable where conforms_to(T, Copyable)):\n'
        '    var v: Int\n'
        '\n'
        'def bad[T: AnyType](x: Box[T]) -> ref[x] Int:\n'
        '    return x.v\n',
        "cannot return 'x's origin, because it might expand to a "
        "RegisterPassable type")


# --- positive controls -----------------------------------------------------

def test_conditional_register_passable_allowed():
    _compile(
        'struct S[T: AnyType](RegisterPassable where conforms_to(T, Copyable)):\n'
        '    var x: Int\n')


def test_no_explicit_rp_conforms_to_rp_trait():
    _compile(
        'trait RP(RegisterPassable):\n'
        '    pass\n'
        'struct S[T: AnyType](RP where conforms_to(T, Copyable)):\n'
        '    var x: Int\n')


def test_ok_conditional_rp_ref_origin():
    _compile(
        'struct Box[T: AnyType](RegisterPassable where conforms_to(T, Copyable)):\n'
        '    var v: Int\n'
        '\n'
        'def ok[T: AnyType](ref x: Box[T]) -> ref[x] Int:\n'
        '    return x.v\n')


def test_where_text_renders_member_access():
    # A `where` constraint may name a member (`conforms_to(Self.IteratorType, ..)`).
    # The MemberExpr field is `member`; rendering it read a non-existent `.attr`
    # and aborted the whole std/iter/__init__.mojo compile (stdlib-dylib skip).
    from fire_compiler import IdentExpr, MemberExpr, _expr_constraint_text
    assert _expr_constraint_text(MemberExpr(IdentExpr('Self'), 'IteratorType')) == 'Self.IteratorType'
    nested = MemberExpr(MemberExpr(IdentExpr('a'), 'b'), 'c')
    assert _expr_constraint_text(nested) == 'a.b.c'


if __name__ == '__main__':
    tests = [v for k, v in sorted(globals().items()) if k.startswith('test_')]
    for t in tests:
        t()
    print(f'OK: {len(tests)} tests passed')
