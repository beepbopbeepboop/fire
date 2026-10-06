"""REAL behavioral tests for nested comptime-bracket-parametrized async
functions — the follow-on to bugs/CODEGEN_comptime_bracket_parametrized_
function_calls_silently_wrong.md's top-level-function fix, matching
test_asyncrt.mojo's/test_tracing.mojo's own exact shape:

  def test_runtime_task() raises:
      @parameter
      async def test_asyncrt_add[lhs: Int](rhs: Int) -> Int:
          return lhs + rhs
      ...

Previously this whole module was refused (async_quick_eligible never even
offered to attempt `test_asyncrt_add` — no existing pass discovers a
nested async def inside a plain top-level function at all). Fixed via a
new gen_module discovery pass that threads every comptime bracket
parameter through as an ordinary trailing runtime parameter (this
codegen's async-unit compiler never folds/specializes on a comptime
value, so this is behaviorally exact, not an approximation) and a new
_lower_call branch (plus an asyncio.run(...)-composed variant) that
forwards bracket arguments as extra positional args at the call site.

Also covers the real, pre-existing bug found while landing this: stripping
a top-level generic function from `stmts` never cleaned up nested async/
generator def ids it contained from _async_fns/_generator_fns, so they
stayed permanently un-poppable and always surfaced in the final "still
unsupported" error — AND the real, NEWLY-discovered silent-miscompile risk
this session's work exposed (test_tracing.mojo's shape: a generic OUTER
function containing a nested async def) — now an honest upfront refusal
instead of a silent placeholder-0.

This compiles + links + RUNS each repro (not compile-only) via
gimple_codegen.compile_to_gimple_with_cpp, mirroring test_gimple_async_
runner.py's/test_async_void_return.py's harness shape, and asserts on
real stdout.
"""
import os
import subprocess
import tempfile


# cpp-path (gimple_cpp_*) escape-hatch test -- its build harness links
# the C++20-coroutine runtime. doc/COROUTINE.html §5.5 made the A3
# stack-switch backend the default, so pin cpp explicitly.
os.environ.setdefault('MOJO_CORO', 'cpp')
import gimple_codegen
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
    wd = tempfile.mkdtemp(prefix='mojo_nested_async_generic_')
    src_path = os.path.join(wd, 'prog.mojo')
    with open(src_path, 'w') as f:
        f.write(mojo_src)

    c_code, cpp_code = gimple_codegen.compile_to_gimple_with_cpp(mojo_src, filename=src_path)
    if not cpp_code:
        raise RuntimeError("expected a non-empty generated .cpp for this async repro")

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

    import fire
    r = mojo.link_executable([c_o, async_o, runtime_o, async_runtime_o], exe, cxx=True)
    if r.returncode != 0:
        raise RuntimeError(f"link_executable(cxx=True) failed: {r.stderr}")

    os.chmod(exe, 0o755)
    r = subprocess.run([exe], capture_output=True, text=True, timeout=30)
    if r.returncode != 0:
        raise RuntimeError(f"program exited {r.returncode}, stderr={r.stderr}")
    return r.stdout


def test_test_asyncrt_mojo_shaped_repro():
    """test_asyncrt.mojo's own exact test_asyncrt_add shape, driven via
    asyncio.run(...) (bypassing create_task, which isn't built yet — see
    the bug report's own note that this is tested in isolation on purpose)."""
    src = """\
import asyncio

def test_runtime_task() raises:
    @parameter
    async def test_asyncrt_add[lhs: Int](rhs: Int) -> Int:
        return lhs + rhs

    print(asyncio.run(test_asyncrt_add[1](10)))
    print(asyncio.run(test_asyncrt_add[2](20)))

def main() raises:
    test_runtime_task()
"""
    out = _build_and_run(src)
    check("test_asyncrt_add[1](10)/[2](20) via asyncio.run -> 11/22",
          out == "11\n22\n", detail=repr(out))


def test_return_value_shaped_repro_zero_runtime_params():
    """test_asyncrt.mojo's second shape: return_value[value: Int]() — a
    nested async function with ONLY a comptime bracket parameter, no
    ordinary runtime parameters at all."""
    src = """\
import asyncio

def test_runtime_taskgroup() raises:
    @parameter
    async def return_value[value: Int]() -> Int:
        return value

    print(asyncio.run(return_value[1]()))
    print(asyncio.run(return_value[2]()))

def main() raises:
    test_runtime_taskgroup()
"""
    out = _build_and_run(src)
    check("return_value[1]()/[2]() via asyncio.run -> 1/2",
          out == "1\n2\n", detail=repr(out))


def test_nested_generic_inside_generic_is_honest_refusal_not_silent_miscompile():
    """A DIRECT (no `create_task`/`await`) call to a nested async def whose
    OWN enclosing function is ALSO comptime-bracket-parametrized. This must
    be an honest refusal (a raised exception whose message names the real
    cause), never a silent placeholder-0.

    NOTE: `_elaborate_generic_call`'s own former blanket "generic contains
    a nested async def -> refuse" guard (which used to fire here, with a
    message naming 'test_tracing'/'nested async' specifically) was removed
    once monomorphize.py genuinely gained dual C/C++ output + shadow-safe
    substitution (see bugs/CODEGEN_comptime_bracket_parametrized_function_
    calls_silently_wrong.md) -- test_tracing.mojo's OWN real shape (`create_
    task(test_tracing_add[enabled, 1](a))`, composed via `await`) now
    genuinely compiles. THIS test's repro is deliberately narrower/
    different: `test_tracing_add[enabled, 1](10)` called DIRECTLY, as if
    it were an ordinary synchronous function -- calling an async function
    with no `await`/`create_task` driving it at all is a separate, still-
    unsupported shape (there's no runtime mechanism to synchronously block
    for a coroutine's completion outside `create_task(...).wait()`), caught
    instead by gen_module's own final "unhandled async function(s)" whole-
    module check -- a different, but equally honest, refusal message."""
    src = """\
def test_tracing[level: Int, enabled: Bool]() raises:
    @parameter
    async def test_tracing_add[enabled: Bool, lhs: Int](rhs: Int) -> Int:
        if enabled:
            return lhs + rhs + level
        return rhs

    print(test_tracing_add[enabled, 1](10))

def main() raises:
    test_tracing[100, True]()
"""
    wd = tempfile.mkdtemp(prefix='mojo_nested_generic_in_generic_')
    src_path = os.path.join(wd, 'prog.mojo')
    with open(src_path, 'w') as f:
        f.write(src)
    try:
        gimple_codegen.compile_to_gimple(src, filename=src_path)
        check("nested-generic-in-generic raises an honest refusal (did not raise at all)",
              False, detail="compile_to_gimple unexpectedly succeeded")
    except Exception as e:
        msg = str(e)
        check("nested-generic-in-generic raises an honest, specific refusal",
              'async function' in msg and 'test_tracing_add' in msg, detail=msg)


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
