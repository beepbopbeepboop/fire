"""REAL behavioral test for Step B (compiled-path async/await codegen,
async_runtime.h Step A's sibling): compiles a Mojo async function's dual
output (.c/.ci via gcc -fgimple, .cpp via g++ -std=c++20) for real, links it
together with Step A's runtime/mojo_async_runtime.cpp AND runtime/
fire_runtime.c via fire.py's link_executable(cxx=True), RUNS the resulting
binary, and asserts on its ACTUAL stdout — mirrors
test_gimple_generator_runner.py's role/shape exactly, but for the async
promise_type/extern "C" API (_start/_is_done/_value/_destroy, no `_resume`
— see gimple_codegen.GimpleGen._gen_cpp_async_unit's docstring) instead of
the generator one.
"""
import os
import socket
import subprocess
import tempfile
import time

from build_config import find_gcc, find_gxx
import gimple_codegen
import fire

HERE = os.path.dirname(os.path.abspath(__file__))
RUNTIME_DIR = os.path.join(HERE, 'runtime')
RUNTIME_C = os.path.join(RUNTIME_DIR, 'fire_runtime.c')
ASYNC_RUNTIME_CPP = os.path.join(RUNTIME_DIR, 'mojo_async_runtime.cpp')

_PASS = 0
_FAIL = 0


def _build_async_program(mojo_src: str) -> str:
    """Compile mojo_src (which must contain at least one Step-B-supported
    async function) to a real executable: .c/.ci -> gcc -fgimple -c, .cpp
    (the async function's own generated coroutine unit) -> g++ -std=c++20
    -c, runtime/fire_runtime.c -> gcc -c, runtime/mojo_async_runtime.cpp
    (Step A's scheduler) -> g++ -std=c++20 -c, then link all four via
    fire.py's link_executable(cxx=True) (g++ as the final link driver, so
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
    runtime_o = os.path.join(wd, 'fire_runtime.o')
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
        raise RuntimeError(f"gcc compile of fire_runtime.c failed: {r.stderr}")

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
    See CODEGEN_compiled_async_eager_execution_semantic_mismatch."""
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


def test_async_value_consumption_is_lazy(name: str, mojo_src: str, forbidden_marker_line: str):
    """Verifies a VALUE-CONSUMING reference to a compiled async function call
    (`x = f()`, `print(f())`, an `await`-driven call whose body itself
    hasn't awaited yet, ...) now correctly matches real Python/this
    project's own interpreter semantics: calling an async function NEVER
    runs its body immediately -- it only produces a not-yet-started
    coroutine object (see commit f5d9021's `_lower_call` change, which
    replaced the OLD honest "consumed as a value" whole-module refusal
    9a3a62b had put in place for the eager-execution bug -- see
    CODEGEN_compiled_async_eager_execution_semantic_mismatch --
    with a real, lazy `MojoAsync *` handle construction instead of ever
    reviving eager execution). `fire.py run` (the interpreter) on the exact
    same source independently confirms this is the right shape: it prints
    `<myinterpreter.MojoCoroutine object at 0x...>`, never the awaited
    value -- the compiled path's own printed representation is a bare
    pointer decimal (no repr-string formatting for MojoAsync* implemented
    yet), a real but separate, purely cosmetic gap, NOT a semantic one.

    `forbidden_marker_line` is a source-distinguishing literal (e.g. a
    large sentinel int printed as f's OWN first statement) that must NOT
    appear anywhere in the real compiled program's stdout if the body
    genuinely never ran -- mirrors bare_async_call_never_runs_body's/
    multiple_bare_async_calls_never_run_bodies's identical side-effect-
    observation technique just above, extended to the value-consuming
    shapes those two tests don't cover."""
    global _PASS, _FAIL
    try:
        exe = _build_async_program(mojo_src)
        out = subprocess.run([exe], capture_output=True, timeout=10).stdout.decode()
        if forbidden_marker_line in out:
            print(f"FAIL  {name}: async function body ran (found {forbidden_marker_line!r} "
                  f"in stdout {out!r}) -- value-consuming call must stay lazy")
            _FAIL += 1
            return
        print(f"PASS  {name}")
        _PASS += 1
    except Exception as e:
        print(f"FAIL  {name}: {e}")
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


def _recv_one_mojo_src(fd: int) -> str:
    """The one Mojo source shape every Step F test below builds: an async
    function that awaits exactly one byte off `fd` (embedded as a literal
    int -- there is no Mojo-level socket type yet to obtain a runtime fd
    from any other way, see gimple_codegen._is_asyncio_sock_recv_call's
    docstring) and prints the resulting int64_t (0-255 on success, -1 on
    EOF, -2 on a real read error) via the ordinary asyncio.run(...) bridge,
    exactly mirroring every other test_async_stdout_timed case in this
    file."""
    return f"""\
import asyncio

async def recv_one():
    fd = {fd}
    b = await asyncio.sock_recv(fd)
    return b

def main():
    x = asyncio.run(recv_one())
    print(x)
"""


def test_sock_recv_delayed_write(name: str, delay_seconds: float):
    """THE core proof for Step F, mirroring test_async_stdout_timed's role
    for Step C's asyncio.sleep(...) exactly but for real socket I/O: a
    compiled async function awaiting `asyncio.sock_recv(fd)` on one end of a
    real `socket.socketpair()`, while THIS (parent) process writes a single
    real byte to the other end only after a genuine delay. Asserts BOTH the
    correct byte value was received (proving the actual `read(2)` in
    `_mojoasync_SockRecvAwaiter::await_resume` ran and its result correctly
    round-tripped back out through `asyncio.run(...)`) AND that the
    measured wall-clock time is close to `delay_seconds`, not ~0 (which
    would mean the coroutine never really suspended on the reactor at all)
    and not wildly larger (a scheduler/reactor stall) -- exactly the same
    two-part rigor bar test_async_stdout_timed already established for the
    timer queue, now applied to the kqueue read-reactor path instead.

    The child process is spawned via subprocess.Popen with the read end's
    fd passed through `pass_fds` (kept open at the SAME fd number across
    exec, which is exactly why that literal number can be safely embedded
    into the Mojo source built just before spawning) -- the write end stays
    in this (parent) Python process, which performs the real delayed
    os.write() itself; nothing about the actual reactor mechanism is
    mocked or simulated in either process."""
    global _PASS, _FAIL
    read_sock, write_sock = socket.socketpair()
    try:
        read_fd = read_sock.fileno()
        mojo_src = _recv_one_mojo_src(read_fd)
        exe = _build_async_program(mojo_src)

        byte_value = 0x41  # 'A'
        t0 = time.monotonic()
        proc = subprocess.Popen([exe], stdout=subprocess.PIPE,
                                 pass_fds=(read_fd,))
        # The child inherited its own copy of read_fd across exec; this
        # process's copy (and the never-inherited write_sock) must stay
        # open on THIS side so the delayed write below actually reaches
        # the child's kqueue registration.
        time.sleep(delay_seconds)
        write_sock.send(bytes([byte_value]))
        try:
            out, _ = proc.communicate(timeout=10)
        finally:
            dt = time.monotonic() - t0
        expected = f"{byte_value}\n"
        if out.decode() != expected:
            print(f"FAIL  {name}: expected stdout {expected!r}, got {out.decode()!r}")
            _FAIL += 1
            return
        # Generous headroom above (process startup + build already excluded
        # -- only the Popen-to-exit window is timed -- but real scheduling/
        # CI-machine noise still needs slack), a real floor below matching
        # test_async_stdout_timed's own ~10ms-below-target convention.
        min_seconds, max_seconds = delay_seconds - 0.03, max(1.0, delay_seconds * 5)
        if not (min_seconds <= dt <= max_seconds):
            print(f"FAIL  {name}: expected wall-clock time in "
                  f"[{min_seconds}, {max_seconds}]s, measured {dt:.4f}s -- "
                  "either sock_recv never really suspended on the reactor "
                  "(too fast) or something stalled well beyond the write "
                  "(too slow)")
            _FAIL += 1
            return
        print(f"PASS  {name} (dt={dt:.4f}s)")
        _PASS += 1
    except Exception as e:
        print(f"FAIL  {name}: {e}")
        _FAIL += 1
    finally:
        read_sock.close()
        write_sock.close()


def test_sock_recv_already_readable_before_await(name: str):
    """Edge case beyond the obvious happy path (per this project's own
    established pattern of budgeting real time for at least one edge case
    at every step -- see this step's own docstrings/plan): the peer writes
    its byte BEFORE the child process (and therefore its
    `mojo_async_register_read` kqueue registration) even exists yet, so the
    fd is already readable at the moment `await_suspend` registers interest
    in it. Real kqueue semantics report an already-satisfied EVFILT_READ
    interest as ready on the very next kevent() call (no special-cased
    "check readability before registering" logic exists anywhere in this
    codegen or in Step A's reactor -- see _mojoasync_SockRecvAwaiter's own
    docstring in gimple_codegen.py), so this should resume on the process's
    very first scheduler turn: asserts the SAME correct byte value, plus a
    generous-but-real upper bound on wall-clock time (well under a second)
    to positively confirm this path does NOT silently degenerate into
    waiting for some unrelated/nonexistent event."""
    global _PASS, _FAIL
    read_sock, write_sock = socket.socketpair()
    try:
        read_fd = read_sock.fileno()
        byte_value = 0x5A  # 'Z'
        write_sock.send(bytes([byte_value]))
        mojo_src = _recv_one_mojo_src(read_fd)
        exe = _build_async_program(mojo_src)

        t0 = time.monotonic()
        proc = subprocess.Popen([exe], stdout=subprocess.PIPE,
                                 pass_fds=(read_fd,))
        out, _ = proc.communicate(timeout=10)
        dt = time.monotonic() - t0
        expected = f"{byte_value}\n"
        if out.decode() != expected:
            print(f"FAIL  {name}: expected stdout {expected!r}, got {out.decode()!r}")
            _FAIL += 1
            return
        if dt >= 0.5:
            print(f"FAIL  {name}: already-readable sock_recv took {dt:.4f}s "
                  "(expected near-instant resumption, well under 0.5s) -- "
                  "looks like it stalled instead of resuming on the first "
                  "scheduler turn")
            _FAIL += 1
            return
        print(f"PASS  {name} (dt={dt:.4f}s)")
        _PASS += 1
    except Exception as e:
        print(f"FAIL  {name}: {e}")
        _FAIL += 1
    finally:
        read_sock.close()
        write_sock.close()


def test_sock_recv_eof(name: str):
    """A second edge case: the peer closes its end WITHOUT ever writing
    anything, rather than sending a byte -- a real, valid `recv()`/`read()`
    outcome (0 bytes read) distinct from "still waiting" and from "got a
    byte", which `_mojoasync_SockRecvAwaiter::await_resume` reports as -1
    (see its docstring). Confirms this third possible outcome round-trips
    correctly too, not just the byte-received happy path."""
    global _PASS, _FAIL
    read_sock, write_sock = socket.socketpair()
    try:
        read_fd = read_sock.fileno()
        mojo_src = _recv_one_mojo_src(read_fd)
        exe = _build_async_program(mojo_src)

        proc = subprocess.Popen([exe], stdout=subprocess.PIPE,
                                 pass_fds=(read_fd,))
        time.sleep(0.05)
        write_sock.close()  # close with nothing ever sent -> peer sees EOF
        out, _ = proc.communicate(timeout=10)
        expected = "-1\n"
        if out.decode() != expected:
            print(f"FAIL  {name}: expected stdout {expected!r}, got {out.decode()!r}")
            _FAIL += 1
            return
        print(f"PASS  {name}")
        _PASS += 1
    except Exception as e:
        print(f"FAIL  {name}: {e}")
        _FAIL += 1
    finally:
        read_sock.close()
        write_sock.close()  # already closed above; socket.close() is idempotent


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
    # just compile_to_gimple as in test_gimple.py) -- USED to require an
    # honest whole-module refusal (9a3a62b), because Step B's first cut
    # fused construct+schedule+run+read+destroy into ONE expression's
    # lowering for ANY value-consuming call, silently running the body
    # immediately (a real semantic bug: real Python never runs an async
    # function's body just from calling it). Commit f5d9021 later replaced
    # that refusal with a real, lazy `MojoAsync *` handle construction
    # instead (matching real Python's "calling an async fn returns a
    # not-yet-started coroutine object" and this project's own
    # interpreter's MojoCoroutine) -- a genuine capability gain, not a
    # revival of the eager-execution bug: independently verified via
    # `fire.py run` on this exact source (prints
    # `<myinterpreter.MojoCoroutine object at 0x...>`, never `42`) AND via
    # the side-effect check below (f's own `print(999999)` must never
    # appear in the compiled program's stdout -- proving the body still
    # genuinely never runs, exactly like the bare-discarded-call shape
    # above). See test_async_value_consumption_is_lazy's docstring.
    test_async_value_consumption_is_lazy("value_consuming_assignment_lazily_constructs_and_never_runs_body", """\
async def f():
    print(999999)
    return 42

def main():
    x = f()
    print(2)
""", "999999")

    # Same shape, argument-position (`print(f())`, no intermediate
    # assignment) -- confirms laziness isn't assignment-specific either.
    test_async_value_consumption_is_lazy("value_consuming_print_arg_lazily_constructs_and_never_runs_body", """\
async def f():
    print(999999)
    return 42

def main():
    print(f())
""", "999999")

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

    # `x = f()` (no `asyncio.run`) with a body that contains a real `await`
    # too (not just the old zero-suspension-point shape) -- same legitimate
    # capability gain as the two tests above (f5d9021), re-verified here
    # with a real `await` inside f's body: `x` still just binds the lazily-
    # constructed, not-yet-scheduled coroutine handle -- f's body (proven
    # via its own `print(999999)` side effect) never runs, so the real
    # `await asyncio.sleep(...)` inside it never fires either.
    test_async_value_consumption_is_lazy("bare_assignment_with_real_await_lazily_constructs_and_never_runs_body", """\
import asyncio

async def f():
    print(999999)
    await asyncio.sleep(0.01)
    return 42

def main():
    x = f()
    print(2)
""", "999999")

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
    # caller in source order) -- USED to be honestly refused (gen_module's
    # async pre-pass over top-level `stmts` compiles callees before callers
    # in ONE single forward pass, so a caller compiled before its later-
    # defined callee can't yet resolve it). gen_module now runs a genuine
    # SECOND pass (see the "Second pass for async functions NOT in top-
    # level stmts" loop and its sibling for async generators) that retries
    # any function left uncompiled after pass 1 against the now-larger
    # self._async_api -- so `f` (which failed pass 1's eligibility check
    # because `g` wasn't compiled yet) succeeds on pass 2, once `g` (defined
    # later in source, but compiled earlier in pass 1's iteration since pass
    # 1 still walks ALL of `stmts` in order before pass 2 starts) is
    # already known. This is a genuine capability gain, not a guessed/
    # dangling C++ reference -- verified below with a REAL `await
    # asyncio.sleep(...)` inside the forward-referenced callee `g` (proving
    # actual suspend/resume through the real callee, not some accidental
    # zero-op path) and a correctness-bearing return value threaded through
    # TWO stack frames (`g` returns 99, `f` returns `g()+1` = 100).
    test_async_stdout_timed("await_forward_reference_now_supported_via_second_pass", """\
import asyncio

async def f():
    x = await g()
    return x + 1

async def g():
    await asyncio.sleep(0.05)
    return 99

def main():
    result = asyncio.run(f())
    print(result)
""", "100\n", min_seconds=0.045, max_seconds=1.0)

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

    # ── Step F: real socket I/O via `await asyncio.sock_recv(<fd>)` ────────
    # Reuses Step A's own kqueue reactor (mojo_async_register_read) EXACTLY
    # as it already is -- these tests are the Mojo-compiled-codegen sibling
    # of Step A's own hand-written socketpair proof
    # (test_async_runtime_scaffold.py's HAND_WRITTEN_MAIN_CPP), proving the
    # SAME genuine reactor-driven suspension through the compiler's own
    # codegen instead of hand-written C++. See gimple_codegen.py's
    # _is_asyncio_sock_recv_call/_mojoasync_SockRecvAwaiter docstrings for
    # the API-shape design rationale (single-byte recv, raw int fd -- no
    # Mojo-level socket type exists yet anywhere in this project).
    test_sock_recv_delayed_write(
        "sock_recv_genuinely_suspends_until_delayed_write",
        delay_seconds=0.08)
    test_sock_recv_already_readable_before_await(
        "sock_recv_resumes_immediately_when_already_readable")
    test_sock_recv_eof(
        "sock_recv_returns_minus_one_on_peer_close_eof")

    # ── Final step: combined async generators (`async def f(): ... yield``,
    # consumed via `async for`) ─────────────────────────────────────────────
    # See gimple_codegen.GimpleGen._gen_cpp_async_generator_unit's docstring
    # for the full design (a THIRD, distinct promise type combining
    # yield_value() with a continuation field, verified safe against
    # Milestone D's GCC-15 frame-corruption bug via a hand-written,
    # Mojo-independent repro before this method was written at all) and
    # _cpp_async_for_stmt's docstring for `async for`'s own lowering (the
    # first codegen anywhere, compiled or interpreted, to consume
    # ForStmt.is_async at all).

    # 1. THE core proof, mirroring test_async_stdout_timed's role for plain
    # `await asyncio.sleep(...)` exactly: two real sleeps genuinely
    # happening IN SEQUENCE between yields (not fused/instant), consumed by
    # a real `async for` in another async function, with the correct
    # accumulated result.
    test_async_stdout_timed(
        "async_gen_two_real_sleeps_between_yields_accumulated_via_async_for",
        """\
async def f():
    await asyncio.sleep(0.08)
    yield 1
    await asyncio.sleep(0.08)
    yield 2

async def main_driver():
    total = 0
    async for x in f():
        total = total + x
    return total

def main():
    import asyncio
    result = asyncio.run(main_driver())
    print(result)
""", "3\n", min_seconds=0.15, max_seconds=1.5)

    # 2. Beyond the obvious happy path (this project's own established
    # pattern): an `async for` that `break`s out EARLY, only partially
    # consuming the generator (2 of 4 yields). Asserts BOTH the correct
    # partial accumulation (proving `break` genuinely stops consumption,
    # not just stops accumulating) AND that wall-clock time reflects only
    # the TWO sleeps that actually ran, not all four -- if the generator's
    # coroutine frame weren't destroyed/abandoned correctly on early exit,
    # this would either hang (if destroy() were never reached) or take
    # ~4x as long (if the loop kept driving the generator past the break).
    test_async_stdout_timed(
        "async_gen_early_break_stops_consumption_and_cleans_up",
        """\
async def f():
    await asyncio.sleep(0.08)
    yield 10
    await asyncio.sleep(0.08)
    yield 20
    await asyncio.sleep(0.08)
    yield 30
    await asyncio.sleep(0.08)
    yield 40

async def main_driver():
    total = 0
    async for x in f():
        total = total + x
        if x == 20:
            break
    return total

def main():
    import asyncio
    result = asyncio.run(main_driver())
    print(result)
""", "30\n", min_seconds=0.15, max_seconds=1.2)

    # 3. Exceptions: a `raise` inside an async generator body (after one
    # real yield) propagates OUT of `async for` as a real, catchable
    # exception in the awaiting function's own body -- composes Milestone
    # D's generator exception machinery (reused verbatim by this step's
    # promise) with Step E's per-awaiter rethrow (reused verbatim by
    # `<base>_AnextAwaiter::await_resume`), exactly like this step's own
    # docstring claims, not a fourth exception mechanism.
    test_async_stdout(
        "async_gen_exception_after_yield_caught_by_async_for_caller", """\
async def f():
    await asyncio.sleep(0.01)
    yield 1
    raise ValueError("boom")

async def main_driver():
    total = 0
    try:
        async for x in f():
            total = total + x
    except ValueError:
        total = total + 100
    return total

def main():
    import asyncio
    result = asyncio.run(main_driver())
    print(result)
""", "101\n")

    # 4. Honest refusal: `yield from` inside an async generator is still out
    # of this step's scope (delegation composed with async suspension is
    # genuinely new risk this step doesn't take on -- see
    # `_async_gen_quick_eligible`'s docstring), even though the plain
    # (non-async) generator path already supports `yield from` on its own.
    test_async_build_refused(
        "async_gen_yield_from_still_refused",
        """\
async def g():
    yield 1

async def f():
    yield from g()

async def main_driver():
    async for x in f():
        pass
    return 0

def main():
    import asyncio
    print(asyncio.run(main_driver()))
""", "cannot compile module")

    # 5. Real capability gain (bugs/hard/
    # CODEGEN_async_gen_params_silent_regression.md's own follow-up fix):
    # a parametrized async generator, consumed via `async for x in f(<real
    # args>):`, now genuinely compiles, links, and RUNS -- `_cpp_async_for_
    # stmt` threads the call site's own arguments into `{base}_impl(...)`
    # exactly like the sibling `AwaitExpr` async-awaits-async composition
    # call site. `f(10)` should yield 10 then 11 (10 + 11 = 21).
    test_async_stdout("async_gen_with_parameters", """\
async def f(n: int):
    yield n
    yield n + 1

async def main_driver():
    total = 0
    async for x in f(10):
        total = total + x
    return total

def main():
    import asyncio
    print(asyncio.run(main_driver()))
""", "21\n")

    # 5b. Multiple parameters thread through correctly too, not just a
    # single one (3 + 4 = 7).
    test_async_stdout("async_gen_with_multiple_parameters", """\
async def g(a: int, b: int):
    yield a + b

async def main_driver():
    total = 0
    async for x in g(3, 4):
        total = total + x
    return total

def main():
    import asyncio
    print(asyncio.run(main_driver()))
""", "7\n")

    # 5c. Honest refusal, now specifically about the ARGUMENT COUNT (not
    # merely "has any params at all", which no longer applies):
    # `_cpp_async_for_stmt` validates the call site's argument count
    # against `api['params']` before emitting anything, raising a clear,
    # specific `_UnsupportedAsyncShape` ("async generator 'f' called with 0
    # argument(s), expected 1") -- confirmed via MOJO_DEBUG's `_debug_note`
    # trace at the actual point of refusal; the outer message stays the
    # same generic "cannot compile module" wrapper every other in-body
    # refusal reason (e.g. test 4's `yield from`) already surfaces through
    # this same architecture, not a regression specific to this fix.
    test_async_build_refused(
        "async_gen_wrong_arg_count_still_refused",
        """\
async def f(n: int):
    yield n

async def main_driver():
    total = 0
    async for x in f():
        total = total + x
    return total

def main():
    import asyncio
    print(asyncio.run(main_driver()))
""", "cannot compile module")

    # ── Step I: create_task/Task/RaisingTask/create_raising_task ──────────
    # (the create_task/Task/TaskGroup/RaisingTask codegen project). Real
    # compile+link+run behavioral coverage for test_raising_asyncrt.mojo's
    # own shapes (that file itself is the fuller, real-stdlib-linked
    # end-to-end proof — these are the same shapes distilled into
    # standalone, stdlib-free snippets this harness can build without a
    # full dylib link, using `print(...)` in place of `assert_equal(...)`).

    # 1. The simplest shape: a nested (`@parameter async def`), zero-
    # parameter async function that itself awaits a top-level, PARAMETERIZED
    # async function (Step H's own parameter-support addition), run via
    # `create_task(...)` then blocked on with `.wait()` from ordinary
    # (non-async) code. Exercises: nested-async compilation + scoped
    # `_async_api` push (_compile_nested_async_functions), the
    # `create_task`/`.wait()` handle tracking (_async_var_api), and that
    # `create_task`/`create_raising_task` are intercepted before the
    # generic-import-elaboration machinery a real `from std.runtime.asyncrt
    # import ...` would otherwise route them through (see _lower_call's own
    # docstring on why this ordering matters).
    test_async_stdout("create_task_basic_wait", """\
from std.runtime.asyncrt import create_task

async def add_async(a: Int, b: Int) -> Int:
    return a + b

def test_basic() raises:
    @parameter
    async def wrapper() -> Int:
        return await add_async(10, 20)

    var task = create_task(wrapper())
    print(task.wait())

def main() raises:
    test_basic()
""", "30\n")

    # 2. RaisingTask success + real error propagation through `.wait()` —
    # the exact shape test_raising_asyncrt.mojo's Phase 2 uses:
    # `create_raising_task(<call>)` at ordinary function scope, `task^.wait()`
    # (the `^` transfer sigil — NOT stripped by the tokenizer, see
    # _lower_method_call's own docstring) inside a real `try`/`except e:`.
    # Exercises the `except e:`/bare-identifier-catch-all fix (a real,
    # pre-existing bug this project found and fixed getting THIS exact
    # shape working — see _handler_exc_name's docstring) and the promise's
    # already-generic exception staging propagating a real error message
    # all the way out through `.wait()`'s mojo_raise() bridge. Prints `e`
    # directly (a plain `char *`, not `String(e)`) — general `String(...)`
    # support for a non-literal argument is a separate, pre-existing gap in
    # this codegen (unrelated to create_task/Task — see the `FIXME` on
    # `String`'s stub extern declaration in gen_module's preamble
    # emission), out of this project's scope; `print(e)` is what actually
    # exercises this project's own exception-message plumbing correctly.
    test_async_stdout("raising_task_wait_success_and_error", """\
from std.runtime.asyncrt import create_task, create_raising_task

async def add_async(a: Int, b: Int) raises -> Int:
    return a + b

async def failing_async() raises -> Int:
    raise Error("intentional error from async task")

def test_success() raises:
    var task = create_raising_task(add_async(10, 20))
    print(task^.wait())

def test_error() raises:
    var task = create_raising_task(failing_async())
    var caught = False
    try:
        _ = task^.wait()
    except e:
        caught = True
        print(e)
    print(caught)

def main() raises:
    test_success()
    test_error()
""", "30\nintentional error from async task\n1\n")

    # 3. A keyword-argument await composition (`await
    # conditional_raise(should_fail=False)`) AND a keyword-argument
    # `create_raising_task(conditional_raise(should_fail=True))` at ordinary
    # function scope — real Mojo's own test_raising_asyncrt.mojo shape.
    # Exercises _resolve_kwargs_for_known_async_call/_normalize_await_kwargs
    # (this codegen's call-lowering is positional-only everywhere else; this
    # is the one bridge from a real keyword-argument call site onto that
    # positional-only async-composition machinery) in BOTH of the two
    # places it's needed: a direct `await` target, and create_raising_task's
    # own inner call.
    test_async_stdout("kwarg_composition_both_shapes", """\
from std.runtime.asyncrt import create_task, create_raising_task

async def conditional_raise(should_fail: Bool) raises -> Int:
    if should_fail:
        raise Error("conditional failure")
    return 42

def test_direct_await() raises:
    @parameter
    async def success_wrapper() -> Int:
        try:
            return await conditional_raise(should_fail=False)
        except:
            return -1

    var task = create_task(success_wrapper())
    print(task.wait())

def test_create_raising_task_kwarg() raises:
    var t_ok = create_raising_task(conditional_raise(should_fail=False))
    print(t_ok^.wait())
    var t_fail = create_raising_task(conditional_raise(should_fail=True))
    var caught = False
    try:
        _ = t_fail^.wait()
    except:
        caught = True
    print(caught)

def main() raises:
    test_direct_await()
    test_create_raising_task_kwarg()
""", "42\n42\n1\n")

    # 4. A held RaisingTask AWAITED from INSIDE another coroutine's own body
    # (`var task = create_raising_task(f()); ...; return await task^`) —
    # the narrow, documented single-use inlining
    # (_inline_single_use_task_composition) that collapses this into a
    # direct `await f()` composition when (and only when) the handle is
    # never referenced anywhere else. Includes the "chained" shape (a
    # `raises` async function itself awaiting a held RaisingTask, no
    # try/except of its own — test_raising_asyncrt.mojo's own
    # test_raising_task_await_chained).
    test_async_stdout("held_raising_task_await_inlined", """\
from std.runtime.asyncrt import create_task, create_raising_task

async def add_async(a: Int, b: Int) raises -> Int:
    return a + b

def test_wrapper_holds_task() raises:
    @parameter
    async def wrapper() -> Int:
        var task = create_raising_task(add_async(1, 2))
        try:
            return await task^
        except:
            return -1

    var task = create_task(wrapper())
    print(task.wait())

def test_chained() raises:
    async def outer() raises -> Int:
        var inner = create_raising_task(add_async(5, 10))
        return await inner^

    var task = create_raising_task(outer())
    print(task^.wait())

def main() raises:
    test_wrapper_holds_task()
    test_chained()
""", "3\n15\n")

    # 5. Two DIFFERENT enclosing functions each define their own nested
    # async helper with the SAME bare name (`wrapper`) — the exact scoping
    # hazard _compile_nested_async_functions/self._nested_async_api's own
    # docstrings call out (every compiled async cpp fragment in a module
    # lands in ONE shared .cpp translation unit, so both the C++ symbol
    # names AND the scoped self._async_api push/pop must keep them
    # distinct). If this collided, one of the two would silently resolve
    # to the WRONG compiled unit — this asserts both produce their own,
    # independently-correct result.
    test_async_stdout("same_named_nested_helpers_different_scopes", """\
from std.runtime.asyncrt import create_task

async def add_async(a: Int, b: Int) -> Int:
    return a + b

def test_a() raises:
    @parameter
    async def wrapper() -> Int:
        return await add_async(1, 1)

    var task = create_task(wrapper())
    print(task.wait())

def test_b() raises:
    @parameter
    async def wrapper() -> Int:
        return await add_async(100, 100)

    var task = create_task(wrapper())
    print(task.wait())

def main() raises:
    test_a()
    test_b()
""", "2\n200\n")

    if _FAIL:
        print(f"\n{_PASS} passed, {_FAIL} failed")
        raise SystemExit(1)
    print(f"\n{_PASS} passed, {_FAIL} failed")


if __name__ == '__main__':
    run_tests()
