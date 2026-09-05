"""test_coro_nested_async_capture.py -- real behavioral test for the A3
stack-switch coroutine backend's mutable closure capture into a nested
`async def` (bugs/hard/CODEGEN_coro_nested_async_closure_capture.md).

Exercises the bug doc's own headline shape verbatim (also the real
`test_async_with_lock_guard.py::test_simple_with_lock_guard_single_task`
cpp-path test source, unmodified) under MOJO_CORO=stackswitch:

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

`rawCounter` is a free variable of the nested `inc()` resolving to
`test_with_lock`'s own local -- v0 support (gimple_gen_coro.py's
`_nested_async_capture_plan`/`_apply_nested_async_capture`) boxes it as
a heap `int64_t` cell (`__mojo_box_new_i64`/`_get_i64`/`_set_i64`,
runtime/mojo_coro_gen.c), threaded as a hidden trailing parameter into
the hoisted `__mgco_test_with_lock_inc_*` unit, with every read/write of
`rawCounter` in BOTH the enclosing function and the nested body rewritten
to go through the box. `with BlockingScopedLock(lock):` itself is elided
(a provable no-op in this single-threaded/cooperative runtime -- see
gimple_gen_coro.py's own `_is_lock_with` docstring), matching the cpp
path's identical treatment.

NOT covered (still open, see the bug doc's own item 4 / this file's own
Status note): the cross-closure stress-test shape
(`test_locks_mojo_shaped_10000_task_stress`), where a DIFFERENT sibling
nested function (`caller()`) calls the hoisted `inc()` -- the qualified-
rename `local_maps` this project's create_task/detached-async plumbing
uses is keyed by the DIRECT enclosing function only, not propagated into
further-nested sibling scopes, so that shape still hits the pre-existing
"TaskGroup.create_task(...) is only supported for a call to another
compiled async function this module already compiled" honest refusal
(falls back to interpreting the module from source, not a miscompile).
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

_RUNTIME_SRCS = [
    os.path.join(RUNTIME_DIR, 'mojo_runtime.c'),
    os.path.join(RUNTIME_DIR, 'mojo_async_runtime.cpp'),
    os.path.join(RUNTIME_DIR, 'mojo_coro.c'),
    os.path.join(RUNTIME_DIR, 'mojo_coro_gen.c'),
    os.path.join(RUNTIME_DIR, 'mojo_async_sched.c'),
    _CORO_CTX_SRC,
]

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
    wd = tempfile.mkdtemp(prefix='mojo_coro_capture_')
    src_path = os.path.join(wd, 'prog.mojo')
    with open(src_path, 'w') as f:
        f.write(mojo_src)

    c_code = gimple_codegen.compile_to_gimple(mojo_src, do_imports=False, filename=src_path)
    if '__mgco_' not in c_code:
        raise RuntimeError(
            "expected the nested async def in this source to be lowered by "
            "gimple_gen_coro (stack-switch) -- no __mgco_ symbols in the "
            "generated C, so this test isn't exercising the code path it "
            "claims to")
    if '__mojo_box_new_i64' not in c_code:
        raise RuntimeError(
            "expected the captured local to be heap-boxed -- no "
            "__mojo_box_new_i64 call in the generated C, so the capture "
            "wasn't actually threaded through as designed")

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


def test_simple_with_lock_guard_single_task():
    """The bug doc's own headline shape (also test_async_with_lock_guard.py
    ::test_simple_with_lock_guard_single_task's exact cpp-path source,
    verbatim): a nested async closure mutating an outer local (`rawCounter
    += 1`) inside a `with BlockingScopedLock(lock):` guard, driven via
    create_task/.wait() -- the mutation must be observed by the enclosing
    function after .wait() returns."""
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


def test_capture_without_lock_guard():
    """The same capture mechanism with no lock-with at all (isolates the
    box-threading itself from the separate lock-elision mechanism) -- two
    separate tasks each incrementing the same captured counter, read after
    both complete."""
    src = """\
def test_plain_capture() raises:
    var counter = 0

    @parameter
    async def bump():
        counter += 1

    var t0 = create_task(bump())
    t0.wait()
    var t1 = create_task(bump())
    t1.wait()
    print(counter)


def main() raises:
    test_plain_capture()
"""
    out = _build_and_run(src)
    check("two sequential create_task(bump()).wait() calls -> counter == 2",
          out == "2\n", detail=repr(out))


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
