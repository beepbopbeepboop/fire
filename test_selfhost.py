#!/usr/bin/env python3
"""Self-host compile guard.

fire.py must compile *itself* to a fully linked binary with zero GCC errors,
zero internal compiler errors (ICEs), and no undefined symbols. This is the
`./fire.py --jit fire.py` path, minus execution.

We deliberately do NOT run the produced binary: the self-hosted runtime still
SIGSEGVs (exit -11), which is a separate, deeper frontier. This test locks the
compile+link cleanliness in place so it cannot silently regress (e.g. a parser
change that emits GIMPLE GCC chokes on, or a codegen change that reintroduces a
type-mismatched binary op / undefined dispatch helper).

build_executable() performs the same compile_to_gimple -> gcc -fgimple -> link
sequence the JIT uses and returns True only if every step exited 0.
"""
import os
import sys
import tempfile

REPO = os.path.dirname(os.path.abspath(__file__))


def run() -> bool:
    sys.path.insert(0, REPO)
    import fire
    main_src = os.path.join(REPO, "fire.py")
    src = open(main_src).read()
    cwd = os.getcwd()
    with tempfile.TemporaryDirectory() as td:
        # build_executable writes mojo.{ci,o} + fire_runtime.o into cwd; keep the
        # repo clean by building inside the temp dir.
        os.chdir(td)
        try:
            out = os.path.join(td, "mojo_selfhost")
            ok = fire.build_executable(main_src, src, output=out)
            return bool(ok) and os.path.exists(out)
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
        print("✓ self-host compiles + links clean (fire.py compiling fire.py)")
        return 0
    print("Results: 0 passed, 1 failed")
    print("✗ self-host compile/link regressed (GCC error, ICE, or undefined symbol)")
    return 1


if __name__ == "__main__":
    sys.exit(main())
