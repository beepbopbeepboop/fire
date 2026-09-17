"""REAL behavioral tests for `TaskGroup` as a compiled type (test_locks.mojo
Step 3, on top of the mutable-capture work in test_mutable_async_capture.py)
-- real Mojo's own `TaskGroup` (std/runtime/asyncrt.mojo) is a genuinely
deep struct (raw MLIR ops, an atomic counter, a `_Chain` low-level
completion primitive, `List[_TaskGroupBox]`) nowhere near reachable by this
codegen's general struct-compiling path, so it's reinterpreted here exactly
like `create_task`/`create_raising_task` already are: not by compiling
TaskGroup's real body, but as a small set of intrinsics (`TaskGroup()`,
`.create_task(...)`, `.wait[origin]()`) this codegen understands directly,
backed by the existing `MojoList`/`mojo_list_*` infrastructure (a
`TaskGroup` is a plain `MojoList *` of int64_t-cast `MojoAsync *` handles).

Also exercises a separate, pre-existing bug this work surfaced and fixed:
nested `for` loops reusing the SAME loop-variable name (`for _ in range(...):
for _ in range(...): ...` -- real Mojo/Python's own extremely common
"don't care" idiom, and test_locks.mojo's exact shape) silently corrupted
the OUTER loop's own iteration state, because the compiled C used the same
variable for both the loop's internal counter AND the user-visible
per-iteration value -- confirmed via a hand-written repro (`100`, not
`10000`) before the fix.

This compiles + links + RUNS each repro (not compile-only) and asserts on
real stdout.
"""
import os
import subprocess
import tempfile

# This file exercises the gimple_cpp_* C++20-coroutine backend's TaskGroup
# intrinsics (its build helper links mojo_async_runtime.cpp, the cpp
# scheduler). Since doc/COROUTINE.html §5.5's cutover made the A3 stack-
# switch backend the default, pin the escape hatch explicitly -- the
# equivalent stack-switch TaskGroup coverage lives in
# test_coro_nested_async_capture.py, whose harness links the A3 runtime.
os.environ.setdefault('MOJO_CORO', 'cpp')

import gimple_codegen
import fire
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


def _build_and_run(mojo_src: str, timeout: int = 30) -> str:
    """Mirrors test_mutable_async_capture.py's/test_async_void_return.py's
    identical harness shape: real gcc -fgimple / g++ -std=c++20 compile,
    real link via fire.py's link_executable(cxx=True), real run, real
    stdout."""
    wd = tempfile.mkdtemp(prefix='mojo_taskgroup_')
    src_path = os.path.join(wd, 'prog.mojo')
    with open(src_path, 'w') as f:
        f.write(mojo_src)

    c_code, cpp_code = gimple_codegen.compile_to_gimple_with_cpp(mojo_src, filename=src_path)

    c_path = os.path.join(wd, 'prog.c')
    with open(c_path, 'w') as f:
        f.write(c_code)

    c_o = os.path.join(wd, 'prog.o')
    runtime_o = os.path.join(wd, 'fire_runtime.o')
    exe = os.path.join(wd, 'prog.exe')
    objs = [c_o, runtime_o]

    r = subprocess.run([GCC, '-fgimple', f'-I{RUNTIME_DIR}', '-c', '-o', c_o, c_path],
                        capture_output=True, text=True, timeout=30)
    if r.returncode != 0:
        raise RuntimeError(f"gcc -fgimple compile of .c failed: {r.stderr}\n---\n{c_code}")

    r = subprocess.run([GCC, f'-I{RUNTIME_DIR}', '-c', '-o', runtime_o, RUNTIME_C],
                        capture_output=True, text=True, timeout=30)
    if r.returncode != 0:
        raise RuntimeError(f"gcc compile of fire_runtime.c failed: {r.stderr}")

    # `cpp_code` is empty for a repro with no async/generator content at
    # all (e.g. the pure nested-for-loop-fix isolation test below) --
    # compile+link only the ordinary .c/fire_runtime.c side in that case,
    # matching how a plain, non-async Mojo program is genuinely built.
    cxx = bool(cpp_code)
    if cxx:
        cpp_path = os.path.join(wd, 'prog_async.cpp')
        with open(cpp_path, 'w') as f:
            f.write(cpp_code)
        async_o = os.path.join(wd, 'prog_async.o')
        async_runtime_o = os.path.join(wd, 'mojo_async_runtime.o')

        r = subprocess.run([GXX, '-std=c++20', f'-I{RUNTIME_DIR}', '-c', '-o', async_o, cpp_path],
                            capture_output=True, text=True, timeout=30)
        if r.returncode != 0:
            raise RuntimeError(f"g++ compile of .cpp failed: {r.stderr}\n---\n{cpp_code}")

        r = subprocess.run([GXX, '-std=c++20', f'-I{RUNTIME_DIR}', '-c', '-o', async_runtime_o,
                            ASYNC_RUNTIME_CPP], capture_output=True, text=True, timeout=30)
        if r.returncode != 0:
            raise RuntimeError(f"g++ compile of mojo_async_runtime.cpp failed: {r.stderr}")
        objs += [async_o, async_runtime_o]

    r = mojo.link_executable(objs, exe, cxx=cxx)
    if r.returncode != 0:
        raise RuntimeError(f"link_executable(cxx={cxx}) failed: {r.stderr}")

    os.chmod(exe, 0o755)
    r = subprocess.run([exe], capture_output=True, text=True, timeout=timeout)
    if r.returncode != 0:
        raise RuntimeError(f"program exited {r.returncode}, stderr={r.stderr}")
    return r.stdout


def test_taskgroup_basic_100_tasks():
    """The simplest TaskGroup shape: construct, create_task in a loop,
    wait, read back the mutated capture -- proves TaskGroup() construction,
    .create_task(...) (with capture-forwarding reused from the free
    create_task path), and .wait() (draining the shared scheduler +
    destroying every handle in the group) are all real, not stubs."""
    src = """\
from std.runtime.asyncrt import TaskGroup


def test_taskgroup_simple() raises:
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
    test_taskgroup_simple()
"""
    out = _build_and_run(src)
    check("TaskGroup: 100 tasks each incrementing a shared capture -> 100",
          out == "100\n", detail=repr(out))


def test_taskgroup_10000_task_stress_with_same_named_nested_loops():
    """test_locks.mojo's own real shape: `for _ in range(maxI): for _ in
    range(maxJ): tg.create_task(inc())` -- SAME loop-variable name (`_`) at
    both nesting levels (real Mojo/Python's extremely common "don't care"
    idiom), 100*100 = 10000 total tasks. This is the "real 10,000-
    increment stress test" proving genuine serialization (a single-
    threaded, cooperative scheduler means "serialization" here is really
    "no task's increment gets lost/double-counted/skipped") -- if either
    the mutable-capture pointer-forwarding OR the nested-same-named-loop
    fix (see this file's own module docstring) were still broken, this
    would print something other than exactly 10000."""
    src = """\
from std.runtime.asyncrt import TaskGroup


def test_taskgroup_stress() raises:
    var counter = 0
    comptime maxI = 100
    comptime maxJ = 100

    @parameter
    async def inc():
        counter += 1

    var tg = TaskGroup()
    for _ in range(0, maxI):
        for _ in range(0, maxJ):
            tg.create_task(inc())
    tg.wait()
    print(counter)


def main() raises:
    test_taskgroup_stress()
"""
    out = _build_and_run(src)
    check("TaskGroup: 10,000-task stress test (same-named nested loops) -> 10000",
          out == "10000\n", detail=repr(out))


def test_nested_for_loops_reusing_same_variable_name():
    """Isolates the nested-same-named-loop bug this session's TaskGroup
    stress-test verification surfaced, independent of async/TaskGroup
    entirely -- confirms the fix in `_gen_for_range` (a dedicated internal
    counter, decoupled from the user-visible loop variable) generally,
    not just for this one call site."""
    src = """\
def test_nested_for() raises:
    var calls = 0
    for _ in range(0, 100):
        for _ in range(0, 100):
            calls += 1
    print(calls)


def main() raises:
    test_nested_for()
"""
    out = _build_and_run(src)
    check("nested `for _ in range(...)` loops sharing the same variable name -> 10000",
          out == "10000\n", detail=repr(out))


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
