"""REAL behavioral test for generator codegen: compiles a Mojo generator
function's C output directly (doc/COROUTINE.html §5.5 cutover: this now
goes through the A3 stack-switch backend by default, gimple_gen_coro.py,
rather than the old cpp-path C++20-coroutine emitter -- MOJO_CORO=cpp
still selects the old path for the shapes it still uniquely covers), links
it against the small, do_imports=False-friendly A3 runtime object set
(mirrors test_coro_nested_async_capture.py's own build helper -- these
fixtures are self-contained, no stdlib imports, so there's no need to pay
build_stdlib_dylib's ~664-module link cost per test the way a full `mojo.py
build`/driver.compile_program invocation would), RUNS the resulting binary,
and asserts on its ACTUAL stdout. Falls back to the cpp companion-unit link
(g++, mojo_async_runtime.cpp) for the rarer shape not yet stack-switch-
eligible.
"""
import os
import platform
import subprocess
import tempfile

import gimple_codegen
from build_config import find_gcc, find_gxx

HERE = os.path.dirname(os.path.abspath(__file__))
RUNTIME_DIR = os.path.join(HERE, 'runtime')
GCC = find_gcc()
GXX = find_gxx()

_CORO_CTX_SRC = (os.path.join(RUNTIME_DIR, 'mojo_coro_ctx_aarch64.S')
                 if platform.machine().lower() in ('arm64', 'aarch64')
                 else os.path.join(RUNTIME_DIR, 'mojo_coro_ctx_generic.c'))

# Runtime object set for a stack-switch (A3) program: compiled ONCE, reused
# by every test in this file (these never change across test cases).
_SS_RUNTIME_SRCS = [
    os.path.join(RUNTIME_DIR, 'mojo_runtime.c'),
    os.path.join(RUNTIME_DIR, 'mojo_coro.c'),
    os.path.join(RUNTIME_DIR, 'mojo_coro_gen.c'),
    os.path.join(RUNTIME_DIR, 'mojo_async_sched.c'),
    _CORO_CTX_SRC,
]
_ss_runtime_objs_cache = None


def _ss_runtime_objs(wd):
    global _ss_runtime_objs_cache
    if _ss_runtime_objs_cache is None:
        objs = []
        for i, src in enumerate(_SS_RUNTIME_SRCS):
            o = os.path.join(wd, f'rt{i}.o')
            r = subprocess.run([GCC, f'-I{RUNTIME_DIR}', '-c', '-o', o, src],
                                capture_output=True, text=True, timeout=30)
            if r.returncode != 0:
                raise RuntimeError(f"compile of {src} failed: {r.stderr}")
            objs.append(o)
        _ss_runtime_objs_cache = objs
    return _ss_runtime_objs_cache


_PASS = 0
_FAIL = 0


def _build_generator_program(mojo_src: str) -> str:
    """Compile mojo_src (which must contain a supported generator) directly
    and link it against the A3 stack-switch runtime (or the cpp path, for a
    shape not yet stack-switch-eligible). Returns the exe path."""
    wd = tempfile.mkdtemp(prefix='mojo_gen_runner_')
    c_code, cpp_code = gimple_codegen.compile_to_gimple_with_cpp(mojo_src)
    c_path = os.path.join(wd, 'prog.c')
    with open(c_path, 'w') as f:
        f.write(c_code)
    exe = os.path.join(wd, 'prog.exe')

    if '__mgco_' in c_code:
        r = subprocess.run([GCC, '-fgimple', f'-I{RUNTIME_DIR}', '-w', '-c', '-o',
                            os.path.join(wd, 'prog.o'), c_path],
                            capture_output=True, text=True, timeout=30)
        if r.returncode != 0:
            raise RuntimeError(f"gcc -fgimple compile of .c failed: {r.stderr}\n---\n{c_code}")
        objs = [os.path.join(wd, 'prog.o')] + _ss_runtime_objs(wd)
        r = subprocess.run([GCC, '-o', exe, *objs], capture_output=True, text=True, timeout=30)
        if r.returncode != 0:
            raise RuntimeError(f"link failed: {r.stderr}")
        os.chmod(exe, 0o755)
        return exe

    if not cpp_code:
        raise RuntimeError(
            "expected a non-empty generated .cpp — this source doesn't "
            "actually contain a supported generator (neither stack-switch "
            "nor cpp path lowered it)")
    cpp_path = os.path.join(wd, 'prog_gen.cpp')
    with open(cpp_path, 'w') as f:
        f.write(cpp_code)
    r = subprocess.run([GCC, '-fgimple', f'-I{RUNTIME_DIR}', '-c', '-o',
                        os.path.join(wd, 'prog.o'), c_path],
                        capture_output=True, text=True, timeout=30)
    if r.returncode != 0:
        raise RuntimeError(f"gcc -fgimple compile of .c failed: {r.stderr}")
    r = subprocess.run([GXX, '-std=c++20', f'-I{RUNTIME_DIR}', '-c', '-o',
                        os.path.join(wd, 'prog_gen.o'), cpp_path],
                        capture_output=True, text=True, timeout=30)
    if r.returncode != 0:
        raise RuntimeError(f"g++ compile of .cpp failed: {r.stderr}")
    runtime_o = os.path.join(wd, 'mojo_runtime.o')
    r = subprocess.run([GCC, f'-I{RUNTIME_DIR}', '-c', '-o', runtime_o,
                        os.path.join(RUNTIME_DIR, 'mojo_runtime.c')],
                        capture_output=True, text=True, timeout=30)
    if r.returncode != 0:
        raise RuntimeError(f"gcc compile of mojo_runtime.c failed: {r.stderr}")
    import mojo
    r = mojo.link_executable(
        [os.path.join(wd, 'prog.o'), os.path.join(wd, 'prog_gen.o'), runtime_o],
        exe, cxx=True)
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

    # Milestone C step 4 (this step): compiled generators as first-class
    # values — bugs/CODEGEN_compiled_generator_not_first_class_value.md's
    # exact repro. Before this step `python3 mojo.py build` failed with a
    # genuine gcc compile error ("invalid use of void expression") the
    # moment a generator call's result was assigned to a variable before
    # being consumed, rather than being consumed inline as the `for` loop's
    # own iterable expression. This is the single most load-bearing new
    # test in this step: real compile+link+run, asserting the exact correct
    # output.
    test_generator_stdout("assign_then_for_loop_consumes_generator", """\
def counter(n):
    i = 0
    while i < n:
        yield i
        i = i + 1

def main():
    g = counter(3)
    for x in g:
        print(x)
""", "0\n1\n2\n")

    # The bug report's SECOND failure: calling next() directly on an
    # assigned generator variable, rather than consuming it via `for`.
    # Previously failed at LINK time (undefined symbol '_next') since the
    # generic next() builtin had no case for MojoGenerator* at all.
    test_generator_stdout("next_on_assigned_generator_var", """\
def counter(n):
    i = 0
    while i < n:
        yield i
        i = i + 1

def main():
    g = counter(3)
    print(next(g))
    print(next(g))
    print(next(g))
""", "0\n1\n2\n")

    # Edge case beyond the bug report's exact repro: calling next() PAST
    # exhaustion must raise StopIteration (not crash, not silently return a
    # stale/garbage value) — confirms the mojo_exc_type_set()/mojo_raise()
    # StopIteration-signaling convention added for next() is actually
    # catchable by an ordinary `except StopIteration:` in the same function,
    # exactly like a real Python generator's exhausted next().
    test_generator_stdout("next_past_exhaustion_raises_stopiteration", """\
def counter(n):
    i = 0
    while i < n:
        yield i
        i = i + 1

def main():
    g = counter(2)
    print(next(g))
    print(next(g))
    try:
        print(next(g))
    except StopIteration:
        print("done")
""", "0\n1\ndone\n")

    # Edge case beyond the bug report's exact repro: a generator variable
    # consumed by TWO separate `for` loops in sequence (the second over an
    # already-exhausted generator, which real Python simply iterates zero
    # times). Found via independent verification during this step: the
    # `for`-loop lowering originally destroyed the underlying coroutine
    # unconditionally once drained (correct ONLY for Milestone B's inline-
    # call-as-iterable shape, where that loop is the value's one and only
    # reference) — the moment the SAME generator became reachable by name
    # after the loop (this step's whole point), that unconditional destroy
    # turned a second consumption attempt into a real use-after-free
    # (confirmed crashing with SIGBUS before the fix). The second `for`
    # loop below must print nothing (not crash) — see _gen_for_iter's
    # destroy_after=isinstance(node.iterable, CallExpr) fix.
    test_generator_stdout("generator_variable_survives_two_for_loops", """\
def counter(n):
    i = 0
    while i < n:
        yield i
        i = i + 1

def main():
    g = counter(3)
    for x in g:
        print(x)
    for x in g:
        print(x)
    print("end")
""", "0\n1\n2\nend\n")

    # ── Milestone C final: generators crossing function-call boundaries ────
    # bugs/CODEGEN_compiled_generator_not_first_class_value.md's stated
    # remaining scope: a stored generator passed AS AN ARGUMENT to a
    # function whose (unannotated) param is consumed by `for x in g:`.
    # Before Pass 1.3f-gen, the call-site scalar contract observed `g`'s
    # stale int64_t inference and the callee's param defaulted to int64_t,
    # so the `for` loop hit the unsupported-iterable fallback (compile
    # still succeeded, but the loop body silently never ran).
    test_generator_stdout("generator_passed_as_argument", """\
def counter(n):
    i = 0
    while i < n:
        yield i
        i = i + 1

def consume(g):
    for x in g:
        print(x)

def main():
    g = counter(3)
    consume(g)
""", "0\n1\n2\n")

    # A generator RETURNED from a function (`def mk(): return counter(3)`)
    # and consumed by the caller — the second first-class shape from the
    # bug report's impact list. Before this step, a call to `mk()` got no
    # MojoGenerator* typing at all on its result (only direct calls to the
    # generator function itself did), so the outer `for` loop fell back.
    test_generator_stdout("generator_returned_from_function", """\
def counter(n):
    i = 0
    while i < n:
        yield i
        i = i + 1

def mk():
    return counter(3)

def main():
    g = mk()
    for x in g:
        print(x)
""", "0\n1\n2\n")

    # The two boundary shapes COMPOSED: return a generator from one
    # function, pass it into another, consume it there. Confirms the
    # provenance chain (caller assignment -> callee param) resolves
    # transitively rather than only for the immediate hop.
    test_generator_stdout("generator_returned_then_passed_as_argument", """\
def counter(n):
    i = 0
    while i < n:
        yield i
        i = i + 1

def mk():
    return counter(3)

def consume(g):
    for x in g:
        print(x)

def main():
    consume(mk())
""", "0\n1\n2\n")

    # next() on a generator that has crossed a function boundary — the
    # callee drives _resume/_value on the passed-in param, and the SAME
    # generator keeps yielding correctly in the caller afterward.
    test_generator_stdout("generator_next_through_function_boundary", """\
def counter(n):
    i = 0
    while i < n:
        yield i
        i = i + 1

def consume(g):
    print(next(g))
    print(next(g))

def main():
    g = counter(3)
    consume(g)
    print(next(g))
""", "0\n1\n2\n")

    # ── Milestone D: try/except/raise inside a compiled generator body ──────
    # (real C++ exceptions confined to the generator's own .cpp translation
    # unit, translated to the pre-existing mojo_exc_type/msg/obj global state
    # only at the extern "C" `_resume` boundary — see gimple_codegen.py's
    # _cpp_try_stmt/_cpp_raise_stmt and mojo_runtime.h's _mojo_exc_pending.)

    # A raise CAUGHT by the generator's OWN internal try/except — continues
    # yielding correctly afterward (not just "doesn't crash").
    test_generator_stdout("generator_raise_caught_internally", """\
def gen_internal_catch():
    i = 0
    while i < 5:
        try:
            if i == 2:
                raise ValueError("boom")
            yield i
        except ValueError:
            yield -1
        i = i + 1

def main():
    for x in gen_internal_catch():
        print(x)
""", "0\n1\n-1\n3\n4\n")

    # A raise NOT caught internally — propagates all the way out through the
    # extern "C" `_resume` boundary to the CALLER's own try/except, with the
    # right exception TYPE (only a ValueError handler matches) and the right
    # MESSAGE (bound via `as e`, read back correctly through the mojo_exc_obj
    # slot) — compared against real interpreter behavior below.
    test_generator_stdout("generator_raise_propagates_to_caller", """\
def gen_raises():
    yield 1
    yield 2
    raise ValueError("boom")

def main():
    try:
        for x in gen_raises():
            print(x)
    except ValueError as e:
        print(e)
""", "1\n2\nboom\n")

    # `yield from` delegating to a generator that raises, uncaught, partway
    # through — confirms the exception propagates correctly THROUGH the
    # delegation (Milestone C step 2) to the outer generator's own caller,
    # with values yielded before the raise (both the outer's own and the
    # relayed inner ones) still coming through in order first.
    test_generator_stdout("generator_yield_from_delegate_raises_propagates", """\
def inner_raises():
    yield 1
    raise KeyError("nope")

def outer_delegates():
    yield 0
    yield from inner_raises()
    yield 99

def main():
    try:
        for x in outer_delegates():
            print(x)
    except KeyError as e:
        print("caught")
        print(e)
""", "0\n1\ncaught\nnope\n")

    # `finally:` actually runs, the right NUMBER of times, across a mix of
    # normal iterations and an internally-caught raise — the observable
    # counterpart to test_gimple.py's compile-only finally coverage (a
    # `finally` result yielded AFTER the loop that used it finishes
    # normally, since `yield` can't appear inside the finally body itself —
    # see _cpp_try_stmt's docstring on why).
    test_generator_stdout("generator_try_except_finally_runs_every_time", """\
def gen_with_cleanup():
    cleanups = 0
    i = 0
    while i < 3:
        try:
            if i == 1:
                raise KeyError("x")
            yield i
        except KeyError:
            yield -1
        finally:
            cleanups = cleanups + 1
        i = i + 1
    yield cleanups

def main():
    for x in gen_with_cleanup():
        print(x)
""", "0\n-1\n2\n3\n")

    # Early exit (`break`) out of a `for` loop consuming a generator that has
    # an ACTIVE `try/finally` suspended mid-`co_yield` inside the try body —
    # the real-exception-machinery counterpart to Milestone B's early-
    # destroy precedent (for_loop_breaks_early_out_of_generator) and
    # Milestone C step 2's yield-from-early-break test. Per the C++20
    # coroutine-frame-destruction rules this relies on (see _cpp_try_stmt's
    # docstring on `_MojoScopeExit`), the finally-guard's destructor must
    # still fire correctly even though the coroutine is destroyed mid-try,
    # never reaching the finally "the normal way" — a crash/hang here (e.g.
    # from the guard's lambda capturing something already invalid) would
    # fail this test's subprocess run, which is the real thing being
    # checked, exactly like the precedent tests this one is modeled on.
    test_generator_stdout("generator_try_finally_survives_early_break", """\
def gen_finally_early_exit():
    i = 0
    while i < 100:
        try:
            yield i
        finally:
            i = i + 1

def main():
    for x in gen_finally_early_exit():
        if x == 2:
            break
        print(x)
""", "0\n1\n")

    # try/else/finally in a generator loop: on a normal (no-exception) pass
    # the `else` clause runs, THEN `finally`, each exactly once per
    # iteration. Regression guard for the fall-through path that used to
    # run the finally body twice (once falling into the finally label,
    # once again inline) — here it would have doubled BOTH `seen` and
    # `done`.
    test_generator_stdout("generator_try_else_finally_counts_once", """\
def gen():
    seen = 0
    done = 0
    i = 0
    while i < 3:
        try:
            yield i
        except KeyError:
            seen = seen + 100
        else:
            seen = seen + 1
        finally:
            done = done + 1
        i = i + 1
    yield seen
    yield done

def main():
    for x in gen():
        print(x)
""", "0\n1\n2\n3\n3\n")

    # Early `return` out of a try body that has a `finally`, inside a
    # generator: the finally must run exactly once on the way out and the
    # generator then stops (StopIteration). Regression guard for the
    # deferred-return path.
    test_generator_stdout("generator_try_finally_early_return_runs_once", """\
def gen():
    n = 0
    while True:
        try:
            if n == 2:
                return
            yield n
        finally:
            n = n + 1

def main():
    for x in gen():
        print(x)
    print("end")
""", "0\n1\nend\n")

    # Re-raise (bare `raise` with no value) inside a handler — the exception
    # is caught internally, immediately re-raised, and propagates out
    # uncaught (no value is ever yielded) to the caller's own try/except.
    # Exercises _cpp_raise_stmt's `throw {caught_var};` path (see
    # _cpp_try_stmt's docstring on why a bare `throw;` doesn't work here).
    test_generator_stdout("generator_reraise_propagates_to_caller", """\
def gen_reraise():
    try:
        raise ValueError("inner")
        yield 1
    except ValueError:
        raise

def main():
    try:
        for x in gen_reraise():
            print(x)
    except ValueError as e:
        print("caught")
        print(e)
""", "caught\ninner\n")

    # Multiple typed `except` clauses for DIFFERENT exception types in the
    # same try, each actually dispatching to its own (not just the first)
    # handler — exercises the descendant-OR dispatch chain built by
    # _cpp_try_stmt for real, not just compile-checked.
    test_generator_stdout("generator_multiple_except_types_dispatch_correctly", """\
def gen_multi_except():
    i = 0
    while i < 4:
        try:
            if i == 0:
                raise ValueError("v")
            if i == 1:
                raise KeyError("k")
            yield i
        except ValueError:
            yield -1
        except KeyError:
            yield -2
        i = i + 1

def main():
    for x in gen_multi_except():
        print(x)
""", "-1\n-2\n2\n3\n")

    # A bare `except:` catch-all — every exception type matches it, not just
    # ones that happen to share tag 0.
    test_generator_stdout("generator_bare_except_catches_anything", """\
def gen_bare_except():
    i = 0
    while i < 3:
        try:
            if i == 1:
                raise RuntimeError("x")
            yield i
        except:
            yield -1
        i = i + 1

def main():
    for x in gen_bare_except():
        print(x)
""", "0\n-1\n2\n")

    # LambdaExpr-as-value / bound-method-as-value in a compiled generator
    # body (see bugs/hard/CODEGEN_generator_lambda_expr_unsupported.md) —
    # mirrors pickletools.py's `_genops` shape EXACTLY: the same local
    # (`getpos`) is assigned a zero-arg `lambda` on one branch and a
    # bound-method VALUE (`self.tell`, not immediately called) on the
    # other, then invoked as a plain `getpos()`. The `self`-method variant.
    test_generator_stdout("generator_lambda_and_self_bound_method_as_value", """\
class Ticker:
    def __init__(self, start: Int):
        self.value = start

    def tell(self):
        return self.value

    def run(self, use_lambda: Int):
        if use_lambda:
            getpos = lambda: 42
        else:
            getpos = self.tell
        pos = getpos()
        yield pos

def main():
    tk = Ticker(7)
    for x in tk.run(1):
        print(x)
    for x in tk.run(0):
        print(x)
""", "42\n7\n")

    # Same shape, but the bound method is read off a struct-pointer
    # PARAMETER rather than `self` — the closer match to `_genops`' own
    # `getpos = data.tell` (where `data` is a generator PARAMETER, not the
    # enclosing struct), just with a statically-known struct type (`data`'s
    # real class in pickletools.py is a dynamically-typed io.BytesIO/file
    # object this narrow scalar-body model can't resolve at all — a
    # SEPARATE, honestly-unfixed gap; see that bug doc's own status notes).
    test_generator_stdout("generator_lambda_and_param_bound_method_as_value", """\
class Ticker:
    def __init__(self, start: Int):
        self.value = start

    def tell(self):
        return self.value

def gen(tk: Ticker, use_lambda: Int):
    if use_lambda:
        getpos = lambda: 99
    else:
        getpos = tk.tell
    pos = getpos()
    yield pos

def main():
    tk = Ticker(11)
    for x in gen(tk, 1):
        print(x)
    for x in gen(tk, 0):
        print(x)
""", "99\n11\n")

    # Struct-pointer-yield support (2026-08-20): a generator YIELDING a real
    # struct pointer value, not just accepting one as a parameter. Bare
    # struct-typed-parameter yield already worked before this change (see
    # `_infer_simple_expr_ctype`'s `known` map) — this confirms it as a
    # regression guard now that the same type-inference function also
    # widens IdentExpr/self.field/CallExpr cases.
    test_generator_stdout("struct_ptr_bare_param_yield", """\
class Ticker:
    def __init__(self, start: Int):
        self.value = start

def gen(tk: Ticker):
    yield tk

def main():
    t = Ticker(5)
    for x in gen(t):
        print(x.value)
""", "5\n")

    # `self.<dict-field>.get(key)` yielding a struct-pointer VALUE read out
    # of a `dict[K, StructType]`-typed field — the confirmed real-world
    # shape (Lib/enum.py's `Flag._iter_member_by_value_`:
    # `cls._value2member_map_.get(val)`, a `Flag *`), reduced to a `self`-
    # based (non-classmethod) generator method here since the `cls`-access
    # gap itself is a separate, still out-of-scope limitation (see
    # CODEGEN_generator_function_Lib_enum.md). Exercises: struct-pointer
    # yield-type inference via `_field_dict_val_types` (seeded early, from
    # the field's own `var map: dict[Int, Flag]` declaration, so it's
    # available in time for generator-method translation), the promise/
    # `co_yield`/consumer-side plumbing (unchanged, already generic), the
    # real `mojo_dict_get_int`-based `.get()` codegen this change ALSO
    # added to `_cpp_expr` (the raw `obj.get(k)` C++ fallback it replaces
    # doesn't compile against an opaque `MojoDict *`), and the struct-
    # typedef-visibility widening (`_cpp_value_struct_names`) for a struct
    # that's reachable ONLY via the yielded value's type, not via `self`, a
    # parameter, or a constructor call.
    test_generator_stdout("struct_ptr_dict_get_yield", """\
class Flag:
    def __init__(self, val: Int):
        self.val = val

class Container:
    var map: dict[Int, Flag]

    def __init__(self):
        self.map = {}

    def add(self, k: Int, f: Flag):
        self.map[k] = f

    def gen(self, k: Int):
        yield self.map.get(k)

def main():
    c = Container()
    f = Flag(42)
    c.add(1, f)
    for x in c.gen(1):
        print(x.val)
""", "42\n")

    # General case: a struct-typed receiver's own METHOD call chain
    # returning ANOTHER struct pointer, yielded directly — not just the
    # `.get()` shape above. Exercises `method_return_types` (this file's
    # existing `self.func_return_types`, reused rather than re-derived) in
    # `_infer_simple_expr_ctype`'s CallExpr/MemberExpr branch.
    test_generator_stdout("struct_ptr_method_chain_yield", """\
class Inner:
    def __init__(self, v: Int):
        self.v = v

class Outer:
    def __init__(self, v: Int):
        self.inner = Inner(v)

    def get_inner(self):
        return self.inner

def gen(o: Outer):
    yield o.get_inner()

def main():
    o = Outer(99)
    for x in gen(o):
        print(x.v)
""", "99\n")

    # `cls.<attr>` class-attribute redirect + `cls.<attr>.get(...)` dict
    # lookup inside a compiled @classmethod generator — the exact
    # Lib/enum.py `Flag._iter_member_by_value_` shape (`for val in
    # _iter_bits_lsb(value & cls._flag_mask_): yield cls._value2member_map_.
    # get(val)`), reduced to its two load-bearing pieces: a bare `cls.<attr>`
    # read (`cls._flag_mask_`-equivalent, used inline rather than yielded)
    # and a `cls.<dict-attr>.get(key)` yield whose value type is a real
    # struct pointer (`cls._value2member_map_.get(val)`-equivalent). Called
    # via an INSTANCE (`r.gen(k)`, mirroring enum.py's own real call site,
    # `self._iter_member_(self._value_)`) — invoking a @classmethod
    # generator via the CLASS NAME directly (`Registry.gen(k)`) hits a
    # separate, pre-existing call-site gap in the ordinary (non-generator)
    # GIMPLE path (routing a class-name method call to the generator-start
    # API), out of this fix's scope (see bugs/CODEGEN_generator_function_
    # Lib_enum.md's 2026-08-21 update). See that same doc's update for the
    # full root-cause.
    test_generator_stdout("cls_class_attr_dict_get_yield", """\
class Flag:
    def __init__(self, val: Int):
        self.val = val

class Registry:
    _value_map: dict[Int, Flag] = {}
    _mask: Int = 3

    def __init__(self):
        self._value_map[1] = Flag(42)
        self._value_map[2] = Flag(43)

    @classmethod
    def gen(cls, k: Int):
        m = cls._mask
        if k <= m:
            yield cls._value_map.get(k)

def main():
    r = Registry()
    for x in r.gen(1):
        print(x.val)
    for x in r.gen(2):
        print(x.val)
""", "42\n43\n")

    # `cls.method(...)` call inside a compiled @classmethod generator —
    # resolved purely by NAME (the enclosing struct's own real compiled
    # classmethod), mirroring the `self.method(...)` call case's own
    # mechanism. See bugs/CODEGEN_generator_function_Lib_enum.md's
    # 2026-08-21 update, point (2). Also called via an instance, for the
    # same call-site-gap reason noted above.
    test_generator_stdout("cls_classmethod_call_in_generator", """\
class Helper:
    def __init__(self):
        self.dummy = 0

    @classmethod
    def double(cls, n: Int):
        return n * 2

    @classmethod
    def gen(cls, n: Int):
        yield cls.double(n)

def main():
    h = Helper()
    for x in h.gen(21):
        print(x)
""", "42\n")

    # `yield from sorted(<iterable>, key=lambda x: ...)` — a single-
    # parameter lambda passed directly as a `key=` call argument (not
    # assigned to a local first, unlike `generator_lambda_and_*_bound_
    # method_as_value` above). Real target: Lib/enum.py's
    # `Flag._iter_member_by_def_`: `yield from sorted(cls._iter_member_
    # by_value_(value), key=lambda m: m._sort_order_)` — see
    # bugs/hard/CODEGEN_generator_lambda_expr_unsupported.md's
    # "single-parameter lambda" follow-up. This is also the regression
    # test for a real, confirmed SEGFAULT this same session found and
    # fixed: the promise/consumer-side type inference for `yield from
    # sorted(...)` previously defaulted to char* (the generic "unknown
    # collection" fallback), so the sort's own int64_t-payload MojoList
    # got read back via `mojo_list_get_str` — a garbage pointer
    # dereference — regardless of element type, not just the struct-
    # pointer-element shape. Asserts DESCENDING order (`-m` key) to
    # confirm the comparator is genuinely being invoked per-element, not
    # just passing the list through unsorted.
    test_generator_stdout("generator_sorted_key_lambda_scalar", """\
def gen(xs: list):
    yield from sorted(xs, key=lambda m: -m)

def main():
    for x in gen([3, 1, 2]):
        print(x)
""", "3\n2\n1\n")

    # `for i, d in enumerate(<call to another compiled generator>, start):`
    # inside a generator body — a GENERATOR CALL as enumerate's OWN first
    # argument (flat 2-name target), composed with the sub-generator drive
    # loop and its index tracking. Real target: Lib/calendar.py's
    # `Calendar.itermonthdays2` (`for i, d in
    # enumerate(self.itermonthdays(year, month), self.firstweekday):`) —
    # previously `_cpp_expr` lowered the generator call through the wrong
    # ordinary extern "C" stub (void-returning), producing g++'s "void
    # value not ignored as it ought to be". The free-function callee shape
    # exercises the same delegation machinery through its other branch.
    test_generator_stdout("enumerate_generator_method_arg_start", """\
class Cal:
    def __init__(self):
        self.firstweekday = 2

    def iterdays(self, n):
        yield from range(1, n + 1)

    def iterdaynum(self, n):
        for i, d in enumerate(self.iterdays(n), self.firstweekday):
            yield d, i % 7

def main():
    c = Cal()
    for d, wd in c.iterdaynum(4):
        print(d, wd)
""", "1 2\n2 3\n3 4\n4 5\n")

    test_generator_stdout("enumerate_generator_free_fn_arg_start", """\
def days(n):
    yield from range(1, n + 1)

def numbered(n, start):
    for i, d in enumerate(days(n), start):
        yield d * 100 + i

def main():
    for v in numbered(3, 10):
        print(v)
""", "110\n211\n312\n")

    # `self.<method>()` inside a generator body OMITTING a defaulted
    # trailing parameter (`def scaled(self, mult=2)` called as
    # `self.scaled()`). Real target: Lib/mailbox.py's
    # `_singlefileMailbox.iterkeys` doing `self._lookup()` on
    # `def _lookup(self, key=None)` and `_ProxyFile.__iter__` doing
    # `self.readline()` on `def readline(self, size=None)` — previously
    # the coroutine-body call lowering emitted only the given arguments
    # ("too few arguments to function '_singlefileMailbox__lookup'").
    # The ordinary (non-coroutine) method-call path already padded short
    # calls; the three coroutine-body struct-method call branches now run
    # through the same arity/defaults padding.
    test_generator_stdout("generator_self_method_defaulted_arg", """\
class Box:
    def __init__(self):
        self.base = 100

    def scaled(self, mult=2):
        return self.base * mult

    def gen(self):
        yield self.scaled()
        yield self.scaled(5)

def main():
    b = Box()
    for v in b.gen():
        print(v)
""", "200\n500\n")

    # `lines = []` + `lines.append(v)` + iteration/subscript/len over the
    # local list inside a generator body — the single most common
    # accumulator idiom in real stdlib generators (ftplib.py's mlsd and
    # many others). Previously the literal lowered to raw C++ brace-init
    # text assigned to an int64_t-declared local ("request for member
    # 'append' in 'lines', which is of non-class type 'int64_t'"); now a
    # real MojoList* with element-type tracking driving the accessors.
    test_generator_stdout("generator_list_literal_local_append_iterate", """\
def gen(n):
    acc = []
    acc.append(1)
    acc.append(2 * n)
    yield len(acc)
    yield acc[1]
    total = 0
    for v in acc:
        total = total + v
    yield total

def main():
    for v in gen(10):
        print(v)
""", "2\n20\n21\n")

    test_generator_stdout("generator_str_list_local_roundtrip", """\
def gen():
    lines = []
    lines.append("alpha")
    lines.append("beta")
    for s in lines:
        yield s
    yield lines[0]

def main():
    for v in gen():
        print(v)
""", "alpha\nbeta\nalpha\n")

    # `entry = {}` + string-keyed writes + reads keyed by a loop variable
    # over a string-literal tuple (the tuple-range-for's `auto` target must
    # be tracked as char* or the dict key gets garbage-stringified through
    # mojo_str_from_int).
    test_generator_stdout("generator_dict_local_string_keys", """\
def dgen():
    entry = {}
    entry["alpha"] = 1
    entry["beta"] = 2
    s = 0
    for k in ("alpha", "beta"):
        s = s + entry[k]
    yield s

def main():
    for v in dgen():
        print(v)
""", "3\n")

    # ── Generator-consumption ordering + param-default padding family ─────
    #
    # A DEEP forward-consumption chain: every consumer is defined BEFORE
    # its producer, and each level's unit only becomes compilable after
    # the level below it registers (gen_module's retry passes). The retry
    # loop used to be a hard-coded 3 passes — this 5-deep chain needs 4,
    # so it used to leave head/l3 refused and fall back to interpreting
    # the whole module. Values are chosen so each link's wiring is
    # visible in the final number: tail(3)=0+1+2 -> l1=30 -> l2=130 ->
    # l3=130 -> head=1130.
    test_generator_stdout("generator_forward_consumption_deep_chain", """\
def head(n):
    t = 0
    for x in l3(n):
        t = t + x
    yield t + 1000

def l3(n):
    t = 0
    for x in l2(n):
        t = t + x
    yield t

def l2(n):
    t = 0
    for x in l1(n):
        t = t + x
    yield t + 100

def l1(n):
    t = 0
    for x in tail(n):
        t = t + x
    yield t * 10

def tail(n):
    i = 0
    while i < n:
        yield i
        i = i + 1

def main():
    for v in head(3):
        print(v)
""", "1130\n")

    # A consuming for-loop omitting a LATER-defaulted argument of the
    # consumed generator (`for x in prod(n)` against `def prod(n,
    # step=10)`): must pad step=10, not refuse on arity and not pad a
    # typed zero (which silently produced 0+1+2=3 instead of 33).
    test_generator_stdout("generator_for_consumption_pads_callee_defaults", """\
def prod(n, step=10):
    i = 0
    while i < n:
        yield i + step
        i = i + 1

def consumer(n):
    total = 0
    for x in prod(n):
        total = total + x
    yield total

def main():
    for v in consumer(3):
        print(v)
""", "33\n")

    # The DIRECT construction call path with an omitted non-zero-offset
    # default (`prod(3)` against `def prod(n, step=10)`): the padding
    # indexed the defaults list WITHOUT its trailing-run offset, so the
    # omitted arg silently got 0 instead of 10 — real compiled output,
    # no refusal, wrong number. Regression test for that silent-miscompile.
    test_generator_stdout("generator_direct_call_pads_nonzero_offset_default", """\
def prod(n, step=10):
    i = 0
    while i < n:
        yield i + step
        i = i + 1

def main():
    total = 0
    for v in prod(3):
        total = total + v
    print(total)
""", "33\n")

    # Same trailing-default padding through the `yield from` delegation
    # drive loop (`yield from inner(base)` against `def inner(start,
    # count=2)`): must delegate with count=2.
    test_generator_stdout("generator_yield_from_pads_callee_defaults", """\
def inner(start, count=2):
    i = start
    k = 0
    while k < count:
        yield i
        i = i + 1
        k = k + 1

def outer(base):
    yield from inner(base)

def main():
    for v in outer(7):
        print(v)
""", "7\n8\n")

    # Method-generator direct call with an omitted default after a
    # leading required non-self param (`c.gen(3)` against `def gen(self,
    # n, step=2)`): the method-call padding must skip `self` AND apply
    # the trailing-run offset — it previously did neither correctly for
    # this shape (padded 0, yielding 10/11/12).
    test_generator_stdout("generator_method_call_pads_nonzero_offset_default", """\
class C:
    def __init__(self, base: Int):
        self.base = base

    def gen(self, n: Int, step: Int = 2):
        i = 0
        while i < n:
            yield self.base + i * step
            i = i + 1

def main():
    c = C(10)
    for v in c.gen(3):
        print(v)
""", "10\n12\n14\n")

    # Pop-time shape discrimination for a heterogeneous / tagged-union
    # `stack` value model: a list holding both scalar elements and nested
    # tuples, drained with `.pop()`, each popped value discriminated with
    # `isinstance(top, tuple)` and (when a tuple) destructured via a
    # tuple-unpack. Exercises: nested-container literal appended to a flat
    # boxed list, `while <list>:` emptiness (not pointer-nullness),
    # `<list>.pop()`, runtime `mojo_is_registered_list` discrimination,
    # and a boxed-value tuple-unpack through the runtime list getters.
    test_generator_stdout("generator_pops_heterogeneous_tagged_stack", """\
def walker():
    stack = [(1, 2)]
    stack.append("leaf")
    stack.append((3, 4))
    while stack:
        top = stack.pop()
        if isinstance(top, tuple):
            a, b = top
            yield a + b
        else:
            yield 99

def main():
    for x in walker():
        print(x)
""", "7\n99\n3\n")

    # Second-level unpack: `marker, payload = stack.pop()` where `payload`
    # is itself a boxed tuple needing its own unpack (the exact `_fwalk`
    # shape from bugs/CODEGEN_generator_function_Lib_os.md — `action,
    # value = stack.pop()` then `isroot, ... = value`).
    test_generator_stdout("generator_pops_stack_two_level_tuple_unpack", """\
def walker():
    stack = []
    stack.append((0, (10, 20, 30)))
    stack.append((1, (40, 50, 60)))
    while stack:
        marker, payload = stack.pop()
        x, y, z = payload
        yield marker + x + y + z

def main():
    for v in walker():
        print(v)
""", "151\n60\n")


    # `var`-declared local (Mojo VarDecl) inside a generator body, plus a
    # string built in the body from a numeric part via String(i) and
    # concatenation — the compiled coroutine emitter used to hard-refuse
    # the VarDecl outright ("unsupported statement in generator body:
    # VarDecl") and, once that was lowered, mis-stringify String(0) as
    # "None" (mojo_str's pointer heuristic reads 0 as NULL).
    test_generator_stdout("generator_vardecl_string_built_in_body", """\
def gen_str(n):
    for i in range(n):
        var s = "item" + String(i)
        yield s

def main():
    for x in gen_str(3):
        print(x)
""", "item0\nitem1\nitem2\n")

    # Resumable list-iterator value model inside a generator body:
    # `it = iter(xs)` binds a real cursor, `next(it)` advances it, a
    # following `for x in it:` continues from where next() left off, and
    # `next(it, default)` returns the default on exhaustion. Plus
    # `min(iterable)`/`max(iterable)` and multi-arg `min(a, b, ...)`.
    # Mirrors bugs/CODEGEN_generator_function_Lib_ipaddress.md's
    # `_find_address_range` shape. Previously every one of these refused
    # the whole module ("unresolved callee 'next(...)'" etc.).
    test_generator_stdout("generator_list_iterator_cursor_and_minmax", """\
def scan(xs):
    it = iter(xs)
    first = next(it)
    yield first
    for x in it:
        yield x
    yield next(it, -1)
    yield min(xs)
    yield max(xs)
    yield min(8, 3, 5, 1, 9)

def main():
    for v in scan([10, 20, 30]):
        print(v)
""", "10\n20\n30\n-1\n10\n30\n1\n")

    # StopIteration from an exhausted list-iterator's next() is a real
    # tagged exception, catchable by an enclosing try/except in the body.
    test_generator_stdout("generator_list_iterator_stopiteration_caught", """\
def scan(xs):
    it = iter(xs)
    yield next(it)
    try:
        yield next(it)
        yield next(it)
    except StopIteration:
        yield 999

def main():
    for v in scan([7]):
        print(v)
""", "7\n999\n")

    # bugs/hard/CODEGEN_coro_stackswitch_iterator_protocol_gaps.md — the A3
    # stack-switch cutover routes a generator BODY through the ordinary
    # codegen, which never had a real iter()/next() over a plain list
    # (only the old cpp-path emitter did, in gimple_cpp_core.py). Below:
    # a STRING-element list iterator (accessor kind picked from the list's
    # tracked element type, not hard-coded to get_int), next(it, default)
    # returning the default only on real exhaustion, and next(it, default)
    # still yielding a real element while the cursor has more.
    test_generator_stdout("generator_str_list_iterator_next_default", """\
def scan():
    xs = ["a", "b"]
    it = iter(xs)
    yield next(it)
    yield next(it, "END")
    yield next(it, "END")

def main():
    for s in scan():
        print(s)
""", "a\nb\nEND\n")

    # enumerate(<generator>) with NO explicit start (0-based) — the
    # zero-arg-start branch of the same _gen_for_enumerate_generator path.
    test_generator_stdout("enumerate_generator_no_start", """\
def src(n):
    for i in range(n):
        yield i * 10

def numbered(n):
    for i, v in enumerate(src(n)):
        yield v + i

def main():
    for x in numbered(4):
        print(x)
""", "0\n11\n22\n33\n")

    # A generator body that consumes its list arg with BOTH next() and a
    # following `for x in it:` — the for-loop must resume from the cursor
    # next() already advanced (single-pass), not restart from element 0.
    test_generator_stdout("generator_list_iter_next_then_for_resumes", """\
def scan(xs):
    it = iter(xs)
    first = next(it)
    yield first
    for x in it:
        yield x

def main():
    for v in scan([1, 2, 3, 4]):
        print(v)
""", "1\n2\n3\n4\n")

    # ── yield-kind inference for identifier / self.field / list-local refs ──
    # (bugs/hard/CODEGEN_coro_stackswitch_yield_kind_identifier_inference.md)
    # The Layer-1 pre-pass's _yield_kind() used to have no case for a bare
    # IdentExpr / `self.<field>` / `<list-local>[idx]` reference, so a
    # Float64/String value yielded through one of those silently defaulted
    # to int64_t and was truncated (float) or printed as a raw pointer
    # value (string). _static_env now resolves them from purely-syntactic
    # type sources available at pre-pass time.

    # self.<field> whose type comes from __init__(self, base: Float64)
    test_generator_stdout("generator_yields_self_float_field_plus_int", """\
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

    # bare identifier resolved from the generator's own param annotation
    test_generator_stdout("generator_yields_string_param_identifier", """\
def echo(s: String):
    yield s
    yield s

def main():
    for v in echo("hello"):
        print(v)
""", "hello\nhello\n")

    # list-typed local: `xs = [<string literals>]`, `yield xs[i % 2]`
    test_generator_stdout("generator_yields_string_list_local_subscript", """\
def strs():
    xs = ["alpha", "beta"]
    i = 0
    while i < 3:
        yield xs[i % 2]
        i = i + 1

def main():
    for s in strs():
        print(s)
""", "alpha\nbeta\nalpha\n")

    # float local seeded from a float literal, yielded bare
    test_generator_stdout("generator_yields_float_local_identifier", """\
def ramp():
    x = 0.5
    i = 0
    while i < 3:
        yield x
        x = x + 1.0
        i = i + 1

def main():
    for v in ramp():
        print(v)
""", "0.5\n1.5\n2.5\n")

    # ── non-plain assignment targets inside a generator body ──────────
    # (bugs/hard/CODEGEN_generator_non_plain_assignment_target_refused.md)
    # The A3 stack-switch path routes the desugared body through ordinary
    # codegen, which handles self-field write, subscript write, and
    # tuple/list-pattern unpack -- shapes the old cpp eligibility gate
    # refused wholesale.
    test_generator_stdout("generator_list_pattern_unpack_literal_rhs", """\
def g():
    yield 1
    [x] = [42]
    yield x

def main():
    for v in g():
        print(v)
""", "1\n42\n")

    test_generator_stdout("generator_list_pattern_unpack_two_and_call_rhs", """\
def src():
    return [7, 8]

def g():
    [a, b] = src()
    yield a
    yield b
    [c] = [99]
    yield c

def main():
    for v in g():
        print(v)
""", "7\n8\n99\n")

    test_generator_stdout("generator_list_pattern_unpack_comprehension_rhs", """\
def g():
    yield 1
    src = [10, 20, 30]
    [first] = [w for w in src if w == 20]
    yield first

def main():
    for v in g():
        print(v)
""", "1\n20\n")

    test_generator_stdout("generator_self_field_write_between_yields", """\
struct Counter:
    var count: Int
    fn __init__(out self):
        self.count = 0
    def gen(self):
        yield self.count
        self.count = 99
        yield self.count

def main():
    c = Counter()
    for v in c.gen():
        print(v)
""", "0\n99\n")

    test_generator_stdout("generator_subscript_write_between_yields", """\
def g(d):
    yield d[0]
    d[0] = 99
    yield d[0]

def main():
    xs = [1, 2, 3]
    for v in g(xs):
        print(v)
""", "1\n99\n")

    # ── recursive `yield from` forwards extra positional + keyword-only
    # arguments (bugs/hard/CODEGEN_generator_recursive_yield_from_no_arg_
    # forwarding.md). The documented "too few arguments" / yield-type
    # mismatch compile failures are gone on the A3 path.
    test_generator_stdout("generator_recursive_yield_from_extra_positional_arg", """\
def countdown(n, step=1):
    if n <= 0:
        return
    yield n
    yield from countdown(n - step, step)

def main():
    for v in countdown(5, 2):
        print(v)
""", "5\n3\n1\n")

    test_generator_stdout("generator_recursive_yield_from_keyword_only_arg", """\
def countdown(n, *, step=1):
    if n <= 0:
        return
    yield n
    yield from countdown(n - step, step=step)

def main():
    for v in countdown(5, 2 if False else 2):
        print(v)
""", "5\n3\n1\n")

    # ── lambda literals inside a generator body ───────────────────────
    # (bugs/hard/CODEGEN_generator_lambda_expr_unsupported.md) -- 0-, 1-
    # and 2-parameter lambdas, a lambda re-bound on each branch of an
    # if/else, and a lambda passed as a call argument all work via the
    # ordinary codegen path's lambda lifting.
    test_generator_stdout("generator_zero_arg_lambda_called", """\
def g(n):
    getpos = lambda: 7
    i = 0
    while i < n:
        yield getpos()
        i = i + 1

def main():
    for v in g(3):
        print(v)
""", "7\n7\n7\n")

    test_generator_stdout("generator_one_arg_lambda_over_list", """\
def g(xs):
    f = lambda m: m + 1
    for x in xs:
        yield f(x)

def main():
    for v in g([10, 20, 30]):
        print(v)
""", "11\n21\n31\n")

    test_generator_stdout("generator_two_arg_lambda_and_lambda_as_arg", """\
def apply(fn, v):
    return fn(v)

def g(xs):
    add = lambda a, b: a + b
    for x in xs:
        yield apply(lambda m: m * 2, add(x, 10))

def main():
    for v in g([1, 2, 3]):
        print(v)
""", "22\n24\n26\n")

    test_generator_stdout("generator_lambda_rebound_per_branch", """\
def g(pick):
    if pick:
        f = lambda: 42
    else:
        f = lambda: 99
    yield f()

def main():
    for v in g(1):
        print(v)
    for v in g(0):
        print(v)
""", "42\n99\n")

    # ---- Regression tests distilled from the 30 bugs/CODEGEN_generator_
    # function_Lib_*.md stdlib shapes that the doc/COROUTINE.html §5.5 A3
    # stack-switch cutover made compile (previously wholesale-refused by
    # the old gimple_cpp_core.py C++20-coroutine eligibility gate). One
    # minimal shape per stdlib family that flipped to compiling.

    # weakref.WeakValueDictionary.__iter__ / tarfile.TarFile.__iter__ /
    # tempfile._TemporaryFileWrapper.__iter__ / typing._GenericAlias.
    # __iter__ / mailbox / shelve: a generator METHOD on a struct that
    # walks a list field and yields each element.
    test_generator_stdout("generator_method_iterates_list_field", """\
struct Bag:
    var items: List[Int]
    fn __init__(out self):
        self.items = [10, 20, 30]
    fn each(self):
        for x in self.items:
            yield x

def main():
    b = Bag()
    for v in b.each():
        print(v)
""", "10\n20\n30\n")

    # dis.findlinestarts / ipaddress._find_address_range: for-loop over an
    # explicitly-typed list param with a guarded yield inside the loop body.
    test_generator_stdout("generator_guarded_yield_in_for_over_typed_param", """\
def positives(xs: List[Int]):
    for x in xs:
        if x > 0:
            yield x

def main():
    for v in positives([-2, 3, -1, 5, 0, 8]):
        print(v)
""", "3\n5\n8\n")

    # enum._iter_bits_lsb / dis._unpack_opargs: for-loop over range() with a
    # modulo guard, yielding a filtered subset.
    test_generator_stdout("generator_range_loop_with_modulo_guard", """\
def evens(n):
    for x in range(n):
        if x % 2 == 0:
            yield x

def main():
    for v in evens(6):
        print(v)
""", "0\n2\n4\n")

    # glob._iglob / pkgutil.walk_packages / tokenize.tokenize: a generator
    # that delegates to another generator with `yield from`, then yields
    # more of its own values afterward.
    test_generator_stdout("generator_yield_from_then_own_values", """\
def inner(n):
    i = 0
    while i < n:
        yield i
        i = i + 1

def outer(n):
    yield from inner(n)
    yield 100
    yield 101

def main():
    for v in outer(3):
        print(v)
""", "0\n1\n2\n100\n101\n")

    # symtable.Symbol._flags_str / tokenize helpers: accumulate across
    # yields with a running local updated before each yield, iterating a
    # locally-built int list.
    test_generator_stdout("generator_running_local_across_yields", """\
def deltas():
    xs = [1, 2, 3, 4]
    total = 0
    for x in xs:
        total = total + x
        yield total

def main():
    for v in deltas():
        print(v)
""", "1\n3\n6\n10\n")

    if _FAIL:
        print(f"\n{_PASS} passed, {_FAIL} failed")
        raise SystemExit(1)
    print(f"\n{_PASS} passed, {_FAIL} failed")


if __name__ == '__main__':
    run_tests()
