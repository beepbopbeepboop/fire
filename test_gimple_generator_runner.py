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

    if _FAIL:
        print(f"\n{_PASS} passed, {_FAIL} failed")
        raise SystemExit(1)
    print(f"\n{_PASS} passed, {_FAIL} failed")


if __name__ == '__main__':
    run_tests()
