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

**WHAT THIS DOES NOT CLAIM TO FIX.** A dynamic splat reserves a fixed
`model.DYNAMIC_SPLAT_SLOTS` (8) slots for its operand, so a source longer than
that appends past the reservation and the capacity guard exits 1. That limit is
the append path's, shared with every comprehension (`_compr_append_elem`), and
it predates this change — before it, the same program exited 0 and answered
wrongly, so this is the direction that leaves a wrong answer behind. It is
measured on BOTH backends and is one number in one place
(`model.dynamic_splat_capacity`), because a cap the two backends state
separately is a program that builds on one machine and dies on the other.

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

# (name, mojo source, CPython source) — the same program twice, so the
# expectation is computed rather than asserted.
#
# EVERY case below now demands the RIGHT ANSWER FROM BOTH BACKENDS. It used to
# accept a refusal from x86-64 ("star-unpack of a non-literal into a list is not
# lowered"), which is the safe direction and so looked like coverage — but it
# is coverage of nothing, and it is how thirteen SIGSEGVs and a construct that
# was half a feature both sat in the tree without a report. A case that accepts
# two outcomes cannot fail when one of them is a refusal, and a refusal is what
# a backend emits when it does not know the construct.
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

    # TWO DYNAMIC SPLATS IN ONE LITERAL. This is the case that separates "the
    # loop keeps its own state" from "the loop keeps its own state ONCE": the
    # second splice runs after the first has finished with its registers, so a
    # base or an index left behind by the first is read by the second. arm64
    # keeps them in X10-X12 and x86-64 on the stack, and the point of the case
    # is that the choice is invisible from here — both have to answer the same
    # list.
    ("two_dynamic_splats_in_one_literal",
     "def main():\n"
     "    var a = [1, 2]\n"
     "    var c = [8, 9, 10]\n"
     "    var b = [*a, *c]\n"
     "    printf(\"n=%d %d %d %d %d\", len(b), b[0], b[1], b[2], b[3])\n"
     "    return 0\n",
     "import sys\n"
     "def main():\n"
     "    a = [1, 2]\n"
     "    c = [8, 9, 10]\n"
     "    b = [*a, *c]\n"
     "    sys.stdout.write(\"n=%d %d %d %d %d\" % "
     "(len(b), b[0], b[1], b[2], b[3]))\n"
     "    return 0\n"),

    # A COMPREHENSION over a spliced result, in the same function. The
    # comprehension keeps its counter and its iterable pointer in named frame
    # slots (`_ci0`/`_cb0`) and leaves its loop with the same setae/jne exit
    # test the splice loop uses, so this is the case where two loops of that
    # shape are emitted into one body and a backend that confuses their state
    # reads a counter as a base address.
    #
    # The comprehension is over a NAME holding a spliced result;
    # `a_comprehension_over_a_spliced_literal` below is the same program with
    # the splice written INSIDE the `for`, which reserves a second blob inside
    # the comprehension's own.
    ("a_comprehension_over_a_spliced_result",
     "def main():\n"
     "    var a = [3, 4]\n"
     "    var c = [7, 8, 9]\n"
     "    var b = [*a, *c]\n"
     "    var d = [v * 2 for v in b]\n"
     "    printf(\"n=%d %d %d\", len(b), b[0], len(d))\n"
     "    return 0\n",
     "import sys\n"
     "def main():\n"
     "    a = [3, 4]\n"
     "    c = [7, 8, 9]\n"
     "    b = [*a, *c]\n"
     "    d = [v * 2 for v in b]\n"
     "    sys.stdout.write(\"n=%d %d %d\" % (len(b), b[0], len(d)))\n"
     "    return 0\n"),

    # THE SAME COMPREHENSION with the splice written as the ITERABLE, which is
    # the case this file deliberately left out while it was a separate defect.
    # `[*a]` builds its blob by appending, so it holds up to
    # `DYNAMIC_SPLAT_SLOTS` elements while `len([*a].elements)` is the ONE `*`
    # written in it — and a comprehension's reservation used to be sized by that
    # count. The iterable is evaluated inside the result's own reservation, so
    # a three-element source appended into a one-element result and the second
    # append hit the capacity guard: no output at all, exit 1, on every array
    # size. Both backends now size it from `model.list_literal_reserved_slots`,
    # the same rule the append path and `+` use.
    #
    # The static operand in the second half is the other side of that rule: it
    # contributes its own length (2), so the result holds 10 and not 8, and a
    # backend that counted the static operand as one would answer 9.
    ("a_comprehension_over_a_spliced_literal",
     "def main():\n"
     "    var a = [3, 4, 5]\n"
     "    var c = [v * 10 for v in [*a]]\n"
     "    var d = [v for v in [*[100, 200], *a]]\n"
     "    printf(\"n=%d %d %d n2=%d %d %d\", len(c), c[0], c[2],"
     " len(d), d[0], d[4])\n"
     "    return 0\n",
     "import sys\n"
     "def main():\n"
     "    a = [3, 4, 5]\n"
     "    c = [v * 10 for v in [*a]]\n"
     "    d = [v for v in [*[100, 200], *a]]\n"
     "    sys.stdout.write(\"n=%d %d %d n2=%d %d %d\" % "
     "(len(c), c[0], c[2], len(d), d[0], d[4]))\n"
     "    return 0\n"),

    # THE SAME SHAPE AT THE LIMIT, and a DICT comprehension rather than a list.
    # Eight elements is `DYNAMIC_SPLAT_SLOTS`, so the reservation has to be
    # exactly right rather than nearly: seven would stop the eighth append and
    # nine would reserve a blob the frame does not have. A dict comprehension
    # stores PAIRS, so its element size is 16 and the same arithmetic runs on a
    # different number — which is why it is here and not folded into the case
    # above.
    ("a_comprehension_at_the_splat_limit_and_a_dict_one",
     "def main():\n"
     "    var a = [1, 2, 3, 4, 5, 6, 7, 8]\n"
     "    var c = [v * 2 for v in [*a]]\n"
     "    var f = {v: v + 1 for v in [*a]}\n"
     "    printf(\"n=%d %d n4=%d %d\", len(c), c[7], len(f), f[8])\n"
     "    return 0\n",
     "import sys\n"
     "def main():\n"
     "    a = [1, 2, 3, 4, 5, 6, 7, 8]\n"
     "    c = [v * 2 for v in [*a]]\n"
     "    f = {v: v + 1 for v in [*a]}\n"
     "    sys.stdout.write(\"n=%d %d n4=%d %d\" % "
     "(len(c), c[7], len(f), f[8]))\n"
     "    return 0\n"),

    # A SLICE OF a spliced literal: the same under-count, one call site over. A
    # slice reserves for the elements it will copy and used to count `elements`
    # for a `[*a]` base, so `[*a][0:2]` of a three-element source reserved one
    # slot and exited 1 on arm64 while x86-64 — whose slice reservation never
    # looked at `elements` — answered it. Two backends, one rule now.
    ("a_slice_of_a_spliced_literal",
     "def main():\n"
     "    var a = [3, 4, 5, 6]\n"
     "    var s = [*a][0:2]\n"
     "    var t = [*a][1:3]\n"
     "    printf(\"n=%d %d %d %d\", len(s), s[0], s[1], t[1])\n"
     "    return 0\n",
     "import sys\n"
     "def main():\n"
     "    a = [3, 4, 5, 6]\n"
     "    s = [*a][0:2]\n"
     "    t = [*a][1:3]\n"
     "    sys.stdout.write(\"n=%d %d %d %d\" % "
     "(len(s), s[0], s[1], t[1]))\n"
     "    return 0\n"),

    # AN APPEND INTO THE SPLICED RESULT. The splice's reservation is sized for
    # the source's length, which is not a compile-time number, so the blob is
    # built by appending and its capacity comes from two places: the splat cap
    # and `_scan_list_caps`'s count of append SITES. A backend that reserved
    # only the splat cap answers the right list and then writes past the blob
    # on the append — so the COUNT is checked here and not only the elements.
    ("append_into_a_spliced_result",
     "def main():\n"
     "    var a = [1, 2]\n"
     "    var b = [*a]\n"
     "    b.append(3)\n"
     "    b.append(4)\n"
     "    printf(\"n=%d %d %d\", len(b), b[0], b[3])\n"
     "    return 0\n",
     "import sys\n"
     "def main():\n"
     "    a = [1, 2]\n"
     "    b = [*a]\n"
     "    b.append(3)\n"
     "    b.append(4)\n"
     "    sys.stdout.write(\"n=%d %d %d\" % (len(b), b[0], b[3]))\n"
     "    return 0\n"),

    # AN EMPTY SOURCE, and a source that is itself the result of a splice. Both
    # are `count == 0` or a count read out of a blob the compiler never saw,
    # and both are shapes where a loop whose exit test is inverted builds an
    # empty result SILENTLY rather than failing — which is arm64's defect and
    # the reason this file is differential rather than a build check. The
    # middle operand is itself a splice result, so its count comes out of a
    # blob the first one built.
    ("an_empty_source_and_a_spliced_source",
     "def main():\n"
     "    var e = []\n"
     "    var one = [4]\n"
     "    var two = [*one]\n"
     "    var b = [*e, *two, *e]\n"
     "    printf(\"n=%d %d %d\", len(b), len(two), b[0])\n"
     "    return 0\n",
     "import sys\n"
     "def main():\n"
     "    e = []\n"
     "    one = [4]\n"
     "    two = [*one]\n"
     "    b = [*e, *two, *e]\n"
     "    sys.stdout.write(\"n=%d %d %d\" % (len(b), len(two), b[0]))\n"
     "    return 0\n"),

    # A CONCATENATION with a spliced literal. `+` has to reserve its result
    # BEFORE evaluating either operand (a nested container must not land inside
    # the region being filled), so its size comes from a static ESTIMATE over
    # the syntax — and the estimate used to be `len(elements)`, which counts a
    # `*` operand as ONE element. `[1, 2] + [*c]` with `c = [7, 8, 9]`
    # therefore estimated 3 elements for a 5-element result. arm64 copied past
    # its own reservation without noticing and got the right answer by luck;
    # x86-64, which CHECKS the run-time total against the estimate, stopped at
    # the overflow guard. One under-estimate, two architectures, two different
    # symptoms — which is why the estimate is now
    # `model.list_literal_reserved_slots` in both.
    ("concat_with_a_spliced_literal",
     "def main():\n"
     "    var c = [7, 8, 9]\n"
     "    var b = [1, 2] + [*c]\n"
     "    printf(\"n=%d %d %d %d\", len(b), b[0], b[2], b[4])\n"
     "    return 0\n",
     "import sys\n"
     "def main():\n"
     "    c = [7, 8, 9]\n"
     "    b = [1, 2] + [*c]\n"
     "    sys.stdout.write(\"n=%d %d %d %d\" % (len(b), b[0], b[2], b[4]))\n"
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