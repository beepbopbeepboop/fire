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
# Derived from test_ab_shim.BUILTIN_TESTS (same program names/shapes) but
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
}


def report(status: str, name: str, detail: str) -> None:
    """Print one program's result line, mirroring test_ab_shim's style."""
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
