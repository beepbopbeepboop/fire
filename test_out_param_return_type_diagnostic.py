#!/usr/bin/env python3
"""Regression test: a function must not declare both an `out` argument and a
return type.

Modular rejects the combination at the return type's location
(`functions must not declare both an 'out' argument and a return type`),
mojo-parser/precompile/mojo_package_moco_773.mojo.  Our parser used to accept
it silently.

Umbrella: bugs/hard/DIAGNOSTICS_missing_validation_modular.md (category A,
"Other").
"""

import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

from gimple_codegen import compile_to_gimple


def _compile(src, filename='t.mojo'):
    return compile_to_gimple(src, do_imports=False, filename=filename)


def test_out_self_with_return_type_fails():
    try:
        _compile('struct A:\n'
                 '    def __init__(out self) -> A:\n'
                 '        pass\n')
    except RuntimeError as e:
        assert "functions must not declare both an 'out' argument and a return type" in str(e), e
        return
    raise AssertionError('out + return type compiled without error')


def test_out_param_with_return_type_fails():
    try:
        _compile('fn f(out x: Int) -> Int:\n'
                 '    return x\n')
    except RuntimeError as e:
        assert "functions must not declare both an 'out' argument and a return type" in str(e), e
        return
    raise AssertionError('out + return type compiled without error')


def test_out_self_without_return_type_passes():
    _compile('struct A:\n'
             '    var x: Int\n'
             '    def __init__(out self):\n'
             '        self.x = 1\n')


def test_return_type_without_out_passes():
    _compile('fn f(x: Int) -> Int:\n'
             '    return x\n')


if __name__ == '__main__':
    for name, fn in sorted(list(globals().items())):
        if name.startswith('test_') and callable(fn):
            fn()
            print('ok', name)
    print('all tests passed')
