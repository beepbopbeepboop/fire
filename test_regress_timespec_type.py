"""Regression test for STDLIB std/sys/_libc.mojo 'unknown type name timespec'.

Compiles the stdlib sys module (which includes _libc.mojo) through the
gimple codegen and asserts the timespec system struct is exposed under its
bare Mojo name so generated C resolves.
"""
import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))


def test_libc_timespec_compiles():
    root = HERE
    res = subprocess.run(
        [sys.executable, os.path.join(root, "compile_stdlib.py"), "--module", "sys"],
        cwd=root, capture_output=True, text=True, timeout=580,
    )
    out = (res.stdout or "") + (res.stderr or "")
    assert "unknown type name 'timespec'" not in out, out
    assert "FAILED: 0" in out or "0 failed" in out.lower(), out


if __name__ == "__main__":
    test_libc_timespec_compiles()
    print("OK")
