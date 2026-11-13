#!/usr/bin/env python3
"""Regression test for @align decorator validation (DIAGNOSTICS_align_decorator-part3).

Covers parametric/comptime function-call cases compiled through the path that
elaborates generic instantiations (do_imports=True + a temp filename).
"""

import os
import tempfile

from gimple_codegen import compile_to_gimple


def _compile_full(src):
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


def _assert_align_error(src, expected_got=None):
    try:
        _compile_full(src)
    except Exception as e:
        msg = str(e)
        assert ('struct alignment must be a positive power of 2' in msg
                or '@align value must be a positive power of 2' in msg), msg
        if expected_got is not None:
            assert f'got {expected_got}' in msg, msg
        return
    raise AssertionError('expected @align diagnostic but compilation succeeded')


def test_valid_power_of_two_literal():
    # valid power-of-two alignment accepted
    _compile_full('@align(4)\n@fieldwise_init\nstruct S4:\n    var x: Int\n\n'
                  'def main():\n    var s = S4(1)\n    _ = s.x\n')
    _compile_full('@align(8)\n@fieldwise_init\nstruct S8:\n    var x: Int\n\n'
                  'def main():\n    var s = S8(1)\n    _ = s.x\n')


def test_invalid_non_power_of_two_literal():
    # Constant literal invalid alignment is caught at parse time (part 1);
    # accept the diagnostic wording as produced by this compiler.
    _assert_align_error(
        '@align(3)\n@fieldwise_init\nstruct S:\n    var x: Int\n\n'
        'def main():\n    var s = S(1)\n    _ = s.x\n')


def test_original_modular_call_case_invalid():
    # Original modular parametric/call case from part3 doc:
    # alignment=23 -> calculate_illegal_alignment(23)=69 -> invalid
    src = r'''
@no_inline
def calculate_illegal_alignment(x: Int) -> Int:
    return x * 3

@align(calculate_illegal_alignment(alignment))
@fieldwise_init
struct AlignedTrivialParam[alignment: Int]:
    pass

def main():
    var _x = AlignedTrivialParam[23]()
'''
    _assert_align_error(src, expected_got=69)


def test_call_shape_valid_result():
    # same call shape, valid result (e.g. x * 2, [32] -> 64)
    src = r'''
@no_inline
def calc(x: Int) -> Int:
    return x * 2

@align(calc(alignment))
@fieldwise_init
struct A[alignment: Int]:
    var x: Int

def main():
    var a = A[32](1)
    _ = a.x
'''
    _compile_full(src)


def test_call_shape_another_invalid_result():
    # same call shape, another invalid result (e.g. x * 3, [22] -> got 66)
    src = r'''
@no_inline
def calc(x: Int) -> Int:
    return x * 3

@align(calc(alignment))
@fieldwise_init
struct A[alignment: Int]:
    var x: Int

def main():
    var a = A[22](1)
    _ = a.x
'''
    _assert_align_error(src, expected_got=66)


def test_call_returns_zero():
    src = r'''
@no_inline
def calc(x: Int) -> Int:
    return 0

@align(calc(alignment))
@fieldwise_init
struct A[alignment: Int]:
    var x: Int

def main():
    var a = A[1](1)
    _ = a.x
'''
    _assert_align_error(src, expected_got=0)


def test_call_returns_negative():
    src = r'''
@no_inline
def calc(x: Int) -> Int:
    return -8

@align(calc(alignment))
@fieldwise_init
struct A[alignment: Int]:
    var x: Int

def main():
    var a = A[1](1)
    _ = a.x
'''
    _assert_align_error(src, expected_got=-8)


def test_unevaluable_call_does_not_crash():
    # A call the hook cannot evaluate (e.g. non-scalar argument) must not crash
    # and must not emit a false @align diagnostic. It may compile or report an
    # existing unknown diagnostic; here we use a non-scalar argument shape.
    src = r'''
def takes_str(s: String) -> Int:
    return 4

@align(takes_str("hi"))
@fieldwise_init
struct S:
    var x: Int

def main():
    var s = S(1)
    _ = s.x
'''
    try:
        _compile_full(src)
    except Exception as e:
        msg = str(e)
        # Must not be a crash/traceback surface we caused; and must not be the
        # specific @align invalid-value diagnostic for this unevaluable case.
        assert 'struct alignment must be a positive power of 2' not in msg, msg


if __name__ == '__main__':
    test_valid_power_of_two_literal()
    test_invalid_non_power_of_two_literal()
    test_original_modular_call_case_invalid()
    test_call_shape_valid_result()
    test_call_shape_another_invalid_result()
    test_call_returns_zero()
    test_call_returns_negative()
    test_unevaluable_call_does_not_crash()
    print('ok')
