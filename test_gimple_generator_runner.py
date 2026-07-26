"""REAL behavioral test for Milestone B (C++20-coroutine generator codegen):
compiles a Mojo generator function's dual output (.c/.ci via gcc -fgimple,
.cpp via g++ -std=c++20) for real, links them together for real via
mojo.py's link_executable(cxx=True) (Milestone A's plumbing), RUNS the
resulting binary, and asserts on its ACTUAL stdout — mirrors
test_gimple_runner.py's/test_mixed_cpp_link.py's shape, combined: this is
the first test in the project to exercise gimple_codegen.py's new dual-
translation-unit output end-to-end as a real dual-language build.
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

_PASS = 0
_FAIL = 0


def _build_generator_program(mojo_src: str) -> str:
    """Compile mojo_src (which must contain exactly one Milestone-B-
    supported generator) to a real executable: .c/.ci -> gcc -fgimple -c,
    .cpp -> g++ -std=c++20 -c, runtime -> gcc -c, then link all three via
    mojo.py's link_executable(cxx=True) (g++ as the final link driver, so
    the C++ standard library / coroutine-support symbols resolve). Returns
    the path to the built executable."""
    c_code, cpp_code = gimple_codegen.compile_to_gimple_with_cpp(mojo_src)
    if not cpp_code:
        raise RuntimeError(
            "expected a non-empty generated .cpp — this source doesn't "
            "actually contain a Milestone-B-supported generator")

    wd = tempfile.mkdtemp(prefix='mojo_gen_runner_')
    c_path = os.path.join(wd, 'prog.c')
    cpp_path = os.path.join(wd, 'prog_gen.cpp')
    with open(c_path, 'w') as f:
        f.write(c_code)
    with open(cpp_path, 'w') as f:
        f.write(cpp_code)

    c_o = os.path.join(wd, 'prog.o')
    gen_o = os.path.join(wd, 'prog_gen.o')
    runtime_o = os.path.join(wd, 'mojo_runtime.o')
    exe = os.path.join(wd, 'prog.exe')

    gcc = find_gcc()
    gxx = find_gxx()

    r = subprocess.run([gcc, '-fgimple', f'-I{RUNTIME_DIR}', '-c', '-o', c_o, c_path],
                        capture_output=True, text=True, timeout=30)
    if r.returncode != 0:
        raise RuntimeError(f"gcc -fgimple compile of .c failed: {r.stderr}")

    r = subprocess.run([gxx, '-std=c++20', f'-I{RUNTIME_DIR}', '-c', '-o', gen_o, cpp_path],
                        capture_output=True, text=True, timeout=30)
    if r.returncode != 0:
        raise RuntimeError(f"g++ compile of .cpp failed: {r.stderr}")

    r = subprocess.run([gcc, f'-I{RUNTIME_DIR}', '-c', '-o', runtime_o, RUNTIME_C],
                        capture_output=True, text=True, timeout=30)
    if r.returncode != 0:
        raise RuntimeError(f"gcc compile of mojo_runtime.c failed: {r.stderr}")

    r = mojo.link_executable([c_o, gen_o, runtime_o], exe, cxx=True)
    if r.returncode != 0:
        raise RuntimeError(f"link_executable(cxx=True) failed: {r.stderr}")

    os.chmod(exe, 0o755)
    return exe


def test_generator_stdout(name: str, mojo_src: str, expected_stdout: str):
    global _PASS, _FAIL
    try:
        exe = _build_generator_program(mojo_src)
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
    # The exact target shape from the Milestone B writeup: a parameterless
    # generator with a plain while-loop/yield/increment body, consumed by an
    # ordinary `for x in counter(): print(x)` loop. Confirms the whole
    # pipeline: constructing the coroutine WITHOUT running the body
    # (`_start`), resuming to each `co_yield` (`_resume`/`_value`), and
    # cleanup (`_destroy`) after the loop's natural exhaustion.
    test_generator_stdout("for_loop_consumes_counter_generator", """\
def counter():
    i = 0
    while i < 5:
        yield i
        i = i + 1

def main():
    for x in counter():
        print(x)
""", "0\n1\n2\n3\n4\n")

    # A second, structurally different call-site/consumption shape —
    # list(...) — routes through _lower_ctor_from_iterable's synthetic
    # Comprehension -> _lower_comprehension -> _compr_generator_loop, a
    # DIFFERENT code path from _gen_for_iter's _gen_for_generator_iter
    # above, so this confirms more than one consumer was actually wired up
    # (not just the for-loop path happening to work).
    test_generator_stdout("list_consumes_counter_generator", """\
def counter():
    i = 0
    while i < 5:
        yield i
        i = i + 1

def main():
    xs = list(counter())
    n = 0
    for x in xs:
        n = n + x
    print(n)
""", "10\n")

    # An early exit (`break`) partway through — the generator's coroutine
    # frame must still be destroyed cleanly (no crash/hang) even though the
    # loop never reaches "resume reports done".
    test_generator_stdout("for_loop_breaks_early_out_of_generator", """\
def counter():
    i = 0
    while i < 100:
        yield i
        i = i + 1

def main():
    for x in counter():
        if x == 3:
            break
        print(x)
""", "0\n1\n2\n")

    # Parameter-support step: the exact target shape from that step's
    # writeup — `counter(start, count)`, two int64_t parameters threaded
    # from the call site (`counter(10, 3)`) through `<base>_start`'s real
    # arguments into the coroutine frame, and read back out via ordinary
    # local variables inside the body. Confirms the whole pipeline actually
    # produces the right VALUES (10, 11, 12), not just that it type-checks.
    test_generator_stdout("param_generator_counter_start_count", """\
def counter(start, count):
    i = start
    n = 0
    while n < count:
        yield i
        i = i + 1
        n = n + 1

def main():
    for x in counter(10, 3):
        print(x)
""", "10\n11\n12\n")

    # A generator call site whose arguments are ordinary expressions (not
    # bare literals) — confirms argument lowering reuses this codegen's
    # normal self.lower_expr(a)-per-arg machinery (the same as any other
    # function call), not just plain literal passthrough.
    test_generator_stdout("param_generator_expression_args", """\
def counter(start, count):
    i = start
    n = 0
    while n < count:
        yield i
        i = i + 1
        n = n + 1

def main():
    base = 5
    for x in counter(base + 1, 1 + 2):
        print(x)
""", "6\n7\n8\n")

    # A single-parameter generator that yields the parameter directly (no
    # intermediate local) — the simplest possible parameterized shape.
    test_generator_stdout("param_generator_single_param_direct_yield", """\
def repeat_twice(v):
    yield v
    yield v

def main():
    for x in repeat_twice(42):
        print(x)
""", "42\n42\n")

    # A Float64-typed parameter, yielded through a local that's mutated each
    # iteration (`v = start`, then `v = v + step`) — confirms the value-type
    # inference correctly resolves to double (not the int64_t default) both
    # for a directly-yielded param and for a local assigned straight from
    # one, per _generator_yield_ctype's `known`-map threading.
    test_generator_stdout("param_generator_float_step", """\
def stepper(start: Float64, step: Float64, count):
    v = start
    n = 0
    while n < count:
        yield v
        v = v + step
        n = n + 1

def main():
    for x in stepper(1.5, 0.5, 3):
        print(x)
""", "1.5\n2\n2.5\n")

    if _FAIL:
        print(f"\n{_PASS} passed, {_FAIL} failed")
        raise SystemExit(1)
    print(f"\n{_PASS} passed, {_FAIL} failed")


if __name__ == '__main__':
    run_tests()
