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
comptime always_true[T: AnyType]: Bool = True

def pick[T: AnyType](n: Int) -> Int:
    comptime if is_deinitable[T]:
        return 1
    else:
        return 2

def always[T: AnyType](n: Int) -> Int:
    comptime if always_true[T]:
        return 1
    else:
        return 2

def use(n: Int) -> Int:
    return pick[Int](n) + always[Int](n)
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
    import path (the doc's own root-cause measurement). A generic alias whose
    body does not mention its parameter is still a template, and its
    application must fold too."""
    c = _compile(LOCAL)
    assert 'pick_1_T_3_Int' in c, 'the in-TU instance was not emitted:\n' + c
    _check(c, 'is_deinitable', 'pick_1_T_3_Int')
    assert 'always_1_T_3_Int' in c, 'the in-TU instance was not emitted:\n' + c
    _check(c, 'always_true', 'always_1_T_3_Int')


FOREIGN_STRUCT = '''\
from std.collections.string import String
from std.traits import IsTriviallyDeinitable

def maybe[T: AnyType](n: Int) -> Int:
    comptime if IsTriviallyDeinitable[T]:
        return 1
    else:
        return 2

def use(n: Int) -> Int:
    return maybe[String](n)
'''

MODULE_TRAIT_ON_SCALAR = '''\
trait Widget:
    pass

comptime is_widget[T: AnyType]: Bool = conforms_to(T, Widget)

def pick[T: AnyType](n: Int) -> Int:
    comptime if is_widget[T]:
        return 1
    else:
        return 2

def use(n: Int) -> Int:
    return pick[Int](n)
'''


def _check_false_arm(c: str, alias: str, mangled: str) -> None:
    """The alias folds to FALSE for this instance: no undeclared-name
    placeholder, no boxed-list read, no runtime branch, and the FALSE arm
    (`return 2`) is the one emitted."""
    assert 'ct param or undeclared: ' + alias not in c, (
        f'{alias} still lowered as an undeclared name:\n{c}')
    body = _body(c, mangled)
    assert 'mojo_list_get_int' not in body, (
        f'{mangled} still reads the condition as a boxed list:\n{body}')
    assert 'if (' not in body, (
        f'{mangled} still branches at RUNTIME on the comptime condition:\n'
        f'{body}')
    assert '= 2LL' in body, (
        f'{mangled} does not contain the FALSE arm (the condition must fold to '
        f'False for this argument):\n{body}')
    assert '= 1LL' not in body, (
        f'{mangled} contains the TRUE arm although the condition is False:\n'
        f'{body}')


def test_foreign_struct_conformance_folds():
    """`conforms_to(String, TrivialRegisterPassable)` must decide False.

    String is imported, so its declared bases exist only in its home module.
    The fold's bases map never held them (the single-TU path does not register
    imported structs' bases), and a trait no declared base names read as
    None, so `IsTriviallyDeinitable[String]` stayed CONST_UNKNOWN and became a
    runtime branch on a zero word. String declares no TrivialRegisterPassable
    and its complete base walk reaches none, so the answer is False.
    """
    c = _compile(FOREIGN_STRUCT)
    assert 'maybe_1_T_6_String' in c, 'the in-TU instance was not emitted:\n' + c
    _check_false_arm(c, 'IsTriviallyDeinitable', 'maybe_1_T_6_String')


def test_module_trait_on_builtin_scalar_folds_false():
    """`conforms_to(Int, Widget)` for a trait THIS module declares must be
    False: no builtin scalar conforms to a trait declared outside std. The
    answer was None, so the alias read CONST_UNKNOWN and was emitted as a
    runtime branch on a zero word, with the TRUE arm live."""
    c = _compile(MODULE_TRAIT_ON_SCALAR)
    assert 'pick_1_T_3_Int' in c, 'the in-TU instance was not emitted:\n' + c
    _check_false_arm(c, 'is_widget', 'pick_1_T_3_Int')


DOT_PREDICATE = '''def unsigned_f64() -> Int:
    comptime if .float64.is_unsigned():
        return 1
    else:
        return 2


def floating_bf16() -> Int:
    comptime if .bfloat16.is_floating_point():
        return 3
    else:
        return 4
'''


def _check_dot_predicate(c: str, name: str, want: int) -> None:
    """`name`'s comptime condition must FOLD: exactly the taken arm is emitted,
    no runtime `if (`, and the other arm's constant is absent."""
    body = _body(c, name)
    assert 'if (' not in body, (
        f'{name} still branches at RUNTIME on a comptime condition that is a '
        f'chained dot-value DType predicate:\n{body}')
    assert f'= {want}LL' in body, (
        f'{name} does not contain the arm the predicate selects:\n{body}')
    other = 2 if want == 1 else (4 if want == 3 else 1)
    assert f'= {other}LL' not in body, (
        f'{name} still contains the arm the predicate rejects (both arms were '
        f'emitted -- the condition read CONST_UNKNOWN):\n{body}')


def test_chained_dot_value_dtype_predicate_folds():
    """`.float64.is_unsigned()` must fold.

    The parser stores a chained dot-relative reference as ONE `DottedLiteral`
    whose `path` is the whole chain (`'float64.is_unsigned'`), not as
    `MemberExpr(DottedLiteral, 'is_unsigned')`. The DType-predicate branch in
    `eval_const_bool`/`_const_foldable` tested only the `MemberExpr` shape, so
    this shape read CONST_UNKNOWN, BOTH arms were emitted, and
    `std/utils/numerics.mojo`'s `max_finite[.float64]` put
    `~Scalar[.float64](0)` -- a bit-complement on a float dtype -- into the C,
    where GCC rejects it (`wrong type argument to bit-complement`). Measured:
    `max_finite[.float64]()` went from a skipped module to printing
    1.7976931348623157e+308.
    """
    c = _compile(DOT_PREDICATE)
    # `_compile` names the TU 'p', so a top-level def's symbol is p_<name>.
    _check_dot_predicate(c, 'p_unsigned_f64', 2)
    _check_dot_predicate(c, 'p_floating_bf16', 3)


if __name__ == '__main__':
    test_imported_generic_alias_folds()
    print('PASS test_imported_generic_alias_folds')
    test_local_generic_alias_folds()
    print('PASS test_local_generic_alias_folds')
    test_chained_dot_value_dtype_predicate_folds()
    print('PASS test_chained_dot_value_dtype_predicate_folds')
    test_foreign_struct_conformance_folds()
    print('PASS test_foreign_struct_conformance_folds')
    test_module_trait_on_builtin_scalar_folds_false()
    print('PASS test_module_trait_on_builtin_scalar_folds_false')
