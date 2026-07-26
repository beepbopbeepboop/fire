"""REAL behavioral test for Step B (compiled-path async/await codegen,
async_runtime.h Step A's sibling): compiles a Mojo async function's dual
output (.c/.ci via gcc -fgimple, .cpp via g++ -std=c++20) for real, links it
together with Step A's runtime/mojo_async_runtime.cpp AND runtime/
mojo_runtime.c via mojo.py's link_executable(cxx=True), RUNS the resulting
binary, and asserts on its ACTUAL stdout — mirrors
test_gimple_generator_runner.py's role/shape exactly, but for the async
promise_type/extern "C" API (_start/_is_done/_value/_destroy, no `_resume`
— see gimple_codegen.GimpleGen._gen_cpp_async_unit's docstring) instead of
the generator one.
"""
import os
import subprocess
import tempfile
import time

from build_config import find_gcc, find_gxx
import gimple_codegen
import mojo

HERE = os.path.dirname(os.path.abspath(__file__))
RUNTIME_DIR = os.path.join(HERE, 'runtime')
RUNTIME_C = os.path.join(RUNTIME_DIR, 'mojo_runtime.c')
ASYNC_RUNTIME_CPP = os.path.join(RUNTIME_DIR, 'mojo_async_runtime.cpp')

_PASS = 0
_FAIL = 0


def _build_async_program(mojo_src: str) -> str:
    """Compile mojo_src (which must contain at least one Step-B-supported
    async function) to a real executable: .c/.ci -> gcc -fgimple -c, .cpp
    (the async function's own generated coroutine unit) -> g++ -std=c++20
    -c, runtime/mojo_runtime.c -> gcc -c, runtime/mojo_async_runtime.cpp
    (Step A's scheduler) -> g++ -std=c++20 -c, then link all four via
    mojo.py's link_executable(cxx=True) (g++ as the final link driver, so
    the C++ standard library / coroutine-support symbols resolve) — mirrors
    test_gimple_generator_runner.py's _build_generator_program exactly, plus
    the one extra object file this project's Step A added."""
    c_code, cpp_code = gimple_codegen.compile_to_gimple_with_cpp(mojo_src)
    if not cpp_code:
        raise RuntimeError(
            "expected a non-empty generated .cpp — this source doesn't "
            "actually contain a Step-B-supported async function")

    wd = tempfile.mkdtemp(prefix='mojo_async_runner_')
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

    gcc = find_gcc()
    gxx = find_gxx()

    r = subprocess.run([gcc, '-fgimple', f'-I{RUNTIME_DIR}', '-c', '-o', c_o, c_path],
                        capture_output=True, text=True, timeout=30)
    if r.returncode != 0:
        raise RuntimeError(f"gcc -fgimple compile of .c failed: {r.stderr}")

    r = subprocess.run([gxx, '-std=c++20', f'-I{RUNTIME_DIR}', '-c', '-o', async_o, cpp_path],
                        capture_output=True, text=True, timeout=30)
    if r.returncode != 0:
        raise RuntimeError(f"g++ compile of .cpp failed: {r.stderr}")

    r = subprocess.run([gcc, f'-I{RUNTIME_DIR}', '-c', '-o', runtime_o, RUNTIME_C],
                        capture_output=True, text=True, timeout=30)
    if r.returncode != 0:
        raise RuntimeError(f"gcc compile of mojo_runtime.c failed: {r.stderr}")

    r = subprocess.run([gxx, '-std=c++20', f'-I{RUNTIME_DIR}', '-c', '-o', async_runtime_o, ASYNC_RUNTIME_CPP],
                        capture_output=True, text=True, timeout=30)
    if r.returncode != 0:
        raise RuntimeError(f"g++ compile of mojo_async_runtime.cpp failed: {r.stderr}")

    r = mojo.link_executable([c_o, async_o, runtime_o, async_runtime_o], exe, cxx=True)
    if r.returncode != 0:
        raise RuntimeError(f"link_executable(cxx=True) failed: {r.stderr}")

    os.chmod(exe, 0o755)
    return exe


def test_async_stdout(name: str, mojo_src: str, expected_stdout: str):
    global _PASS, _FAIL
    try:
        exe = _build_async_program(mojo_src)
        out = subprocess.run([exe], capture_output=True, timeout=10).stdout.decode()
        if out == expected_stdout:
            print(f"PASS  {name}")
            _PASS += 1
        else:
            print(f"FAIL  {name}: expected {expected_stdout!r}, got {out!r}")
            _FAIL += 1
    except Exception as e:
        print(f"FAIL  {name}: {e}")
        _FAIL += 1


def test_async_build_refused(name: str, mojo_src: str, expected_substr: str):
    """REAL behavioral counterpart of test_gimple.py's test_raises, but
    through the actual dual-output (.c + .cpp) build entry point
    (compile_to_gimple_with_cpp) this file's other tests use to build+link+
    run real executables — not just compile_to_gimple. Asserts this source
    is honestly refused (raises with a message containing expected_substr)
    rather than silently producing the old eager-execution .cpp that would
    otherwise link and run fine while being semantically wrong.
    See bugs/CODEGEN_compiled_async_eager_execution_semantic_mismatch.md."""
    global _PASS, _FAIL
    try:
        gimple_codegen.compile_to_gimple_with_cpp(mojo_src)
    except Exception as e:
        if expected_substr in str(e):
            print(f"PASS  {name}")
            _PASS += 1
        else:
            print(f"FAIL  {name}: wrong error: {e}")
            _FAIL += 1
        return
    print(f"FAIL  {name}: expected an exception containing {expected_substr!r}, "
          f"compile_to_gimple_with_cpp succeeded instead")
    _FAIL += 1


def test_async_stdout_timed(name: str, mojo_src: str, expected_stdout: str,
                             min_seconds: float, max_seconds: float):
    """Step C's own rigor bar, mirroring test_async_runtime_scaffold.py's
    (Step A) real wall-clock-timing verification: builds+links+runs a real
    executable and asserts BOTH the correct stdout (proving the coroutine
    actually ran and `asyncio.run(...)` actually delivered its value) AND
    that the measured real elapsed time is close to the requested sleep
    duration, not ~0 (which would mean `await asyncio.sleep(...)` never
    really suspended -- a faked/instant await) and not wildly larger
    (which would mean something is stalling well beyond the timer, e.g. a
    scheduler bug). `min_seconds`/`max_seconds` bracket the expected sleep
    duration with the same kind of scheduling-slack floor Step A's own
    test used (an ~5-10ms floor below the target, generous headroom
    above)."""
    global _PASS, _FAIL
    try:
        exe = _build_async_program(mojo_src)
        t0 = time.monotonic()
        run = subprocess.run([exe], capture_output=True, timeout=10)
        dt = time.monotonic() - t0
        out = run.stdout.decode()
        if out != expected_stdout:
            print(f"FAIL  {name}: expected stdout {expected_stdout!r}, got {out!r}")
            _FAIL += 1
            return
        if not (min_seconds <= dt <= max_seconds):
            print(f"FAIL  {name}: expected wall-clock time in "
                  f"[{min_seconds}, {max_seconds}]s, measured {dt:.4f}s -- "
                  "either the await never really suspended (too fast) or "
                  "something stalled well beyond the timer (too slow)")
            _FAIL += 1
            return
        print(f"PASS  {name} (dt={dt:.4f}s)")
        _PASS += 1
    except Exception as e:
        print(f"FAIL  {name}: {e}")
        _FAIL += 1


def run_tests():
    # REVISED (bugs/CODEGEN_compiled_async_eager_execution_semantic_
    # mismatch.md): Step B's first cut consumed an async call's result via
    # `x = f(); print(x)` / `print(f())`, which independent hand-
    # verification against real CPython found to fuse construct+schedule+
    # run+read+destroy into ONE expression's lowering -- eagerly running
    # the coroutine's body the instant it's referenced, with no `await`
    # anywhere, unlike real Python (and this project's own interpreter's
    # MojoCoroutine) where calling an async function only ever produces a
    # not-yet-started coroutine object. Fixed by narrowing this step's
    # scope: the ONLY supported call shape is now a bare, value-discarding
    # statement (`f()` alone) -- see test_async_build_refused's tests below
    # for the honest-refusal counterpart proving the old eager-execution
    # shapes no longer silently build.
    #
    # THE key correctness bar from Step B's (revised) plan: "calling f()
    # must NOT run the body immediately -- nothing without a real `await`/
    # driver may ever do so." A bare, value-discarding `f()` statement
    # constructs the coroutine and destroys it WITHOUT ever scheduling/
    # running it (see _gen_stmt_ExprStmt's async special case), so a
    # `print(1)` side effect placed before the `return` must NEVER fire --
    # if this codegen were instead (incorrectly) eager, the output below
    # would be "1\n" instead of "" (empty). This is the one place, in real
    # compiled+linked+run Mojo source (not just a hand-verified .cpp
    # detail or a compile-time-only refusal check), where this step's
    # laziness requirement is independently observable.
    test_async_stdout("bare_async_call_never_runs_body", """\
async def f():
    print(1)
    return 42

def main():
    f()
""", "")

    # Same bar, multiple calls across two distinct async functions in one
    # module -- confirms the per-module bookkeeping (self._supported_async/
    # self._async_api, each keyed by name) doesn't cross-contaminate AND
    # that laziness holds no matter how many times a bare call happens.
    test_async_stdout("multiple_bare_async_calls_never_run_bodies", """\
async def f():
    print(1)
    return 42

async def g():
    print(2)
    return 7

def main():
    f()
    g()
    f()
""", "")

    # A multi-statement body (assignment + a while loop) ending in a scalar
    # `return`, called bare -- confirms this step's async body translation
    # genuinely reuses the SAME shared _cpp_stmt/_cpp_expr whitelist
    # emitter the generator path already has (assignment, AugAssignStmt,
    # WhileStmt, IfStmt, ...), not a separate narrower one that only
    # happens to handle a bare `return <literal>`, AND that it still
    # compiles+links+runs cleanly (no crash) even though this step has no
    # mechanism to observe the computed value from outside.
    test_async_stdout("async_function_multi_statement_body_compiles_and_runs", """\
async def f():
    total = 0
    i = 0
    while i < 5:
        total = total + i
        i = i + 1
    return total

def main():
    f()
""", "")

    # A `Float64`-typed scalar return, called bare -- confirms this isn't
    # hardcoded to int64_t; the promise's `result` field resolves to
    # `double` and the whole unit still compiles+links+runs cleanly.
    test_async_stdout("async_function_float_return_compiles_and_runs", """\
async def f():
    return 3.5

def main():
    f()
""", "")

    # The bug's exact repro, through the REAL dual-output build path (not
    # just compile_to_gimple as in test_gimple.py) -- must be refused, not
    # silently compiled into the old eager-execution shape.
    test_async_build_refused("value_consuming_assignment_refused_at_real_build", """\
async def f():
    return 42

def main():
    x = f()
    print(x)
""", "consumed as a value")

    # Same bug, argument-position shape (`print(f())`, no intermediate
    # assignment) -- confirms the refusal isn't assignment-specific.
    test_async_build_refused("value_consuming_print_arg_refused_at_real_build", """\
async def f():
    return 42

def main():
    print(f())
""", "consumed as a value")

    # ── Step C (compiled-path async/await codegen project): real `await`
    # on a real timer, driven via an explicit `asyncio.run(...)` top-level
    # bridge ────────────────────────────────────────────────────────────
    # THE core proof for this step: an `async def` that does `await
    # asyncio.sleep(0.05)` then `return 42`, driven to completion by
    # `asyncio.run(f())` at the top level, prints the correct value AND
    # genuinely took ~50ms of real wall-clock time -- not ~0ms (which would
    # mean the `co_await` never actually suspended) and not some huge
    # unexplained stall. Mirrors test_async_runtime_scaffold.py's own
    # >= 45ms / < 1000ms bracketing exactly, applied here to a REAL
    # Mojo-source-compiled program for the first time.
    test_async_stdout_timed("await_sleep_then_return_driven_by_asyncio_run", """\
import asyncio

async def f():
    await asyncio.sleep(0.05)
    return 42

def main():
    result = asyncio.run(f())
    print(result)
""", "42\n", min_seconds=0.045, max_seconds=1.0)

    # A longer sleep (0.15s) -- confirms the timing isn't a coincidence of
    # one specific duration, and gives a wider margin between the sleep
    # floor and process-startup/scheduling noise.
    test_async_stdout_timed("await_longer_sleep_then_return_driven_by_asyncio_run", """\
import asyncio

async def f():
    await asyncio.sleep(0.15)
    return 7

def main():
    result = asyncio.run(f())
    print(result)
""", "7\n", min_seconds=0.13, max_seconds=1.2)

    # A Float64-typed return value through the same await-then-drive path --
    # confirms this isn't hardcoded to int64_t (mirrors
    # async_function_float_return_compiles_and_runs above, but for the real
    # await/asyncio.run path instead of the bare-discarded-call one).
    test_async_stdout_timed("await_sleep_then_return_float_driven_by_asyncio_run", """\
import asyncio

async def f():
    await asyncio.sleep(0.05)
    return 2.5

def main():
    result = asyncio.run(f())
    print(result)
""", "2.5\n", min_seconds=0.045, max_seconds=1.0)

    # A multi-statement body (assignment + a while loop) BEFORE the
    # `await`, ending in a scalar `return` -- confirms ordinary statements
    # and the real suspension point compose correctly through the shared
    # _cpp_stmt/_cpp_expr whitelist emitter, not just a single-statement
    # body.
    test_async_stdout_timed("multi_statement_body_then_await_then_return", """\
import asyncio

async def f():
    total = 0
    i = 0
    while i < 5:
        total = total + i
        i = i + 1
    await asyncio.sleep(0.05)
    return total

def main():
    result = asyncio.run(f())
    print(result)
""", "10\n", min_seconds=0.045, max_seconds=1.0)

    # `x = f()` (no `asyncio.run`) must STILL be honestly refused through
    # the real dual-output build path -- re-verifying Step B's bug fix
    # (9a3a62b) is unregressed by Step C's changes, now with a body that
    # actually contains a real `await` too (not just the old zero-
    # suspension-point shape), through the SAME real build entry point the
    # rest of this file uses.
    test_async_build_refused("bare_assignment_with_real_await_still_refused", """\
import asyncio

async def f():
    await asyncio.sleep(0.01)
    return 42

def main():
    x = f()
    print(x)
""", "consumed as a value")

    # `await` on anything other than `asyncio.sleep(...)` -- here, one Mojo
    # async function awaiting ANOTHER -- must still be honestly refused
    # through the real build path (async-awaits-async composition is
    # Step D, not this step).
    test_async_build_refused("await_on_another_async_function_still_refused", """\
async def g():
    return 1

async def f():
    x = await g()
    return x

def main():
    f()
""", "async function")

    if _FAIL:
        print(f"\n{_PASS} passed, {_FAIL} failed")
        raise SystemExit(1)
    print(f"\n{_PASS} passed, {_FAIL} failed")


if __name__ == '__main__':
    run_tests()
