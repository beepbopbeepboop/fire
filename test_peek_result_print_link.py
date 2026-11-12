#!/usr/bin/env python3
"""`print(it.peek())` on a `peekable(...)` iterator must describe the
Optional[Pointer[...]] value, not print a raw integer address.

Regression for CODEGEN_peek_result_prints_raw_address: compiled `fire.py
build` printed the nulled-pointer word as a decimal address
(e.g. 48136352). It must instead print Optional(Some) / Optional(None).

    python3 test_peek_result_print_link.py
"""
import os, subprocess, sys, tempfile
HERE = os.path.dirname(os.path.abspath(__file__))

CASES = [
    ("""\
from std.iter import peekable

def main():
    var it = peekable(range(3))
    print(it.peek())
""", "Optional(Some)\n"),
    ("""\
from std.iter import peekable

def main():
    var l = List[Int]()
    var it = peekable(l)
    print(it.peek())
""", "Optional(None)\n"),
]


def main():
    for i, (program, expected) in enumerate(CASES):
        with tempfile.TemporaryDirectory(prefix="peek_print_%d_" % i) as td:
            src = os.path.join(td, "peek.mojo")
            exe = os.path.join(td, "peek.bin")
            with open(src, "w") as f:
                f.write(program)
            b = subprocess.run(
                [sys.executable, os.path.join(HERE, "fire.py"), "build", src, "-o", exe],
                capture_output=True, text=True, cwd=HERE, timeout=1200)
            if b.returncode != 0 or not os.path.exists(exe):
                print("FAIL peek_result_print_link[%d]: fire.py build did not produce a binary (exit %d)" % (i, b.returncode))
                print((b.stdout + b.stderr).strip().splitlines()[-1][:300] if (b.stdout + b.stderr).strip() else "")
                return 1
            r = subprocess.run([exe], capture_output=True, text=True, timeout=60)
            if r.returncode != 0 or r.stdout != expected:
                print("FAIL peek_result_print_link[%d]: exit %d, stdout %r, stderr %r"
                      % (i, r.returncode, r.stdout, r.stderr.strip()[:200]))
                return 1
    print("PASS peek_result_print_link")
    return 0


if __name__ == "__main__":
    sys.exit(main())
