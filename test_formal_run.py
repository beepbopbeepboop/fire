#!/usr/bin/env python3
"""Build formal-backend executables and RUN them, checking the answers.

test_formal.py only ever typechecks the generated proof; it never executes the
binary, which is why an entire class of Mach-O emission bugs could sit there
green: images dyld refused to load (SIGKILL at exec), an LC_CODE_SIGNATURE that
landed on the first instructions, a GOT slot nothing ever bound so the call stub
branched through zero. Every one of those produced a *correct proof* about code
that could not run.

This suite executes instead. Each case names the exit status (and stdout) the
program must produce, so "it linked" and "it computed the right answer" are
separate assertions. Grounded in what clang/ld emits: a working image and a
broken one differ in load-command details, and this is the test that notices.

    python3 test_formal_run.py [-v] [case ...]
"""
import argparse
import os
import platform
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
FIRE = os.path.join(HERE, "fire.py")
BUILD_TIMEOUT = 120
RUN_TIMEOUT = 60

# (name, source, expected exit status, expected stdout substring)
#
# The first two are the "does anything run at all" cases: before the Mach-O
# layout fixes in formal/macho_linker.py, every executable this suite builds was
# killed by the kernel at exec with no output at all. `printf` is the case that
# covers the whole extern path — stubs, __DATA_CONST,__got, and the classic dyld
# bind opcodes that fill the GOT slot the stub branches through.
CASES = [
    ("ret42", "def ret42():\n    return 42\n", 42, None),
    ("seven", "def seven():\n    return 7\n", 7, None),
    ("absval", "def absval(n):\n    if n > 0:\n        return n\n"
               "    else:\n        return 0 - n\n", 10, None),
    ("fib", "def fib(n):\n    if n <= 1:\n        return n\n"
            "    else:\n        return fib(n - 1) + fib(n - 2)\n", 55, None),
    ("hello", 'def hello(n):\n    printf("hello from mojo")\n    return 0\n',
     0, "hello from mojo"),
    ("two_calls", 'def two(n):\n    printf("one")\n    printf("two")\n'
                 '    return 5\n', 5, "onetwo"),
    # `comptime f(...)` is resolved by COMPILING f with this same backend and
    # calling it at compile time (formal/comptime_runner.py), so a folded
    # constant and the code emitted for the same expression cannot come from
    # two different implementations. The callee here has a loop and a nested
    # call, and the second binding is fed by the first, so this covers the
    # whole path: run the callee, fold its result, fold arithmetic over that
    # result, and emit the branch the folded condition selects.
    # The entry function is the FIRST one in the file, so it comes first here
    # and the comptime callees it folds follow.
    ("comptime_call", "def comptime_call(n):\n"
                      "    comptime var a = square(6)\n"
                      "    comptime var b = add(a, 1)\n"
                      "    comptime var c = fact(5)\n"
                      "    comptime var flag = a > 30\n"
                      "    if flag:\n        return b + c\n"
                      "    return 0\n"
                      "def square(x):\n    return x * x\n"
                      "def add(a, b):\n    return a + b\n"
                      "def fact(n):\n    var acc = 1\n    var i = 1\n"
                      "    while i <= n:\n        acc = acc * i\n"
                      "        i = i + 1\n    return acc\n", 157, None),
]


def run_case(name, source, want_exit, want_stdout, tmpdir, verbose):
    src = os.path.join(tmpdir, name + ".mojo")
    with open(src, "w") as f:
        f.write(source)
    out = os.path.join(tmpdir, name)
    build = subprocess.run(
        [sys.executable, FIRE, "build", "--formal", "--no-prove", "-o", out, src],
        capture_output=True, text=True, timeout=BUILD_TIMEOUT, cwd=HERE)
    if build.returncode != 0:
        return False, (build.stderr or build.stdout or "build failed").strip()[-300:]
    if not os.path.isfile(out):
        return False, "build reported success but wrote no binary"

    # The formal entry function's return value becomes the process exit status.
    run = subprocess.run([out], capture_output=True, text=True, timeout=RUN_TIMEOUT)
    if run.returncode != want_exit:
        return False, (f"exit status {run.returncode}, expected {want_exit}"
                       + (f"; stderr: {run.stderr.strip()[:120]}" if run.stderr.strip() else ""))
    if want_stdout is not None and want_stdout not in run.stdout:
        return False, f"stdout {run.stdout[:120]!r} does not contain {want_stdout!r}"
    if verbose:
        print(f"      stdout={run.stdout[:60]!r} exit={run.returncode}")
    return True, ""


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("-v", "--verbose", action="store_true")
    ap.add_argument("cases", nargs="*", help="subset of case names")
    args = ap.parse_args()

    if platform.machine() not in ("arm64", "aarch64"):
        print(f"SKIP: formal output is arm64-only, host is {platform.machine()}")
        return 0

    selected = [c for c in CASES if not args.cases or c[0] in args.cases]
    if args.cases and len(selected) != len(args.cases):
        missing = set(args.cases) - {c[0] for c in selected}
        print(f"ERROR: unknown case(s): {sorted(missing)}", file=sys.stderr)
        return 2

    passed = failed = 0
    with tempfile.TemporaryDirectory() as tmpdir:
        for name, source, want_exit, want_stdout in selected:
            try:
                ok, detail = run_case(name, source, want_exit, want_stdout,
                                      tmpdir, args.verbose)
            except subprocess.TimeoutExpired:
                ok, detail = False, "timed out"
            except Exception as e:  # unexpected: report, do not mask
                ok, detail = False, f"{type(e).__name__}: {e}"
                if args.verbose:
                    import traceback
                    traceback.print_exc()
            if ok:
                passed += 1
                print(f"  PASS  {name} (exit {want_exit})")
            else:
                failed += 1
                print(f"  FAIL  {name}: {detail}")

    print(f"\nformal run: PASS={passed} FAIL={failed}")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
