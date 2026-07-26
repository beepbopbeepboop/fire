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

    # An UNANNOTATED parameter that's provably `double` at every call site
    # (the cross-call scalar-contract mechanism, reused from the ordinary
    # non-generator compiled-function path per e387af9/8799ec4) now compiles
    # correctly end-to-end as `double`, not the naive int64_t default —
    # the positive counterpart to the honest-refusal fix in
    # bugs/CODEGEN_compiled_generator_unannotated_string_param_mistyped.md
    # (an unannotated param unanimously called with a NON-scalar argument,
    # e.g. a string, is refused instead; this one is unanimously called
    # with a scalar double argument, so it's positively confirmed safe to
    # compile). Before the fix, `x`'s compile attempt ran before the
    # cross-call inference existed for generators at all, so it would have
    # silently defaulted to int64_t and truncated/corrupted the double
    # value instead of round-tripping it correctly.
    test_generator_stdout("param_generator_unannotated_double_via_cross_call", """\
def g(x):
    yield x

def main():
    for v in g(3.5):
        print(v)
""", "3.5\n")

    # Milestone C step 2 (yield-from delegation): the exact target shape —
    # `outer` delegates its entire output to `inner` via a bare
    # `yield from inner()`. `inner` must be defined before `outer` (see
    # gimple_codegen.GimpleGen._cpp_yield_from's docstring). Confirms the
    # hand-rolled resume/yield/exhaust delegation loop actually produces the
    # right VALUES, in order, not just that it type-checks.
    test_generator_stdout("yield_from_delegates_to_another_generator", """\
def inner():
    yield 1
    yield 2
    yield 3

def outer():
    yield from inner()

def main():
    for x in outer():
        print(x)
""", "1\n2\n3\n")

    # `yield from` composed with other statements around it in the
    # delegating generator's own body — confirms the delegation loop is a
    # normal statement in the body (not required to be the only statement),
    # and that values yielded directly by `outer` and values relayed from
    # `inner` interleave in the right order.
    test_generator_stdout("yield_from_delegation_with_surrounding_yields", """\
def inner():
    yield 2
    yield 3

def outer():
    yield 1
    yield from inner()
    yield 4

def main():
    for x in outer():
        print(x)
""", "1\n2\n3\n4\n")

    # An EMPTY inner generator (yields nothing at all) — the delegation
    # loop's while-condition must be false on the very first `_resume`
    # call, so `yield from` contributes zero values and execution falls
    # through to whatever follows it in `outer`'s own body, cleanly (no
    # crash/hang on a sub-generator that never produces anything).
    test_generator_stdout("yield_from_delegates_to_empty_generator", """\
def inner():
    if False:
        yield 1

def outer():
    yield from inner()
    yield 99

def main():
    for x in outer():
        print(x)
""", "99\n")

    # Early exit (`break`) partway through consuming `outer()` from OUTSIDE
    # — this calls outer's own `_destroy` (coroutine_handle::destroy()) on
    # a coroutine suspended mid-`co_yield` INSIDE the yield-from delegation
    # loop's nested block, holding a live handle to `inner`. Per the C++20
    # coroutine-frame-destruction rules, all locals in scope at that
    # suspension point (the `_mojogen_sub_guard` RAII wrapper) get
    # destroyed as part of destroying outer's frame, which must in turn
    # call inner's own `_destroy` -- confirms delegation composes correctly
    # with early exit of the OUTER generator, not just normal exhaustion.
    # (No direct way to observe "inner's _destroy actually ran" from mojo
    # stdout alone, but a hang or crash here -- e.g. from a double-destroy,
    # a leaked/never-destroyed inner coroutine frame corrupting later
    # allocations, or an outright segfault destroying an in-flight frame --
    # would fail this test's subprocess run/timeout, which is the real
    # thing being checked.)
    test_generator_stdout("yield_from_delegation_early_break_cleans_up_both_generators", """\
def inner():
    i = 0
    while i < 100:
        yield i
        i = i + 1

def outer():
    yield from inner()

def main():
    for x in outer():
        if x == 3:
            break
        print(x)
""", "0\n1\n2\n")

    # TWO LEVELS of `yield from` (level2 -> level1 -> level0), each level
    # also yielding its own extra values around the delegation -- confirms
    # delegation composes/nests correctly (not just a single hop), each
    # generator's own extern "C" API calling into the next one down's,
    # entirely resolved via same-translation-unit definitions.
    test_generator_stdout("yield_from_delegation_two_levels_deep", """\
def level0():
    yield 1
    yield 2

def level1():
    yield from level0()
    yield 3

def level2():
    yield from level1()
    yield 4

def main():
    for x in level2():
        print(x)
""", "1\n2\n3\n4\n")

    # Parameterized delegation: BOTH the delegating (`outer`) and the
    # delegated-to (`inner`) generator take parameters, and `outer` passes
    # an expression (not just a bare literal) built from its own parameter
    # as one of `inner`'s arguments -- confirms parameter support (from the
    # Milestone C step 1 parameter-support step) and yield-from delegation
    # (this step) compose correctly together, not just each in isolation.
    test_generator_stdout("yield_from_delegation_with_parameters_both_sides", """\
def inner(start, count):
    i = start
    n = 0
    while n < count:
        yield i
        i = i + 1
        n = n + 1

def outer(base):
    yield from inner(base + 5, 3)

def main():
    for x in outer(10):
        print(x)
""", "15\n16\n17\n")

    # Milestone C step 3 (generator METHODS on structs): the target shape
    # from that step's writeup -- a method reading a scalar `self` field,
    # constructed via an ordinary compiled struct constructor and consumed
    # by an inline `for x in obj.method(...):` loop (the same call-site
    # shape _lower_struct_method_call's new generator-method branch
    # handles; see that method's own comment for why an intermediate
    # `g = obj.method(...)` assignment isn't supported -- a PRE-EXISTING
    # gap shared with every other compiled generator, free-function or
    # method, not something specific to this step).
    test_generator_stdout("generator_method_reads_self_field", """\
class Counter:
    def __init__(self, start: Int):
        self.value = start

    def countdown(self, n: Int):
        i = 0
        while i < n:
            yield self.value - i
            i = i + 1

def main():
    c = Counter(10)
    for x in c.countdown(3):
        print(x)
""", "10\n9\n8\n")

    # Per-instance isolation: TWO different Counter instances, each with
    # its own `value`, each driving its own `countdown(...)` call -- the
    # real bug-finding candidate for this step (a `self` binding that was
    # accidentally shared/aliased across instances, e.g. a stray global/
    # static instead of a genuine per-coroutine-frame copy of the `self`
    # pointer argument, would make the second loop's output depend on the
    # first instance's state instead of its own). Confirms each instance's
    # generator produces independently-correct output.
    test_generator_stdout("generator_method_self_binding_is_per_instance", """\
class Counter:
    def __init__(self, start: Int):
        self.value = start

    def countdown(self, n: Int):
        i = 0
        while i < n:
            yield self.value - i
            i = i + 1

def main():
    a = Counter(10)
    b = Counter(100)
    for x in a.countdown(3):
        print(x)
    for x in b.countdown(2):
        print(x)
""", "10\n9\n8\n100\n99\n")

    # A generator method combining `self.<field>` reads with an ORDINARY
    # scalar parameter (`step`) alongside the implicit `self` -- confirms
    # this step's self-binding support composes naturally with the
    # parameter-support step's existing machinery (Milestone C step 1),
    # not just the self-only case.
    test_generator_stdout("generator_method_self_field_plus_scalar_param", """\
class Counter:
    def __init__(self, start: Int):
        self.value = start

    def countup(self, n: Int, step: Int):
        i = 0
        while i < n:
            yield self.value + i * step
            i = i + 1

def main():
    c = Counter(10)
    for x in c.countup(3, 2):
        print(x)
""", "10\n12\n14\n")

    # A `double`-typed self field, read directly (no intermediate local) --
    # confirms self-field type inference correctly resolves to `double`
    # (not the int64_t default), mirroring the free-function parameter
    # step's float coverage but for a struct field instead of a parameter.
    test_generator_stdout("generator_method_self_field_double", """\
class Sampler:
    def __init__(self, base: Float64):
        self.base = base

    def samples(self, n: Int):
        i = 0
        while i < n:
            yield self.base + i
            i = i + 1

def main():
    s = Sampler(1.5)
    for x in s.samples(3):
        print(x)
""", "1.5\n2.5\n3.5\n")

    if _FAIL:
        print(f"\n{_PASS} passed, {_FAIL} failed")
        raise SystemExit(1)
    print(f"\n{_PASS} passed, {_FAIL} failed")


if __name__ == '__main__':
    run_tests()
