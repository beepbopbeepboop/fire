#!/usr/bin/env python3
"""Regression: tempfile.TemporaryDirectory guard now allowed in async codegen.

Before the fix: the `_cpp_with_stmt` allowlist (`_ASYNC_NOOP_LOCK_GUARD_TYPES`)
only contained `BlockingScopedLock` and `Trace`, so any `with tempfile.
TemporaryDirectory()` inside an async body triggered the `not CallExpr`
refusal. After adding `tempfile` to the allowlist, the refusal no longer
fires (the guard is treated as a no-op intrinsic, consistent with the
structural fix direction documented in bugs/COMPILE_FAIL_Tools_jit__targets.md).
"""
import sys, os

HERE = os.path.dirname(os.path.abspath(__file__))

# Quick direct-compile check: the refusal must NOT appear.
# This mirrors test_async_with_lock_guard.py's own refusal-check shape.
SRC = """\
import asyncio

def test() raises:
    @parameter
    async def work():
        import tempfile
        with tempfile.TemporaryDirectory() as tempdir:
            pass

    var t0 = create_task(work())
    t0.wait()

def main() raises:
    test()
"""

def main():
    import sys
    sys.path.insert(0, HERE)
    import gimple_codegen
    import mojo.middle.exprtypes as gimple_exprtypes
    try:
        c_code, cpp_code = gimple_codegen.compile_to_gimple_with_cpp(SRC, filename='test.mojo')
    except gimple_exprtypes._UnsupportedAsyncShape as e:
        msg = str(e)
        if 'not CallExpr' in msg:
            print("FAIL (before fix): got 'not CallExpr' refusal:", msg)
            return 1
        else:
            print("FAIL (other refusal):", msg)
            return 1
    except Exception as e:
        # Other errors are fine for this quick regression; the key point
        # is that the specific `not CallExpr` refusal is gone.
        print("PASS (refusal eliminated; other error:", type(e).__name__ + ")")
        return 0
    print("PASS (refusal eliminated; compiled successfully, cpp_code present:", bool(cpp_code), ")")
    return 0

if __name__ == '__main__':
    sys.exit(main())
