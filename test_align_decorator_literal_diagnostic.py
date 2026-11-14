#!/usr/bin/env python3
"""Regression test for malformed/non-power-of-2 constant @align arguments.

Parses snippets directly (no whole-closure compile needed).
"""

import fire_compiler


def _parse(src):
    p = fire_compiler.Parser(fire_compiler.py_tokenize(src))
    p._filename = "t.mojo"
    return p.parse_module()


def _assert_syntax_error(src, msg):
    try:
        _parse(src)
    except SyntaxError as e:
        s = str(e)
        assert msg in s, (msg, s)
        return
    raise AssertionError(f"expected SyntaxError containing {msg!r} for: {src!r}")


def _assert_parses(src):
    mod = _parse(src)
    assert len(mod) == 1, mod
    assert isinstance(mod[0], fire_compiler.StructDef), mod[0]
    return mod[0]


def test_arg_count():
    msg = "@align requires exactly one argument"
    for src in [
        "@align\nstruct S:\n    pass\n",
        "@align()\nstruct S:\n    pass\n",
        "@align(64, 128)\nstruct S:\n    pass\n",
    ]:
        _assert_syntax_error(src, msg)


def test_not_power_of_two():
    msg = "@align value must be a positive power of 2"
    for v in [0, -1, 3, 5, 6, 7, 100]:
        _assert_syntax_error(f"@align({v})\nstruct S:\n    pass\n", msg)


def test_exceeds_max():
    msg = "@align value exceeds maximum alignment (2^29)"
    for v in [1073741824, 4294967296]:
        _assert_syntax_error(f"@align({v})\nstruct S:\n    pass\n", msg)


def test_valid_constants():
    for v in [1, 2, 4, 64, "0x40", 4096]:
        src = f"@align({v})\nstruct S:\n    pass\n"
        sd = _assert_parses(src)
        assert len(sd.decorators) == 1, sd.decorators
        assert isinstance(sd.decorators[0], fire_compiler.CallExpr), sd.decorators


def test_deferred_non_constant():
    # Non-constant argument accepted by this part (deferred to parts 2/3).
    sd = _assert_parses("@align(alignment)\nstruct S[alignment: Int]:\n    pass\n")
    assert len(sd.decorators) == 1
    assert isinstance(sd.decorators[0], fire_compiler.CallExpr)


if __name__ == "__main__":
    test_arg_count()
    test_not_power_of_two()
    test_exceeds_max()
    test_valid_constants()
    test_deferred_non_constant()
    print("ok")
