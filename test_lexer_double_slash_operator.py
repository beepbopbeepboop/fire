#!/usr/bin/env python3
"""`//` is Mojo's floor-division operator and parameter-list separator.

It is NOT a line-comment marker.  Mojo line comments start with `#`; the
LLVM-style `// RUN:` / `// CHECK:` lines that prompted the original bug doc
belong to lit tests, not to Mojo source.  Treating `//` as a comment in the
lexer silently truncated every expression that used floor division
(`bit_width // 2`) and every parameter list with a positional-only separator
(`def f[T: Boolable, //](...)`), which is what turned the landing gate red.

Run:  python3 test_lexer_double_slash_operator.py [-v]
"""
from fire_compiler import BinaryOp, Parser, py_tokenize


def _parse(src):
    return Parser(py_tokenize(src)).parse_module()


def test_floor_division_stays_an_operator():
    src = "x = 7 // 2\n"
    tokens = py_tokenize(src)
    ops = [t.value for t in tokens if t.kind == "OP"]
    assert "//" in ops, ops
    mod = _parse(src)
    assert len(mod) == 1
    value = mod[0].value
    assert isinstance(value, BinaryOp), value
    assert value.op == "//", value.op


def test_inline_floor_division_is_not_stripped():
    # A `#` comment after floor division must still be stripped, and the
    # division itself must survive.
    src = "y = bit_width // 2  # halve it\n"
    mod = _parse(src)
    assert len(mod) == 1
    assert isinstance(mod[0].value, BinaryOp)
    assert mod[0].value.op == "//"


def test_positional_only_separator_in_parameter_list():
    src = "def f[T: Boolable, //](out self):\n    pass\n"
    mod = _parse(src)
    assert len(mod) == 1
    assert mod[0].name == "f"
    assert mod[0].comptime_params == ["T"], mod[0].comptime_params


def test_trailing_separator_on_its_own_line():
    # This is the shape most stdlib parameter lists use: the separator ends a
    # line by itself, inside a bracketed parameter block.
    src = "def f[\n    dtype: DType, //\n](value: Int):\n    pass\n"
    mod = _parse(src)
    assert len(mod) == 1
    assert mod[0].name == "f"
    assert mod[0].comptime_params == ["dtype"], mod[0].comptime_params


def test_hash_comments_still_stripped():
    src = "# leading comment\nz = 42  # trailing\n"
    mod = _parse(src)
    assert len(mod) == 1
    assert mod[0].target.name == "z"


if __name__ == "__main__":
    test_floor_division_stays_an_operator()
    test_inline_floor_division_is_not_stripped()
    test_positional_only_separator_in_parameter_list()
    test_trailing_separator_on_its_own_line()
    test_hash_comments_still_stripped()
    print("ok")
