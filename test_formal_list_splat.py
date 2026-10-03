#!/usr/bin/env python3
"""`[*xs]` — a list literal with a DYNAMIC splat — has to answer, not build.

A list literal whose `*` operand is a list LITERAL is expanded at compile time
and both backends have always got it right (`[0, *[1, 2], 3]` → `0 1 2 3`,
pinned here as a control). The dynamic spelling — `[*a]` where `a` is a name —
has no compile-time length, so the result blob is reserved up front and the
elements are appended at run time, and that path is where the defect was.

**arm64 built it, ran it, exited 0, and answered with an EMPTY list.**
`formal/arm64_codegen.py`'s `_emit_star_splice` branched to its `done` label
when the loop's exit flag was CLEAR, and the flag (`cset ge`) is clear exactly
when the index has NOT reached the count — so the body never ran:

    def main():
        a = [1, 2]
        b = [*a]
        printf("%d", len(b))
        return 0

    arm64   ->  0            (CPython: 2)
    x86_64  ->  build refused: "star-unpack of a non-literal into a list is
               not lowered on the formal x86-64 path"

`len` said 0, so reading `b[0]` hit the subscript's bounds guard and exited 1
with nothing on stderr. Nothing in a build, a link or an exit code reports it,
which is why a differential case is the only thing that catches it.

The same function kept the source base and the index in X9 and X3 across the
append, and `_compr_append_elem` re-derives the RESULT base into X9 and puts
its capacity flag in X3 — so even with the exit test repaired, every element
after the first would have been read out of the result blob. Both are fixed
together, and the fixed version keeps that state in X10-X13, which nothing in
the sequence touches.

**WHAT THIS DOES NOT CLAIM TO FIX.** A dynamic splat reserves a fixed 8 slots
for its operand, so a source longer than 8 appends past the reservation and the
capacity guard exits 1. That limit is the append path's, shared with every
comprehension (`_compr_append_elem`), and it predates this change — before it,
the same program exited 0 and answered wrongly, so this is the direction that
leaves a wrong answer behind. `bugs/FORMAL_x86_64_dynamic_list_splat_is_refused.md`
holds the x86-64 half: the construct is refused there rather than wrong, which
is the safe direction and is why the x86-64 half of each case below asserts
"right answer OR a refusal", never a number.

    python3 test_formal_list_splat.py [-v] [--list]
"""

import argparse
import os
import platform
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
FIRE = os.path.join(HERE, "fire.py")
BUILD_TIMEOUT = 600
RUN_TIMEOUT = 120
BACKENDS = ("arm64", "x86_64")

# The refusal the x86-64 backend uses, or a phrase of it. Matched on a
# substring rather than the whole sentence so a wording improvement does not
# turn this file red; what must not change is that the construct is named.
X86_REFUSES = "star-unpack of a non-literal into a list is not lowered"

# (name, mojo source, CPython source) — the same program twice, so the
# expectation is computed rather than asserted.
CASES = [
    # The control: a literal operand, expanded at compile time. It has always
    # worked on both machines, and it is here so the dynamic cases below cannot
    # pass by the whole shape being refused.
    ("literal_splat_is_expanded_at_compile_time",
     "def main():\n"
     "    var b = [0, *[1, 2], 3]\n"
     "    printf(\"n=%d %d %d %d %d\", len(b), b[0], b[1], b[2], b[3])\n"
     "    return 0\n",
     "import sys\n"
     "def main():\n"
     "    b = [0, *[1, 2], 3]\n"
     "    sys.stdout.write(\"n=%d %d %d %d %d\" % "
     "(len(b), b[0], b[1], b[2], b[3]))\n"
     "    return 0\n"),
    # The defect: a NAME as the operand, so the length is a run-time value.
    ("dynamic_splat_alone",
     "def main():\n"
     "    var a = [1, 2]\n"
     "    var b = [*a]\n"
     "    printf(\"n=%d %d %d\", len(b), b[0], b[1])\n"
     "    return 0\n",
     "import sys\n"
     "def main():\n"
     "    a = [1, 2]\n"
     "    b = [*a]\n"
     "    sys.stdout.write(\"n=%d %d %d\" % (len(b), b[0], b[1]))\n"
     "    return 0\n"),
    # Elements on BOTH sides of the splat, so a result blob that starts its
    # count at the wrong place shows up as a shifted list rather than as an
    # empty one — the shape that separates "the count is right" from "the
    # elements are in the right slots".
    ("dynamic_splat_between_two_literals",
     "def main():\n"
     "    var a = [7, 8]\n"
     "    var b = [*a, 9, *a]\n"
     "    printf(\"n=%d %d %d %d %d\", len(b), b[0], b[1], b[2], b[3])\n"
     "    return 0\n",
     "import sys\n"
     "def main():\n"
     "    a = [7, 8]\n"
     "    b = [*a, 9, *a]\n"
     "    sys.stdout.write(\"n=%d %d %d %d %d\" % "
     "(len(b), b[0], b[1], b[2], b[3]))\n"
     "    return 0\n"),
    # A `range` as the operand: not a list at all, so the count the loop reads
    # is a blob's count field rather than a literal's length.
    ("dynamic_splat_of_a_range",
     "def main():\n"
     "    var r = range(4)\n"
     "    var b = [*r]\n"
     "    printf(\"n=%d %d %d\", len(b), b[0], b[3])\n"
     "    return 0\n",
     "import sys\n"
     "def main():\n"
     "    r = range(4)\n"
     "    b = [*r]\n"
     "    sys.stdout.write(\"n=%d %d %d\" % (len(b), b[0], b[3]))\n"
     "    return 0\n"),
    # Every element read back through a LOOP rather than through fixed
    # subscripts, because the second-and-later elements are exactly what the
    # X9 clobber broke: a fixed subscript reads one slot the first append
    # filled, and only a walk reads the ones after it.
    ("dynamic_splat_read_back_through_a_loop",
     "def main():\n"
     "    var a = [3, 1, 2]\n"
     "    var b = [*a]\n"
     "    var t = 0\n"
     "    for i in range(len(b)):\n"
     "        t += b[i]\n"
     "    printf(\"n=%d t=%d\", len(b), t)\n"
     "    return 0\n",
     "import sys\n"
     "def main():\n"
     "    a = [3, 1, 2]\n"
     "    b = [*a]\n"
     "    t = 0\n"
     "    for i in range(len(b)):\n"
     "        t += b[i]\n"
     "    sys.stdout.write(\"n=%d t=%d\" % (len(b), t))\n"
     "    return 0\n"),
]


def build(src, out, backend):
    cmd = [sys.executable, FIRE, "build", "--formal", "--no-prove",
           f"--backend={backend}", "-o", out, src]
    p = subprocess.run(cmd, capture_output=True, text=True,
                       timeout=BUILD_TIMEOUT, cwd=HERE)
    return p.returncode, (p.stderr or p.stdout or "")


def run(path, backend, timeout=RUN_TIMEOUT):
    """Execute a built image, under Rosetta 2 when it is an x86-64 one.

    Selected by the BACKEND, not by what was built: `arch -x86_64 <an arm64
    image>` is "Bad CPU type in executable", which reads as the host's fault and
    is really the harness asking the wrong machine to run the program.
    """
    argv = [path]
    if (backend == "x86_64" and platform.machine() in ("arm64", "aarch64")
            and sys.platform == "darwin"):
        argv = ["arch", "-x86_64", path]
    return subprocess.run(argv, capture_output=True, text=True, timeout=timeout)


def cpython_answer(source, tmpdir, name):
    """CPython's stdout and exit status for `source` + `main()`, run now."""
    py = os.path.join(tmpdir, name + ".ref.py")
    with open(py, "w") as f:
        f.write(source + "\nmain()\n")
    ref = subprocess.run([sys.executable, py], capture_output=True, text=True,
                         timeout=RUN_TIMEOUT)
    return ref.returncode, ref.stdout


def run_case(case, tmpdir, verbose):
    name, mojo_src, cpython_src = case
    src = os.path.join(tmpdir, name + ".mojo")
    with open(src, "w") as f:
        f.write(mojo_src)
    want_exit, want_out = cpython_answer(cpython_src, tmpdir, name)
    if want_exit != 0:
        return False, (f"the CPython reference itself failed (exit "
                       f"{want_exit}); a case whose oracle does not run asserts "
                       f"nothing")
    for backend in BACKENDS:
        out = os.path.join(tmpdir, f"{name}.{backend}")
        rc, text = build(src, out, backend)
        if rc != 0:
            if backend == "x86_64" and X86_REFUSES in text:
                # A refusal is the SAFE direction and this case does not demand
                # more of it — see the module docstring. What must never happen
                # is the other outcome, which is why the branch below is the
                # only one that accepts a non-zero build.
                if verbose:
                    print(f"      x86_64: refused, as it does today")
                continue
            return False, (f"--backend={backend} did not build: "
                           f"{text.strip()[-300:]}")
        if not os.path.isfile(out):
            return False, f"--backend={backend} reported success, wrote no binary"
        r = run(out, backend)
        if r.returncode != want_exit:
            return False, (f"--backend={backend} exited {r.returncode}, CPython "
                           f"exits {want_exit}; stderr: {r.stderr.strip()[:160]}")
        if r.stdout != want_out:
            return False, (f"--backend={backend} printed {r.stdout[:120]!r}, "
                           f"CPython prints {want_out[:120]!r}")
        if verbose:
            print(f"      {backend}: {r.stdout[:60]!r} exit={r.returncode}")
    return True, ""


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("-v", "--verbose", action="store_true")
    ap.add_argument("--list", action="store_true", help="list the cases and exit")
    ap.add_argument("cases", nargs="*", help="run only these cases")
    args = ap.parse_args()

    if args.list:
        for name, _s, _c in CASES:
            print(f"  case  {name}")
        return 0

    known = {c[0] for c in CASES}
    wanted = CASES
    if args.cases:
        missing = set(args.cases) - known
        if missing:
            print(f"ERROR: unknown case(s): {sorted(missing)}", file=sys.stderr)
            return 2
        wanted = [c for c in CASES if c[0] in args.cases]

    passed = failed = 0
    with tempfile.TemporaryDirectory() as tmpdir:
        for case in wanted:
            try:
                ok, why = run_case(case, tmpdir, args.verbose)
            except subprocess.TimeoutExpired:
                ok, why = False, "timed out"
            except Exception as e:                       # report, do not mask
                ok, why = False, f"{type(e).__name__}: {e}"
            if ok:
                passed += 1
                print(f"  PASS  {case[0]}")
            else:
                failed += 1
                print(f"  FAIL  {case[0]}: {why}")

    print(f"\nformal list splat: PASS={passed} FAIL={failed}")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())