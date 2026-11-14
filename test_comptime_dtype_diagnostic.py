#!/usr/bin/env python3
"""Regression test: DType predicate evaluation in comptime diagnostics.

Comptime validation must (previously missing for DType predicates)
catch provably-false conditions involving DType predicates such as
`dtype.is_integral()`. The comptime evaluator now folds DType member access
(`DType.int32`) and DType predicate methods, so `comptime assert` and
`constrained` reject provably-false DType conditions instead of silently
accepting them.
"""

from gimple_codegen import compile_to_gimple


def _compile(src, filename='t.mojo'):
    return compile_to_gimple(src, do_imports=False, filename=filename)


def test_comptime_assert_dtype_is_integral_false():
    try:
        _compile('fn f():\n    comptime assert DType.float32.is_integral(), "nope"\n')
    except RuntimeError as e:
        assert 'comptime assertion failed' in str(e), e
        assert 'nope' in str(e), e
        return
    raise AssertionError('provably-false DType.is_integral() comptime assert compiled')


def test_comptime_assert_dtype_is_integral_true():
    _compile('fn f():\n    comptime assert DType.int32.is_integral(), "ok"\n')


def test_comptime_assert_dtype_is_floating_point_false():
    try:
        _compile('fn f():\n    comptime assert DType.int64.is_floating_point(), "fp"\n')
    except RuntimeError as e:
        assert 'comptime assertion failed' in str(e), e
        return
    raise AssertionError('provably-false DType.is_floating_point() compiled')


def test_comptime_assert_dtype_is_floating_point_true():
    _compile('fn f():\n    comptime assert DType.float64.is_floating_point(), "ok"\n')


def test_comptime_assert_dtype_signedness():
    try:
        _compile('fn f():\n    comptime assert DType.uint8.is_signed(), "signed"\n')
    except RuntimeError as e:
        assert 'comptime assertion failed' in str(e), e
        return
    raise AssertionError('provably-false DType.is_signed() compiled')


def test_constrained_dtype_predicate_false():
    try:
        _compile('fn f():\n    constrained[DType.float32.is_integral(), "nope"]()\n')
    except RuntimeError as e:
        assert 'constraint failed' in str(e), e
        assert 'nope' in str(e), e
        return
    raise AssertionError('provably-false constrained DType predicate compiled')


def test_constrained_dtype_predicate_true():
    _compile('fn f():\n    constrained[DType.int32.is_integral(), "ok"]()\n')


def _compile_full(src):
    """Compile a self-contained module through the path that elaborates generic
    instantiations (do_imports=True + a temp filename), so compile-time
    diagnostics inside elaborated generic struct bodies are exercised."""
    import os
    import tempfile
    tmpdir = os.environ.get('TMPDIR', '.tmp')
    os.makedirs(tmpdir, exist_ok=True)
    with tempfile.NamedTemporaryFile(suffix='.mojo', dir=tmpdir,
                                     delete=False, mode='w') as f:
        f.write(src)
        fn = f.name
    try:
        return compile_to_gimple(src, do_imports=True, filename=fn)
    finally:
        try:
            os.unlink(fn)
        except OSError:
            pass


def test_generic_struct_constrained_dtype_param_false():
    # DType predicate on an instantiated struct comptime param: the elaborated
    # struct body must diagnose, not silently accept
    # Regression for the case
    # where elaboration swallows compile-time diagnostics from instantiated
    # generic struct bodies.
    src = '''
struct DTypeDiagCF[dtype: DType]:
    fn check(self):
        constrained[dtype.is_integral(), "bad"]()

fn main():
    var f = DTypeDiagCF[DType.bfloat16]()
    f.check()
'''
    try:
        _compile_full(src)
    except RuntimeError as e:
        assert 'constraint failed' in str(e), e
        assert 'bad' in str(e), e
        return
    raise AssertionError('instantiated generic struct constrained(dtype predicate) compiled')


def test_generic_struct_comptime_assert_dtype_param_false():
    # comptime assert with a DType predicate on an instantiated struct param.
    # `constrained[True]()` follows to ensure the generic struct takes the
    # elaboration path that must propagate compile-time diagnostics.
    src = '''
struct DTypeDiagAF2[dtype: DType]:
    fn check(self):
        comptime assert dtype.is_floating_point(), "fp"
        constrained[True]()

fn main():
    var f = DTypeDiagAF2[DType.uint32]()
    f.check()
'''
    try:
        _compile_full(src)
    except RuntimeError as e:
        assert 'comptime assertion failed' in str(e), e
        assert 'fp' in str(e), e
        return
    raise AssertionError('instantiated generic struct comptime assert(dtype predicate) compiled')


def test_generic_struct_constrained_dtype_param_true():
    src = '''
struct DTypeDiagCT[dtype: DType]:
    fn check(self):
        constrained[dtype.is_integral(), "ok"]()

fn main():
    var f = DTypeDiagCT[DType.int16]()
    f.check()
'''
    _compile_full(src)


def test_generic_struct_comptime_assert_dtype_param_only_stmt():
    # A comptime assert with a DType predicate on an instantiated struct
    # param, as the method's ONLY statement. Regression for a tokenizer bug
    # where a line ending in a string literal (`assert ..., "fp"`) left
    # prev_ended_string set across a blank line, suppressing the DEDENTs
    # before the following top-level `fn main` and swallowing the
    # instantiation site — so elaboration never ran and the provably-false
    # diagnostic was silently accepted
    # (comptime validation diagnostics for DType predicates).
    src = '''
struct DTypeDiagAS[dtype: DType]:
    fn check(self):
        comptime assert dtype.is_floating_point(), "fp"

fn main():
    var f = DTypeDiagAS[DType.uint32]()
    f.check()
'''
    try:
        _compile_full(src)
    except RuntimeError as e:
        assert 'comptime assertion failed' in str(e), e
        assert 'fp' in str(e), e
        return
    raise AssertionError(
        'instantiated generic struct comptime assert(dtype predicate, only stmt) compiled')


def test_comptime_scalar_type_name_is_a_dtype_value():
    # Monomorphization substitutes a `dtype: DType` argument TEXTUALLY, so a
    # call that supplies the scalar type (`isinf[Float32, 1]`, or the inferred
    # `isinf(x)` with `x: Float32`) instantiates a body containing
    # `Float32.is_floating_point()` and `Float32 == .float32`. Those are DType
    # VALUES in Mojo terms and must fold: otherwise a `comptime if` over them is
    # emitted as a runtime branch with every arm, including arms only correct
    # for another dtype. `DType.float32 == .float32` is the same fold and
    # covers the dotted value's own spelling (its field is `path`, not `name`).
    _compile('fn f():\n    comptime assert Float32.is_floating_point(), "ok"\n')
    _compile('fn f():\n    comptime assert Float32 == .float32, "ok"\n')
    _compile('fn f():\n    comptime assert DType.float32 == .float32, "ok"\n')
    _compile('fn f():\n    comptime assert Float32 not in (DType.float8_e5m2, DType.float8_e4m3fn), "ok"\n')
    try:
        _compile('fn f():\n    comptime assert Float32 == .float64, "nope"\n')
    except RuntimeError as e:
        assert 'comptime assertion failed' in str(e), e
        assert 'nope' in str(e), e
    else:
        raise AssertionError('Float32 == .float64 folded true')


def test_generic_dtype_comptime_if_prunes_other_dtypes_arm():
    # Regression for the stdlib-dylib gate: std/utils/numerics.mojo's
    # isnan/isinf dispatch on `dtype` with a first arm for the float8 formats
    # that calls `val.to_bits()`. The inferred instantiation for a float
    # scalar substitutes the TYPE spelling (`Float32`/`Float64`); while the
    # guard stayed unfoldable, the float8 arm was emitted anyway and, once a
    # float SIMD parameter keeps its scalar C type, `val.to_bits() & 0x7F`
    # became `float & float` in the generated C (gcc: "invalid operands to
    # binary &"). Folding the guard prunes every inapplicable arm, so the
    # instantiation contains no `to_bits` at all.
    src = '''
def dtype_arm_probe[dtype: DType, width: SIMDLength](
    val: SIMD[dtype, width]
) -> SIMD[.bool, width]:
    comptime if not dtype.is_floating_point() or dtype in (
        DType.float8_e4m3fnuz,
        DType.float8_e5m2fnuz,
        DType.float4_e2m1fn,
    ):
        return SIMD[.bool, width](fill=False)
    elif dtype == .float8_e4m3fn:
        return (val.to_bits() & 0x7F).eq(0x7F)
    elif dtype == .float8_e5m2:
        return (val.to_bits() & 0x7F).gt(0x7C)
    elif dtype == .float16:
        var bits = val.to_bits()
        return (bits & 0x7C00).eq(0x7C00) & (bits & 0x03FF).ne(0)
    return SIMD[.bool, width](fill=False)

def probe32(x: Float32) -> Bool:
    return dtype_arm_probe(x)

def probe64(x: Float64) -> Bool:
    return dtype_arm_probe(x)
'''
    c = _compile_full(src)
    assert 'to_bits' not in c, c
    assert 'dtype_arm_probe_5_dtype_7_Float32_5_width_1_1 (float)' in c, c
    assert 'dtype_arm_probe_5_dtype_7_Float64_5_width_1_1 (double)' in c, c


if __name__ == '__main__':
    test_comptime_assert_dtype_is_integral_false()
    test_comptime_assert_dtype_is_integral_true()
    test_comptime_assert_dtype_is_floating_point_false()
    test_comptime_assert_dtype_is_floating_point_true()
    test_comptime_assert_dtype_signedness()
    test_constrained_dtype_predicate_false()
    test_constrained_dtype_predicate_true()
    test_generic_struct_constrained_dtype_param_false()
    test_generic_struct_comptime_assert_dtype_param_false()
    test_generic_struct_constrained_dtype_param_true()
    test_generic_struct_comptime_assert_dtype_param_only_stmt()
    test_comptime_scalar_type_name_is_a_dtype_value()
    test_generic_dtype_comptime_if_prunes_other_dtypes_arm()
    print('ok')
