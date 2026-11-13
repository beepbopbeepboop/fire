#!/usr/bin/env python3
"""Per-part quick tests for CODEGEN_simd_and_array_values_erase_to_int64.

Each `test_partN_*` function is the Done-when test of bugs/mid/
CODEGEN_simd_and_array_values_erase_to_int64-partN.md. They assert on the C of
one generated function body, not on the whole module: the module header
already contains `double` and `float` (`extern double copysign`), so a
whole-module substring check passes whether or not the part is fixed.

Run one part:      python3 test_codegen_erased_container_values.py part1
Run every part:    python3 test_codegen_erased_container_values.py
Run a nested part: python3 test_codegen_erased_container_values.py part4_part1
                   (the argument is the prefix after `test_`, so a replan's
                   sub-part tests run under their own prefix)

A `test_partN_*` function is RED until part N lands. The `*_unchanged`
functions pin behaviour that must not regress and are GREEN today.
"""

import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

import build_stdlib_dylib as b
import gimple_codegen as g


def _compile(src, name):
    return b.compile_module_to_c(src, name + '.mojo', name, linkable=False)


def _body(c, fn):
    """The text of the generated `<fn> (void)` definition, and nothing else."""
    m = re.search(r'\n[^\n]*\b' + re.escape(fn) + r' \(void\)\s*\n\{.*?\n\}',
                  c, re.S)
    assert m is not None, 'no generated definition of %s' % fn
    return m.group(0)


def _defn(c, prefix):
    """The text of the generated definition of the function whose C name
    starts with `prefix`, and nothing else. The mangled suffix after the
    name hashes the parameter types, so it changes with the fix and cannot
    be pinned. The parameter list is matched on one line without a `;`, so
    the forward declaration (which ends `;`) can never be the anchor."""
    m = re.search(r'\n[^\n]*\b' + re.escape(prefix) + r'\w* \([^\n;]*\)\s*\n\{.*?\n\}',
                  c, re.S)
    assert m is not None, 'no generated definition of %s*' % prefix
    return m.group(0)


ARRAY_SRC = 'def f():\n    var a = Array[Float32, 4](fill=0.0)\n    print(a[0])\n'
SPAN_SRC = ('def f():\n    var a = Array[Float32, 4](fill=0.0)\n'
            '    var s = Span(a)\n    print(s[0])\n')
LIST_SRC = 'def f():\n    var l = List[Int]()\n    l.append(1)\n    print(l[0])\n'
SIMD_CTOR_SRC = 'def f():\n    var v = SIMD[DType.float32, 2](1.0)\n    return v\n'
SIMD_ARG_SRC = (
    'def id_simd(x: SIMD[DType.float32, 2]) -> SIMD[DType.float32, 2]:\n'
    '    return x\n'
    '\n'
    'def f():\n'
    '    var v = SIMD[DType.float32, 2](1.0)\n'
    '    var r = id_simd(v)\n'
    '    return r\n'
)
# No SIMD constructor in this source: every type comes from a PARAMETER or
# RETURN annotation, so the part4-part1 result is independent of part 3
# (the constructor, which another worker carries).
SIMD_SIG_SRC = (
    'def id_simd(x: SIMD[DType.float32, 2]) -> SIMD[DType.float32, 2]:\n'
    '    return x\n'
    '\n'
    'def use_it(x: SIMD[DType.float32, 2]):\n'
    '    var r = id_simd(x)\n'
    '    return r\n'
)
SIMD_INT_SIG_SRC = (
    'def gi(x: SIMD[DType.int32, 2]) -> SIMD[DType.int32, 2]:\n'
    '    return x\n'
)


# part1: Array[T, N](...) is a real container with a tracked element type.
def test_part1_array_ctor_is_tracked():
    body = _body(_compile(ARRAY_SRC, 'array'), 'array_f')
    assert 'indirect call via SubscriptExpr' not in body, body
    assert 'mojo_list_get_int' not in body, body


def test_part1_list_ctor_unchanged():
    # The List[Int] construction and element read that work today, pinned so
    # the Array fix cannot change them: inline storage, typed int append/get.
    body = _body(_compile(LIST_SRC, 'lst'), 'lst_f')
    assert 'mojo_list_init (&_owned_storage1_l)' in body, body
    assert 'mojo_list_append_int (l, _t2)' in body, body
    assert 'mojo_list_get_int (l, _t4)' in body, body


# part2: Span(<tracked container>) inherits the element type.
def test_part2_span_over_array_inherits_element_type():
    body = _body(_compile(SPAN_SRC, 'span'), 'span_f')
    assert '_mojo_at_char' not in body, body


# part3: float SIMD constructors keep their scalar dtype.
def test_part3_float_simd_ctor_keeps_dtype():
    body = _body(_compile(SIMD_CTOR_SRC, 'simd_ctor'), 'simd_ctor_f')
    assert 'indirect call via SubscriptExpr' not in body, body
    assert 'int64_t v;' not in body, body


SIMD_LANE_READ_SRC = (
    'def f():\n'
    '    var v = SIMD[DType.float64, 2](2.5)\n'
    '    return v[1]\n'
)
SIMD_LANE_WRITE_SRC = (
    'def f():\n'
    '    var v = SIMD[DType.float32, 4]()\n'
    '    v[2] = 1.5\n'
    '    return v[2]\n'
)


def test_part3_erased_simd_lane_access_uses_the_value():
    # `mlir.py` states the model: every SIMD[dtype, N] value is scalar-erased
    # (width 1 IS the scalar; wider lanes are not stored). A lane of the erased
    # value is therefore the value itself, and a scalar C type has no other
    # legal Mojo subscript. Before 2026-11-12 the lane read emitted
    # `_mojo_at_int64_t (double_value, i)` and the write emitted `v[2] = 1.5;`,
    # both invalid C once a float SIMD constructor started producing its scalar
    # C type, which is how test_simd/test_math failed to compile.
    body = _body(_compile(SIMD_LANE_READ_SRC, 'simd_lane_read'), 'simd_lane_read_f')
    assert '_mojo_at_' not in body, body
    wbody = _body(_compile(SIMD_LANE_WRITE_SRC, 'simd_lane_write'), 'simd_lane_write_f')
    assert '_mojo_at_' not in wbody, wbody
    assert 'v[' not in wbody, wbody
    assert 'v = ' in wbody, wbody


# part4: a float SIMD value keeps its type through a call and a return.
def test_part4_float_simd_survives_call_and_return():
    body = _body(_compile(SIMD_ARG_SRC, 'simd_arg'), 'simd_arg_f')
    assert 'indirect call via SubscriptExpr' not in body, body
    assert 'int64_t r;' not in body, body


# part4-part1 (replan of part4, see bugs/mid/CODEGEN_simd_and_array_values_
# erase_to_int64-part4-part1.md): a SIMD[<float dtype>, N] parameter and
# return keep the scalar C type, and the call-result local inherits it.
def test_part4_part1_simd_param_return_keep_ctype():
    c = _compile(SIMD_SIG_SRC, 'simd_sig')
    assert 'indirect call via SubscriptExpr' not in c, c
    idbody = _defn(c, 'simd_sig_id_simd')
    idsig = idbody.splitlines()[1].strip()
    assert idsig.startswith('float ') and idsig.endswith('(float x)'), idbody
    assert re.search(r'^float \S+ \(float\);', c, re.M), c
    ubody = _defn(c, 'simd_sig_use_it')
    assert 'int64_t r;' not in ubody, ubody
    assert 'float r;' in ubody, ubody


def test_part4_part1_int_simd_unchanged():
    # The float-dtype arm must dispatch on a FLOAT dtype: an integer SIMD
    # spelling keeps its current int64_t lowering.
    c = _compile(SIMD_INT_SIG_SRC, 'simd_sig')
    idbody = _defn(c, 'simd_sig_gi')
    idsig = idbody.splitlines()[1].strip()
    assert idsig.startswith('int64_t ') and idsig.endswith('(int64_t x)'), idbody


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
