#!/usr/bin/env python3
"""Regression: trait comptime member type/where requirements (part 5)."""

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
    src = (
        'trait EnumLike:\n'
        '    comptime _enum_is_exhaustive: Bool\n'
        '\n'
        'struct Mistyped(EnumLike):\n'
        '    comptime _enum_is_exhaustive = 5\n'
        '    def __init__(out self):\n'
        '        pass\n'
    )
    _assert_err(
        src,
        "does not implement all requirements for 'EnumLike'",
        "comptime member '_enum_is_exhaustive'",
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
        'struct Good(EnumLike):\n'
        '    comptime _enum_is_exhaustive = True\n'
        '    def __init__(out self):\n'
        '        pass\n'
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


def main():
    test_enum_exhaustive_mistyped()
    test_cond_alias_not_implied_struct()
    test_positive_enum_bool()
    test_positive_cond_alias_implied()
    print('PASS')


if __name__ == '__main__':
    main()
