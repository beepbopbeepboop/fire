#!/usr/bin/env python3
"""Direct check: _generator_yield_ctype must resolve loop-bound names to the
delegate generator's value_ctype, not default to int64_t."""
import sys, os
sys.path.insert(0, '.')
from fire_compiler import FunctionDef, ForStmt, CallExpr, IdentExpr, YieldExpr, StringLiteral
from mojo.middle.exprtypes import _generator_yield_ctype

# Minimal AST for:
# def render():
#     yield ''
#     for line in _rows([...]):
#         yield line

fn = FunctionDef(name='render', params=[], return_type=None,
    body=[
        YieldExpr(value=StringLiteral('')),
        ForStmt(target='line', iterable=CallExpr(func=IdentExpr('_rows'), args=[], kwargs=[]), body=[
            YieldExpr(value=IdentExpr('line'))
        ]),
    ],
    decorators=[], is_generator=True)

# The delegate _rows yields char *
generator_api = {'_rows': {'base': '__mgco__rows', 'value_ctype': 'char *'}}

ctype = _generator_yield_ctype(fn, known={}, generator_api=generator_api)
print('yield_ctype =', ctype)
if ctype == 'char *':
    print('PASS: loop-bound yield resolves to char *')
    sys.exit(0)
else:
    print('FAIL: loop-bound yield should be char *, got', ctype)
    sys.exit(1)
