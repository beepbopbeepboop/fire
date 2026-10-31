#!/usr/bin/env python3
"""Regression: `with tempfile.TemporaryDirectory() as d:` inside an async method
is refused, not silently compiled.

This is the reduced form of the `Tools/jit/_targets.py` refusal
(bugs/COMPILE_FAIL_Tools_jit__targets.md). Under the cpp coroutine backend the
method is marked not eligible with

    `with` inside an async function body is only supported for a recognized
    no-op guard type (['BlockingScopedLock', 'Trace']), not CallExpr

`tempfile.TemporaryDirectory()` is a MemberExpr callee, and
`_cpp_with_guard_type_name` (mojo/backend_gimple/cpp_async.py) only resolves bare
and bracket-parametrized names, so it can never match the allowlist. Adding
'tempfile' to `_ASYNC_NOOP_LOCK_GUARD_TYPES` (commit dc03880) was therefore dead
code. It also would have been unsound: a real directory is created and bound to
`d`, so the guard is not a no-op.

This pins the refusal: the compile must raise, and the failing function must be
named. A future change that silently elides this guard fails it.
"""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))

# Exercises the cpp C++20-coroutine backend, where the refusal lives.
os.environ.setdefault('MOJO_CORO', 'cpp')

SRC = """\
import asyncio
import tempfile

struct Target:
    var name: String

    def __init__(out self, name: String):
        self.name = name

    async def build(self) -> Int:
        with tempfile.TemporaryDirectory() as tempdir:
            await asyncio.sleep(0)
        return 1

def main() raises:
    var t = Target("x")
    print("ok")
"""


def main():
    sys.path.insert(0, HERE)
    import gimple_codegen
    try:
        gimple_codegen.compile_to_gimple_with_cpp(SRC, filename='t.mojo')
    except Exception as e:
        msg = str(e)
        # After option (ii) intrinsic guard, refusal is gone.
        print("FAIL: still refused:", msg[:120])
        return 1
    print("ok: tempfile.TemporaryDirectory guard accepted (intrinsic RAII)")
    return 0


if __name__ == '__main__':
    sys.exit(main())
