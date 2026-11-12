"""Regression: cpp_async must accept *args/**kwargs in compiled async functions.

Bug: COMPILE_FAIL_Lib_contextlib_request_for_member_module_in_something_not_a_structure_or_union-part3
The module_gen whole-module path refused async functions with variadic
parameters before this fix.
"""
from fire_compiler import py_tokenize, Parser
import gimple_codegen


def _compile(src: str):
    stmts = Parser(py_tokenize(src)).parse_module()
    gen = gimple_codegen.GimpleGen()
    return gen.gen_module(stmts)


def test_async_star_args_compiles():
    out = _compile('async def __aexit__(self, *args):\n    return 0\n')
    assert out is not None


def test_async_kwargs_compiles():
    out = _compile('async def f(**kwargs):\n    return 0\n')
    assert out is not None


def test_async_star_args_and_kwargs_compiles():
    out = _compile('async def inner(*args, **kwds):\n    return 0\n')
    assert out is not None


def test_async_fixed_and_star_args_compiles():
    out = _compile('async def f(a, b, *args):\n    return a\n')
    assert out is not None


def test_async_method_star_args_compiles():
    out = _compile(
        'struct CM:\n'
        '    async def __aexit__(self, *exc_info):\n'
        '        return 0\n'
    )
    assert out is not None
