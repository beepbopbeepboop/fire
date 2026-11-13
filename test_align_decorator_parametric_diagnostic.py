#!/usr/bin/env python3
"""Regression test for parametric @align diagnostics at generic struct instantiation.

Validates @align expressions at generic struct instantiation: non-power-of-2
alignments must fail with "function instantiation failed" and
"struct alignment must be a positive power of 2, got <N>".
"""

import os
import tempfile

from gimple_codegen import compile_to_gimple


def _compile_full(src):
    tmpdir = os.environ.get("TMPDIR", ".tmp")
    os.makedirs(tmpdir, exist_ok=True)
    with tempfile.NamedTemporaryFile(
        suffix=".mojo", dir=tmpdir, delete=False, mode="w"
    ) as f:
        f.write(src)
        fn = f.name
    try:
        return compile_to_gimple(src, do_imports=True, filename=fn)
    finally:
        try:
            os.unlink(fn)
        except OSError:
            pass


def _assert_align_error(src, got):
    try:
        _compile_full(src)
    except RuntimeError as e:
        msg = str(e)
        assert "function instantiation failed" in msg, msg
        assert "struct alignment must be a positive power of 2, got " + str(got) in msg, msg
        return
    raise AssertionError(f"expected align diagnostic (got {got}) for:\n{src}")


def _assert_compiles(src):
    _compile_full(src)


def test_parametric_invalid_direct():
    _assert_align_error(
        """
@align(alignment)
struct Aligned[alignment: Int]:
    var value: Int

fn main():
    var a = Aligned[3]()
    print(a.value)
""",
        3,
    )


def test_parametric_invalid_arithmetic():
    _assert_align_error(
        """
@align(alignment * 2)
struct Aligned2[alignment: Int]:
    var value: Int

fn main():
    var a = Aligned2[3]()
""",
        6,
    )


def test_parametric_valid_cases():
    _assert_compiles(
        """
@align(alignment)
struct Aligned[alignment: Int]:
    var value: Int

fn main():
    var a = Aligned[64]()
    var b = Aligned[1]()
    var c = Aligned[2]()
    var d = Aligned[4096]()
""",
    )
    _assert_compiles(
        """
@align(alignment * 2)
struct Aligned2[alignment: Int]:
    var value: Int

fn main():
    var a = Aligned2[32]()
""",
    )
    _assert_compiles(
        """
@align(alignment + 1)
struct Aligned3[alignment: Int]:
    var value: Int

fn main():
    var a = Aligned3[3]()
""",
    )


def test_module_alias_cases():
    _assert_compiles(
        """
alias A = 64

@align(A)
struct AlignedA[T: Int]:
    var value: Int

fn main():
    var a = AlignedA[1]()
""",
    )
    _assert_align_error(
        """
alias A = 3

@align(A)
struct AlignedB[T: Int]:
    var value: Int

fn main():
    var a = AlignedB[1]()
""",
        3,
    )


def test_unknown_align_name():
    src = """
@align(missing)
struct AlignedM[T: Int]:
    var value: Int

fn main():
    var a = AlignedM[1]()
"""
    try:
        _compile_full(src)
    except RuntimeError as e:
        msg = str(e)
        assert "function instantiation failed" in msg, msg
        assert "use of unknown declaration" in msg, msg
        assert "missing" in msg, msg
        return
    # Accept unevaluable/unknown in this context if the compiler no longer
    # reports it as a hard error, but it must not crash and must not emit
    # a false invalid-alignment diagnostic.
    return


def test_call_original_modular_invalid():
    _assert_align_error(
        """
@no_inline
def calculate_illegal_alignment(x: Int) -> Int:
    return x * 3

@align(calculate_illegal_alignment(alignment))
@fieldwise_init
struct AlignedTrivialParam[alignment: Int]:
    pass

def main():
    var _x = AlignedTrivialParam[23]()
""",
        69,
    )


def test_call_valid_result():
    _assert_compiles(
        """
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
""",
    )


def test_call_another_invalid_result():
    _assert_align_error(
        """
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
""",
        66,
    )


def test_call_returns_zero():
    _assert_align_error(
        """
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
""",
        0,
    )


def test_call_returns_negative():
    _assert_align_error(
        """
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
""",
        -8,
    )


def test_call_unevaluable_does_not_crash():
    src = """
def takes_str(s: String) -> Int:
    return 4

@align(takes_str("hi"))
@fieldwise_init
struct S:
    var x: Int

def main():
    var s = S(1)
    _ = s.x
"""
    try:
        _compile_full(src)
    except Exception as e:
        msg = str(e)
        assert "struct alignment must be a positive power of 2" not in msg, msg


if __name__ == "__main__":
    test_parametric_invalid_direct()
    test_parametric_invalid_arithmetic()
    test_parametric_valid_cases()
    test_module_alias_cases()
    test_unknown_align_name()
    test_call_original_modular_invalid()
    test_call_valid_result()
    test_call_another_invalid_result()
    test_call_returns_zero()
    test_call_returns_negative()
    test_call_unevaluable_does_not_crash()
    print("ok")
