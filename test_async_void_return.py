"""REAL behavioral tests for device_context.mojo's follow-on async support,
landed this session on top of the general closure-capture fixes in
test_closure_capture_comptime_func_params.py:

  1. Void/None-returning compiled async functions (`async def f() -> None:`
     or unannotated with no value-carrying `return` anywhere) — previously
     an honest whole-module refusal ("every `return` must carry a scalar
     value"); device_context.mojo's `async def wrapper(...) capturing ->
     None:` closures never return a value at all.
  2. A NESTED async closure (defined inside a struct method, not itself a
     method or a top-level function) — a shape neither the top-level
     free-function async pre-pass nor the generator/async-METHOD passes
     ever attempted. Its captured free variable(s) (the enclosing method's
     comptime-threaded function parameter) are threaded through as an
     ordinary trailing parameter of the compiled coroutine unit, and the
     `wrapper()` call site (inside the method's own ordinary GIMPLE body)
     supplies them automatically.
  3. A bare CallExpr inside a compiled async closure's body, calling the
     captured function-type value (`func()`/`func(idx)`) — the coroutine
     sub-compiler (_cpp_expr/_cpp_stmt) previously had no CallExpr case at
     all.
  4. The `std.builtin.coroutine` primitives device_context.mojo's real code
     actually uses on the resulting coroutine object: `_set_noop_callback()`
     (a no-op, matching this codegen's synchronous-stub simplification),
     `_take_handle()` (returns the same MojoAsync* handle as a plain
     int64_t), and `_coro_resume_fn`/`_coro_destroy_fn` used as bare
     function-pointer VALUES (substituted for this codegen's own generic
     `mojo_coro_resume_generic`/`mojo_coro_destroy_generic`), wired through
     `external_call["AsyncRT_DeviceContext_enqueueHostFunction", ...]` (the
     honest synchronous-simplification stub from runtime/
     mojo_async_runtime.h/.cpp, commit 2ea4eaf) to ACTUALLY invoke the
     captured function for real.

This compiles + links + RUNS the full device_context.mojo-shaped repro
(not compile-only) and asserts on real stdout — verifying the captured
function genuinely gets called via the runtime stub's resume callback,
not just that the pieces compile.
"""
import os
import subprocess
import tempfile

import gimple_codegen
from build_config import find_gcc, find_gxx

HERE = os.path.dirname(os.path.abspath(__file__))
RUNTIME_DIR = os.path.join(HERE, 'runtime')
RUNTIME_C = os.path.join(RUNTIME_DIR, 'mojo_runtime.c')
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
    """Compile mojo_src (written to a REAL file — the method-comptime-
    parameter-threading registration in gen_module reads the source back
    off disk, see _method_threaded_comptime_params) to real .c/.cpp text,
    build both with gcc -fgimple / g++ -std=c++20, link against this
    project's own runtime/mojo_runtime.c + runtime/mojo_async_runtime.cpp
    via mojo.py's real link_executable(cxx=True), run it, and return
    stdout. Mirrors test_gimple_async_runner.py's harness shape."""
    wd = tempfile.mkdtemp(prefix='mojo_async_void_')
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
    runtime_o = os.path.join(wd, 'mojo_runtime.o')
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
        raise RuntimeError(f"gcc compile of mojo_runtime.c failed: {r.stderr}")

    r = subprocess.run([GXX, '-std=c++20', f'-I{RUNTIME_DIR}', '-c', '-o', async_runtime_o,
                        ASYNC_RUNTIME_CPP], capture_output=True, text=True, timeout=30)
    if r.returncode != 0:
        raise RuntimeError(f"g++ compile of mojo_async_runtime.cpp failed: {r.stderr}")

    import mojo
    r = mojo.link_executable([c_o, async_o, runtime_o, async_runtime_o], exe, cxx=True)
    if r.returncode != 0:
        raise RuntimeError(f"link_executable(cxx=True) failed: {r.stderr}")

    os.chmod(exe, 0o755)
    r = subprocess.run([exe], capture_output=True, text=True, timeout=30)
    if r.returncode != 0:
        raise RuntimeError(f"program exited {r.returncode}, stderr={r.stderr}")
    return r.stdout


def test_void_returning_async_function_driven_via_asyncio_run():
    """A plain top-level async function with no return value at all,
    actually driven to completion via asyncio.run(...) (not just
    constructed) — proves the void co_return/return_void() plumbing is
    real, not just "doesn't fail to compile"."""
    src = """\
import asyncio

async def noop() -> None:
    print(42)

def main() raises:
    asyncio.run(noop())
"""
    out = _build_and_run(src)
    check("void async function actually runs its body via asyncio.run(...)",
          out == "42\n", detail=repr(out))


def test_device_context_shaped_repro_end_to_end():
    """The real device_context.mojo shape, full chain: a comptime
    function-typed bracket method parameter, a nested async closure
    capturing it, `_set_noop_callback()`/`_take_handle()`, and
    `_coro_resume_fn`/`_coro_destroy_fn` threaded through `external_call[
    "AsyncRT_DeviceContext_enqueueHostFunction", ...]` — must actually
    invoke `func_impl` for real (via the runtime stub's synchronous
    resume_fn callback), not merely construct-and-never-run it."""
    src = """\
from std.builtin.coroutine import AnyCoroutine, _coro_resume_fn, _coro_destroy_fn

struct Ctx:
    var _handle: Int
    def __init__(out self):
        self._handle = 0

    def enqueue_cpu_function[
        func: def() capturing -> None,
    ](self) raises:
        async def wrapper() capturing -> None:
            func()

        var coro = wrapper()
        coro._set_noop_callback()
        external_call["AsyncRT_DeviceContext_enqueueHostFunction", UnsafePointer[Int8]](
            self._handle,
            _coro_resume_fn,
            _coro_destroy_fn,
            coro^._take_handle(),
        )

fn func_impl():
    print("ran-for-real")

def main() raises:
    var c = Ctx()
    c.enqueue_cpu_function[func_impl]()
    print("done")
"""
    out = _build_and_run(src)
    check("device_context.mojo-shaped repro: func_impl actually invoked via the runtime stub",
          out == "ran-for-real\ndone\n", detail=repr(out))


def test_enqueue_cpu_range_shaped_repro_multiple_handles():
    """device_context.mojo's SECOND real shape: `wrapper(idx: Int)` (an
    ordinary int64_t parameter, not just captures), called in a loop to
    build up a List[AnyCoroutine] of handles, then all enqueued together
    via AsyncRT_DeviceContext_enqueueHostFunctionRange. Each of the three
    handles must independently drive its own captured call with the right
    index."""
    src = """\
from std.builtin.coroutine import AnyCoroutine, _coro_resume_fn, _coro_destroy_fn

struct Ctx:
    var _handle: Int
    def __init__(out self):
        self._handle = 0

    def enqueue_cpu_range[
        func: def(count: Int) capturing -> None,
    ](self, count: Int) raises:
        var handles = List[Int](capacity=count)

        async def wrapper(idx: Int) capturing -> None:
            func(idx)

        for j in range(count):
            var coro = wrapper(j)
            coro._set_noop_callback()
            handles.append(coro^._take_handle())

        for h in handles:
            external_call["AsyncRT_DeviceContext_enqueueHostFunction", UnsafePointer[Int8]](
                self._handle,
                _coro_resume_fn,
                _coro_destroy_fn,
                h,
            )

fn print_idx(i: Int):
    print("idx", i)

def main() raises:
    var c = Ctx()
    c.enqueue_cpu_range[print_idx](3)
"""
    out = _build_and_run(src)
    check("enqueue_cpu_range-shaped repro: three captured calls, each with the right idx",
          out == "idx 0\nidx 1\nidx 2\n", detail=repr(out))


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
