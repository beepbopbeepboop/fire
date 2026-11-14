#!/usr/bin/env python3
"""Regression: @align argument is parsed and stored on StructDef (part 1)."""

import fire_compiler


def _parse(src):
    p = fire_compiler.Parser(fire_compiler.py_tokenize(src))
    p._filename = "t.mojo"
    return p.parse_module()


def test_align_expr_stored_for_constant():
    sd = _parse("@align(16)\nstruct S:\n    var x: Int\n")[0]
    assert isinstance(sd, fire_compiler.StructDef)
    assert isinstance(sd.align_expr, fire_compiler.IntLiteral), sd.align_expr
    assert sd.align_expr.value == 16


def test_align_expr_stored_for_parametric_expression():
    sd = _parse("@align(alignment)\nstruct S[alignment: Int]:\n    pass\n")[0]
    assert isinstance(sd, fire_compiler.StructDef)
    assert isinstance(sd.align_expr, fire_compiler.IdentExpr), sd.align_expr
    assert sd.align_expr.name == "alignment"


def test_align_expr_none_without_decorator():
    sd = _parse("struct S:\n    pass\n")[0]
    assert sd.align_expr is None


if __name__ == "__main__":
    test_align_expr_stored_for_constant()
    test_align_expr_stored_for_parametric_expression()
    test_align_expr_none_without_decorator()
    print("ok")
