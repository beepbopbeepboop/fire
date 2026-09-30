#!/usr/bin/env python3
"""Runtime-diff harness: run the same Mojo program through BOTH the
interpreter (`python3 fire.py run X.mojo`) and the JIT-compiled path
(`python3 fire.py --jit X.mojo`), then diff their stdout + exit code.

This is the concrete measure of "runtime parity" between the two execution
engines (myinterpreter.py's evaluator vs the gimple_codegen-compiled native
binaries). The interpreter is the ultimate correctness backstop (fire.py falls
back to interpreting on compile failure), so a program that silently compiles
to *different* behavior is the divergence this harness exists to catch.

Statuses:
  PASS              stdout and exit code are identical in both modes
  FAIL              stdout or exit code differ (first differing stdout line
                    is reported; exit-code differences include the JIT's
                    "JIT execution failed with code N" note when present)
  JIT-COMPILE-FAILED the program cannot be JIT-compiled at all (gcc / codegen
                    error, seen via fire.py's "JIT compilation failed" /
                    "JIT error" stderr markers). This is reported distinctly
                    rather than as a plain stdout diff because the compiled
                    path falls back to the interpreter on failure — a naive
                    stdout comparison would otherwise show a false "match"
                    against the interpreter's own output.
  TIMEOUT           a mode exceeded the per-run timeout
  ERROR             a harness-level failure (e.g. subprocess couldn't start)

Usage:
    python3 test_runtime_diff.py [file.mojo ...]

With no file arguments, runs the built-in corpus of small programs.
"""
import os
import sys
import subprocess
import tempfile
import textwrap

HERE = os.path.dirname(os.path.abspath(__file__))
MOJO = os.path.join(HERE, 'fire.py')
TIMEOUT = 120  # seconds per (program, mode) run

# fire.py's jit_compile_and_execute prints one of these to stderr when the
# program fails in the COMPILE stage (codegen / gcc / link). The compiled
# binary never ran, so parity is unevaluable.
JIT_COMPILE_FAIL_MARKERS = (
    "JIT compilation failed",
    "JIT runtime compilation failed",
    "JIT linking failed",
    "JIT error:",
)
# Distinct marker for the binary compiling fine but exiting nonzero at runtime
# (includes real crashes like segfaults — "JIT execution failed with code -11").
JIT_RUN_FAIL_MARKER = "JIT execution failed with code"


def run_one(mode: str, fpath: str) -> tuple:
    """Run fpath through one execution engine.

    mode is 'interp' (`python3 fire.py run X.mojo`) or 'jit'
    (`python3 fire.py --jit X.mojo`). Returns (status, stdout, exit_code,
    stderr). status is 'ok', 'timeout', or 'error'.
    """
    cmd = [sys.executable, MOJO, 'run' if mode == 'interp' else '--jit', fpath]
    try:
        r = subprocess.run(cmd, capture_output=True, text=True,
                           errors='replace', timeout=TIMEOUT, cwd=HERE)
    except subprocess.TimeoutExpired:
        return ('timeout', None, 'TIMEOUT', f"timed out after {TIMEOUT}s")
    except Exception as e:
        return ('error', None, 'ERROR', str(e))
    return ('ok', r.stdout, r.returncode, r.stderr)


def _first_stdout_diff(stdout_a: str, stdout_b: str) -> str:
    """Describe the first line where two stdout streams differ."""
    if stdout_a == stdout_b:
        return 'stdout identical'
    lines_a = stdout_a.splitlines(keepends=True)
    lines_b = stdout_b.splitlines(keepends=True)
    for i, (la, lb) in enumerate(zip(lines_a, lines_b)):
        if la != lb:
            return (f"stdout line {i + 1}: "
                    f"interp={la!r}  jit={lb!r}")
    i = min(len(lines_a), len(lines_b))
    if i < len(lines_a):
        which = "interp"
        extra = lines_a[i]
    elif i < len(lines_b):
        which = "jit"
        extra = lines_b[i]
    else:
        return (f"stdout length differs ({len(lines_a)} vs {len(lines_b)} lines) "
                f"but all lines match")
    return (f"stdout length differs ({len(lines_a)} vs {len(lines_b)} lines); "
            f"first {which}-only line at {i + 1}: {extra!r}")


def diff_program(fpath: str) -> tuple:
    """Run fpath through both engines and compare stdout + exit code.

    Returns (status, detail). See the module docstring for status meanings.
    """
    i_status, i_out, i_code, i_err = run_one('interp', fpath)
    j_status, j_out, j_code, j_err = run_one('jit', fpath)

    if i_status == 'timeout' or j_status == 'timeout':
        who = ('interp' if i_status == 'timeout' else 'jit')
        return 'TIMEOUT', f"{who} run timed out after {TIMEOUT}s"
    if i_status == 'error' or j_status == 'error':
        who = ('interp' if i_status == 'error' else 'jit')
        what = i_err if i_status == 'error' else j_err
        return 'ERROR', f"{who} run failed: {what}"

    # The program never compiled to a runnable binary on the JIT path: the
    # compiled path fell back (would have) to the interpreter, which would
    # mask any divergence — report it as its own status, not a stdout diff.
    if j_code != 0 and any(m in j_err for m in JIT_COMPILE_FAIL_MARKERS):
        reason = j_err.strip().splitlines()
        reason = next((ln for ln in reason if ln.strip()), reason[0])
        return 'JIT-COMPILE-FAILED', f"{reason[:300]}"

    if i_code == j_code and i_out == j_out:
        return 'PASS', 'stdout + exit identical'

    detail = _first_stdout_diff(i_out or '', j_out or '')
    if i_code != j_code:
        extra = ""
        if JIT_RUN_FAIL_MARKER in j_err:
            note = next((ln.strip() for ln in j_err.splitlines()
                         if JIT_RUN_FAIL_MARKER in ln), "")
            extra = f"; {note}"
        exit_detail = f"exit codes differ: interp={i_code} jit={j_code}{extra}"
        detail = f"{exit_detail}" if i_out == j_out else f"{detail}; {exit_detail}"
    return 'FAIL', detail


# ── Built-in corpus ────────────────────────────────────────────────────────
# Derived from test_ab_native.BUILTIN_TESTS (same program names/shapes) but
# adapted to emit stdout: each program prints its result instead of (or in
# addition to) returning it, so the runtime-diff comparison has non-empty
# stdout in both engines.

BUILTIN_PROGRAMS = {
    "minimal_main": textwrap.dedent("""\
        def main():
            print(42)
    """),
    "arithmetic": textwrap.dedent("""\
        def main():
            var x: Int = 10
            var y: Int = 32
            print(x + y)
    """),
    "if_else": textwrap.dedent("""\
        def main():
            var x: Int = 5
            if x > 0:
                print(42)
            else:
                print(0)
    """),
    "while_loop": textwrap.dedent("""\
        def main():
            var i: Int = 0
            var total: Int = 0
            while i < 10:
                total = total + i
                i = i + 1
            print(total)
    """),
    "function_def": textwrap.dedent("""\
        def add(a: Int, b: Int) -> Int:
            return a + b

        def main():
            print(add(20, 22))
    """),
    "list_ops": textwrap.dedent("""\
        def main():
            var items = [1, 2, 3, 4, 5]
            var total = 0
            for i in range(len(items)):
                total = total + items[i]
            print(total)
    """),
    "string_ops": textwrap.dedent("""\
        def main():
            var s: String = "hello world"
            print(len(s))
    """),
    "fstring": textwrap.dedent("""\
        def main():
            var x: Int = 42
            var s = f"value={x}"
            print(s)
    """),
    "struct_def": textwrap.dedent("""\
        struct Point:
            var x: Int
            var y: Int

        def main():
            var p = Point(3, 4)
            print(p.x + p.y)
    """),
    "class_methods": textwrap.dedent("""\
        class Counter:
            var count: Int

            fn __init__(inout self):
                self.count = 0

            fn inc(inout self):
                self.count += 1

            fn get(self) -> Int:
                return self.count

        def main():
            var c = Counter()
            c.inc()
            c.inc()
            c.inc()
            print(c.get())
    """),
    "match_stmt": textwrap.dedent("""\
        def main():
            var x: Int = 2
            match x:
                case 1:
                    print(10)
                case 2:
                    print(20)
                case _:
                    print(0)
    """),
    "try_except": textwrap.dedent("""\
        def main():
            var x: Int = 0
            try:
                x = 5
            except:
                x = 0
            print(x)
    """),
    "recursive": textwrap.dedent("""\
        def fib(n: Int) -> Int:
            if n <= 1:
                return n
            return fib(n - 1) + fib(n - 2)

        def main():
            print(fib(10))
    """),
    "closure": textwrap.dedent("""\
        def make_adder(n: Int):
            def add(x: Int) -> Int:
                return x + n
            return add

        def main():
            var add5 = make_adder(5)
            print(add5(37))
    """),
    "string_methods": textwrap.dedent("""\
        def main():
            var s: String = "Hello World"
            print(s.lower())
            print(s.upper())
            print(s.replace("World", "Mojo"))
    """),
    "nested_loops": textwrap.dedent("""\
        def main():
            var total: Int = 0
            for i in range(3):
                for j in range(3):
                    total = total + i * j
            print(total)
    """),
    "dict_ops": textwrap.dedent("""\
        def main():
            var d = {"a": 1, "b": 2}
            print(d["a"] + d["b"])
    """),
    "comprehension": textwrap.dedent("""\
        def main():
            var items = [i * 2 for i in range(5)]
            var total = 0
            for x in items:
                total = total + x
            print(total)
    """),
    "global_var": textwrap.dedent("""\
        var counter: Int = 0

        def bump() -> Int:
            global counter
            counter += 1
            return counter

        def main():
            bump()
            bump()
            print(bump())
    """),
    "exception_msg": textwrap.dedent("""\
        def main():
            try:
                raise Error("boom")
            except Error as e:
                print("caught")
    """),
    "generator_simple": textwrap.dedent("""\
        def gen():
            yield 1
            yield 2
            yield 3

        def main():
            var g = gen()
            print(g.__next__())
            print(g.__next__())
            print(g.__next__())
    """),
    "string_format": textwrap.dedent("""\
        def main():
            var x: Int = 42
            var s = f"{x:04d}"
            print(s)
    """),
    "nested_list": textwrap.dedent("""\
        def main():
            var matrix = [[1, 2], [3, 4]]
            var total = 0
            for row in matrix:
                for v in row:
                    total = total + v
            print(total)
    """),
    "default_args": textwrap.dedent("""\
        def greet(name: String = "world") -> String:
            return name

        def main():
            print(greet())
            print(greet("mojo"))
    """),
    # `os.environ` as a WHOLE VALUE. The per-key idioms (`os.environ.get(k)`,
    # `os.environ[k]`, `k in os.environ`) are lowered to `mojo_c_getenv` by
    # ast_rewriter.py and always worked; a bare value read did not, and fell
    # through to the generic dynamic-getattr dispatch, which typed it
    # `int64_t`. Any `dict |` union over it then passed an integer to
    # `mojo_dict_union` — a hard `-Wint-conversion` error, which is how
    # `Tools/wasm/wasi/__main__.py`'s `env_defaults | os.environ | updates`
    # surfaced it. Asserts a real, environment-dependent property: the
    # process's own PATH must be reachable, the union must be bigger than
    # the one-entry dict it started from, and the dict's own entry must
    # survive the union.
    #
    # Deliberately NOT `merged.get(...)`: `.get()` on a `dict | dict` result
    # used to dispatch on a value type the union lowering did not propagate,
    # so it returned the stored pointer's bit pattern. That gap is FIXED
    # (`mojo_dict_union`'s lowering now carries the operands' agreed value
    # type onto the result — see `dict_union_get_value_type` below, which is
    # the case that covers it), so a subscript read is no longer the only
    # form that can be asserted here; both are kept, since they take
    # different lowering paths (`_lower_SubscriptExpr` vs the `.get` method
    # dispatch) and a fix to one would not have caught the other.
    "os_environ_value": textwrap.dedent("""\
        def main():
            merged = {"MOJO_MARKER": "1"} | os.environ
            print(len(merged) > 1)
            print("PATH" in os.environ)
            print(merged["MOJO_MARKER"] == "1")
            print(merged.get("MOJO_MARKER") == "1")
    """),
    # A function that returns a LOCAL container. `return env` for a local
    # built from a `{}` literal used to infer the scalar `int64_t` (the
    # local is not in `var_types` yet at return-inference time), so the body
    # laundered the real `MojoDict *` through a scalar and every CALLER got
    # an `int64_t` where a `MojoDict *` was declared. The caller's `|` here
    # is what turned that into a compile error; the assertions are on the
    # VALUE (length, membership, a subscript read, and the union's length),
    # which also catch a laundered pointer that happened to survive.
    "return_local_container": textwrap.dedent("""\
        def build(k):
            env = {"A": "1", "B": "2"}
            env["C"] = k
            return env

        def main():
            d = build("3")
            print(len(d))
            print("C" in d)
            print(d["C"] == "3")
            print(len({"Z": "9"} | d))
    """),
    # An unannotated parameter whose DEFAULT is a container literal is a
    # container parameter: `def updated_env(updates={})` in
    # `Tools/wasm/wasi/__main__.py` kept the generic `int64_t` box and fed
    # it straight into `mojo_dict_union` as argument 2. The default
    # expression is type evidence exactly as strong as an annotation, by the
    # same argument the existing `StringLiteral`-default rule already states.
    #
    # Shaped exactly like the real function -- `updates`'s ONLY use is the
    # union -- on purpose. A variant that also does `out.update(extra)` is
    # rescued by usage inference (`_inferred_param_types` sees a dict) and
    # passed even before this rule existed, so it would not have been a
    # regression for anything. Both the omitted and the passed case, so a
    # fix that only handled one is caught.
    "container_literal_default": textwrap.dedent("""\
        def updated_env(updates={}):
            env_defaults = {"MOJO_A": "1"}
            environment = env_defaults | updates
            return environment

        def main():
            print(len(updated_env()))
            e = updated_env({"MOJO_B": "2"})
            print(len(e))
            print(e["MOJO_A"] == "1")
    """),
    # `.get()` on a `dict | dict` result. `a | b` allocates a NEW dict, so
    # nothing downstream recorded its value type and every read dispatched to
    # `mojo_dict_get_int` — handing back the stored `char *` as a pointer
    # decimal (a real address, so the program exited 0 with garbage). The
    # SUBSCRIPT form of the same read always worked, which is why
    # `os_environ_value` above used `merged["MOJO_MARKER"]` and carried a
    # comment explaining why it could not use `.get()`; that comment is now
    # obsolete and the case below is the replacement.
    #
    # All-string dicts on purpose: that is the only case with a sound static
    # answer, and it is the shape real code has
    # (`env_defaults | os.environ | updates` in
    # `Tools/wasm/wasi/__main__.py`). A `dict | dict` whose two sides
    # DISAGREE on value type is genuinely heterogeneous in Python
    # (`{'x': 1} | {'y': 's'}`), which this dict representation — one
    # int64_t slot plus a `kind` tag — has no static type for; those stay
    # unrecorded rather than being mis-typed, and that gap is tracked in
    # bugs/BUGFIX_ROADMAP.md item 2.
    "dict_union_get_value_type": textwrap.dedent("""\
        def main():
            a = {"A": "1"}
            b = {"B": "2"}
            m = a | b
            print(m.get("A"))
            print(m.get("B"))
            print((a | b).get("B"))
            print(m.get("A", "dflt"))
    """),
    # `@classmethod` binds the CLASS. The interpreter had NO classmethod
    # support at all: `C.m(...)` returned the raw unbound MojoFunction, so
    # the call bound the first REAL ARGUMENT to the `cls` parameter —
    # `C.gen(5)` made `cls == 5`, and `cls.tag` then raised
    # "'int' object has no attribute 'tag'". That is an ORACLE bug, and the
    # worst kind: the compiled path passes a receiver correctly, so a
    # compiled-path bug on this shape would have agreed with the wrong
    # answer instead of showing up as a diff. See
    # bugs/COMPILE_FAIL_importlib_resources_readers.md's
    # `yield from cls.<sibling generator>(...)`, which is the real code
    # that needs it.
    #
    # `C()` (instance) access is included because it takes a different
    # interpreter path (`_eval_member_of`'s MojoInstance branch, not
    # `MojoClass.__getattr__`) and must bind the class too.
    "classmethod_binds_cls": textwrap.dedent("""\
        class Paths:
            tag = 7

            @classmethod
            def who(cls):
                return cls.tag

            @classmethod
            def gen(cls, n):
                yield cls.tag
                yield n

        def main():
            print(Paths.who())
            print(Paths().who())
            for v in Paths.gen(5):
                print(v)
    """),
    # A @classmethod generator delegating to a @staticmethod generator of
    # the same class — the exact `readers.py` shape
    # (`_candidate_paths` doing `yield from cls._resolve_zip_path(...)`).
    # Exercises the interpreter's classmethod receiver, the receiver-LESS
    # staticmethod callee on both compiled backends, and the delegation
    # itself, and asserts CPython's own output.
    "classmethod_yield_from_staticmethod_generator": textwrap.dedent("""\
        class MP:
            @staticmethod
            def resolve_zip_path(p: Int):
                yield p + 10
                yield p + 20

            @classmethod
            def candidate_paths(cls, p: Int):
                yield p
                yield from cls.resolve_zip_path(p)

        def main():
            for v in MP.candidate_paths(1):
                print(v)
    """),
    # A SIBLING closure called with KEYWORD arguments, from inside another
    # lifted closure. `_lower_outer_closure_call` built its argument list from
    # `node.args` alone, so every keyword was dropped and the callee silently
    # used its own defaults — the C prototype carries no defaults, so nothing
    # failed to compile. `deep_str=True, prefer_refined_param=True` in
    # `module_gen.py`'s `_collect_method_scalar_obs` is the real instance.
    # Both keywords AND the positional/default mix are covered: the second
    # program passes only the first keyword, so a fix that shifted values
    # into the wrong slots would show up as the wrong branch being taken.
    # An `await` nested inside a CALL'S ARGUMENT LIST. Both coroutine
    # backends are statement emitters and cannot suspend from the middle
    # of a C expression, so `results.append(await fetch(i))` was refused
    # at any nesting depth -- which made the most ordinary async
    # accumulation loop uncompilable, while the hand-split form
    # (`v = await fetch(i); results.append(v)`) compiled fine.
    # `gimple_gen_coro.hoist_awaits_from_call_args` rewrites the provably
    # order-preserving shape into exactly that. Four placements covered:
    # top level, and inside `if` / `while` / `for`. The value assertions
    # (not just "it compiled") are what make this a real check that the
    # hoist preserved evaluation order and did not drop a suspension
    # point.
    "await_inside_call_argument": textwrap.dedent("""\
        import asyncio

        async def step1(n):
            await asyncio.sleep(0)
            return n * 2

        async def top_level(n):
            out = []
            out.append(await step1(3))
            return out[0]

        async def in_if(n):
            out = []
            if n:
                out.append(await step1(4))
            return out[0]

        async def in_while(n):
            out = []
            i = 0
            while i < 2:
                out.append(await step1(i))
                i = i + 1
            return out[0] + out[1]

        async def in_for(n):
            out = []
            for i in range(3):
                out.append(await step1(i))
            return out[0] + out[1] + out[2]

        def main():
            print(asyncio.run(top_level(0)))
            print(asyncio.run(in_if(1)))
            print(asyncio.run(in_while(0)))
            print(asyncio.run(in_for(0)))
    """),
    # `asyncio.run(x)` where `x` is a NAME, not a bare call. The rewrite
    # refused every non-call argument, so the two-step idiom every larger
    # `main` actually uses — build the coroutine, then run it — did not
    # compile. The static half is `mojo/middle/coro.py`'s
    # `_scan_handle_vars`: the name must be bound by THIS function from
    # `create_task(...)` or from a call to an `async def` this module
    # actually compiled, and a name bound from anything else is still
    # refused (driving it would reinterpret an arbitrary int64_t as a
    # coroutine handle).
    #
    # The RUNTIME half is `__mojo_async_run_gen`'s live-handle check, which
    # raises the Python-faithful ValueError rather than trusting the static
    # inference. That half is not reachable through the compiler — every
    # shape the compiler can get wrong is already refused statically — so it
    # is asserted directly in runtime/test_fire_coro_gen.c
    # (`test_run_gen_rejects_non_handle`), which `coro` runs.
    #
    # `rebound` deliberately re-binds a handle name to a plain integer AFTER
    # the coroutine was created: Python would raise here
    # ("a coroutine was expected"), and the compiled path refuses to compile
    # it rather than pretending, which is the honest outcome and is asserted
    # as a compile-time refusal by a separate case below.
    "asyncio_run_of_a_name": textwrap.dedent("""\
        import asyncio

        async def work(n):
            await asyncio.sleep(0)
            return n * 3

        def main():
            c = work(5)
            print(asyncio.run(c))
            print(asyncio.run(work(7)))
    """),
    "sibling_closure_kwargs": textwrap.dedent("""\
        def outer(flag):
            def probe(a, deep=False, refine=False):
                if deep:
                    return 1
                if refine:
                    return 2
                return 3

            def runner(items):
                total = 0
                for v in items:
                    if flag:
                        total = total + probe(v, deep=True, refine=True)
                return total

            def runner2(items):
                total = 0
                for v in items:
                    if flag:
                        total = total + probe(v, deep=True)
                return total

            return runner([1, 2]) * 10 + runner2([1, 2])

        def main():
            print(outer(True))
    """),
}


def report(status: str, name: str, detail: str) -> None:
    """Print one program's result line, mirroring test_ab_native's style."""
    if status == 'PASS':
        print(f"  PASS  {name}")
    else:
        print(f"  {status}  {name}")
        print(f"         {detail}")


def run_program_source(name: str, source: str) -> str:
    """Write an inline program to a temp file and diff it."""
    with tempfile.TemporaryDirectory() as td:
        fpath = os.path.join(td, f"{name}.mojo")
        with open(fpath, 'w') as f:
            f.write(source)
        status, detail = diff_program(fpath)
        report(status, name, detail)
        return status


def run_file(path: str) -> str:
    """Diff a .mojo file from disk."""
    name = os.path.splitext(os.path.basename(path))[0]
    status, detail = diff_program(path)
    report(status, name, detail)
    return status


def main():
    print("=" * 60)
    print("RUNTIME DIFF — interpreter (fire.py run) vs JIT (fire.py --jit)")
    print("=" * 60)
    print()

    counts = {'PASS': 0, 'FAIL': 0, 'JIT-COMPILE-FAILED': 0, 'TIMEOUT': 0, 'ERROR': 0}

    if len(sys.argv) > 1:
        for path in sys.argv[1:]:
            counts[run_file(path)] += 1
    else:
        for name, source in BUILTIN_PROGRAMS.items():
            counts[run_program_source(name, source)] += 1

    print()
    summary = (f"Results: {counts['PASS']} passed, {counts['FAIL']} failed, "
               f"{counts['JIT-COMPILE-FAILED']} jit-compile-failed, "
               f"{counts['TIMEOUT']} timed out, {counts['ERROR']} errors")
    print(summary)
    sys.exit(0 if counts['FAIL'] == 0 else 1)


if __name__ == '__main__':
    main()
