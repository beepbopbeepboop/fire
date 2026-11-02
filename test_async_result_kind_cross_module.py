"""Regression: cross-module async result kind must not fall back to int64."""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from mojo.middle import coro as c

def test_cross_module_result_kind_registered():
    # Simulate an imported module's async float function in closure_stmts
    import fire_compiler as fc
    src_a = 'async def imported_fn() -> Float64:\n    return 1.5\n'
    stmts_a = fc.Parser(fc.py_tokenize(src_a)).parse_module()
    # Local module only has an await expression referencing the import
    src_b = 'async def caller() -> Float64:\n    return 1.0\n'
    stmts_b = fc.Parser(fc.py_tokenize(src_b)).parse_module()
    # Before fix: _register_async_result_kinds(stmts_b) cleared the table
    # and never saw imported_fn, so it answered 'i'. After fix with
    # closure_stmts=[stmts_a], the float kind is registered.
    c._register_async_result_kinds(stmts_b, [stmts_a])
    kind = c._result_kind_of(fc.CallExpr(fc.IdentExpr('imported_fn'), args=[]))
    assert kind == 'd', f"expected 'd' for imported float async, got {kind!r}"
    print("PASS cross-module result kind registered as 'd'")

def test_existing_local_kind_still_works():
    import fire_compiler as fc
    src = 'async def f() -> Float64:\n    return 1.5\n'
    stmts = fc.Parser(fc.py_tokenize(src)).parse_module()
    c._register_async_result_kinds(stmts)
    kind = c._result_kind_of(fc.CallExpr(fc.IdentExpr('f'), args=[]))
    assert kind == 'd', f"expected 'd', got {kind!r}"
    print("PASS local float kind still 'd'")

if __name__ == '__main__':
    test_cross_module_result_kind_registered()
    test_existing_local_kind_still_works()
