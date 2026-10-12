"""REAL behavioral tests for mutable (by-reference) closure capture in
compiled async coroutines -- the foundational piece test_locks.mojo's
`inc()` needs (`async def inc() {mut}: rawCounter += 1`), landed on top of
the create_task/await-composition work (see bugs/CODEGEN_comptime_
bracket_parametrized_function_calls_silently_wrong.md's own "Update"
sections for that project's history).

Before this, EVERY captured free variable in a compiled async closure
(device_context.mojo's `wrapper`, test_asyncrt.mojo's bracket-parametrized
nested defs, ...) was threaded through as a BY-VALUE parameter copy --
correct for those shapes (none of them ever reassign a captured name), but
silently WRONG for a closure that mutates a captured local across many
separate task invocations: each `create_task(...)` call would get its own
private copy, and the mutation would never be visible to the caller. A
hand-written, Mojo-independent repro against this project's actual GCC 15
(not included here -- see this session's own commit message / bugs/
CODEGEN_comptime_bracket_parametrized_function_calls_silently_wrong.md)
confirmed a coroutine taking one or more POINTER-typed formal parameters
(not an extra PROMISE field, the shape this project's GCC 15 previously
corrupted -- see _gen_cpp_generator_unit's `unhandled_exception()`
docstring) is safe, including with multiple pointer parameters and
suspend points interleaved between writes to each.

This file compiles + links + RUNS each repro (not compile-only) and
asserts on real stdout, proving the mutation genuinely propagates back to
the caller's own variable across multiple separate coroutine instances,
not just that the pieces compile.
"""
import os
import subprocess
import tempfile


# cpp-path (gimple_cpp_*) escape-hatch test -- its build harness links
# the C++20-coroutine runtime. doc/COROUTINE.html §5.5 made the A3
# stack-switch backend the default, so pin cpp explicitly.
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


def _build_and_run(mojo_src: str) -> str:
    """Mirrors test_async_void_return.py's/test_gimple_async_runner.py's
    identical harness shape: real gcc -fgimple / g++ -std=c++20 compile,
    real link via fire.py's link_executable(cxx=True), real run, real
    stdout."""
    wd = tempfile.mkdtemp(prefix='mojo_mut_capture_')
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
    r = subprocess.run([exe], capture_output=True, text=True, timeout=30)
    if r.returncode != 0:
        raise RuntimeError(f"program exited {r.returncode}, stderr={r.stderr}")
    return r.stdout


def test_single_counter_incremented_across_three_tasks():
    """The simplest possible mutating-capture case: one captured local
    Int, three separate create_task(...) calls each incrementing it once,
    read back after all three complete. If captures were still by-value
    (the pre-existing behavior for every OTHER capture shape), this would
    print 0, not 3 -- each task would mutate its own private copy."""
    src = """\
from std.runtime.asyncrt import create_task


def test_mutable_capture() raises:
    var counter = 0

    @parameter
    async def inc():
        counter += 1

    var t0 = create_task(inc())
    var t1 = create_task(inc())
    var t2 = create_task(inc())
    t0.wait()
    t1.wait()
    t2.wait()
    print(counter)


def main() raises:
    test_mutable_capture()
"""
    out = _build_and_run(src)
    check("single mutable capture incremented by 3 separate tasks -> 3",
          out == "3\n", detail=repr(out))


def test_two_independent_counters_interleaved():
    """Two DIFFERENT captured locals, mutated by two DIFFERENT nested
    closures, with task creation interleaved (inc_a, inc_b, inc_a, inc_b,
    inc_a) -- checks neither capture's own pointer parameter aliases or
    corrupts the other's coroutine frame."""
    src = """\
from std.runtime.asyncrt import create_task


def test_mutable_capture_two_counters() raises:
    var counter_a = 0
    var counter_b = 100

    @parameter
    async def inc_a():
        counter_a += 1

    @parameter
    async def inc_b():
        counter_b += 2

    var t0 = create_task(inc_a())
    var t1 = create_task(inc_b())
    var t2 = create_task(inc_a())
    var t3 = create_task(inc_b())
    var t4 = create_task(inc_a())
    t0.wait()
    t1.wait()
    t2.wait()
    t3.wait()
    t4.wait()
    print(counter_a)
    print(counter_b)


def main() raises:
    test_mutable_capture_two_counters()
"""
    out = _build_and_run(src)
    check("two independent mutable captures, interleaved tasks -> 3 / 104",
          out == "3\n104\n", detail=repr(out))


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
