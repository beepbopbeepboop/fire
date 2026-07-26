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


def run_tests():
    # The exact target shape from Step B's writeup: `async def f(): return
    # 42`, consumed by `x = f(); print(x)` in main() — proves the whole
    # pipeline for real: constructing the coroutine WITHOUT running the body
    # (`_start`, initial_suspend()==suspend_always), driving it to
    # completion via Step A's OWN scheduler API
    # (mojo_async_schedule_ready + mojo_async_run_until_complete — no
    # bespoke `_resume` reinvented for this, see _lower_call's async
    # branch), reading the completed result (`_value`), and cleanup
    # (`_destroy`).
    test_async_stdout("simple_async_function_returns_scalar", """\
async def f():
    return 42

def main():
    x = f()
    print(x)
""", "42\n")

    # A second, structurally different consumption shape: the async call's
    # result used directly as a `print(...)` argument, without an
    # intermediate assignment — confirms the CallExpr lowering in
    # _lower_call works from any value-consuming expression context, not
    # just an AssignStmt's RHS (this step's design deliberately reuses the
    # SAME ordinary self.lower_expr(...)-based call-lowering machinery every
    # other function call in this codegen uses, rather than a special
    # assignment-only statement-level hack).
    test_async_stdout("async_call_result_used_directly_as_print_arg", """\
async def f():
    return 7

def main():
    print(f())
""", "7\n")

    # THE key correctness bar from Step B's plan: "calling f() must NOT run
    # the body immediately... something must actually drive it to
    # completion before its result is available." A bare, value-discarding
    # `f()` statement constructs the coroutine and destroys it WITHOUT ever
    # scheduling/running it (see _gen_stmt_ExprStmt's async special case) —
    # so its `print(1)` side effect must NEVER fire. The second call,
    # `x = f()`, DOES get driven to completion (the value-consuming path in
    # _lower_call), so its own `print(1)` fires exactly once. If this
    # codegen were instead (incorrectly) eager -- running an async
    # function's body the moment it's called, regardless of whether the
    # result is ever consumed -- the first, unused `f()` call would ALSO
    # print "1", and the expected output below would see TWO "1"s instead
    # of one. This is the one place, in real compiled+linked+run Mojo
    # source (not just a hand-verified .cpp detail), where this step's
    # laziness requirement is independently observable.
    test_async_stdout("unconsumed_async_call_never_runs_body", """\
async def f():
    print(1)
    return 42

def main():
    f()
    x = f()
    print(x)
""", "1\n42\n")

    # A multi-statement body (assignment + a while loop + a print) ending in
    # a scalar `return` — confirms this step's async body translation
    # genuinely reuses the SAME shared _cpp_stmt/_cpp_expr whitelist
    # emitter the generator path already has (assignment, AugAssignStmt,
    # WhileStmt, IfStmt, ...), not a separate narrower one that only
    # happens to handle a bare `return <literal>`.
    test_async_stdout("async_function_multi_statement_body", """\
async def f():
    total = 0
    i = 0
    while i < 5:
        total = total + i
        i = i + 1
    return total

def main():
    x = f()
    print(x)
""", "10\n")

    # A `Float64`-typed scalar return — confirms this isn't hardcoded to
    # int64_t; the promise's `result` field and `_value`'s C++ return type
    # both correctly resolve to `double`.
    test_async_stdout("async_function_float_return", """\
async def f():
    return 3.5

def main():
    x = f()
    print(x)
""", "3.5\n")

    # TWO independent async functions, each called and consumed once —
    # confirms the per-module bookkeeping (self._supported_async/
    # self._async_api, each keyed by name) doesn't cross-contaminate between
    # two distinct compiled coroutine units in the same translation unit.
    test_async_stdout("two_independent_async_functions", """\
async def f():
    return 1

async def g():
    return 2

def main():
    a = f()
    b = g()
    print(a)
    print(b)
""", "1\n2\n")

    if _FAIL:
        print(f"\n{_PASS} passed, {_FAIL} failed")
        raise SystemExit(1)
    print(f"\n{_PASS} passed, {_FAIL} failed")


if __name__ == '__main__':
    run_tests()
