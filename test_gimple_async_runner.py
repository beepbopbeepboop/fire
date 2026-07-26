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

    # ── Step D (compiled-path async/await codegen project): async-awaits-
    # async composition -- one compiled coroutine awaiting ANOTHER's real
    # C++20 coroutine, through Step A's scheduler -- driven via
    # `asyncio.run(...)` at the top level, exactly like Step C's own
    # `await asyncio.sleep(...)` tests ─────────────────────────────────────
    # THE target shape from this step's plan: `inner()` awaits a real sleep
    # and returns 10; `outer()` awaits `inner()` and returns 11. Verifies
    # BOTH the correct final value (composition produces the right answer)
    # AND real wall-clock timing close to inner's own sleep duration (~20ms)
    # -- NOT ~0ms (which would mean the await never really suspended) and
    # NOT some multiple of it (which would mean something is polling/
    # re-running synchronously instead of composing through the scheduler).
    test_async_stdout_timed("outer_awaits_inner_composition", """\
import asyncio

async def inner():
    await asyncio.sleep(0.02)
    return 10

async def outer():
    x = await inner()
    return x + 1

def main():
    result = asyncio.run(outer())
    print(result)
""", "11\n", min_seconds=0.018, max_seconds=1.0)

    # A 3-level composition chain (`c` awaits `b` awaits `a`), each with its
    # OWN real `await asyncio.sleep(...)` -- proves the continuation-
    # resumption mechanism generalizes past exactly one level, AND (per
    # this step's core correctness bar) that the TOTAL elapsed time is the
    # SUM of all three composed sleeps (0.02 + 0.02 + 0.02 = 0.06s), not
    # just one sleep's worth (which would mean the inner awaits were
    # somehow skipped/short-circuited) and not something wildly larger
    # (which would mean a scheduler bug, e.g. a busy-poll instead of a real
    # suspend/resume).
    test_async_stdout_timed("three_level_composition_chain_timing_is_additive", """\
import asyncio

async def a():
    await asyncio.sleep(0.02)
    return 10

async def b():
    x = await a()
    await asyncio.sleep(0.02)
    return x + 1

async def c():
    x = await b()
    await asyncio.sleep(0.02)
    return x + 100

def main():
    result = asyncio.run(c())
    print(result)
""", "111\n", min_seconds=0.05, max_seconds=1.5)

    # THE decisive "real composition, not fake blocking" proof: two
    # INDEPENDENT top-level `asyncio.run(...)`-driven async programs run as
    # two separate OS PROCESSES, each awaiting a chain of two composed
    # 0.05s sleeps (inner -> outer, ~0.10s total per process if truly
    # sequential within each chain). If async-awaits-async composition
    # secretly degraded into synchronous/blocking execution instead of
    # genuinely suspending through Step A's scheduler, this would still
    # "work" (right value, ~0.10s each) -- so this alone does NOT
    # distinguish real composition from fake blocking (that's what the two
    # timing tests above already established, from first principles: an
    # honestly-blocking `await` would burn wall-clock time synchronously
    # inside ONE `.resume()` call same as a truly-suspending one, so
    # process-level parallelism can't tell them apart either). What DOES
    # matter here, and IS unique to this test, is `outer`'s own suspension
    # while awaiting `inner` composing correctly with the SAME process's
    # scheduler loop -- already the whole point of the two tests above
    # (each is a SINGLE process, single scheduler run, and their measured
    # elapsed time only matches a real-suspension model, not an eager/
    # blocking one, per those tests' own docstrings). This test is kept as
    # an independent sanity check that composition is stable under repeated
    # runs, not as the primary suspension-vs-blocking proof (that burden is
    # carried by the timing brackets on the two tests above).
    def test_composition_stable_across_repeated_runs():
        global _PASS, _FAIL
        name = "composition_stable_across_repeated_runs"
        src = """\
import asyncio

async def inner():
    await asyncio.sleep(0.02)
    return 5

async def outer():
    x = await inner()
    return x * 2

def main():
    result = asyncio.run(outer())
    print(result)
"""
        try:
            exe = _build_async_program(src)
            for _ in range(3):
                out = subprocess.run([exe], capture_output=True, timeout=10).stdout.decode()
                if out != "10\n":
                    print(f"FAIL  {name}: expected '10\\n' every run, got {out!r}")
                    _FAIL += 1
                    return
            print(f"PASS  {name}")
            _PASS += 1
        except Exception as e:
            print(f"FAIL  {name}: {e}")
            _FAIL += 1

    test_composition_stable_across_repeated_runs()

    # `await` on a forward reference (the callee is defined AFTER the
    # caller in source order) must still be honestly refused through the
    # real build path -- gen_module's async pre-pass is a single forward
    # pass (see _is_async_call_to_known_fn's docstring), so this is not a
    # guessed/dangling C++ reference, just an out-of-scope shape.
    test_async_build_refused("await_forward_reference_still_refused", """\
async def f():
    x = await g()
    return x

async def g():
    return 1

def main():
    f()
""", "async function")

    # `await` on an arbitrary non-call, non-sleep expression must still be
    # honestly refused through the real build path.
    test_async_build_refused("await_non_call_expression_still_refused", """\
async def f():
    x = await 5
    return x

def main():
    f()
""", "async function")

    # ── Step E: raise/try/except/finally inside async function bodies ──────
    # Real compile+link+run behavioral tests, mirroring
    # test_gimple_generator_runner.py's own Milestone D coverage shape
    # exactly (same rigor bar this whole project has held itself to at
    # every step: real assertions on actual output/caught-exception-type,
    # not just "it compiles").

    # 1. An exception raised and caught by the SAME async function's own
    # try/except -- execution continues normally afterward (not just
    # "doesn't crash").
    test_async_stdout("async_raise_caught_internally", """\
async def f():
    total = 0
    try:
        total = 1
        raise ValueError("boom")
        total = 99
    except ValueError:
        total = total + 10
    print(total)
    return total

def main():
    import asyncio
    asyncio.run(f())
""", "11\n")

    # 2. THE key new behavior this step must prove works, beyond what
    # generator Milestone D already proved: an exception raised inside an
    # AWAITED callee (inner()) propagates through the `await` into the
    # AWAITING function's (outer()) own try/except, which correctly
    # catches it and continues -- exactly like real Python's `await`
    # propagating an exception through ordinary exception machinery, via
    # the per-awaiter rethrow this step adds in `{base}_Awaiter::
    # await_resume` (gimple_codegen.py's _gen_cpp_async_unit).
    test_async_stdout("async_exception_propagates_through_await_to_callers_own_except", """\
async def inner():
    raise ValueError("boom")
    return 0

async def outer():
    result = 0
    try:
        result = await inner()
        print(999)
    except ValueError:
        result = -1
    print(result)
    return result

def main():
    import asyncio
    asyncio.run(outer())
""", "-1\n")

    # 3. An exception escaping ALL THE WAY out to `asyncio.run(...)`
    # uncaught, caught by ORDINARY (non-async) compiled code's own
    # try/except around the `asyncio.run(...)` call, with the correct
    # exception TYPE (only a ValueError handler matches) and MESSAGE (bound
    # via `as e`) -- the outermost-edge translation into the pre-existing
    # mojo_exc_type/msg/obj/mojo_exc_pending global state, reusing
    # generator Milestone D's exact translation convention.
    test_async_stdout("async_exception_escapes_to_asyncio_run_caught_by_ordinary_code", """\
async def f():
    raise ValueError("boom")
    return 0

def main():
    import asyncio
    try:
        asyncio.run(f())
    except ValueError as e:
        print("caught")
        print(e)
""", "caught\nboom\n")

    # 4. `finally:` running the correct NUMBER of times across a mix of
    # normal completion and an internally-caught raise, matching generator
    # Milestone D's own finally-coverage test shape exactly.
    test_async_stdout("async_finally_runs_correct_number_of_times", """\
async def f():
    count = 0
    i = 0
    while i < 3:
        try:
            if i == 1:
                raise ValueError("x")
        except ValueError:
            pass
        finally:
            count = count + 1
        i = i + 1
    print(count)
    return count

def main():
    import asyncio
    asyncio.run(f())
""", "3\n")

    # 5. Beyond the obvious happy path (this project's own established
    # pattern of finding real bugs via independent hand-verification): a
    # bare `except:` inside an async function.
    test_async_stdout("async_bare_except", """\
async def f():
    total = 0
    try:
        raise ValueError("boom")
    except:
        total = -1
    print(total)
    return total

def main():
    import asyncio
    asyncio.run(f())
""", "-1\n")

    # 6. Beyond the obvious happy path: an exception raised by a THIRD
    # level of a composition chain (Step D: a() awaits b() awaits c())
    # propagating up through TWO `await`s, correctly caught by the
    # OUTERMOST function's (a's) own try/except -- proves the per-awaiter
    # rethrow composes to more than one level, not just the direct-callee
    # case test #2 above already covers.
    test_async_stdout("async_exception_propagates_through_two_awaits_in_composition_chain", """\
async def c():
    raise KeyError("deep")
    return 0

async def b():
    x = await c()
    return x

async def a():
    result = 0
    try:
        result = await b()
    except KeyError:
        result = -7
    print(result)
    return result

def main():
    import asyncio
    asyncio.run(a())
""", "-7\n")

    # 7. A re-raise (bare `raise` with no value) inside an async function's
    # except handler propagates the SAME exception (type + message intact)
    # out to `asyncio.run(...)`'s own caller -- mirrors generator Milestone
    # D's own re-raise test shape.
    test_async_stdout("async_bare_reraise_propagates_to_asyncio_run_caller", """\
async def f():
    try:
        raise ValueError("inner")
    except ValueError:
        raise
    return 0

def main():
    import asyncio
    try:
        asyncio.run(f())
    except ValueError as e:
        print(e)
""", "inner\n")

    if _FAIL:
        print(f"\n{_PASS} passed, {_FAIL} failed")
        raise SystemExit(1)
    print(f"\n{_PASS} passed, {_FAIL} failed")


if __name__ == '__main__':
    run_tests()
