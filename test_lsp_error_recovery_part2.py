#!/usr/bin/env python3
"""Regression test for DIAGNOSTICS_lsp_error_recovery part 2.

Ensures that when an error occurs from a declaration, subsequent declarations
are still emitted/processed (error recovery in module emission path).
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


def test_unknown_align_error_followed_by_struct_still_emitted():
    src = """@align(missing)
struct Bad:
    var x: Int

struct Good:
    var y: Int

fn main():
    var b = Bad[1]()
"""
    try:
        result = _compile_full(src)
        raise AssertionError("expected error")
    except Exception as e:
        msg = str(e)
        # Error must be reported
        assert "use of unknown declaration" in msg or "Bad" in msg
        # Subsequent struct must still be emitted in module output
        out = getattr(e, "module_output", msg)
        assert "Good" in out


if __name__ == "__main__":
    test_unknown_align_error_followed_by_struct_still_emitted()
    print("ok")
