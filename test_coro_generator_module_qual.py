#!/usr/bin/env python3
"""Regression: free-function generator base must be module-qualified."""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

def test():
    import mojo.middle.coro as coro
    # Manually build a minimal FunctionDef with generator flag
    import fire_compiler as N
    fn = N.FunctionDef(name='tokenize', params=[], return_type='', body=[N.ExprStmt(value=N.YieldExpr(value=N.IntLiteral(value=1)))], decorators=[])
    fn.is_generator = True
    # Test qualified base via lower()
    coro._MODULE_QUALIFIER = ''
    out, meta = coro.lower([fn], module_name='lexer')
    assert meta, "expected meta"
    assert meta[0]['base'] == '__mgco_lexer_tokenize', f"got {meta[0]['base']}"
    # Different module
    coro._MODULE_QUALIFIER = ''
    out2, meta2 = coro.lower([fn], module_name='plexer')
    assert meta2[0]['base'] == '__mgco_plexer_tokenize', f"got {meta2[0]['base']}"
    # Empty module -> bare
    coro._MODULE_QUALIFIER = ''
    out3, meta3 = coro.lower([fn], module_name=None)
    assert meta3[0]['base'] == '__mgco_tokenize', f"got {meta3[0]['base']}"
    print("PASS")

if __name__ == '__main__':
    test()
