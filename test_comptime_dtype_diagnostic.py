#!/usr/bin/env python3
"""Regression test: DType predicate evaluation in comptime diagnostics.

`bugs/DIAGNOSTICS_missing_validation_modular.md`: comptime validation must
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
    # (bugs/DIAGNOSTICS_missing_validation_modular.md). Regression for the case
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
    print('ok')
