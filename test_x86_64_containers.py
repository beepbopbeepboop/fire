#!/usr/bin/env python3
"""Run x86-64 container/surface programs and check the ANSWER, not the build.

`tools/formal_sweep.py` measures which files BUILD, and `test_x86_64_examples.py`
differential-tests the 43 integer examples against the arm64 backend. Neither
touches the blob runtime — lists, tuples, dicts, comprehensions, slices,
for-in, unpacking, string subscripts — which is nearly all of the
`formal/x86_64_codegen.py` surface those files exercise. A container emitter
that assembles and computes the wrong number is invisible to both.

So: each case is a whole program whose entry function returns a value, the
expected value is written down here, and the x86-64 binary is executed under
Rosetta 2 with the exit status compared. `--arch arm64` runs the same cases
through the arm64 backend, which is how a mismatch between the two is told
apart from a bug in both.

Two things about that comparison, both of which have cost a wrong reading:

  * A POSIX wait status is 8 bits wide, so an entry returning 750 exits 238.
    Every expectation therefore has to be in 0..255, and `main` REPORTS one
    that is not rather than comparing a truncated status against the real
    answer (which reads as a codegen bug in the backend rather than as the
    harness). A case that wants to observe a bigger number has to fold it
    (`len(xs)`, a comparison, a modulo) before returning.
  * The expected value is checked against CPython's answer for the same
    source, so it cannot drift into being a second hand's arithmetic.

    python3 test_x86_64_containers.py [--arch x86_64]
"""

import argparse
import os
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)


def _p(*lines):
    return "\n".join(lines) + "\n"


# (name, source, expected)
#
# The entry function is `main` when present (the startup stub calls it with
# the -n value); otherwise the FIRST top-level function is the entry, so
# single-function cases below rely on that and return directly.
CASES = [
    ("list-literal-index", _p(
        "def f():",
        "    xs = [10, 20, 30]",
        "    return xs[1]"), 20),
    ("list-negative-index", _p(
        "def f():",
        "    xs = [10, 20, 30]",
        "    return xs[-1]"), 30),
    ("list-first-last", _p(
        "def f(n):",
        "    xs = [1, 2, 3, 4, 5]",
        "    return xs[0] + xs[n - 1]"), 6),
    ("list-assign", _p(
        "def f():",
        "    xs = [1, 2, 3]",
        "    xs[1] = 42",
        "    return xs[1] + xs[0]"), 43),
    ("list-length-via-count", _p(
        "def f():",
        "    xs = [1, 2, 3, 4]",
        "    return xs[3]"), 4),
    ("tuple-literal", _p(
        "def f():",
        "    t = (7, 8, 9)",
        "    return t[0] + t[2]"), 16),
    ("tuple-unpack-assign", _p(
        "def f():",
        "    a = 0",
        "    b = 0",
        "    a, b = 5, 9",
        "    return a * b"), 45),
    ("tuple-swap", _p(
        "def f():",
        "    a = 1",
        "    b = 2",
        "    a, b = b, a",
        "    return a * 10 + b"), 21),
    ("nested-list-index", _p(
        "def f():",
        "    xs = [[1, 2], [3, 4]]",
        "    inner = xs[1]",
        "    return inner[0]"), 3),
    ("for-in-sum", _p(
        "def f():",
        "    total = 0",
        "    for x in [1, 2, 3, 4, 5]:",
        "        total += x",
        "    return total"), 15),
    ("for-in-index", _p(
        "def f():",
        "    last = 0",
        "    for x in [3, 5, 7]:",
        "        last = x",
        "    return last"), 7),
    ("for-in-tuple-target", _p(
        "def f():",
        "    total = 0",
        "    for a, b in [(1, 2), (3, 4)]:",
        "        total += a * b",
        "    return total"), 14),
    ("for-in-empty", _p(
        "def f():",
        "    n = 0",
        "    for x in []:",
        "        n = 99",
        "    return n"), 0),
    # A for-else runs when the loop finishes WITHOUT break, so here it does
    # run and out ends at 5.
    ("for-in-else-runs", _p(
        "def f():",
        "    out = 0",
        "    for x in [1]:",
        "        out = 1",
        "    else:",
        "        out = 5",
        "    return out"), 5),
    ("for-in-else-skipped-by-break", _p(
        "def f():",
        "    out = 0",
        "    for x in [1, 2]:",
        "        break",
        "    else:",
        "        out = 5",
        "    return out"), 0),
    ("list-concat", _p(
        "def f():",
        "    a = [1, 2]",
        "    b = [3, 4]",
        "    c = a + b",
        "    return c[0] + c[3]"), 5),
    ("list-concat-then-sum", _p(
        "def f():",
        "    a = [1, 2]",
        "    b = [3, 4]",
        "    c = a + b",
        "    t = 0",
        "    for x in c:",
        "        t += x",
        "    return t"), 10),
    ("membership", _p(
        "def f():",
        "    xs = [4, 5, 6]",
        "    return (5 in xs) + (9 in xs)"), 1),
    ("string-subscript", _p(
        "def f():",
        "    s = \"abc\"",
        "    return s[1]"), 98),          # ord('b')
    # Kept under 256: the answer travels out as the process exit status,
    # which POSIX truncates to a byte, so a larger sum would compare against
    # its own low byte (326 came back as 70 and looked like a codegen bug).
    ("string-index-in-loop", _p(
        "def f():",
        "    s = \"ab\"",
        "    t = 0",
        "    for i in range(2):",
        "        t += s[i]",
        "    return t"), 97 + 98),
    ("slice-basic", _p(
        "def f():",
        "    xs = [0, 1, 2, 3, 4, 5]",
        "    s = xs[1:4]",
        "    return s[0] * 10 + s[2]"), 13),
    ("slice-to-end", _p(
        "def f():",
        "    xs = [0, 1, 2, 3, 4, 5]",
        "    s = xs[3:]",
        "    return s[0] * 10 + s[1]"), 34),
    ("slice-step", _p(
        "def f():",
        "    xs = [0, 1, 2, 3, 4, 5]",
        "    s = xs[0:6:2]",
        "    return s[0] * 10 + s[1] * 10 + s[2]"), 24),
    ("slice-negative-bound", _p(
        "def f():",
        "    xs = [0, 1, 2, 3, 4, 5]",
        "    s = xs[-2:]",
        "    return s[0] * 10 + s[1]"), 45),
    ("slice-empty", _p(
        "def f():",
        "    xs = [0, 1, 2, 3]",
        "    s = xs[3:1]",
        "    t = 0",
        "    for x in s:",
        "        t = 99",
        "    return t"), 0),
    # A SECOND slice in one function. The five rows above are all ONE slice, and
    # that is why the bug they missed survived a file full of them
    # (fixed 2026-10-03 in 68671a62): the three bound-clamp
    # labels of `_emit_slice_parts` were named after the REGISTER alone
    # (`f_s4a`/`_z`/`_c`) while every other label in the emitter carries a
    # per-site counter, and `Assembler.label` keeps the LAST address for a name
    # — so the second slice rebound the first's `jge` and the first slice's copy
    # loop ran with the second's `r8`/`r9`. Measured on x86-64 before the fix:
    # a SIGSEGV here, 14 for 7 below, 2 for 26 in the third row. All three built,
    # and two of the three exited 0 with the wrong number.
    ("slice-two-bound-both-iterated", _p(
        "def f():",
        "    xs = [1, 2, 3, 4, 5, 6]",
        "    a = xs[1:3]",
        "    b = xs[2:6]",
        "    s = 0",
        "    for v in a:",
        "        s += v",
        "    for v in b:",
        "        s += v",
        "    return (s + a[0] * 13 + b[0] * 29) % 251"), 136),
    ("slice-two-bound-three", _p(
        "def f():",
        "    xs = [1, 2, 3, 4, 5, 6]",
        "    a = xs[0:2]",
        "    b = xs[2:4]",
        "    c = xs[4:6]",
        "    return a[0] * 100 + b[0] * 10 + c[0]"), 135),
    ("slice-two-len", _p(
        "def f():",
        "    xs = [1, 2, 3, 4, 5, 6]",
        "    return len(xs[1:3]) * 10 + len(xs[:])"), 26),
    # A slice OF a slice: the inner one has to copy out of the outer's freshly
    # built blob, so it re-enters the same emitter while the outer's own result
    # is still the only copy of anything.
    ("slice-of-slice", _p(
        "def f():",
        "    xs = [1, 2, 3, 4, 5, 6]",
        "    t = 0",
        "    for v in xs[1:5][1:3]:",
        "        t += v",
        "    return t"), 7),
    # A descending slice next to an ascending one, because the descending stop
    # default is the ONE case where only the start bound is clamped
    # (`wrap = [RCX] if not ascending and stop is None else [RCX, RDX]`) and so
    # it is the case where the two clamps do not have the same shape to collide.
    ("slice-reversed-and-bound", _p(
        "def f():",
        "    xs = [1, 2, 3, 4, 5, 6]",
        "    r = xs[::-1]",
        "    b = xs[1:4]",
        "    return r[0] * 10 + b[0]"), 62),
    ("comprehension-simple", _p(
        "def f(n):",
        "    xs = [i * 2 for i in range(n)]",
        "    t = 0",
        "    for x in xs:",
        "        t += x",
        "    return t"), 20),          # 0+2+4+6+8
    ("comprehension-filter", _p(
        "def f(n):",
        "    xs = [i for i in range(n) if i > 2]",
        "    t = 0",
        "    for x in xs:",
        "        t += x",
        "    return t"), 7),           # 3+4
    ("comprehension-expr", _p(
        "def f(n):",
        "    xs = [i + 1 for i in range(n)]",
        "    s = 0",
        "    for x in xs:",
        "        s += x",
        "    return s"), 15),          # 1+2+3+4+5
    ("comprehension-of-list", _p(
        "def f():",
        "    src = [5, 6, 7]",
        "    xs = [v * 2 for v in src]",
        "    t = 0",
        "    for x in xs:",
        "        t += x",
        "    return t"), 36),          # 10+12+14
    ("dict-literal-lookup", _p(
        "def f():",
        "    d = {1: 10, 2: 20}",
        "    return d[2]"), 20),
    ("dict-string-key", _p(
        "def f():",
        "    d = {\"a\": 1, \"b\": 2}",
        "    return d[\"b\"]"), 2),
    ("dict-in-loop", _p(
        "def f():",
        "    d = {1: 5, 2: 6, 3: 7}",
        "    t = 0",
        "    for k in [1, 2, 3]:",
        "        t += d[k]",
        "    return t"), 18),
    ("nested-comprehension", _p(
        "def f(n):",
        "    xs = [i + j for i in range(n) for j in range(n)]",
        "    t = 0",
        "    for x in xs:",
        "        t += x",
        "    return t"), 100),         # n=5: 5*10 + 5*10
    # The shapes that separate "one range() in the function" from "two".
    # `_emit_range_list`'s `jge` used to target a label every range() in the
    # function shared, so the FIRST one jumped into the SECOND one's abs
    # block and continued from ITS `jmp div_label` — the first range's blob
    # was never built and its base never stored, and the outer generator
    # looped over a register nothing had written. 2x2 hides it (both ranges
    # are the same length, so the borrowed block computes the same count);
    # these do not.
    ("nested-comprehension-len", _p(
        "def f(n):",
        "    xs = [i + j for i in range(n) for j in range(n)]",
        "    return len(xs)"), 25),    # n=5: 5*5
    ("nested-comprehension-5x5", _p(
        "def f(n):",
        "    xs = [i + j for i in range(n) for j in range(n)]",
        "    t = 0",
        "    for x in xs:",
        "        t += x",
        "    return t"), 100),        # n=5: 25 elements, 5*10 + 5*10
    # Three generators put THREE range() calls in one function, which is the
    # shape the shared label broke worst: the count is the cheap observable
    # and it is in the exit-status domain (a POSIX status is 8 bits wide, so
    # the sum 750 is not expressible here — see the module docstring).
    ("nested-comprehension-three-generators", _p(
        "def f(n):",
        "    xs = [i + j + k for i in range(n) for j in range(n)"
        " for k in range(n)]",
        "    return len(xs)"), 125),   # n=5: 5*5*5
    ("nested-comprehension-condition", _p(
        "def f(n):",
        "    xs = [i + j for i in range(n) for j in range(n)"
        " if (i + j) % 2 == 0]",
        "    t = 0",
        "    for x in xs:",
        "        t += x",
        "    return t"), 52),         # n=5: the even-sum pairs
    ("nested-comprehension-j-only", _p(
        "def f(n):",
        "    xs = [j for i in range(n) for j in range(n)]",
        "    return len(xs)"), 25),
    ("two-ranges-one-function", _p(
        "def f(n):",
        "    a = range(3)",
        "    b = range(4)",
        "    t = 0",
        "    for x in a:",
        "        t += x",
        "    for x in b:",
        "        t += x",
        "    return t"), 9),           # 0+1+2 + 0+1+2+3
    ("nested-comprehension-literal-inner", _p(
        "def f(n):",
        "    xs = [i + j for i in range(n) for j in [10, 20]]",
        "    t = 0",
        "    for x in xs:",
        "        t += x",
        "    return t"), 170),        # n=5: 5*(10+20) + 0+1+2+3+4
    # A comprehension is a blob of the same shape as a literal, so subscripting
    # one is a subscript. arm64 refused the base (`subscript base must be a
    # list/tuple name or literal`) while x86-64 computed it — the two backends
    # disagreeing about one program.
    ("comprehension-subscript", _p(
        "def f(n):",
        "    return [i * 2 for i in [1, 2, 3]][2]"), 6),
    # index 15 of a 5x5 is (3, 0) — the index arithmetic is the case's, and
    # the CPython check below is what says so.
    ("nested-comprehension-subscript", _p(
        "def f(n):",
        "    return [i + j for i in range(n) for j in range(n)][15]"), 3),
    # A dict comprehension's SUBSCRIPT is a key lookup. Both backends asked
    # `isinstance(base, DictExpr)`, which a dict comprehension is not (it is a
    # Comprehension with kind='dict'), so `d` was treated as a plain blob and
    # `d[k]` indexed the pair array: right len, right keys, the key read as
    # the value under it.
    ("dict-comprehension-lookup-first", _p(
        "def f(n):",
        "    d = {i: 100 + i for i in range(3)}",
        "    return d[0]"), 100),
    ("dict-comprehension-lookup-middle", _p(
        "def f(n):",
        "    d = {i: 100 + i for i in range(3)}",
        "    return d[1]"), 101),
    ("dict-comprehension-lookup-last", _p(
        "def f(n):",
        "    d = {i: 100 + i for i in range(3)}",
        "    return d[2]"), 102),
    ("dict-comprehension-len", _p(
        "def f(n):",
        "    d = {i: 100 + i for i in range(3)}",
        "    return len(d)"), 3),
    # A MISSING key exits 1: this path has no exception runtime to raise
    # KeyError with, and a miss is the same signal an out-of-range index
    # gives. Asserted rather than left implicit, because "the value happened
    # to be 1" and "the lookup missed and exited 1" are otherwise the same
    # exit status.
    ("dict-comprehension-missing-key", _p(
        "def f(n):",
        "    d = {i: 100 + i for i in range(3)}",
        "    return d[3]"), 1),
    ("dict-literal-still-a-lookup", _p(
        "def f(n):",
        "    d = {1: 10, 2: 20}",
        "    return d[2]"), 20),
    ("try-finally-runs", _p(
        "def f():",
        "    out = 0",
        "    try:",
        "        out = 1",
        "    finally:",
        "        out = out + 10",
        "    return out"), 11),
    ("return-inside-try", _p(
        "def f():",
        "    out = 0",
        "    try:",
        "        return 5",
        "    finally:",
        "        out = 1",
        "    return out"), 5),
    ("with-statement", _p(
        "def f():",
        "    x = 0",
        "    with 7 as y:",
        "        x = y",
        "    return x"), 7),
    # n=5: (5>5 is false -> 2) + (5>0 is true -> 3) = 5
    ("ternary-and-chain", _p(
        "def f(n):",
        "    return (1 if n > 5 else 2) + (3 if n > 0 else 4)"), 5),
    ("chained-compare", _p(
        "def f(n):",
        "    return (1 < n < 10) + (10 < n < 20)"), 1),
    # n=5 is truthy, so `n or 99` is 5 -> 6
    ("short-circuit-or", _p(
        "def f(n):",
        "    return (n or 99) + 1"), 6),
    ("short-circuit-and", _p(
        "def f(n):",
        "    return (n and 3) + 1"), 4),
    # `main` must be the entry when a module has several functions — the
    # startup stub calls the FIRST function otherwise, with a second argument
    # it was never given. n=5: 5*3 + 2*5 = 25.
    ("nested-def-and-call", _p(
        "def helper(a, b):",
        "    return a * b",
        "",
        "def main():",
        "    return helper(5, 3) + helper(2, 5)"), 25),
    ("string-in-if", _p(
        "def f(n):",
        "    s = \"abc\"",
        "    if n > 0:",
        "        return s[0]",
        "    return 0"), 97),
    ("string-equality", _p(
        "def f():",
        "    a = \"xy\"",
        "    b = \"xy\"",
        "    return (a == b) + (a == b)"), 2),
    ("break-in-for", _p(
        "def f():",
        "    t = 0",
        "    for x in [1, 2, 3, 4]:",
        "        if x == 3:",
        "            break",
        "        t += x",
        "    return t"), 3),
    ("continue-in-for", _p(
        "def f():",
        "    t = 0",
        "    for x in [1, 2, 3, 4]:",
        "        if x == 2:",
        "            continue",
        "        t += x",
        "    return t"), 8),
]


def run_case(name: str, source: str, arch: str):
    """Build and run one case; return (status, detail) with status None on a
    build/run failure."""
    import formal.build as B
    with tempfile.TemporaryDirectory(prefix="formal-x86c-") as td:
        src = os.path.join(td, "case.mojo")
        with open(src, "w") as f:
            f.write(source)
        out = os.path.join(td, "a.out")
        try:
            B.compile_formal(src, output=out, test_input=5, prove=False,
                             arch=arch)
        except Exception as e:                          # noqa: BLE001
            return None, f"build: {type(e).__name__}: {e}"
        argv = ["arch", "-x86_64", out] if (arch == "x86_64"
                                            and sys.platform == "darwin") \
            else [out]
        r = subprocess.run(argv, capture_output=True, text=True)
        if r.returncode < 0:
            return None, f"signal {-r.returncode}"
        if "Bad CPU type" in (r.stderr or ""):
            return None, "Bad CPU type in executable"
        return r.returncode, ""


def cpython_answer(source: str, test_input: int = 5):
    """What CPython says this program's entry returns, or None if it cannot
    be asked (a syntax the host interpreter and this file disagree about).

    Every case here is an ordinary Python program, so the expectation written
    beside it is a TRANSCRIPT of CPython's answer rather than a second hand's
    arithmetic — and the wrong-expectation failure mode (a case that passes on
    both backends because both are wrong in the same way as the note) is then
    impossible. Checked once per case, so it costs 52 short interpreter runs.
    """
    import ast
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return None
    entry = None
    for node in tree.body:
        if isinstance(node, ast.FunctionDef):
            entry = node
    if entry is None:
        return None
    takes_arg = bool(entry.args.args)
    driver = ("print(%s(%d))\n" % (entry.name, test_input) if takes_arg
              else "print(%s())\n" % entry.name)
    with tempfile.TemporaryDirectory(prefix="formal-x86c-py-") as td:
        path = os.path.join(td, "case.py")
        with open(path, "w") as f:
            f.write(source + driver)
        r = subprocess.run([sys.executable, path], capture_output=True,
                           text=True, cwd=td, timeout=60)
    if r.returncode != 0:
        return None
    out = r.stdout.strip()
    try:
        return int(out)
    except ValueError:
        return None


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--arch", default="x86_64",
                    choices=("x86_64", "arm64"))
    ap.add_argument("-v", action="store_true")
    ap.add_argument("--no-cpython", action="store_true",
                    help="skip the CPython cross-check of the expectations")
    args = ap.parse_args()

    failed = passed = 0
    for name, source, want in CASES:
        # CPython first, and on its own: a wrong EXPECTATION has to be
        # reported as one even when the backend happens to agree with it,
        # and it has to be reported even when the backend does not (which is
        # the case that costs the most time — a note computed at n=4 read by
        # a harness that runs at n=5 looks exactly like a codegen bug).
        problems = []
        cpy = None if args.no_cpython else cpython_answer(source)
        if cpy is not None and cpy != want:
            problems.append(f"expectation {want} is not what CPython "
                            f"answers ({cpy})")
        if not 0 <= want <= 255:
            # A wait status cannot carry it, so the comparison below would be
            # against a truncated value and read as a codegen bug that is not
            # there. A property of the CASE, so the case is what has to change.
            problems.append(f"expectation {want} is outside the 8-bit "
                            f"exit-status domain (0..255)")
        got, detail = run_case(name, source, args.arch)
        if got is None:
            problems.append(detail)
        elif got != want:
            problems.append(f"returned {got}, want {want}")
        if problems:
            failed += 1
            status, note = "FAIL", "; ".join(problems)
        else:
            passed += 1
            status, note = "PASS", f"= {got}"
        if status != "PASS" or args.v:
            print(f"{status:4} {name:34} {note}")
    print(f"[{args.arch}] PASS={passed} FAIL={failed} of {len(CASES)}")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
