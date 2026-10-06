"""REAL behavioral tests for `with BlockingScopedLock(lock): ...` inside an
async coroutine body -- test_locks.mojo's gap (2) (`_cpp_stmt` had no
`WithStmt` case at all).

Real Mojo's `BlockingScopedLock`/`BlockingSpinLock` (std/utils/lock.mojo)
is a deep, `external_call`/`Atomic`-backed struct (a real spin-wait loop
against a compiler-rt primitive) entirely outside this narrow scalar-only
async C++ coroutine codegen's model -- genuinely compiling it is out of
scope, the same "scalar-only barrier" gap (3) (a non-scalar `Atomic[DType.
int64]` capture) separately documents.

Instead, `BlockingScopedLock` is reinterpreted as a compiler-recognized
INTRINSIC (mirroring `TaskGroup`/`create_task` already being reinterpreted
the same way) whose entire `__enter__`/`__exit__` pair is elided --
verified real: `runtime/mojo_async_runtime.cpp` has no `pthread`/
`std::thread`/worker-pool anywhere (grep-confirmed), so this project's
async runtime is genuinely single-threaded and cooperative. A coroutine's
body only ever yields control at an explicit `co_await`; nothing can
interleave between two statements with no suspension point between them.
A scoped lock guard whose only job is mutual exclusion is therefore a
real, PROVABLE no-op for correctness in this specific runtime -- not an
approximation. Safety is enforced (not just asserted): `_cpp_with_stmt`
refuses (does not silently elide) a `with BlockingScopedLock(...):` body
containing an `await`, where a different coroutine genuinely could run
during the suspension.

This compiles + links + RUNS each repro (not compile-only) and asserts on
real stdout, including a real 10,000-task concurrent-increment stress test
(mirroring test_taskgroup.py's own) to prove the elision doesn't lose any
increments -- proving genuine correctness under this runtime's real
scheduling, not just that the syntax parses.
"""
import os
import subprocess
import tempfile

# Exercises the gimple_cpp_* C++20-coroutine backend (this harness links
# mojo_async_runtime.cpp, the cpp scheduler). doc/COROUTINE.html §5.5's
# cutover made the A3 stack-switch backend the default, so pin the escape
# hatch explicitly -- the equivalent stack-switch coverage (single-level
# and the cross-closure / TaskGroup stress shape) lives in
# test_coro_nested_async_capture.py.
os.environ.setdefault('MOJO_CORO', 'cpp')

import gimple_codegen
import fire
from build_config import find_gcc, find_gxx

HERE = os.path.dirname(os.path.abspath(__file__))
RUNTIME_DIR = os.path.join(HERE, 'runtime')
RUNTIME_C = os.path.join(RUNTIME_DIR, 'fire_runtime.c')
ASYNC_RUNTIME_CPP = os.path.join(RUNTIME_DIR, 'mojo_async_runtime.cpp')
GCC = find_gcc()
GXX = find_gxx()

_PASS = 0
_FAIL = 0


def check(name, cond, detail=""):
    global _PASS, _FAIL
    if cond:
        print(f"PASS  {name}")
        _PASS += 1
    else:
        print(f"FAIL  {name}  {detail}")
        _FAIL += 1


def _build_and_run(mojo_src: str, timeout: int = 30) -> str:
    """Mirrors test_transitive_closure_capture.py's/test_taskgroup.py's
    identical harness shape: real gcc -fgimple / g++ -std=c++20 compile,
    real link via fire.py's link_executable(cxx=True), real run, real
    stdout."""
    wd = tempfile.mkdtemp(prefix='mojo_with_lock_')
    src_path = os.path.join(wd, 'prog.mojo')
    with open(src_path, 'w') as f:
        f.write(mojo_src)

    c_code, cpp_code = gimple_codegen.compile_to_gimple_with_cpp(mojo_src, filename=src_path)
    if not cpp_code:
        raise RuntimeError(
            "expected a non-empty generated .cpp — this source doesn't "
            "actually contain a supported async function/closure")

    c_path = os.path.join(wd, 'prog.c')
    cpp_path = os.path.join(wd, 'prog_async.cpp')
    with open(c_path, 'w') as f:
        f.write(c_code)
    with open(cpp_path, 'w') as f:
        f.write(cpp_code)

    c_o = os.path.join(wd, 'prog.o')
    async_o = os.path.join(wd, 'prog_async.o')
    runtime_o = os.path.join(wd, 'fire_runtime.o')
    async_runtime_o = os.path.join(wd, 'mojo_async_runtime.o')
    exe = os.path.join(wd, 'prog.exe')

    r = subprocess.run([GCC, '-fgimple', f'-I{RUNTIME_DIR}', '-c', '-o', c_o, c_path],
                        capture_output=True, text=True, timeout=30)
    if r.returncode != 0:
        raise RuntimeError(f"gcc -fgimple compile of .c failed: {r.stderr}\n---\n{c_code}")

    r = subprocess.run([GXX, '-std=c++20', f'-I{RUNTIME_DIR}', '-c', '-o', async_o, cpp_path],
                        capture_output=True, text=True, timeout=30)
    if r.returncode != 0:
        raise RuntimeError(f"g++ compile of .cpp failed: {r.stderr}\n---\n{cpp_code}")

    r = subprocess.run([GCC, f'-I{RUNTIME_DIR}', '-c', '-o', runtime_o, RUNTIME_C],
                        capture_output=True, text=True, timeout=30)
    if r.returncode != 0:
        raise RuntimeError(f"gcc compile of fire_runtime.c failed: {r.stderr}")

    r = subprocess.run([GXX, '-std=c++20', f'-I{RUNTIME_DIR}', '-c', '-o', async_runtime_o,
                        ASYNC_RUNTIME_CPP], capture_output=True, text=True, timeout=30)
    if r.returncode != 0:
        raise RuntimeError(f"g++ compile of mojo_async_runtime.cpp failed: {r.stderr}")

    r = mojo.link_executable([c_o, async_o, runtime_o, async_runtime_o], exe, cxx=True)
    if r.returncode != 0:
        raise RuntimeError(f"link_executable(cxx=True) failed: {r.stderr}")

    os.chmod(exe, 0o755)
    r = subprocess.run([exe], capture_output=True, text=True, timeout=timeout)
    if r.returncode != 0:
        raise RuntimeError(f"program exited {r.returncode}, stderr={r.stderr}")
    return r.stdout


def test_simple_with_lock_guard_single_task():
    """Simplest possible shape: one task, one increment inside `with
    BlockingScopedLock(lock): rawCounter += 1`."""
    src = """\
def test_with_lock() raises:
    var lock = BlockingSpinLock()
    var rawCounter = 0

    @parameter
    async def inc():
        with BlockingScopedLock(lock):
            rawCounter += 1

    var t0 = create_task(inc())
    t0.wait()
    print(rawCounter)


def main() raises:
    test_with_lock()
"""
    out = _build_and_run(src)
    check("with BlockingScopedLock(lock): rawCounter += 1 -> 1",
          out == "1\n", detail=repr(out))


def test_locks_mojo_shaped_10000_task_stress():
    """test_locks.mojo's own real shape (minus the separately-tracked
    Atomic[DType.int64] capture, gap (3)): `inc() {mut}` guards its
    increment with `with BlockingScopedLock(lock):`, called 10,000 times
    (100*100 same-named nested loops + comptime bounds) from a DIFFERENT
    sibling closure (`caller()`, exercising gap (1)'s transitive-capture
    fix at the same time). If lock elision were unsafe in this runtime, or
    if `lock` itself were wrongly threaded through as a real capture that
    corrupted the coroutine frame, this would print something other than
    exactly 10000."""
    src = """\
def test_with_lock_stress() raises:
    var lock = BlockingSpinLock()
    var rawCounter = 0
    comptime maxI = 100
    comptime maxJ = 100

    @parameter
    async def inc():
        with BlockingScopedLock(lock):
            rawCounter += 1

    def caller() raises:
        var tg = TaskGroup()
        for _ in range(0, maxI):
            for _ in range(0, maxJ):
                tg.create_task(inc())
        tg.wait()

    caller()
    print(rawCounter)


def main() raises:
    test_with_lock_stress()
"""
    out = _build_and_run(src, timeout=60)
    check("test_locks.mojo-shaped with-lock-guarded 10,000-task stress "
          "test -> 10000", out == "10000\n", detail=repr(out))


def test_await_inside_with_lock_is_honestly_refused():
    """Safety guard: an `await` inside a `with BlockingScopedLock(...):`
    body must be an honest compile-time refusal (falls back to
    interpreting the module from source), NOT a silent lock elision --
    eliding the guard would be genuinely unsafe across a real suspension
    point, where another coroutine could actually run."""
    src = """\
import asyncio


def test_with_lock_await() raises:
    var lock = BlockingSpinLock()
    var rawCounter = 0

    @parameter
    async def inc():
        with BlockingScopedLock(lock):
            await asyncio.sleep(0.001)
            rawCounter += 1

    var t0 = create_task(inc())
    t0.wait()
    print(rawCounter)


def main() raises:
    test_with_lock_await()
"""
    try:
        c_code, cpp_code = gimple_codegen.compile_to_gimple_with_cpp(src, filename='prog.mojo')
        refused = not cpp_code
    except Exception:
        refused = True
    check("await inside with-lock-guard body is honestly refused, not "
          "silently elided", refused)


def run_all():
    for name, fn in list(globals().items()):
        if name.startswith('test_') and callable(fn):
            try:
                fn()
            except Exception as e:
                check(name, False, detail=f"exception: {e}")
    print(f"\nResults: {_PASS} passed, {_FAIL} failed")
    return _FAIL == 0


if __name__ == '__main__':
    import sys
    sys.exit(0 if run_all() else 1)
