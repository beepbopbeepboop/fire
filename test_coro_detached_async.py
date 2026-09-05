"""test_coro_detached_async.py -- real behavioral tests for the A3
stack-switch coroutine backend's "detached async" support (bugs/hard/
CODEGEN_coro_detached_async_take_handle.md).

`std.gpu.host.DeviceContext.enqueue_cpu_function`/`enqueue_cpu_range`
(device_context.mojo) construct a nested async closure, extract its raw
coroutine handle via `coro._set_noop_callback()` / `coro^._take_handle()`,
and hand it to `external_call["AsyncRT_DeviceContext_enqueueHostFunction
(Range)", ...]` alongside `_coro_resume_fn`/`_coro_destroy_fn` (used as
bare function-pointer VALUES). Under MOJO_CORO=stackswitch this exercises:

  1. `_lower_method_call`'s `_set_noop_callback`/`_take_handle` special
     case recognizing a `MojoGenerator *` handle (this backend's own
     coroutine representation), not just the cpp path's `MojoAsync *`.
  2. `GimpleGen.BUILTIN_VALUE_MAP` substituting `_coro_resume_fn`/
     `_coro_destroy_fn` for `__mojo_gen_resume_once`/`__mojo_gen_destroy`
     (runtime/mojo_coro_gen.c) instead of the cpp path's
     `mojo_coro_resume_generic`/`destroy_generic`.
  3. A BARE call to a local nested async helper (`var coro = wrapper()`,
     no `create_task`/`asyncio.run` wrapper at all) being rewritten to its
     qualified `{base}_start` symbol by `gimple_gen_coro._rewrite_asyncio_
     run` (previously only the `create_task(...)` shape was handled).
  4. `gimple_module_gen.py`'s preamble emitting the `MojoGenerator` typedef
     + this handle's own extern trampoline decls, and the
     `mojo_async_runtime.h` include (for `AsyncRT_DeviceContext_
     enqueueHostFunction(Range)`'s declaration) even when the module's
     only coroutine is a stack-switch one (previously gated on cpp-path-
     only bookkeeping that stays empty here).

This compiles the REAL generated C with `gcc -fgimple`, links against this
project's own runtime (mojo_runtime.c, mojo_async_runtime.cpp,
mojo_coro.c/mojo_coro_gen.c/mojo_async_sched.c/mojo_coro_ctx_*), runs the
executable, and asserts on real stdout.
"""
import os
import platform
import subprocess
import tempfile

os.environ['MOJO_CORO'] = 'stackswitch'

import gimple_codegen
from build_config import find_gcc, find_gxx

HERE = os.path.dirname(os.path.abspath(__file__))
RUNTIME_DIR = os.path.join(HERE, 'runtime')
GCC = find_gcc()
GXX = find_gxx()

_CORO_CTX_SRC = (os.path.join(RUNTIME_DIR, 'mojo_coro_ctx_aarch64.S')
                 if platform.machine() in ('arm64', 'aarch64')
                 else os.path.join(RUNTIME_DIR, 'mojo_coro_ctx_generic.c'))

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


_RUNTIME_SRCS = [
    os.path.join(RUNTIME_DIR, 'mojo_runtime.c'),
    os.path.join(RUNTIME_DIR, 'mojo_async_runtime.cpp'),
    os.path.join(RUNTIME_DIR, 'mojo_coro.c'),
    os.path.join(RUNTIME_DIR, 'mojo_coro_gen.c'),
    os.path.join(RUNTIME_DIR, 'mojo_async_sched.c'),
    _CORO_CTX_SRC,
]


def _build_and_run(mojo_src: str) -> str:
    wd = tempfile.mkdtemp(prefix='mojo_coro_detached_')
    src_path = os.path.join(wd, 'prog.mojo')
    with open(src_path, 'w') as f:
        f.write(mojo_src)

    c_code = gimple_codegen.compile_to_gimple(mojo_src, do_imports=False, filename=src_path)
    if '__mgco_' not in c_code:
        raise RuntimeError(
            "expected the generator/async in this source to be lowered by "
            "gimple_gen_coro (stack-switch) -- no __mgco_ symbols in the "
            "generated C, so this test isn't exercising the code path it "
            "claims to")

    c_path = os.path.join(wd, 'prog.c')
    with open(c_path, 'w') as f:
        f.write(c_code)

    objs = []
    r = subprocess.run([GCC, '-fgimple', f'-I{RUNTIME_DIR}', '-w', '-c', '-o',
                        os.path.join(wd, 'prog.o'), c_path],
                        capture_output=True, text=True, timeout=30)
    if r.returncode != 0:
        raise RuntimeError(f"gcc -fgimple compile of .c failed: {r.stderr}\n---\n{c_code}")
    objs.append(os.path.join(wd, 'prog.o'))

    for i, src in enumerate(_RUNTIME_SRCS):
        is_cpp = src.endswith('.cpp')
        cc = GXX if is_cpp else GCC
        extra = ['-std=c++20'] if is_cpp else []
        o = os.path.join(wd, f'rt{i}.o')
        r = subprocess.run([cc, *extra, f'-I{RUNTIME_DIR}', '-c', '-o', o, src],
                            capture_output=True, text=True, timeout=30)
        if r.returncode != 0:
            raise RuntimeError(f"compile of {src} failed: {r.stderr}")
        objs.append(o)

    exe = os.path.join(wd, 'prog.exe')
    r = subprocess.run([GXX, '-o', exe, *objs], capture_output=True, text=True, timeout=30)
    if r.returncode != 0:
        raise RuntimeError(f"link failed: {r.stderr}")

    os.chmod(exe, 0o755)
    r = subprocess.run([exe], capture_output=True, text=True, timeout=30)
    if r.returncode != 0:
        raise RuntimeError(f"program exited {r.returncode}, stderr={r.stderr}")
    return r.stdout


def test_detached_async_single_handle_actually_invoked():
    """device_context.mojo's `enqueue_cpu_function` shape: a nested async
    closure with no captures, constructed directly (no create_task), its
    handle extracted via `_set_noop_callback()`/`_take_handle()` and driven
    through `AsyncRT_DeviceContext_enqueueHostFunction` -- must actually
    call `func_impl` for real, not merely construct-and-never-run it."""
    src = """\
def enqueue_it(handle: Int) raises:
    async def wrapper() capturing -> None:
        func_impl()

    var coro = wrapper()
    coro._set_noop_callback()
    external_call["AsyncRT_DeviceContext_enqueueHostFunction", UnsafePointer[Int8]](
        handle,
        _coro_resume_fn,
        _coro_destroy_fn,
        coro^._take_handle(),
    )

fn func_impl():
    print("ran-for-real")

def main() raises:
    enqueue_it(0)
    print("done")
"""
    out = _build_and_run(src)
    check("detached-async single handle: func_impl actually invoked",
          out == "ran-for-real\ndone\n", detail=repr(out))


def test_detached_async_range_multiple_handles():
    """device_context.mojo's `enqueue_cpu_range` shape: a nested async
    closure with an ordinary int param, constructed in a loop into a list
    of handles, then all driven via AsyncRT_DeviceContext_
    enqueueHostFunction one at a time (this backend has no ...Range
    variant of its own dispatch code -- the real call site loops)."""
    src = """\
def enqueue_range(handle: Int, count: Int) raises:
    var handles = List[Int](capacity=count)

    async def wrapper(idx: Int) capturing -> None:
        print_idx(idx)

    for j in range(count):
        var coro = wrapper(j)
        coro._set_noop_callback()
        handles.append(coro^._take_handle())

    for h in handles:
        external_call["AsyncRT_DeviceContext_enqueueHostFunction", UnsafePointer[Int8]](
            handle,
            _coro_resume_fn,
            _coro_destroy_fn,
            h,
        )

fn print_idx(i: Int):
    print("idx", i)

def main() raises:
    enqueue_range(0, 3)
"""
    out = _build_and_run(src)
    check("detached-async range: three captured calls, each with the right idx",
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
