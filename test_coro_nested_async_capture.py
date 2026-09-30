"""test_coro_nested_async_capture.py -- real behavioral test for the A3
stack-switch coroutine backend's mutable closure capture into a nested
`async def`.

Fixed 2026-09-27 and registered in tools/suite.py as `coro-nested-capture`
(in `check`/`gate`): `_RUNTIME_SRCS` named the pre-rename `mojo_*.c` runtime
files (renamed to `fire_*.c`), so 7 of 9 cases died compiling the runtime
before the program under test was ever compiled. 9/9 then: struct-typed
capture (`test_struct_capture_compiles_boxed_and_correct`) used to assert
the PRE-Increment-E refusal-to-cpp-path behaviour, which no longer happens
-- a struct capture now boxes and runs correctly, so that test was rewritten
to assert the current (correct) behaviour instead of the old one.

10/10 as of 2026-09-29, with the bug doc's item 3 added
(`test_nested_async_generator_driven_by_async_for`): a nested async
GENERATOR consumed by `async for` in its own enclosing function built, ran,
exited 0 and printed `0` where CPython prints `11`. A comment in this file
still claimed the cross-closure stress shape below was uncovered and
unreachable; it has been covered (and passing) since the
`_rewrite_asyncio_run_stmts` local_map merge, so that claim is corrected
here rather than left to mislead the next reader.

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

STILL not covered here, and deliberately so:
  * the wait-descriptor boundary of `async for` -- an async generator whose
    body can PARK, consumed by a function with no yield channel of its own.
    That is a compile-time refusal, and the shape needs `import asyncio`
    plus a real scheduler, so it lives with its siblings in
    test_gimple_generator_runner.py (`async_for_over_parking_async_gen_
    refused` and the three other cases beside it), whose harness compiles
    the same way this one does.
  * any `async for` whose iterable is not a plain call (a variable, an
    attribute, an expression) -- `_async_for_ok` refuses the containing
    coroutine outright for that, and the ordinary loop lowering's
    `MojoGenerator *` route is what the item-3 fix is about, not this
    file's capture plan.
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

_CORO_CTX_SRC = (os.path.join(RUNTIME_DIR, 'fire_coro_ctx_aarch64.S')
                 if platform.machine() in ('arm64', 'aarch64')
                 else os.path.join(RUNTIME_DIR, 'fire_coro_ctx_generic.c'))

_RUNTIME_SRCS = [
    os.path.join(RUNTIME_DIR, 'fire_runtime.c'),
    os.path.join(RUNTIME_DIR, 'fire_async_runtime.cpp'),
    os.path.join(RUNTIME_DIR, 'fire_coro.c'),
    os.path.join(RUNTIME_DIR, 'fire_coro_gen.c'),
    os.path.join(RUNTIME_DIR, 'fire_async_sched.c'),
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
    if '__mojo_box_new_' not in c_code:
        raise RuntimeError(
            "expected the captured local to be heap-boxed -- no "
            "__mojo_box_new_* call in the generated C, so the capture "
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


def test_cross_closure_taskgroup_stress():
    """The bug doc's item 4 (also test_async_with_lock_guard.py::
    test_locks_mojo_shaped_10000_task_stress's exact cpp-path source):
    the nested `inc()` async closure is called from a DIFFERENT sibling
    nested function (`caller()`), which builds a `TaskGroup`, creates
    10,000 tasks across two same-named nested loops, and waits. The box
    handle for the captured `rawCounter` must be threaded THROUGH
    `caller()` (its own hidden param), forwarded to every `inc()` call
    inside it, and forwarded at the `caller()` call site -- and the
    stack-switch `TaskGroup.create_task(...)` / `.wait()` path must
    drive every task to completion. Result read after `caller()`
    returns must be exactly 10000."""
    src = """\
from std.runtime.asyncrt import TaskGroup


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
    out = _build_and_run(src)
    check("cross-closure TaskGroup 10,000-task stress -> 10000",
          out == "10000\n", detail=repr(out))


def test_cross_closure_single_scope_taskgroup():
    """The simpler single-scope `TaskGroup` shape (the callee and the
    group live in the SAME function): proves the stack-switch
    `TaskGroup.create_task(...)`/`.wait()` intrinsics on their own,
    independent of the further-nested sibling-function threading."""
    src = """\
from std.runtime.asyncrt import TaskGroup


def test_tg() raises:
    var counter = 0

    @parameter
    async def inc():
        counter += 1

    var tg = TaskGroup()
    for _ in range(0, 100):
        tg.create_task(inc())
    tg.wait()
    print(counter)


def main() raises:
    test_tg()
"""
    out = _build_and_run(src)
    check("single-scope TaskGroup 100-task -> 100", out == "100\n", detail=repr(out))


def test_nonliteral_initializer_capture():
    """Increment A: the captured outer local's initializer is a call
    (`var n = compute()`), not a bare int literal -- the box is still an
    int64_t cell; only the plan's initializer restriction is relaxed
    (kind taken from the callee's `-> Int` return annotation)."""
    src = """\
def compute() -> Int:
    return 40 + 2


def test_nonlit() raises:
    var n = compute()

    @parameter
    async def bump():
        n += 1

    var t0 = create_task(bump())
    t0.wait()
    print(n)


def main() raises:
    test_nonlit()
"""
    out = _build_and_run(src)
    check("var n = compute(); nested bump() -> 43", out == "43\n", detail=repr(out))


def test_captured_parameter():
    """Increment B: the nested async captures one of the ENCLOSING
    function's own PARAMETERS directly (no `var c = seed` indirection).
    The param is renamed and its incoming value boxed at function entry."""
    src = """\
def run(seed: Int) raises:
    @parameter
    async def bump():
        seed += 2

    var t0 = create_task(bump())
    t0.wait()
    print(seed)


def main() raises:
    run(10)
"""
    out = _build_and_run(src)
    check("captured parameter seed=10, +2 -> 12", out == "12\n", detail=repr(out))


def test_float_capture():
    """Increment C: a Float64 captured local, mutated in the nested async
    then read back -- the box cell is a `double` (`__mojo_box_new_d`/
    `_get_d`/`_set_d`) instead of int64_t."""
    src = """\
def test_f() raises:
    var acc = 0.0

    @parameter
    async def addf():
        acc += 1.5

    var t0 = create_task(addf())
    t0.wait()
    var t1 = create_task(addf())
    t1.wait()
    print(acc)


def main() raises:
    test_f()
"""
    out = _build_and_run(src)
    check("Float64 capture acc += 1.5 twice -> 3.0",
          out.strip() in ("3.0", "3.000000", "3"), detail=repr(out))


def test_string_capture():
    """Increment C: a String captured local, appended-to in the nested
    async then read back -- the box cell is a `char *` (`__mojo_box_new_p`/
    `_get_p`/`_set_p`)."""
    src = """\
def test_s() raises:
    var msg = String("a")

    @parameter
    async def app():
        msg += "b"

    var t0 = create_task(app())
    t0.wait()
    print(msg)


def main() raises:
    test_s()
"""
    out = _build_and_run(src)
    check("String capture msg += \"b\" -> ab", out == "ab\n", detail=repr(out))


def test_struct_capture_compiles_boxed_and_correct():
    """A struct-typed captured local IS now representable by v0's box (a
    heap cell holding the struct pointer, boxed/unboxed exactly like the
    scalar cases above) -- this used to be refused to the cpp path (pre-
    Increment-E), but that refusal is gone: the program compiles, the box
    shim is present, and running it gives the CPython-correct answer."""
    src = """\
struct P:
    var x: Int
    fn __init__(out self, x: Int):
        self.x = x


def test_p() raises:
    var p = P(1)

    @parameter
    async def bump():
        p.x += 1

    var t0 = create_task(bump())
    t0.wait()
    print(p.x)


def main() raises:
    test_p()
"""
    out = _build_and_run(src)
    check("struct capture p.x += 1 -> 2", out.strip() == "2", detail=out)


def _cpython_stdout(py_src: str) -> str:
    """The oracle for the case below, measured at test time rather than
    transcribed: this file's harness has always asserted a hand-written
    expected string, which is precisely how bugs/hard/
    CODEGEN_bytes_silent_wrong_values.md's anti-tests came to encode the
    CPython-WRONG answer. The `async for` shape's failure mode is a
    SILENT wrong value, so the expected answer is the one CPython actually
    produces for the reference twin, not one written down here."""
    wd = tempfile.mkdtemp(prefix='mojo_coro_capture_cpy_')
    p = os.path.join(wd, 'ref.py')
    with open(p, 'w') as f:
        f.write(py_src)
    r = subprocess.run(['python3', p], capture_output=True, text=True, timeout=30)
    if r.returncode != 0:
        raise RuntimeError(f"the CPython reference program itself failed: {r.stderr}")
    return r.stdout


def test_nested_async_generator_driven_by_async_for():
    """A nested async GENERATOR that mutates a captured enclosing local,
    consumed by `async for` in that local's OWN enclosing (ordinary,
    never-suspended) function.

    This is the shape the doc proved was neither refused nor correct: it
    built, linked, ran, exited 0, and printed `0` where CPython prints
    `11`. The `mojo_unsupported_iter` warning it did emit names a
    `MojoGenerator *`, so it looked handled from the outside.

    Not a capture bug: the identical wrong `0` appeared with no capture at
    all, and the cause is that a nested `async def gen()`'s call site is
    rewritten by coro.py to its QUALIFIED `__mgco_outer_gen_start`, which
    the bare-name `_generator_api` lookup the ordinary `for`-loop lowering
    uses cannot see -- so the loop found no generator api and dropped its
    body. The capture box IS threaded (this file's `_build_and_run`
    requires `__mojo_box_new_*` in the C, and asserts it), which is exactly
    why the failure looked like a capture problem.

    The wait-descriptor half of the same boundary -- an async generator
    that can PARK under `async for` driven by a function with no yield
    channel -- is covered in test_gimple_generator_runner.py, which has
    this harness's compile-only sibling; see `async_for_over_parking_
    async_gen_refused` there."""
    src = """\
def outer() raises:
    var acc = 0

    async def gen():
        acc = acc + 1
        yield 10

    async for x in gen():
        acc = acc + x
    print(acc)


def main() raises:
    outer()
"""
    out = _build_and_run(src)
    want = _cpython_stdout("""\
import asyncio


async def outer():
    acc = 0

    async def gen():
        nonlocal acc
        acc = acc + 1
        yield 10

    async for x in gen():
        acc = acc + x
    print(acc)


asyncio.run(outer())
""")
    check("nested async gen consumed by `async for` in its own enclosing "
          f"function -> {want.strip()!r}", out == want, detail=f"got {out!r}, "
          f"CPython {want!r}")


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
