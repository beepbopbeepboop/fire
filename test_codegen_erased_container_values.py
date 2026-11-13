#!/usr/bin/env python3
"""Per-part Done-when probes of the STILL-OPEN parts of
CODEGEN_simd_and_array_values_erase_to_int64.

Each `test_<prefix>_*` here is the Done-when test of an open bug doc under
bugs/mid/ and is RED until its part lands. This file is deliberately NOT a
registered gate job: a red probe belongs to its bug doc's command, not to the
green regression bucket. The landed parts' tests are in
test_codegen_erased_container_values_pins.py.

Run one probe:  python3 test_codegen_erased_container_values.py p4_alias
                python3 test_codegen_erased_container_values.py p4_comptime
                python3 test_codegen_erased_container_values.py part5
A bare run executes every open probe and is red until they all land.
"""

import re
import sys

import gimple_codegen as g

from test_codegen_erased_container_values_pins import _compile, _defn


# part4 replan parts 2 and 3 (see bugs/mid/CODEGEN_simd_and_array_values_
# erase_to_int64-part4-part2.md / -part3.md). Their prefixes deliberately do
# NOT start with `part4_`: the landed part4 pins (in the pins file) run every
# `test_part4_*` under the `part4` prefix, so an open sub-part must not be
# reachable through that prefix.
#
# part 2: a module-level `alias` of a float SIMD type is expanded, so the
# parameter, the return and the call-result local keep the scalar C type.
P4_ALIAS_SRC = (
    'alias F2 = SIMD[DType.float32, 2]\n'
    '\n'
    'def id_simd(x: F2) -> F2:\n'
    '    return x\n'
    '\n'
    'def use_it(x: F2):\n'
    '    var r = id_simd(x)\n'
    '    return r\n'
)


def test_p4_alias_simd_param_return_keep_ctype():
    c = _compile(P4_ALIAS_SRC, 'p4_alias')
    assert 'indirect call via SubscriptExpr' not in c, c
    idbody = _defn(c, 'p4_alias_id_simd')
    idsig = idbody.splitlines()[1].strip()
    assert idsig.startswith('float ') and idsig.endswith('(float x)'), idbody
    assert re.search(r'^float \S+ \(float\);', c, re.M), c
    ubody = _defn(c, 'p4_alias_use_it')
    assert 'int64_t r;' not in ubody, ubody
    assert 'float r;' in ubody, ubody


# part 3: a `comptime` name bound to a float DType is resolved before the
# annotation reaches `_mojo_type`, both at module scope (a signature) and in a
# function body (an explicitly annotated local).
P4_COMPTIME_TOP_SRC = (
    'comptime dt = DType.float32\n'
    '\n'
    'def id_simd(x: SIMD[dt, 2]) -> SIMD[dt, 2]:\n'
    '    return x\n'
    '\n'
    'def use_it(x: SIMD[dt, 2]):\n'
    '    var r = id_simd(x)\n'
    '    return r\n'
)
P4_COMPTIME_LOCAL_SRC = (
    'def id_simd(x: SIMD[DType.float32, 2]) -> SIMD[DType.float32, 2]:\n'
    '    return x\n'
    '\n'
    'def use_it(x: SIMD[DType.float32, 2]):\n'
    '    comptime dt = DType.float32\n'
    '    var r: SIMD[dt, 2] = id_simd(x)\n'
    '    return r\n'
)


def test_p4_comptime_dtype_keeps_ctype():
    c = _compile(P4_COMPTIME_TOP_SRC, 'p4_ct_top')
    assert 'indirect call via SubscriptExpr' not in c, c
    idbody = _defn(c, 'p4_ct_top_id_simd')
    idsig = idbody.splitlines()[1].strip()
    assert idsig.startswith('float ') and idsig.endswith('(float x)'), idbody
    ubody = _defn(c, 'p4_ct_top_use_it')
    assert 'int64_t r;' not in ubody, ubody
    assert 'float r;' in ubody, ubody
    lc = _compile(P4_COMPTIME_LOCAL_SRC, 'p4_ct_loc')
    lbody = _defn(lc, 'p4_ct_loc_use_it')
    assert 'int64_t r;' not in lbody, lbody
    assert 'float r;' in lbody, lbody


# part5: Scalar[X] / SIMD[X, 1] resolve to the scalar C type of X.
def test_part5_scalar_annotation_resolves_to_scalar_ctype():
    gen = g.GimpleGen()
    expect = {
        'Float32': 'float',
        'Float64': 'double',
        'Scalar[Float32]': 'float',
        'SIMD[Float32, 1]': 'float',
        'Scalar[DType.float32]': 'float',
        'Scalar[Float64]': 'double',
        'Scalar[DType.float64]': 'double',
    }
    bad = {a: (gen._resolve_type(a), want) for a, want in expect.items()
           if gen._resolve_type(a) != want}
    assert not bad, 'annotation -> (got, want): %r' % (bad,)

    # A comptime local `dt` bound to a float dtype must resolve through the
    # comptime binding, not stay erased to int64_t.
    gen._comptime_vals['dt32'] = 'DType.float32'
    gen._comptime_vals['dt64'] = 'DType.float64'
    expect_ct = {
        'Scalar[dt32]': 'float',
        'SIMD[dt32, 1]': 'float',
        'Scalar[dt64]': 'double',
        'SIMD[dt64, 1]': 'double',
    }
    bad = {a: (gen._resolve_type(a), want) for a, want in expect_ct.items()
           if gen._resolve_type(a) != want}
    assert not bad, 'comptime annotation -> (got, want): %r' % (bad,)


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
