#!/usr/bin/env python3
"""Self-host compile guard.

fire.py must compile *itself* to a fully linked binary with zero GCC errors,
zero internal compiler errors (ICEs), and no undefined symbols. This is the
`./fire.py --jit fire.py` path.

It must then also COMPILE: the produced binary is run over a two-line program
and the generated `.ci` is checked for real output. The second half is not
redundant with the first. A self-hosted compiler whose own analysis helper was
emitted as the `weak` "unavailable in compiled mode" stub links perfectly,
exits 0, and emits a `.ci` containing nothing but that diagnostic — so the
compile+link check above is structurally blind to the whole class, and a green
`selfhost` step coexisted with a `mojoc` that could compile nothing at all.
`run_produced_binary`'s docstring has the real instance.

build_executable() performs the same compile_to_gimple -> gcc -fgimple -> link
sequence the JIT uses and returns True only if every step exited 0.
"""
import os
import subprocess
import sys
import tempfile

REPO = os.path.dirname(os.path.abspath(__file__))

# The smallest input that exercises the whole self-hosted compile path: a
# module's worth of statements, a function, a call and a print. Two lines is
# enough and is deliberately the smallest thing that used to crash — see
# `run_produced_binary` below.
TWO_LINE = "x = 1\nprint(x)\n"


def build(td: str) -> str:
    """Self-compile fire.py into `td`, returning the binary path.

    build_executable writes mojo.{ci,o} + fire_runtime.o into the CWD, so the
    caller chdirs into a temp dir to keep the repo clean.
    """
    sys.path.insert(0, REPO)
    import fire
    main_src = os.path.join(REPO, "fire.py")
    src = open(main_src).read()
    out = os.path.join(td, "mojo_selfhost")
    ok = fire.build_executable(main_src, src, output=out)
    if not ok or not os.path.exists(out):
        return ""
    return out


def run_produced_binary(exe: str, td: str) -> tuple:
    """Compile a two-line program with the freshly built self-hosted compiler
    and report `(exit_status, ci_bytes, unsupported_stub_hits)`.

    This is the end-to-end regression for the class of bug where the
    self-hosted binary *builds and links cleanly* — so `run()` above is
    green — and then cannot compile anything, because one of its own
    analysis helpers was emitted as the `weak` "unavailable in compiled
    mode" stub. A stub returns nothing, so every `for node in <stub>(...)`
    in the compiled compiler iterated zero times and the whole
    self-hosted codegen pass became a no-op. The result was a `.ci` file
    containing nothing but that diagnostic, repeated once per call, with
    exit status 0 — a silent wrong answer that no exit code reports and
    that the compile+link check is structurally blind to.

    The real instance: `mojo/middle/lambdareduce.py`'s `_walk` /
    `_walk_body` were `yield`/`yield from` generators, which do not
    survive self-compilation, so `./mojoc --dump-full` on a TWO-LINE
    program produced a 164-byte `.ci` that was entirely
    `"_walk: unavailable in compiled mode"`. `mojo/middle/coro.py`'s
    identically-named `_walk` had already been converted to an accumulator
    function for the same class of reason (see its docstring); this makes
    the two agree.

    Asserted on the CONTENT, not the exit status, for that reason.
    """
    prog = os.path.join(td, "probe.mojo")
    with open(prog, "w") as f:
        f.write(TWO_LINE)
    r = subprocess.run([exe, "--dump-full", prog], cwd=td,
                       capture_output=True, text=True, timeout=300)
    ci = os.path.join(td, "probe.ci")
    text = ""
    if os.path.exists(ci):
        with open(ci) as f:
            text = f.read()
    return (r.returncode, len(text),
            text.count("unavailable in compiled mode"))


def run() -> bool:
    cwd = os.getcwd()
    with tempfile.TemporaryDirectory() as td:
        os.chdir(td)
        try:
            exe = build(td)
            if not exe:
                return False
            rc, nbytes, stubs = run_produced_binary(exe, td)
            print(f"  self-hosted compiler on a two-line program: "
                  f"exit={rc} ci_bytes={nbytes} stub_hits={stubs}")
            if rc != 0:
                print("  ✗ the self-hosted binary did not exit 0")
                return False
            if stubs:
                print(f"  ✗ {stubs} of the self-hosted compiler's own "
                      "functions were emitted as 'unavailable in compiled "
                      "mode' stubs — its analysis passes are no-ops")
                return False
            if nbytes < 200:
                print(f"  ✗ the self-hosted binary produced a {nbytes}-byte "
                      ".ci for a two-line program; expected real output")
                return False
            return True
        finally:
            os.chdir(cwd)


def main() -> int:
    try:
        ok = run()
    except Exception as e:
        print(f"Results: 0 passed, 1 failed")
        print(f"✗ self-host build raised: {e}")
        return 1
    if ok:
        print("Results: 1 passed, 0 failed")
        print("✓ self-host compiles + links clean, and the produced binary "
              "compiles a two-line program to real output")
        return 0
    print("Results: 0 passed, 1 failed")
    print("✗ self-host compile/link regressed (GCC error, ICE, undefined "
          "symbol, or the produced binary cannot compile)")
    return 1


if __name__ == "__main__":
    sys.exit(main())
