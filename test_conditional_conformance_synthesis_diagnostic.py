#!/usr/bin/env python3
"""Regression: conditional trait conformance copy/move synthesis diagnostics (part 4)."""

from gimple_codegen import compile_to_gimple


def _compile(src, filename='t.mojo'):
    return compile_to_gimple(src, do_imports=False, filename=filename)


def _assert_raises(src, msg, field_name=None):
    try:
        _compile(src)
    except RuntimeError as e:
        out = str(e)
        assert msg in out, out
        if field_name is not None:
            assert f"field '{field_name}'" in out, out
        return
    assert False, "expected RuntimeError"


def test_copy_synth_fails_with_or():
    _assert_raises(
        'trait Copyable:\n'
        '    pass\n'
        'trait Intable:\n'
        '    pass\n'
        'struct CopySynthFailsWithOR[T: AnyType](Copyable where conforms_to(T, Copyable) or conforms_to(T, Intable)):\n'
        '    var value: T\n',
        "cannot synthesize copy constructor because field 'value' has non-copyable type",
        field_name='value')


def test_copy_synth_fails_multi_field():
    _assert_raises(
        'trait Copyable:\n'
        '    pass\n'
        'struct CopySynthFailsMultiField[T: AnyType, U: AnyType](Copyable where conforms_to(T, Copyable)):\n'
        '    var first: T\n'
        '    var second: U\n',
        "cannot synthesize copy constructor because field 'second' has non-copyable type",
        field_name='second')


def test_unsatisfied_variadic_copy_synthesis():
    _assert_raises(
        'trait Copyable:\n'
        '    pass\n'
        'struct NegativeVariadicCopyField[*Ts: AnyType](Copyable where Ts.all_conforms_to[Copyable]()):\n'
        '    var x: Int\n'
        'struct UnsatisfiedVariadicCopySynthesis[T: AnyType](Copyable):\n'
        '    var field: NegativeVariadicCopyField[Int, T]\n',
        "cannot synthesize copy constructor because field 'field' has non-copyable type",
        field_name='field')


def test_unsatisfied_variadic_move_synthesis():
    _assert_raises(
        'trait Movable:\n'
        '    pass\n'
        'struct NegativeVariadicMoveField[*Ts: AnyType](Movable where Ts.all_conforms_to[Movable]()):\n'
        '    var x: Int\n'
        'struct UnsatisfiedVariadicMoveSynthesis[T: AnyType](Movable):\n'
        '    var field: NegativeVariadicMoveField[Int, T]\n',
        "cannot synthesize move constructor because field 'field' has non-movable and non-implicitly-copyable type",
        field_name='field')


# --- positive controls -----------------------------------------------------

def test_unconditional_copyable_movable_fields_synthesize():
    _compile(
        'trait Copyable:\n'
        '    pass\n'
        'trait Movable:\n'
        '    pass\n'
        'struct Inner(Copyable, Movable):\n'
        '    var x: Int\n'
        'struct Outer(Copyable, Movable):\n'
        '    var a: Inner\n'
        '    var b: Int\n')


def test_conditional_constraint_covers_field_type_params():
    _compile(
        'trait Copyable:\n'
        '    pass\n'
        'trait Movable:\n'
        '    pass\n'
        'struct Box[T: AnyType](Copyable where conforms_to(T, Copyable),\n'
        '                       Movable where conforms_to(T, Movable)):\n'
        '    var value: T\n')


if __name__ == '__main__':
    tests = [v for k, v in sorted(globals().items()) if k.startswith('test_')]
    for t in tests:
        t()
    print(f'OK: {len(tests)} tests passed')
