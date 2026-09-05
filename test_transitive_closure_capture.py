"""REAL behavioral tests for TRANSITIVE closure-capture propagation --
test_locks.mojo's gap (1) (formerly documented as gap (3) before the
general {mut}-capture fix landed): `test_atomic()` calls `inc()` via
`tg.create_task(inc())` without itself ever textually referencing `inc()`'s
own captured `lock`/`rawCounter`/`counter` -- the general (non-async)
closure-lifting mechanism (`_gen_lifted_closure`/`_scan_for_closures`) had
no notion of "this closure transitively needs a capture because it calls
something that does", so the CALLING closure's own compiled body had no
access to the captured names at all (an honest refusal, not a silent
miscompile, before this fix -- see `_resolve_and_start_task`'s prior
`RuntimeError` for "mutably captures ..., which isn't in scope").

Landed on top of the general mutable-capture fix (test_general_mutable_
closure_capture.py) -- that fix is what made this one even POSSIBLE to
attempt, per bugs/CODEGEN_comptime_bracket_parametrized_function_calls_
silently_wrong.md's own prior "deeper than a name-propagation fix"
assessment: transitively propagating capture NAMES alone wasn't enough
without the general closure lifter also being able to thread a capture
through BY REFERENCE at all, which it now can (heap-boxed pointer locals).

Fix (in gimple_codegen.py's `_scan_for_closures`): when computing a nested
(non-async) closure's own free-variable set, also scan its body for calls
to any REGISTERED nested async unit (`self._nested_async_api`, keyed
`f"{enclosing}::{name}"`, already populated by `_compile_nested_async_
functions` before this scan runs) and transitively union in THAT unit's own
captures (value AND mut_names) -- a flat name lookup, not general call-
graph analysis, since the async registration already gives an exact
name -> captures table. `_resolve_and_start_task` (the `create_task(...)`/
`TaskGroup.create_task(...)` call-site lowering) was widened to forward a
mutably-captured name either from a heap-boxed LOCAL of the current
function or from an ALREADY-preloaded `_gimple_mut_ptr` entry (this
closure's own by-reference capture of that same name), instead of only
ever trying `&name` (invalid once inside a closure body, where the name is
never a plain addressable local at all).

Verifying this exact scenario surfaced two FURTHER, separate, genuinely
pre-existing bugs (both fixed here too, since `.wait()`/`comptime` inside a
nested closure was simply never reached by any test before this):
  - Every `.wait()` call site's own `mojo_exc_pending_get()` pending-
    exception check declared its result temp as `_Bool`, but the real
    runtime prototype returns `int` -- invalid under STRICT `-fgimple`
    ("invalid conversion in gimple call"), tolerated everywhere else only
    because every OTHER `.wait()` call site compiled through `gen_func`'s
    LENIENT (non-`__GIMPLE`) top-level-function path, which accepts the
    implicit narrowing like ordinary C. Fixed by declaring it `int`
    instead (works identically as an `if (...)` condition).
  - A `comptime NAME = <value>` declared in an enclosing function was
    invisible to that function's OWN nested closures (silently read as
    `0`, NOT a compile error) -- closures are compiled in a pre-pass
    BEFORE the enclosing function's own body (and hence its `comptime`
    statement) is ever compiled. Fixed by pre-folding an enclosing
    function's own top-level `comptime` statements into `self.
    _comptime_vals` before compiling its nested closures at all.
"""
import os
import subprocess
import tempfile


# cpp-path (gimple_cpp_*) escape-hatch test -- its build harness links
# the C++20-coroutine runtime. doc/COROUTINE.html §5.5 made the A3
# stack-switch backend the default, so pin cpp explicitly.
os.environ.setdefault('MOJO_CORO', 'cpp')
import gimple_codegen
import mojo
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


def _build_and_run(mojo_src: str, timeout: int = 30) -> str:
    """Mirrors test_taskgroup.py's/test_mutable_async_capture.py's
    identical harness shape: real gcc -fgimple / g++ -std=c++20 compile,
    real link via mojo.py's link_executable(cxx=True), real run, real
    stdout."""
    wd = tempfile.mkdtemp(prefix='mojo_transitive_capture_')
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

    r = mojo.link_executable([c_o, async_o, runtime_o, async_runtime_o], exe, cxx=True)
    if r.returncode != 0:
        raise RuntimeError(f"link_executable(cxx=True) failed: {r.stderr}")

    os.chmod(exe, 0o755)
    r = subprocess.run([exe], capture_output=True, text=True, timeout=timeout)
    if r.returncode != 0:
        raise RuntimeError(f"program exited {r.returncode}, stderr={r.stderr}")
    return r.stdout


def test_bare_create_task_from_sibling_closure():
    """Simplest possible transitive-capture shape: `caller()`, an ordinary
    nested closure, calls `create_task(inc())` three times without ever
    itself referencing `inc()`'s own captured `counter`. Before this fix:
    an honest RuntimeError refusal ("mutably captures 'counter', which
    isn't in scope..."), not a silent miscompile -- but still a hard
    compile failure for a real, valid Mojo shape."""
    src = """\
def test_transitive() raises:
    var counter = 0

    @parameter
    async def inc():
        counter += 1

    def caller() raises:
        var t0 = create_task(inc())
        var t1 = create_task(inc())
        var t2 = create_task(inc())
        t0.wait()
        t1.wait()
        t2.wait()

    caller()
    print(counter)


def main() raises:
    test_transitive()
"""
    out = _build_and_run(src)
    check("bare create_task(...) from a sibling closure, transitively "
          "captured -> 3", out == "3\n", detail=repr(out))


def test_taskgroup_10000_stress_from_sibling_closure():
    """test_locks.mojo's OWN exact shape (modulo the Atomic/with-statement
    gaps, still separately tracked): `test_atomic()` (here `caller()`) is a
    DIFFERENT nested closure than the one declaring `inc()`'s captures,
    calling `tg.create_task(inc())` inside SAME-named nested `for _` loops
    with `comptime` bounds -- 100*100 = 10000 total tasks, transitively
    capturing BOTH `counter` (by reference) and `maxI`/`maxJ` (comptime
    constants) across the closure boundary. If the transitive-capture
    propagation, the strict-GIMPLE `.wait()` fix, OR the comptime-
    visibility fix were broken, this would print something other than
    exactly 10000 (most likely 0, from a `comptime` value misread as 0 --
    confirmed via a hand-verified repro before this fix)."""
    src = """\
def test_transitive_tg() raises:
    var counter = 0
    comptime maxI = 100
    comptime maxJ = 100

    @parameter
    async def inc():
        counter += 1

    def caller() raises:
        var tg = TaskGroup()
        for _ in range(0, maxI):
            for _ in range(0, maxJ):
                tg.create_task(inc())
        tg.wait()

    caller()
    print(counter)


def main() raises:
    test_transitive_tg()
"""
    out = _build_and_run(src, timeout=60)
    check("TaskGroup 10,000-task stress test, transitively captured from "
          "a sibling closure -> 10000", out == "10000\n", detail=repr(out))


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
