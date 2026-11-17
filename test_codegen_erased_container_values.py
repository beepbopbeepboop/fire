#!/usr/bin/env python3
"""Per-part Done-when probes of the STILL-OPEN parts of
CODEGEN_simd_and_array_values_erase_to_int64.

Each `test_<prefix>_*` here is the Done-when test of an open part doc under
bugs/ and is RED until its part lands. This file is deliberately NOT a
registered gate job: a red probe belongs to its bug doc's command, not to the
green regression bucket. The landed parts' tests are in
test_codegen_erased_container_values_pins.py.

Open parts (2026-11-15 replan):

    python3 test_codegen_erased_container_values.py ctor_dtype_spelling
    python3 test_codegen_erased_container_values.py simd_value_across_return

`p1_alias`, `p2_alias_ctor` and `p3_comptime` below are landed (their docs were
deleted with their fixes) and stay green here until they are moved into the
registered pins file. A bare run executes every probe in this file.
"""

import re
import sys

from test_codegen_erased_container_values_pins import _compile, _defn


# part 1 (landed; doc deleted):
# a module-level `alias` of a type is expanded wherever an annotation is
# resolved -- a parameter, a return, an explicitly annotated local, and a
# container's element type.
P1_ALIAS_SRC = (
    'alias F2 = SIMD[DType.float32, 2]\n'
    'alias F = Float32\n'
    'alias I2 = SIMD[DType.int32, 2]\n'
    '\n'
    'def id_simd(x: F2) -> F2:\n'
    '    return x\n'
    '\n'
    'def use_it(x: F2):\n'
    '    var r = id_simd(x)\n'
    '    return r\n'
    '\n'
    'def use_local(x: F2):\n'
    '    var r: F2 = x\n'
    '    return r\n'
    '\n'
    'def gi(x: I2) -> I2:\n'
    '    return x\n'
    '\n'
    'def arr():\n'
    '    var a = Array[F, 4](fill=0.0)\n'
    '    return a[0]\n'
)


def test_p1_alias_expands_in_annotations():
    c = _compile(P1_ALIAS_SRC, 'p1_alias')
    assert 'indirect call via SubscriptExpr' not in c, c
    idbody = _defn(c, 'p1_alias_id_simd')
    idsig = idbody.splitlines()[1].strip()
    assert idsig.startswith('float ') and idsig.endswith('(float x)'), idbody
    assert re.search(r'^float \S+ \(float\);', c, re.M), c
    ubody = _defn(c, 'p1_alias_use_it')
    assert 'int64_t r;' not in ubody and 'float r;' in ubody, ubody
    lbody = _defn(c, 'p1_alias_use_local')
    assert 'int64_t r;' not in lbody and 'float r;' in lbody, lbody
    # An integer alias keeps today's int64_t lowering: expansion feeds the
    # existing dtype dispatch, it does not turn every alias into a float.
    gbody = _defn(c, 'p1_alias_gi')
    gsig = gbody.splitlines()[1].strip()
    assert gsig.startswith('int64_t ') and gsig.endswith('(int64_t x)'), gbody
    abody = _defn(c, 'p1_alias_arr')
    assert 'mojo_list_get_int' not in abody, abody
    assert 'mojo_list_get_double' in abody, abody


# part 2 (CODEGEN_simd_and_array_values_erase_to_int64, alias as constructor callee):
# a module-level `alias` naming a constructible type is expanded when it is
# the CALLEE of a constructor call (`F2(1.0)`, `A4(fill=0.0)`), not only in an
# annotation.
P2_ALIAS_CTOR_SRC = (
    'alias F2 = SIMD[DType.float32, 2]\n'
    'alias A4 = Array[Float32, 4]\n'
    'alias I2 = SIMD[DType.int32, 2]\n'
    '\n'
    'def mk_simd():\n'
    '    var v = F2(1.0)\n'
    '    return v\n'
    '\n'
    'def mk_int():\n'
    '    var v = I2(1)\n'
    '    return v\n'
    '\n'
    'def mk_arr():\n'
    '    var a = A4(fill=0.0)\n'
    '    return a[0]\n'
)


def test_p2_alias_ctor_expands_callee():
    c = _compile(P2_ALIAS_CTOR_SRC, 'p2_alias_ctor')
    assert 'indirect call via SubscriptExpr' not in c, c
    sbody = _defn(c, 'p2_alias_ctor_mk_simd')
    assert 'int64_t v;' not in sbody and 'float v;' in sbody, sbody
    # An integer alias stays on the integer ctor arm.
    ibody = _defn(c, 'p2_alias_ctor_mk_int')
    assert 'int64_t v;' in ibody, ibody
    abody = _defn(c, 'p2_alias_ctor_mk_arr')
    assert 'mojo_list_get_int' not in abody, abody
    assert 'mojo_list_append_double' in abody, abody
    assert 'mojo_list_get_double' in abody, abody


# part 3 (landed 2026-11-14, a0f321f1c):
# a `comptime` name bound to a float DType resolves in a module-scope
# signature, in a function-scope annotated local, and in the dtype argument
# of a SIMD constructor.
P3_COMPTIME_SRC = (
    'comptime dt = DType.float32\n'
    '\n'
    'def id_simd(x: SIMD[dt, 2]) -> SIMD[dt, 2]:\n'
    '    return x\n'
    '\n'
    'def use_it(x: SIMD[dt, 2]):\n'
    '    var r = id_simd(x)\n'
    '    return r\n'
    '\n'
    'def mk():\n'
    '    var v = SIMD[dt, 2](1.0)\n'
    '    return v\n'
    '\n'
    'def use_local(x: SIMD[DType.float32, 2]):\n'
    '    comptime d2 = DType.float32\n'
    '    var r: SIMD[d2, 2] = id_simd(x)\n'
    '    return r\n'
    '\n'
    'comptime dt64 = DType.float64\n'
    'def id64(x: SIMD[dt64, 2]) -> SIMD[dt64, 2]:\n'
    '    return x\n'
)


def test_p3_comptime_dtype_resolves_in_all_type_positions():
    c = _compile(P3_COMPTIME_SRC, 'p3_comptime')
    idbody = _defn(c, 'p3_comptime_id_simd')
    idsig = idbody.splitlines()[1].strip()
    assert idsig.startswith('float ') and idsig.endswith('(float x)'), idbody
    assert re.search(r'^float \S+ \(float\);', c, re.M), c
    ubody = _defn(c, 'p3_comptime_use_it')
    assert 'int64_t r;' not in ubody and 'float r;' in ubody, ubody
    mbody = _defn(c, 'p3_comptime_mk')
    assert 'int64_t v;' not in mbody and 'float v;' in mbody, mbody
    lbody = _defn(c, 'p3_comptime_use_local')
    assert 'int64_t r;' not in lbody and 'float r;' in lbody, lbody
    # float64 maps to double through the same dtype table.
    dbody = _defn(c, 'p3_comptime_id64')
    dsig = dbody.splitlines()[1].strip()
    assert dsig.startswith('double ') and dsig.endswith('(double x)'), dbody


# part 1 of the 2026-11-15 replan (doc: bugs/
# CODEGEN_simd_and_array_values_erase_to_int64-part1.md):
# a float SIMD/Scalar constructor whose dtype is written with the SCALAR TYPE
# NAME (`SIMD[Float32, 4]`, `Scalar[Float32]`) keeps that scalar C type, the
# same way the `DType.float32` / `.float32` / `float32` spellings already do.
CTOR_DTYPE_SPELLING_SRC = (
    'def f32():\n'
    '    var v = SIMD[Float32, 4](1.5)\n'
    '    return v\n'
    '\n'
    'def f64():\n'
    '    var w = SIMD[Float64, 2](2.5)\n'
    '    return w\n'
    '\n'
    'def sc():\n'
    '    var x = Scalar[Float32](0.5)\n'
    '    return x\n'
    '\n'
    'def i32():\n'
    '    var i = SIMD[Int32, 4](1)\n'
    '    return i\n'
)


def test_ctor_dtype_spelling_simd_scalar_name_keeps_float_ctype():
    c = _compile(CTOR_DTYPE_SPELLING_SRC, 'ctor_dtype_spelling')
    assert 'indirect call via SubscriptExpr' not in c, c
    for fn, decl in (('f32', 'float v;'), ('f64', 'double w;'),
                     ('sc', 'float x;')):
        body = _defn(c, 'ctor_dtype_spelling_' + fn)
        assert decl in body, (fn, body)
        assert 'int64_t ' + decl.split()[1] not in body, (fn, body)
    # An integer dtype keeps today's int64_t lowering: the fix widens the
    # dtype SPELLINGS the constructor arm recognizes, it does not turn every
    # SIMD value into a float.
    ibody = _defn(c, 'ctor_dtype_spelling_i32')
    assert 'int64_t i;' in ibody, ibody


# part 3 of the 2026-11-15 replan (doc: bugs/


# part 3 of the 2026-11-15 replan (doc: bugs/
# CODEGEN_simd_and_array_values_erase_to_int64-part3.md):
# an unannotated function whose return value is a local bound to a float SIMD
# constructor keeps the float's scalar C type (a SIMD value is scalar-erased,
# so `float` IS the value's type). The body's local is already float; only the
# inferred SIGNATURE erases it to int64_t today.
SIMD_VALUE_RETURN_SRC = (
    'def mk32():\n'
    '    var v = SIMD[DType.float32, 4](1.5)\n'
    '    return v\n'
    '\n'
    'def mk64():\n'
    '    var w = SIMD[DType.float64, 2](2.5)\n'
    '    return w\n'
    '\n'
    'def mi():\n'
    '    var i = SIMD[DType.int32, 4](1)\n'
    '    return i\n'
    '\n'
    'def use():\n'
    '    var a = mk32()\n'
    '    return a\n'
)


def test_simd_value_across_return_keeps_float_ctype():
    c = _compile(SIMD_VALUE_RETURN_SRC, 'simd_value_return')
    b32 = _defn(c, 'simd_value_return_mk32')
    assert b32.splitlines()[1].strip().startswith('float '), b32
    b64 = _defn(c, 'simd_value_return_mk64')
    assert b64.splitlines()[1].strip().startswith('double '), b64
    # The caller's local inherits the same answer.
    ubody = _defn(c, 'simd_value_return_use')
    assert 'float a;' in ubody, ubody
    assert 'int64_t a;' not in ubody, ubody
    # An integer SIMD value keeps the int64_t word.
    ibody = _defn(c, 'simd_value_return_mi')
    assert ibody.splitlines()[1].strip().startswith('int64_t '), ibody


if __name__ == '__main__':
    part = sys.argv[1] if len(sys.argv) > 1 else ''
    prefix = 'test_%s_' % part if part else 'test_'
    names = sorted(n for n, f in list(globals().items())
                   if n.startswith(prefix) and callable(f))
    if not names:
        sys.exit('no test named with prefix %r' % prefix)
    for name in names:
        globals()[name]()
        print('ok', name)
    print('all tests passed')
