"""test_coro_nested_async_capture.py -- real behavioral test for the A3
stack-switch coroutine backend's mutable closure capture into a nested
`async def`.

Fixed 2026-09-27 and registered in tools/suite.py as `coro-nested-capture`
(in `check`/`gate`): `_RUNTIME_SRCS` named the pre-rename `mojo_*.c` runtime
files (renamed to `fire_*.c`), so 7 of 9 cases died compiling the runtime
before the program under test was ever compiled. 9/9 then: struct-typed
capture (`test_struct_capture_compiles_boxed_and_correct`) used to assert
the PRE-Increment-E refusal-to-cpp-path behaviour, which no longer happens
-- a struct capture now boxes and runs correctly, so that test was rewritten
to assert the current (correct) behaviour instead of the old one.

10/10 as of 2026-09-29, with the bug doc's item 3 added
(`test_nested_async_generator_driven_by_async_for`): a nested async
GENERATOR consumed by `async for` in its own enclosing function built, ran,
exited 0 and printed `0` where CPython prints `11`. A comment in this file
still claimed the cross-closure stress shape below was uncovered and
unreachable; it has been covered (and passing) since the
`_rewrite_asyncio_run_stmts` local_map merge, so that claim is corrected
here rather than left to mislead the next reader.

Exercises the bug doc's own headline shape verbatim (also the real
`test_async_with_lock_guard.py::test_simple_with_lock_guard_single_task`
cpp-path test source, unmodified) under MOJO_CORO=stackswitch:

    def test_with_lock() raises:
        var lock = BlockingSpinLock()
        var rawCounter = 0

        @parameter
        async def inc():
            with BlockingScopedLock(lock):
                rawCounter += 1

        var t0 = create_task(inc())
        t0.wait()
        print(rawCounter)

`rawCounter` is a free variable of the nested `inc()` resolving to
`test_with_lock`'s own local -- v0 support (gimple_gen_coro.py's
`_nested_async_capture_plan`/`_apply_nested_async_capture`) boxes it as
a heap `int64_t` cell (`__mojo_box_new_i64`/`_get_i64`/`_set_i64`,
runtime/mojo_coro_gen.c), threaded as a hidden trailing parameter into
the hoisted `__mgco_test_with_lock_inc_*` unit, with every read/write of
`rawCounter` in BOTH the enclosing function and the nested body rewritten
to go through the box. `with BlockingScopedLock(lock):` itself is elided
(a provable no-op in this single-threaded/cooperative runtime -- see
gimple_gen_coro.py's own `_is_lock_with` docstring), matching the cpp
path's identical treatment.

STILL not covered here, and deliberately so:
  * the wait-descriptor boundary of `async for` -- an async generator whose
    body can PARK, consumed by a function with no yield channel of its own.
    That is a compile-time refusal, and the shape needs `import asyncio`
    plus a real scheduler, so it lives with its siblings in
    test_gimple_generator_runner.py (`async_for_over_parking_async_gen_
    refused` and the three other cases beside it), whose harness compiles
    the same way this one does.
  * any `async for` whose iterable is not a plain call (a variable, an
    attribute, an expression) -- `_async_for_ok` refuses the containing
    coroutine outright for that, and the ordinary loop lowering's
    `MojoGenerator *` route is what the item-3 fix is about, not this
    file's capture plan.

The wait-descriptor FIXED POINT that decides the boundary above
(`coro._compute_no_wd_forward`) IS covered here, in the last three cases,
because it is the one piece of this area with no native runtime to fail
against: the first two run the analysis in-process over synthetic call
graphs -- the walk budget and the answer on every shape that has ever
distinguished a correct implementation from a wrong one -- and the third
runs the algorithm's SHAPE compiled and native, against CPython, which is
the only way to see that the containers it uses still mean what they mean
once this codegen has erased their element types.
"""
import os
import platform
import subprocess
import tempfile

os.environ['MOJO_CORO'] = 'stackswitch'

import gimple_codegen
import fire_compiler
from mojo.middle import coro
from build_config import find_gcc, find_gxx

HERE = os.path.dirname(os.path.abspath(__file__))
RUNTIME_DIR = os.path.join(HERE, 'runtime')
GCC = find_gcc()
GXX = find_gxx()

_CORO_CTX_SRC = (os.path.join(RUNTIME_DIR, 'fire_coro_ctx_aarch64.S')
                 if platform.machine() in ('arm64', 'aarch64')
                 else os.path.join(RUNTIME_DIR, 'fire_coro_ctx_generic.c'))

_RUNTIME_SRCS = [
    os.path.join(RUNTIME_DIR, 'fire_runtime.c'),
    os.path.join(RUNTIME_DIR, 'fire_async_runtime.cpp'),
    os.path.join(RUNTIME_DIR, 'fire_coro.c'),
    os.path.join(RUNTIME_DIR, 'fire_coro_gen.c'),
    os.path.join(RUNTIME_DIR, 'fire_async_sched.c'),
    _CORO_CTX_SRC,
]

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


def _build_and_run(mojo_src: str, require=('__mgco_', '__mojo_box_new_')) -> str:
    wd = tempfile.mkdtemp(prefix='mojo_coro_capture_')
    src_path = os.path.join(wd, 'prog.mojo')
    with open(src_path, 'w') as f:
        f.write(mojo_src)

    c_code = gimple_codegen.compile_to_gimple(mojo_src, do_imports=False, filename=src_path)
    for sym, why in (('__mgco_', "expected the nested async def in this source to be "
                                 "lowered by gimple_gen_coro (stack-switch) -- no "
                                 "__mgco_ symbols in the generated C, so this test "
                                 "isn't exercising the code path it claims to"),
                     ('__mojo_box_new_', "expected the captured local to be "
                                          "heap-boxed -- no __mojo_box_new_* call in "
                                          "the generated C, so the capture wasn't "
                                          "actually threaded through as designed")):
        if sym in require and sym not in c_code:
            raise RuntimeError(why)

    c_path = os.path.join(wd, 'prog.c')
    with open(c_path, 'w') as f:
        f.write(c_code)

    objs = []
    r = subprocess.run([GCC, '-fgimple', f'-I{RUNTIME_DIR}', '-w', '-c', '-o',
                        os.path.join(wd, 'prog.o'), c_path],
                        capture_output=True, text=True, timeout=30)
    if r.returncode != 0:
        raise RuntimeError(f"gcc -fgimple compile of .c failed: {r.stderr}\n---\n{c_code}")
    objs.append(os.path.join(wd, 'prog.o'))

    for i, src in enumerate(_RUNTIME_SRCS):
        is_cpp = src.endswith('.cpp')
        cc = GXX if is_cpp else GCC
        extra = ['-std=c++20'] if is_cpp else []
        o = os.path.join(wd, f'rt{i}.o')
        r = subprocess.run([cc, *extra, f'-I{RUNTIME_DIR}', '-c', '-o', o, src],
                            capture_output=True, text=True, timeout=30)
        if r.returncode != 0:
            raise RuntimeError(f"compile of {src} failed: {r.stderr}")
        objs.append(o)

    exe = os.path.join(wd, 'prog.exe')
    r = subprocess.run([GXX, '-o', exe, *objs], capture_output=True, text=True, timeout=30)
    if r.returncode != 0:
        raise RuntimeError(f"link failed: {r.stderr}")

    os.chmod(exe, 0o755)
    r = subprocess.run([exe], capture_output=True, text=True, timeout=30)
    if r.returncode != 0:
        raise RuntimeError(f"program exited {r.returncode}, stderr={r.stderr}")
    return r.stdout


def test_simple_with_lock_guard_single_task():
    """The bug doc's own headline shape (also test_async_with_lock_guard.py
    ::test_simple_with_lock_guard_single_task's exact cpp-path source,
    verbatim): a nested async closure mutating an outer local (`rawCounter
    += 1`) inside a `with BlockingScopedLock(lock):` guard, driven via
    create_task/.wait() -- the mutation must be observed by the enclosing
    function after .wait() returns."""
    src = """\
def test_with_lock() raises:
    var lock = BlockingSpinLock()
    var rawCounter = 0

    @parameter
    async def inc():
        with BlockingScopedLock(lock):
            rawCounter += 1

    var t0 = create_task(inc())
    t0.wait()
    print(rawCounter)


def main() raises:
    test_with_lock()
"""
    out = _build_and_run(src)
    check("with BlockingScopedLock(lock): rawCounter += 1 -> 1",
          out == "1\n", detail=repr(out))


def test_capture_without_lock_guard():
    """The same capture mechanism with no lock-with at all (isolates the
    box-threading itself from the separate lock-elision mechanism) -- two
    separate tasks each incrementing the same captured counter, read after
    both complete."""
    src = """\
def test_plain_capture() raises:
    var counter = 0

    @parameter
    async def bump():
        counter += 1

    var t0 = create_task(bump())
    t0.wait()
    var t1 = create_task(bump())
    t1.wait()
    print(counter)


def main() raises:
    test_plain_capture()
"""
    out = _build_and_run(src)
    check("two sequential create_task(bump()).wait() calls -> counter == 2",
          out == "2\n", detail=repr(out))


def test_cross_closure_taskgroup_stress():
    """The bug doc's item 4 (also test_async_with_lock_guard.py::
    test_locks_mojo_shaped_10000_task_stress's exact cpp-path source):
    the nested `inc()` async closure is called from a DIFFERENT sibling
    nested function (`caller()`), which builds a `TaskGroup`, creates
    10,000 tasks across two same-named nested loops, and waits. The box
    handle for the captured `rawCounter` must be threaded THROUGH
    `caller()` (its own hidden param), forwarded to every `inc()` call
    inside it, and forwarded at the `caller()` call site -- and the
    stack-switch `TaskGroup.create_task(...)` / `.wait()` path must
    drive every task to completion. Result read after `caller()`
    returns must be exactly 10000."""
    src = """\
from std.runtime.asyncrt import TaskGroup


def test_with_lock_stress() raises:
    var lock = BlockingSpinLock()
    var rawCounter = 0
    comptime maxI = 100
    comptime maxJ = 100

    @parameter
    async def inc():
        with BlockingScopedLock(lock):
            rawCounter += 1

    def caller() raises:
        var tg = TaskGroup()
        for _ in range(0, maxI):
            for _ in range(0, maxJ):
                tg.create_task(inc())
        tg.wait()

    caller()
    print(rawCounter)


def main() raises:
    test_with_lock_stress()
"""
    out = _build_and_run(src)
    check("cross-closure TaskGroup 10,000-task stress -> 10000",
          out == "10000\n", detail=repr(out))


def test_cross_closure_single_scope_taskgroup():
    """The simpler single-scope `TaskGroup` shape (the callee and the
    group live in the SAME function): proves the stack-switch
    `TaskGroup.create_task(...)`/`.wait()` intrinsics on their own,
    independent of the further-nested sibling-function threading."""
    src = """\
from std.runtime.asyncrt import TaskGroup


def test_tg() raises:
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
    test_tg()
"""
    out = _build_and_run(src)
    check("single-scope TaskGroup 100-task -> 100", out == "100\n", detail=repr(out))


def test_nonliteral_initializer_capture():
    """Increment A: the captured outer local's initializer is a call
    (`var n = compute()`), not a bare int literal -- the box is still an
    int64_t cell; only the plan's initializer restriction is relaxed
    (kind taken from the callee's `-> Int` return annotation)."""
    src = """\
def compute() -> Int:
    return 40 + 2


def test_nonlit() raises:
    var n = compute()

    @parameter
    async def bump():
        n += 1

    var t0 = create_task(bump())
    t0.wait()
    print(n)


def main() raises:
    test_nonlit()
"""
    out = _build_and_run(src)
    check("var n = compute(); nested bump() -> 43", out == "43\n", detail=repr(out))


def test_captured_parameter():
    """Increment B: the nested async captures one of the ENCLOSING
    function's own PARAMETERS directly (no `var c = seed` indirection).
    The param is renamed and its incoming value boxed at function entry."""
    src = """\
def run(seed: Int) raises:
    @parameter
    async def bump():
        seed += 2

    var t0 = create_task(bump())
    t0.wait()
    print(seed)


def main() raises:
    run(10)
"""
    out = _build_and_run(src)
    check("captured parameter seed=10, +2 -> 12", out == "12\n", detail=repr(out))


def test_float_capture():
    """Increment C: a Float64 captured local, mutated in the nested async
    then read back -- the box cell is a `double` (`__mojo_box_new_d`/
    `_get_d`/`_set_d`) instead of int64_t."""
    src = """\
def test_f() raises:
    var acc = 0.0

    @parameter
    async def addf():
        acc += 1.5

    var t0 = create_task(addf())
    t0.wait()
    var t1 = create_task(addf())
    t1.wait()
    print(acc)


def main() raises:
    test_f()
"""
    out = _build_and_run(src)
    check("Float64 capture acc += 1.5 twice -> 3.0",
          out.strip() in ("3.0", "3.000000", "3"), detail=repr(out))


def test_string_capture():
    """Increment C: a String captured local, appended-to in the nested
    async then read back -- the box cell is a `char *` (`__mojo_box_new_p`/
    `_get_p`/`_set_p`)."""
    src = """\
def test_s() raises:
    var msg = String("a")

    @parameter
    async def app():
        msg += "b"

    var t0 = create_task(app())
    t0.wait()
    print(msg)


def main() raises:
    test_s()
"""
    out = _build_and_run(src)
    check("String capture msg += \"b\" -> ab", out == "ab\n", detail=repr(out))


def test_struct_capture_compiles_boxed_and_correct():
    """A struct-typed captured local IS now representable by v0's box (a
    heap cell holding the struct pointer, boxed/unboxed exactly like the
    scalar cases above) -- this used to be refused to the cpp path (pre-
    Increment-E), but that refusal is gone: the program compiles, the box
    shim is present, and running it gives the CPython-correct answer."""
    src = """\
struct P:
    var x: Int
    fn __init__(out self, x: Int):
        self.x = x


def test_p() raises:
    var p = P(1)

    @parameter
    async def bump():
        p.x += 1

    var t0 = create_task(bump())
    t0.wait()
    print(p.x)


def main() raises:
    test_p()
"""
    out = _build_and_run(src)
    check("struct capture p.x += 1 -> 2", out.strip() == "2", detail=out)


def _cpython_stdout(py_src: str) -> str:
    """The oracle for the case below, measured at test time rather than
    transcribed: this file's harness has always asserted a hand-written
    expected string, which is precisely how bugs/hard/
    CODEGEN_bytes_silent_wrong_values.md's anti-tests came to encode the
    CPython-WRONG answer. The `async for` shape's failure mode is a
    SILENT wrong value, so the expected answer is the one CPython actually
    produces for the reference twin, not one written down here."""
    wd = tempfile.mkdtemp(prefix='mojo_coro_capture_cpy_')
    p = os.path.join(wd, 'ref.py')
    with open(p, 'w') as f:
        f.write(py_src)
    r = subprocess.run(['python3', p], capture_output=True, text=True, timeout=30)
    if r.returncode != 0:
        raise RuntimeError(f"the CPython reference program itself failed: {r.stderr}")
    return r.stdout


def test_nested_async_generator_driven_by_async_for():
    """A nested async GENERATOR that mutates a captured enclosing local,
    consumed by `async for` in that local's OWN enclosing (ordinary,
    never-suspended) function.

    This is the shape the doc proved was neither refused nor correct: it
    built, linked, ran, exited 0, and printed `0` where CPython prints
    `11`. The `mojo_unsupported_iter` warning it did emit names a
    `MojoGenerator *`, so it looked handled from the outside.

    Not a capture bug: the identical wrong `0` appeared with no capture at
    all, and the cause is that a nested `async def gen()`'s call site is
    rewritten by coro.py to its QUALIFIED `__mgco_outer_gen_start`, which
    the bare-name `_generator_api` lookup the ordinary `for`-loop lowering
    uses cannot see -- so the loop found no generator api and dropped its
    body. The capture box IS threaded (this file's `_build_and_run`
    requires `__mojo_box_new_*` in the C, and asserts it), which is exactly
    why the failure looked like a capture problem.

    The wait-descriptor half of the same boundary -- an async generator
    that can PARK under `async for` driven by a function with no yield
    channel -- is covered in test_gimple_generator_runner.py, which has
    this harness's compile-only sibling; see `async_for_over_parking_
    async_gen_refused` there."""
    src = """\
def outer() raises:
    var acc = 0

    async def gen():
        acc = acc + 1
        yield 10

    async for x in gen():
        acc = acc + x
    print(acc)


def main() raises:
    outer()
"""
    out = _build_and_run(src)
    want = _cpython_stdout("""\
import asyncio


async def outer():
    acc = 0

    async def gen():
        nonlocal acc
        acc = acc + 1
        yield 10

    async for x in gen():
        acc = acc + x
    print(acc)


asyncio.run(outer())
""")
    check("nested async gen consumed by `async for` in its own enclosing "
          f"function -> {want.strip()!r}", out == want, detail=f"got {out!r}, "
          f"CPython {want!r}")


def _synthetic_module(src: str):
    """Parse `src` with the compiler's own parser -- the statement list
    `coro.lower()` is handed, and the only thing `_compute_no_wd_forward`
    takes."""
    return (fire_compiler.Parser(fire_compiler.py_tokenize(src))
            .with_filename('synthetic.py').parse_module())


def _no_wd_forward(src: str) -> tuple:
    """Run the wait-descriptor fixed point over `src`; return
    (`_NO_WD_FORWARD`, the number of `_walk` calls it made).

    The walk count is the budget this test exists to hold: the analysis may
    walk each function's body exactly ONCE, and nothing more. The runtime
    has no garbage collector, so a walk per ROUND of a fixed point is
    memory no later round can give back -- see
    `test_no_wd_forward_walks_each_body_once`."""
    stmts = _synthetic_module(src)
    calls = [0]
    real_walk = coro._walk

    def counting(node):
        calls[0] += 1
        return real_walk(node)

    coro._walk = counting
    try:
        coro._compute_no_wd_forward(stmts)
    finally:
        coro._walk = real_walk
    return coro._NO_WD_FORWARD, calls[0]


def test_no_wd_forward_walks_each_body_once():
    """The regression test for the self-host blowup: a chain of async
    functions `f0 -> f1 -> ... -> f(n-1)`, whose tail parks.

    Re-deriving the whole answer per round -- the shape this replaced -- takes
    one round per function here (each round proves exactly one more link of
    the chain dirty) and walks EVERY body on each round, so n*(n+1) walks.
    The worklist walks each body once and never revisits it: n. With n = 150
    that is 22,650 walks against a budget of 300, and the difference is not
    academic: this is the analysis the self-hosted compiler runs on every
    module it compiles, with no garbage collector to reclaim the lists."""
    n = 150
    lines = ['import asyncio', '']
    for i in range(n - 1):
        lines.append('async def f%d():' % i)
        lines.append('    await f%d()' % (i + 1))
        lines.append('')
    lines.append('async def f%d():' % (n - 1))
    lines.append('    await asyncio.sleep(0)')
    clean, walks = _no_wd_forward('\n'.join(lines))
    check('a %d-deep await chain costs at most 2 AST walks per function '
          '(took %d, budget %d)' % (n, walks, 2 * n), walks <= 2 * n)
    check('a chain whose tail parks leaves nothing clean',
          clean == set(), detail='clean=%r' % (sorted(clean),))


def test_no_wd_forward_graph_shapes():
    """The fixed point's ANSWER on every shape that has ever distinguished a
    correct implementation from a wrong one: a body that parks, propagation
    through both arms of a diamond, an awaited name that is not in the module
    at all, an awaited bare name that is ALSO a struct method's (ambiguous,
    so unresolvable), and a cycle of awaits with no parking await anywhere
    in it -- which is CLEAN here, because the fixed point is a greatest one
    and each side of the cycle can only conclude "clean" about the other."""
    src = '''\
import asyncio


async def clean_leaf():
    pass


async def parks():
    await asyncio.sleep(0)


async def calls_parks():
    await parks()


async def also_calls_parks():
    await parks()


async def diamond():
    await calls_parks()
    await also_calls_parks()


async def unresolvable():
    await nowhere()


async def over_ambiguous():
    await meth()


async def live_cycle_a():
    await live_cycle_b()


async def live_cycle_b():
    await live_cycle_a()


struct S:
    var x: Int

    async def meth(self):
        pass
'''
    clean, _walks = _no_wd_forward(src)
    want = {'clean_leaf', 'live_cycle_a', 'live_cycle_b', 'S_meth'}
    check('parks / diamond / unresolvable / ambiguous propagate, a '
          'seedless cycle stays clean -> %r' % (sorted(want),),
          clean == want, detail='got %r' % (sorted(clean),))


# The fixed point's SHAPE, as a compiled program: the same statement sequence
# `coro._compute_no_wd_forward` runs, over a call graph handed in as data.
# In-process Python tests cannot see any of what this one checks -- that the
# dict-of-lists `preds`, the name-keyed membership tables and the
# `while len(queue) > 0` worklist loop mean the same thing once COMPILED.
#
# Two properties of this program are deliberate, both consequences of how this
# codegen erases a generic container's element type, and neither is what this
# case is testing:
#   * it is ONE function, because a container handed across a call boundary
#     reaches codegen as a boxed `int64_t`, and `x in <boxed dict>` then goes
#     through the `mojo_in_dispatch_*` runtime dispatcher rather than the
#     typed `mojo_dict_contains` — a registry probe per membership test.
#     (That dispatcher used to have no dict branch at all on the int view,
#     which was a silent "not present"; see test_container_membership.py.)
#     coro.py's fixed point keeps every one of its tables local for the same
#     reason.
#   * it prints each clean function's INDEX in `names`, so the comparison
#     needs no string value back out of a `list[str]`.
_FIXED_POINT_PROGRAM = '''\
def main() raises:
    var names = ["f0", "f1", "f2", "p", "a", "b", "d", "c", "h", "u"]
    var edges = {}
    edges["f0"] = ["f1"]
    edges["f1"] = ["f2"]
    edges["f2"] = []
    edges["p"] = ["zz"]
    edges["a"] = ["p"]
    edges["b"] = ["p"]
    edges["d"] = ["a", "b"]
    edges["c"] = []
    edges["h"] = ["c"]
    edges["u"] = ["nope"]
    var amb = ["m"]
    var fns = {}
    var ambiguous = {}
    var preds = {}
    var seeds = []
    for name in names:
        fns[name] = len(fns)
    for a in amb:
        ambiguous[a] = 1
    for name in fns:
        var targets = edges[name]
        var other = False
        for t in targets:
            if t not in fns or t in ambiguous:
                other = True
        if other:
            seeds.append(name)
        else:
            for t in targets:
                if t in preds:
                    preds[t].append(name)
                else:
                    preds[t] = [name]
    var dirty = {}
    var queue = seeds
    for name in seeds:
        dirty[name] = 1
    while len(queue) > 0:
        var name = queue.pop()
        if name in preds:
            var callers = preds[name]
            for caller in callers:
                if caller not in dirty:
                    dirty[caller] = 1
                    queue.append(caller)
    for name in fns:
        if name not in dirty:
            print(fns[name])
'''

# The same algorithm as CPython runs it -- the oracle, measured at test time
# for the reason `_cpython_stdout`'s own docstring gives.
_FIXED_POINT_TWIN = '''\
def main():
    names = ["f0", "f1", "f2", "p", "a", "b", "d", "c", "h", "u"]
    edges = {"f0": ["f1"], "f1": ["f2"], "f2": [], "p": ["zz"],
             "a": ["p"], "b": ["p"], "d": ["a", "b"], "c": [], "h": ["c"],
             "u": ["nope"]}
    amb = ["m"]
    fns = {}
    ambiguous = {}
    preds = {}
    seeds = []
    for name in names:
        fns[name] = len(fns)
    for a in amb:
        ambiguous[a] = 1
    for name in fns:
        targets = edges[name]
        other = False
        for t in targets:
            if t not in fns or t in ambiguous:
                other = True
        if other:
            seeds.append(name)
        else:
            for t in targets:
                if t in preds:
                    preds[t].append(name)
                else:
                    preds[t] = [name]
    dirty = {}
    queue = seeds
    for name in seeds:
        dirty[name] = 1
    while len(queue) > 0:
        name = queue.pop()
        if name in preds:
            for caller in preds[name]:
                if caller not in dirty:
                    dirty[caller] = 1
                    queue.append(caller)
    for name in fns:
        if name not in dirty:
            print(fns[name])


main()
'''


def test_no_wd_forward_shape_when_compiled():
    """The worklist, compiled and run, agrees with CPython.

    This is the half of the fix that `test_no_wd_forward_walks_each_body_once`
    cannot reach. It failed before: the fixed point it replaced terminated on
    `if nxt == proven: break`, and `==` between two containers lowers to a
    POINTER comparison (runtime/fire_runtime.c and the generated C agree), so
    self-hosted the loop never exited -- a two-line program sat in it past
    8 GB. Nothing here can hang on that any more: the loop ends when the
    worklist drains, and the harness's own 30s timeout would fail this case
    if it ever did."""
    out = _build_and_run(_FIXED_POINT_PROGRAM, require=())
    want = _cpython_stdout(_FIXED_POINT_TWIN)
    check('the fixed point compiled to native code agrees with CPython '
          f'-> {want.split()!r}', out == want,
          detail=f'got {out!r}, CPython {want!r}')


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
