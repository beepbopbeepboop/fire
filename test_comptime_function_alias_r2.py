#!/usr/bin/env python3
"""Regression for CODEGEN_comptime_function_type_alias_is_erased_by_the_parser.
Part 3: a comptime function-type alias must survive as a signature (not be
erased to _comptime_expr)."""
import sys
sys.path.insert(0, '.')
import fire_compiler as F

def test_comptime_function_type_alias_survives():
    src = 'comptime Sig = def[width: Int](Int) -> None\n'
    p = F.Parser(F.py_tokenize(src)).with_filename('<test>')
    stmts = p.parse_module()
    assert len(stmts) == 1, stmts
    stmt = stmts[0]
    assert isinstance(stmt, F.ComptimeVarStmt), stmt
    value = stmt.value
    # Before fix: IdentExpr('_comptime_expr'). After fix: FunctionType.
    assert not (isinstance(value, F.IdentExpr) and value.name == '_comptime_expr'), \
        f"function-type alias erased to placeholder: {value!r}"
    assert isinstance(value, F.FunctionType), f"expected FunctionType, got {type(value).__name__}: {value!r}"
    # Must carry signature info
    assert hasattr(value, 'comptime_params'), value
    print("PASS: comptime function-type alias survives as FunctionType")

if __name__ == '__main__':
    test_comptime_function_type_alias_survives()
