#!/usr/bin/env python3
"""Regression: a `comptime if` over a GENERIC comptime alias must fold.

A generic alias has no value of its own — its RHS names its bracket
parameters —

    comptime IsTriviallyDeinitable[T: AnyType]: Bool = conforms_to(
        T, TrivialRegisterPassable
    ) or (...)

— so the importer's `from X import NAME` walk could not fold it at import time
and recorded nothing. In a generic body the name then lowered as an undeclared
identifier: a zero word, cast to a `MojoList *` and read (`mojo_list_get_int
(0, 0)`) as the condition of a RUNTIME branch. For `T = Int` the source's
condition is TRUE, so the emitted program was not the one the source describes
— a silent miscompile whose measured instance is `std/memory/memory.mojo`'s
`unsafe_destroy_n`.

The fix keeps the alias DECLARATION in the binding table (parser:
`ComptimeVarStmt.comptime_params`; importer + module prefold record the node)
and makes the evaluator substitute an application's arguments into its body
(`mojo/middle/comptime.py`'s ComptimeAlias handling). A builtin scalar is
known to conform to the compiler-synthesized `TrivialRegisterPassable` and the
traits it derives, which is what decides `IsTriviallyDeinitable[Int]`.

The second case is the same alias declared LOCALLY: the doc's measurement put
the root cause in the evaluator, not in the import path, so the fold must not
depend on the alias coming from another module.

Compile-only (no gcc, no link): `compile_module_to_c` is the per-module path
`build_stdlib_dylib` uses, and it emits the in-TU instantiation.
"""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

import build_stdlib_dylib as b

IMPORTED = '''\
from std.traits import IsTriviallyDeinitable

def maybe[T: AnyType](n: Int) -> Int:
    comptime if IsTriviallyDeinitable[T]:
        return 1
    else:
        return 2

def use(n: Int) -> Int:
    return maybe[Int](n)
'''

LOCAL = '''\
comptime is_deinitable[T: AnyType]: Bool = conforms_to(T, Deinitable)

def pick[T: AnyType](n: Int) -> Int:
    comptime if is_deinitable[T]:
        return 1
    else:
        return 2

def use(n: Int) -> Int:
    return pick[Int](n)
'''


def _compile(src: str) -> str:
    return b.compile_module_to_c(src, 'p.mojo', 'p', linkable=False)


def _body(c: str, name: str) -> str:
    """The emitted DEFINITION body of `name` (not its forward declaration)."""
    at = 0
    while True:
        i = c.find('int64_t ' + name + ' (', at)
        assert i >= 0, f'{name} has no definition in:\n{c}'
        j = c.find('{', i)
        k = c.find(';', i)
        if 0 <= j and (k < 0 or j < k):
            return c[i:c.find('\n}', j)]
        at = i + 1


def _check(c: str, alias: str, mangled: str) -> None:
    assert 'ct param or undeclared: ' + alias not in c, (
        f'{alias} still lowered as an undeclared name:\n{c}')
    body = _body(c, mangled)
    assert 'mojo_list_get_int' not in body, (
        f'{mangled} still reads the condition as a boxed list:\n{body}')
    assert 'if (' not in body, (
        f'{mangled} still branches at RUNTIME on the comptime condition:\n'
        f'{body}')
    assert '= 1LL' in body, (
        f'{mangled} does not contain the TRUE arm (the condition must fold to '
        f'True for T = Int):\n{body}')


def test_imported_generic_alias_folds():
    """The doc's exact repro: `from std.traits import IsTriviallyDeinitable`
    (a package `__init__` RE-EXPORT of a submodule's alias)."""
    c = _compile(IMPORTED)
    assert 'maybe_1_T_3_Int' in c, 'the in-TU instance was not emitted:\n' + c
    _check(c, 'IsTriviallyDeinitable', 'maybe_1_T_3_Int')


def test_local_generic_alias_folds():
    """The same alias declared locally: the defect is the evaluator, not the
    import path (the doc's own root-cause measurement)."""
    c = _compile(LOCAL)
    assert 'pick_1_T_3_Int' in c, 'the in-TU instance was not emitted:\n' + c
    _check(c, 'is_deinitable', 'pick_1_T_3_Int')


if __name__ == '__main__':
    test_imported_generic_alias_folds()
    print('PASS test_imported_generic_alias_folds')
    test_local_generic_alias_folds()
    print('PASS test_local_generic_alias_folds')
