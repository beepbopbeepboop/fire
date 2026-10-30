#!/usr/bin/env python3
"""Regression test for bug-compile-fail-ctypes-macholib-dyld.

Root cause: cross-module struct-typed-subscript-element-typing gap;
`framework_info`'s dict return value type isn't threaded into the
coroutine body's yield-slot inference, so `_generator_yield_ctype`
refuses honestly rather than miscompiling `dyld_default_search`.
"""
import sys, os
sys.path.insert(0, '.')
import fire_compiler
from mojo.middle.exprtypes import _generator_yield_ctype, _UnsupportedGeneratorShape

with open('/Users/mrs/net/Python-3.14.6/Lib/ctypes/macholib/dyld.py') as f:
    source = f.read()
parser = fire_compiler.Parser(fire_compiler.py_tokenize(source))
fn_ast = parser.parse_module()

nodes = fn_ast.body if hasattr(fn_ast, 'body') else fn_ast
for node in nodes:
    if getattr(node, 'name', None) == 'dyld_default_search':
        try:
            ctype = _generator_yield_ctype(node)
            if ctype == 'char *':
                print('PASS: dyld_default_search yields agree on char *')
                sys.exit(0)
            else:
                print('FAIL: unexpected yield type', ctype)
                sys.exit(1)
        except _UnsupportedGeneratorShape as e:
            print('FAIL (expected before fix):', str(e)[:200])
            sys.exit(1)
        break
else:
    print('FAIL: dyld_default_search not found')
    sys.exit(1)
