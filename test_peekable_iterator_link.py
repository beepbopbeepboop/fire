#!/usr/bin/env python3
"""std/iter's `peekable` must build and run through the real `fire.py build` path (the stdlib dylib), not only through
the gimple test harness.

Regression for bugs/CODEGEN_peekable_iterator_methods_not_emitted.md: the stdlib dylib referenced
`_std_iter___init____PeekableIterator_peek` and never defined it, so every compiled program aborted at load. The
generic template's refused method bodies are prototype-only by design, and their class-table entries named a symbol
no translation unit here defines. The table now leaves those entries out; the instantiating unit still emits its copy.

    python3 test_peekable_iterator_link.py
"""
import os, subprocess, sys, tempfile
HERE = os.path.dirname(os.path.abspath(__file__))

PROGRAM = """\
from std.iter import peekable

def main():
    var it = peekable(range(3))
    for x in it:
        print(x)
"""
EXPECTED = "0\n1\n2\n"


def main():
    with tempfile.TemporaryDirectory(prefix="peekable_link_") as td:
        src = os.path.join(td, "peek.mojo")
        exe = os.path.join(td, "peek.bin")
        with open(src, "w") as f:
            f.write(PROGRAM)
        b = subprocess.run([sys.executable, os.path.join(HERE, "fire.py"), "build", src, "-o", exe],
                           capture_output=True, text=True, cwd=HERE, timeout=1200)
        if b.returncode != 0 or not os.path.exists(exe):
            print("FAIL peekable_iterator_link: fire.py build did not produce a binary (exit %d)" % b.returncode)
            print((b.stdout + b.stderr).strip().splitlines()[-1][:300] if (b.stdout + b.stderr).strip() else "")
            return 1
        r = subprocess.run([exe], capture_output=True, text=True, timeout=60)
        if r.returncode != 0 or r.stdout != EXPECTED:
            print("FAIL peekable_iterator_link: exit %d, stdout %r, stderr %r"
                  % (r.returncode, r.stdout, r.stderr.strip()[:200]))
            return 1
    print("PASS peekable_iterator_link: printed %r" % r.stdout)
    return 0


if __name__ == "__main__":
    sys.exit(main())
