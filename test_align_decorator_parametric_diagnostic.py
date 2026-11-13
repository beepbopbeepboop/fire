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
    raise AssertionError(f"expected unknown declaration diagnostic for:\n{src}")


if __name__ == "__main__":
    test_parametric_invalid_direct()
    test_parametric_invalid_arithmetic()
    test_parametric_valid_cases()
    test_module_alias_cases()
    test_unknown_align_name()
    print("ok")
