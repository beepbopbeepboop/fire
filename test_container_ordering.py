#!/usr/bin/env python3
"""`<` / `<=` / `>` / `>=` between containers on the compiled path is Python's
ordering, not a heap-address comparison.

`a < b` between two containers used to fall through to C's generic numeric
tail, which emits the same raw POINTER comparison `==` used to — so the answer
was decided by which container happened to be allocated lower, which is stable
within one run and simply wrong. Exit 0, no diagnostic: `a < b` gives a
plausible answer, just not Python's. Unlike `==`, this is ANSWERABLE rather
than a refusal — this project's CPython implements ordering for lists
(lexicographic, a shorter prefix ordering first) and for sets (proper subset),
so there is a correct answer to give. See
bugs/CODEGEN_container_ordering_is_pointer_identity.md for the measurement that
found it, as the sibling of the `==` bug test_container_equality.py covers.

A dict is the exception: `{'a':1} < {'b':2}` is a genuine TypeError on 3.14 as
well, so it is a REFUSAL here too — and so is a pair of different kinds, and a
container against a scalar. The refusal is CPython's own TypeError with CPython's
own type names, which the cases below check by diffing the message against
CPython's rather than against an answer written down here.

Every case is a whole PROGRAM run TWICE — once compiled to an executable
through the GIMPLE backend, once by CPython on the same text with the Mojo
spellings stripped — and stdout, exit status AND (for the refusal cases) the
TypeError text must agree. Diffing against CPython is the point: the expected
values are Python's, so a divergence is the compiler's, not the test's.

Run:  python3 test_container_ordering.py [-v] [--keep]
"""
import argparse
import os
import re
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

RUNTIME = os.path.join(HERE, 'runtime')


def _p(*lines: str) -> str:
    return "\n".join(lines) + "\n"


# Every program is written ONCE and used for both engines (see `_py_source`).
# Each prints one line per assertion and returns 0, so a divergence is a
# line-by-line diff rather than one opaque exit status.
#
# The refusal cases are the odd ones out: their reference program does not
# produce stdout at all, it raises. `_run` below compares the exit status and
# the TypeError line instead, so they are diffed on the same footing.
CASES = [
    # ── the bug itself: the five lines the bug doc measured ────────────────
    ("doc-repro", _p(
        "def main() -> Int:",
        "    a = [1, 2]",
        "    b = [1, 3]",
        "    c = [1]",
        "    s1 = {1, 2}",
        "    s2 = {1, 3}",
        "    print(a < b)",
        "    print(a > b)",
        "    print(a <= c)",
        "    print(s1 < s2)",
        "    print(s1 > s2)",
        "    return 0")),

    # ── lists: lexicographic, and a SHORTER PREFIX orders first ────────────
    # The prefix rule is the half of the list rule that is easiest to get wrong
    # and the most consequential: `[1] < [1, 2]` is True, and a comparison
    # that only looks at the shared prefix gets it exactly backwards.
    ("list-lexicographic", _p(
        "def main() -> Int:",
        "    print([1, 2] < [1, 3])",
        "    print([1, 3] < [1, 2])",
        "    print([2, 1] < [1, 3])",
        "    print([1] < [1, 2])",
        "    print([1, 2] < [1])",
        "    print([] < [0])",
        "    print([] <= [])",
        "    print([1, 2] < [1, 2])",
        "    print([1, 2] <= [1, 2])",
        "    print([1, 2] >= [1, 2])",
        "    return 0")),
    ("list-elementwise-float", _p(
        "def main() -> Int:",
        # an int slot against a float slot compares NUMERICALLY, not by bit
        # pattern and not by converting the float to an int
        "    print([1] < [1.5])",
        "    print([0.5] < [1])",
        "    print([1.5] < [1])",
        "    print([2] > [1.5])",
        "    print([1, 2.5] < [1, 3])",
        "    print([1.0, 2] < [1.0, 2.5])",
        "    return 0")),
    ("list-elementwise-str", _p(
        "def main() -> Int:",
        '    print(["a"] < ["b"])',
        '    print(["b"] < ["a"])',
        '    print(["a", "b"] < ["a", "c"])',
        '    print(["a"] < ["a", "b"])',
        '    print(["abc"] < ["abd"])',
        # "10" < "9" as TEXT, which is the opposite of the numeric answer --
        # the shape that catches a comparison accidentally going through the
        # decimal-string path the dict key layer uses
        '    print(["10"] < ["9"])',
        "    return 0")),
    ("list-nested", _p(
        "def main() -> Int:",
        "    print([[1]] < [[2]])",
        "    print([[2]] < [[1]])",
        "    print([[1, 2]] < [[1, 3]])",
        '    print([["a"]] < [["b"]])',
        "    print([[1]] < [[1, 2]])",
        "    print([[[1]]] < [[[2]]])",
        "    return 0")),
    # A tuple is a MojoList with a marker, so the two rules are one rule plus
    # the marker: a tuple against a tuple is lexicographic, and a TUPLE against
    # a LIST has no ordering at all (covered in the refusal cases below).
    ("tuple-lexicographic", _p(
        "def main() -> Int:",
        "    print((1, 2) < (1, 3))",
        "    print((1, 3) < (1, 2))",
        "    print((1,) < (1, 2))",
        "    print((2,) > (1, 2))",
        "    print((1, 2) <= (1, 2))",
        '    print(("a", 1) < ("a", 2))',
        '    print(("a", "b") < ("a", "c"))',
        "    return 0")),

    # ── sets: PROPER SUBSET, which is a different rule from the list's ─────
    # `{1,2} < {1,3}` is False and so is `{1,2} < {2,3}`: neither is a subset of
    # the other. This is the case the bug doc singled out as the one the
    # `mojo_set_difference`-emptiness shortcut gets wrong, because it answers
    # "does s1 have something s2 lacks" and says nothing about the other
    # direction -- `s1 > s2` is False for two equal-size proper subsets.
    ("set-subset", _p(
        "def main() -> Int:",
        "    print({1, 2} < {1, 2, 3})",
        "    print({1, 2, 3} > {1, 2})",
        "    print({1, 2} < {1, 2})",
        "    print({1, 2} <= {1, 2})",
        "    print({1, 2} >= {1, 2})",
        "    print({1, 2} < {1, 3})",
        "    print({1, 2} > {1, 3})",
        "    print({1, 2} <= {1, 3})",
        "    print({1, 2} >= {1, 3})",
        "    print({1, 2} < {2, 3})",
        "    print({1, 2} > {2, 3})",
        "    print(set() < {1})",
        "    print(set() <= set())",
        "    print({1, 2, 3, 4} < {1, 2})",
        "    return 0")),
    ("set-elementwise", _p(
        "def main() -> Int:",
        '    print({"a"} < {"a", "b"})',
        '    print({"a"} < {"b"})',
        '    print({"b"} < {"a"})',
        "    print({1} < {1, 2})",
        "    print({1} < {1, 2, 3})",
        "    print({1, 2} < {1, 2, 3})",
        "    return 0")),

    # ── built containers, not literals: the shape a fixed point is written in
    ("built-not-literal", _p(
        "def main() -> Int:",
        "    a = list()",
        "    b = list()",
        "    a.append(1)",
        "    b.append(2)",
        "    print(a < b)",
        "    b.append(1)",
        "    print(a < b)",
        "    s1 = set()",
        "    s2 = set()",
        "    s1.add(1)",
        "    s2.add(1)",
        "    s2.add(2)",
        "    print(s1 < s2)",
        "    print(s1 > s2)",
        "    print(a[:] <= a)",
        "    return 0")),

    # ── erased operands: a container behind an unannotated parameter ───────
    # The cross-function shape, which is a runtime registry dispatch rather
    # than a statically-typed predicate call. One kind per helper because the
    # call-site evidence is required to be UNANIMOUS (a helper called with both
    # a list and a set learns nothing), and because the container literals at
    # the call sites are what supply the evidence at all -- passing LOCAL
    # variables instead leaves the parameter untyped and the comparison falls
    # back to a pointer comparison.
    ("erased-list", _p(
        "def less(a, b):",
        "    if a < b:",
        "        return 1",
        "    return 0",
        "",
        "def main() -> Int:",
        "    print(less([1, 2], [1, 3]))",
        "    print(less([1, 3], [1, 2]))",
        "    print(less([1], [1, 2]))",
        "    print(less([1, 2], [1, 2]))",
        "    return 0")),
    ("erased-list-le", _p(
        "def le(a, b):",
        "    if a <= b:",
        "        return 1",
        "    return 0",
        "",
        "def main() -> Int:",
        "    print(le([1, 2], [1, 3]))",
        "    print(le([1, 2], [1, 2]))",
        "    print(le([1, 3], [1, 2]))",
        "    return 0")),
    ("erased-set", _p(
        "def less(a, b):",
        "    if a < b:",
        "        return 1",
        "    return 0",
        "",
        "def main() -> Int:",
        "    print(less({1, 2}, {1, 2, 3}))",
        "    print(less({1, 2, 3}, {1, 2}))",
        "    print(less({1, 2}, {1, 3}))",
        "    print(less({1, 2}, {1, 2}))",
        "    return 0")),
    # ...and the same question against a container that arrived some other
    # erased way: returned from a call, or read out of a list of containers.
    ("erased-via-return", _p(
        "def mk():",
        "    return [1, 2]",
        "",
        "def less(a, b):",
        "    if a < b:",
        "        return 1",
        "    return 0",
        "",
        "def main() -> Int:",
        "    print(less(mk(), [1, 3]))",
        "    print(less([1, 3], mk()))",
        "    var xs = [mk(), [1, 3]]",
        "    print(less(xs[0], xs[1]))",
        "    return 0")),

    # ── chained comparisons go through the same per-link lowering ──────────
    ("chained", _p(
        "def main() -> Int:",
        "    print([1] < [2] < [3])",
        "    print([1] < [3] < [2])",
        "    print([1] < [2] <= [2])",
        "    print([3] < [2] < [1])",
        "    return 0")),

    # ── sorted() / min() / max() over containers ───────────────────────────
    # Named in the bug doc as part of this bug's surface, because they are the
    # operations whose whole meaning IS an ordering. They lower through their
    # own runtime entry points (mojo_sorted_by_keys etc.) rather than through
    # the comparison lowering, so they were never affected by it — which is
    # exactly why they belong in this file as the "must not change" half.
    ("sorted-min-max", _p(
        "def main() -> Int:",
        "    print(sorted([3, 1, 2]))",
        "    print(sorted([3, 1, 2], reverse=True))",
        "    print(sorted([1, 2]))",
        "    print(sorted({3, 1, 2}))",
        "    print(min([3, 1, 2]))",
        "    print(max([3, 1, 2]))",
        "    print(min({3, 1, 2}))",
        "    print(max({3, 1, 2}))",
        "    print(sorted([2, 1], key=lambda x: -x))",
        "    return 0")),
    # sorted/min/max over a container that reached the call as an argument --
    # the erased shape, where the element type is not statically known at all.
    ("sorted-erased", _p(
        "def lo(xs):",
        "    return min(xs)",
        "",
        "def main() -> Int:",
        "    print(lo([3, 1, 2]))",
        "    print(sorted([3, 1, 2]))",
        "    return 0")),

    # ── what must NOT change ───────────────────────────────────────────────
    # `is` / `is not` are pointer identity in Python and must stay that way;
    # routing them through the value predicates would make `a is b` True for
    # two separately-built lists.
    ("is-is-identity", _p(
        "def main() -> Int:",
        "    a = [1, 2]",
        "    b = [1, 2]",
        "    print(a is b)",
        "    print(a is not b)",
        "    c = a",
        "    print(a is c)",
        "    s1 = {1}",
        "    s2 = {1}",
        "    print(s1 is s2)",
        "    print(s1 < {1, 2})",
        "    return 0")),
    # Scalars, strings and None keep whatever they answered before: `==` on
    # them was never a container comparison, and a wrong answer here would be
    # a much wider blast radius than the one being fixed.
    ("scalar-unchanged", _p(
        "def main() -> Int:",
        "    n = 3",
        "    m = 4",
        "    f = 1.5",
        "    g = 2.5",
        '    s = "ab"',
        '    t = "ac"',
        "    print(n < m)",
        "    print(m < n)",
        "    print(n <= n)",
        "    print(f < g)",
        '    print(s < t)',
        "    print(n < 4)",
        "    return 0")),
    # A string against a string is strcmp and stays strcmp; the ordering
    # comparison must not have captured it.
    ("str-vs-str", _p(
        "def main() -> Int:",
        '    print("a" < "b")',
        '    print("b" < "a")',
        '    print("abc" < "abd")',
        '    print("abc" < "abcd")',
        '    print("10" < "9")',
        "    return 0")),
    # `==` / `!=` between containers are already value equality
    # (test_container_equality.py); this is the "the six operators are one
    # decision" half, checked here so a change to the ordering half cannot
    # quietly break the equality half.
    ("eq-still-value-equality", _p(
        "def main() -> Int:",
        "    print([1, 2] == [1, 2])",
        "    print([1, 2] != [1, 3])",
        "    print({1, 2} == {2, 1})",
        "    print({'x': 1} == {'x': 1})",
        "    print((1, 2) == (1, 2))",
        "    print([1, 2] == (1, 2))",
        "    return 0")),
]

# The REFUSAL cases, kept apart because they have no stdout to compare: their
# reference program raises, and what has to match is the exit status and the
# TypeError text. Each is `(name, source)`, and `_run` below compares
# `TypeError: ...` out of stderr against CPython's own.
REFUSALS = [
    # A dict has no ordering in CPython either, so this is not a limitation of
    # this backend being papered over -- it is CPython's answer, and the text
    # has to match CPython's for a program printing an exception to agree.
    ("refuse-dict-dict", _p(
        "def main() -> Int:",
        '    a = {"x": 1}',
        '    b = {"y": 2}',
        "    print(a < b)",
        "    return 0")),
    ("refuse-dict-le", _p(
        "def main() -> Int:",
        '    a = {"x": 1}',
        '    b = {"y": 2}',
        "    print(a <= b)",
        "    return 0")),
    ("refuse-dict-ge", _p(
        "def main() -> Int:",
        '    a = {"x": 1}',
        '    b = {"y": 2}',
        "    print(a >= b)",
        "    return 0")),
    # A dict against a list, either way round.
    ("refuse-dict-list", _p(
        "def main() -> Int:",
        '    a = {"x": 1}',
        "    b = [1]",
        "    print(a < b)",
        "    return 0")),
    ("refuse-list-dict", _p(
        "def main() -> Int:",
        '    a = {"x": 1}',
        "    b = [1]",
        "    print(b < a)",
        "    return 0")),
    # A container against a non-container. The generic numeric tail would
    # answer these by comparing a pointer against an integer -- a stable,
    # plausible and meaningless verdict -- so each of them is the case where
    # "silently wrong" was available and was not taken.
    ("refuse-list-int", _p(
        "def main() -> Int:",
        "    print([1] < 1)",
        "    return 0")),
    ("refuse-int-list", _p(
        "def main() -> Int:",
        "    print(1 < [1])",
        "    return 0")),
    ("refuse-set-str", _p(
        "def main() -> Int:",
        "    print({1} < 'a')",
        "    return 0")),
    ("refuse-str-list", _p(
        "def main() -> Int:",
        '    print("a" < [1])',
        "    return 0")),
    # Two DIFFERENT container kinds.
    ("refuse-list-set", _p(
        "def main() -> Int:",
        "    print([1] < {1})",
        "    return 0")),
    ("refuse-set-list", _p(
        "def main() -> Int:",
        "    print({1} > [1])",
        "    return 0")),
    # A tuple against a list: both are a MojoList at the C level, so this is
    # the refusal that can only be made from the tuple MARKER, which is what
    # makes it a real test of the mechanism rather than of the static kinds.
    ("refuse-list-tuple", _p(
        "def main() -> Int:",
        "    a = [1, 2]",
        "    print(a < (1, 2))",
        "    return 0")),
    ("refuse-tuple-list", _p(
        "def main() -> Int:",
        "    a = [1, 2]",
        "    print((1, 2) < a)",
        "    return 0")),
    # A list of incompatible element types. CPython compares element by
    # element and refuses at the FIRST pair it cannot order, so the message
    # names the element types and not the container types.
    ("refuse-elem-int-str", _p(
        "def main() -> Int:",
        "    print([1] < ['a'])",
        "    return 0")),
    ("refuse-elem-str-int", _p(
        "def main() -> Int:",
        "    print(['b'] < [1])",
        "    return 0")),
]


def _py_source(src: str) -> str:
    """The same program as CPython sees it: drop the Mojo annotations."""
    out = []
    for line in src.splitlines():
        line = re.sub(r"\bvar\s+", "", line)
        line = re.sub(r"->\s*Int(?!\w)", "", line)
        out.append(line)
    return "\n".join(out) + "\n\nmain()\n"


def run_cpython(src: str, tmp: str, tag: str):
    path = os.path.join(tmp, tag + "_ref.py")
    with open(path, "w") as f:
        f.write(_py_source(src))
    p = subprocess.run([sys.executable, path], capture_output=True, text=True,
                       timeout=60)
    return p.stdout, p.returncode, p.stderr


def run_compiled(src: str, tmp: str, name: str):
    """(stdout, exitcode, stderr) of the compiled program, or raises."""
    from build_config import find_gcc
    from gimple_codegen import compile_to_gimple

    c = compile_to_gimple(src)
    c_file = os.path.join(tmp, name + ".c")
    exe = os.path.join(tmp, name)
    with open(c_file, "w") as f:
        f.write(c)
    sources = [c_file, os.path.join(RUNTIME, "fire_runtime.c")]
    if "__mgco_" in c or "__mojo_coro_yield_i" in c:
        import platform
        arch = ("fire_coro_ctx_aarch64.S"
                if platform.machine().lower() in ("arm64", "aarch64")
                else "fire_coro_ctx_generic.c")
        sources += [os.path.join(RUNTIME, x) for x in
                    ("fire_coro_gen.c", "fire_coro.c", "fire_async_sched.c",
                     arch)]
    r = subprocess.run([find_gcc(), "-fgimple", "-I" + RUNTIME, "-o", exe,
                        *sources], capture_output=True, text=True, timeout=600)
    if r.returncode != 0:
        raise RuntimeError("generated C rejected by gcc -fgimple:\n"
                           + r.stderr[-3000:])
    p = subprocess.run([exe], capture_output=True, text=True, timeout=60)
    return p.stdout, p.returncode, p.stderr


def _type_error_line(stderr: str) -> str:
    """The `TypeError: ...` line out of a traceback, or '' if there is none.

    The compiled runtime prints `Unhandled exception: TypeError: ...` on one
    line and CPython prints the same text inside a traceback, so this matches
    the part both spell identically — which is the part that is the program's
    answer rather than either engine's presentation of it."""
    for line in stderr.splitlines():
        if "TypeError:" in line:
            return line[line.index("TypeError:"):].strip()
    return ""


def _diff(want: str, got: str) -> str:
    wl, gl = want.splitlines(), got.splitlines()
    lines = []
    for i in range(max(len(wl), len(gl))):
        w = wl[i] if i < len(wl) else "<missing>"
        g = gl[i] if i < len(gl) else "<missing>"
        if w != g:
            lines.append("      line %d: cpython %s, compiled %s"
                         % (i + 1, w, g))
    return "\n".join(lines[:12])


def _run_value_case(name: str, src: str, tmp: str, verbose: bool):
    """A case whose answer is stdout. Returns (passed, note)."""
    py_out, py_rc, py_err = run_cpython(src, tmp, name)
    if py_rc != 0 or py_err.strip():
        # A reference program that cannot run makes the case meaningless; say
        # so instead of reporting a phantom failure. This is also the check
        # that keeps a case out of CASES by mistake when CPython REFUSES it --
        # a refusal case belongs in REFUSALS, where the TypeError is the
        # answer being diffed rather than a broken reference.
        return False, ("BROKEN: the reference program does not run under "
                       "CPython:\n" + py_err[-800:])
    try:
        c_out, c_rc, c_err = run_compiled(src, tmp, name)
    except Exception as e:                                   # noqa: BLE001
        return False, str(e)
    if (c_out, c_rc) == (py_out, py_rc):
        return True, "%d line(s)" % len(py_out.splitlines())
    note = "compiled answer differs from CPython's"
    if c_rc != py_rc:
        note += " (exit %d vs %d)" % (c_rc, py_rc)
    te = _type_error_line(c_err)
    if te:
        note += "\n      compiled raised: %s" % te
    return False, note + "\n" + _diff(py_out, c_out)


def _run_refusal_case(name: str, src: str, tmp: str):
    """A case whose answer IS the refusal. Returns (passed, note).

    Three things have to agree: CPython refuses (otherwise the case is not
    testing a refusal), the compiled program refuses (rather than answering
    something), and the TypeError TEXT matches — the last because a program that
    prints an exception message would print the wrong one."""
    py_out, py_rc, py_err = run_cpython(src, tmp, name)
    py_te = _type_error_line(py_err)
    if py_rc == 0 or not py_te:
        return False, ("BROKEN: CPython does not refuse this program "
                       "(rc=%d, stderr=%r) — it is not a refusal case"
                       % (py_rc, py_err[-300:]))
    try:
        c_out, c_rc, c_err = run_compiled(src, tmp, name)
    except Exception as e:                                   # noqa: BLE001
        return False, str(e)
    c_te = _type_error_line(c_err)
    if not c_te:
        return False, ("the compiled program did NOT raise; it answered "
                       "rc=%d stdout=%r — a refusal became a verdict"
                       % (c_rc, c_out.strip()[:200]))
    if c_rc == 0:
        return False, ("the compiled program raised but exited 0 (CPython "
                       "exits %d)" % py_rc)
    if c_te == py_te:
        return True, c_te
    return False, ("the TypeError text differs\n      cpython:   %s\n"
                   "      compiled: %s" % (py_te, c_te))


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("-v", "--verbose", action="store_true",
                    help="print every case, not just failures")
    ap.add_argument("--keep", action="store_true",
                    help="keep the generated C and binaries")
    args = ap.parse_args()

    tmp = tempfile.mkdtemp(prefix="ordtest-", dir=HERE)
    passed = failed = 0
    try:
        for name, src in CASES:
            ok, note = _run_value_case(name, src, tmp, args.verbose)
            passed += ok
            failed += not ok
            if not ok or args.verbose:
                print("%-6s %-28s %s" % ("PASS" if ok else "FAIL", name, note))
        for name, src in REFUSALS:
            ok, note = _run_refusal_case(name, src, tmp)
            passed += ok
            failed += not ok
            if not ok or args.verbose:
                print("%-6s %-28s %s" % ("PASS" if ok else "FAIL", name, note))
        total = len(CASES) + len(REFUSALS)
        if args.keep:
            print("kept: %s" % tmp)
            tmp = None
    finally:
        if tmp is not None:
            for f in os.listdir(tmp):
                os.unlink(os.path.join(tmp, f))
            os.rmdir(tmp)

    print("PASS=%d FAIL=%d of %d" % (passed, failed, total))
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())