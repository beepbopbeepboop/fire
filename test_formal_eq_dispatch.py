#!/usr/bin/env python3
"""`a == b` must reach the struct's OWN `__eq__` — measured against CPython.

`a == b` on two struct receivers was one flag-setting compare of two WORDS, and
for a multi-field struct a word is the ADDRESS of a frame of 8-byte slots.  So
the operator answered "are these the same object", which is CPython's INHERITED
`__eq__` and is correct for a struct that declares none — and completely bypassed
the one a struct DOES declare.  The method was found, called and ignored: a
class whose `__eq__` returned unconditionally True gave `eq=0 direct=1` against
CPython's `eq=1 direct=1`, so a program took the wrong branch and said nothing
about it, on both architectures.

    python3 test_formal_eq_dispatch.py [-v] [case ...]

**Why this file exists separately from `test_formal_run.py`**, which also builds
and runs and also covers these programs with fixed expected values: this one
holds no expectations of its own.  It derives the CPython program from the SAME
text, runs it, and requires the image's stdout and exit status to be identical —
so a case cannot be pinned to a value that was wrong in the first place, which is
exactly the failure mode of the bug it guards (a hardcoded `1` where the source
says `1` and the image says `0` reads as a regression in the image, not as the
pre-existing wrong answer it is).  The split is the one `test_runtime_diff.py`
and `test_interp_oracle.py` already make: fixed expectations in the suite that
gates every commit, an oracle in a file that is run when the construct changes.

The `printf` shim is the one line that makes the two texts runnable by both
engines, and it is deliberately `sys.stdout.write(fmt % a)` rather than
`print`: this backend's string literals do not process `\\n` (measured — a
`printf("A[%d]\\n", 7)` image writes a literal backslash and an `n`, 12 bytes,
no newline), so a format string carrying an escape would make the two engines
disagree about bytes that have nothing to do with the construct under test.
Every case here prints one line with no escape in it, and the two outputs are
compared byte for byte, exit status included.
"""
import argparse
import os
import platform
import re
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
FIRE = os.path.join(HERE, "fire.py")
BUILD_TIMEOUT = 180
RUN_TIMEOUT = 60

# The CPython translation of a case: a `printf` shim, the same text with the
# `var` declaration keyword dropped (fire_compiler parses both spellings and
# CPython only one), and the call that starts `main`.
_SHIM = ("import sys\n"
         "def printf(fmt, *a):\n"
         "    sys.stdout.write(fmt % a)\n")
_VAR = re.compile(r"^(\s*)var (\w)", re.M)


def cpython_source(source: str) -> str:
    return _SHIM + _VAR.sub(r"\1\2", source) + "\nsys.exit(main(1))\n"


# (name, source, expected stdout)
#
# `expected` is what CPython prints, and it is asserted against CPython as well
# as against both images: a case whose expectation does not match CPython is a
# case whose expectation is wrong, and saying so is more useful than reporting
# the image.
CASES = [
    # THE REPRODUCER.  A class whose `__eq__` ignores its argument, compared
    # through the operator and through the explicit spelling, in one printf: the
    # two numbers are the same question asked twice and CPython makes them equal.
    ("operator_reaches_a_declared_eq",
     "class Plain:\n"
     "    x: int\n"
     "    y: int\n"
     "    def __init__(self, p, q):\n"
     "        self.x = p\n"
     "        self.y = q\n"
     "    def __eq__(self, other):\n"
     "        return True\n"
     "\n"
     "def eq(a, b):\n"
     "    if a == b:\n"
     "        return 1\n"
     "    return 0\n"
     "\n"
     "def main(n):\n"
     "    var a = Plain(1, 2)\n"
     "    var b = Plain(3, 4)\n"
     "    printf(\"eq=%d direct=%d\", eq(a, b), 1 if a.__eq__(b) else 0)\n"
     "    return 0\n",
     "eq=1 direct=1"),
    # `!=` is the SECOND spelling of one question, and the language reaches it
    # through `__ne__` when there is one and through the negation of `__eq__`
    # when there is not.  Both halves, because "reached through `__eq__`" and
    # "reached through `__ne__`" are different callables and a rewrite that
    # spelled the callee from the operator would call the wrong one for `HasNe`.
    ("ne_prefers_a_declared_ne_and_negates_a_declared_eq",
     "class Yes:\n"
     "    x: int\n"
     "    y: int\n"
     "    def __init__(self, p, q):\n"
     "        self.x = p\n"
     "        self.y = q\n"
     "    def __eq__(self, other):\n"
     "        return True\n"
     "\n"
     "class HasNe:\n"
     "    x: int\n"
     "    y: int\n"
     "    def __init__(self, p, q):\n"
     "        self.x = p\n"
     "        self.y = q\n"
     "    def __eq__(self, other):\n"
     "        return True\n"
     "    def __ne__(self, other):\n"
     "        return False\n"
     "\n"
     "def main(n):\n"
     "    var a = Yes(1, 2)\n"
     "    var b = Yes(3, 4)\n"
     "    var c = HasNe(1, 2)\n"
     "    var d = HasNe(3, 4)\n"
     "    printf(\"eq=%d ne=%d hne=%d same=%d\",\n"
     "           1 if a == b else 0, 1 if a != b else 0,\n"
     "           1 if c != d else 0, 1 if a == a else 0)\n"
     "    return 0\n",
     "eq=1 ne=0 hne=0 same=1"),
    # THE GUARD, and it is the direction the fix must NOT move: a struct that
    # declares no `__eq__` keeps CPython's INHERITED identity comparison, which
    # on this path is the address compare that was always there.  `a == a` is
    # True, `a == b` is False for two live objects (their frames are at
    # different addresses), and `a == c` is False for two objects that hold the
    # same field values — which is what Python says too, and what a
    # field-wise `__eq__` would get wrong.  A rewrite that fired on every
    # comparison rather than on a declared dunder would break all three.
    ("no_declared_eq_stays_an_identity_compare",
     "class Bare:\n"
     "    x: int\n"
     "    y: int\n"
     "    def __init__(self, p, q):\n"
     "        self.x = p\n"
     "        self.y = q\n"
     "\n"
     "def main(n):\n"
     "    var a = Bare(1, 2)\n"
     "    var b = Bare(3, 4)\n"
     "    var c = Bare(1, 2)\n"
     "    printf(\"same=%d diff=%d cross=%d\",\n"
     "           1 if a == a else 0, 1 if a == b else 0, 1 if a == c else 0)\n"
     "    return 0\n",
     "same=1 diff=0 cross=0"),
    # A CHAIN is one `CompareChain` in the AST and `a AND b AND c` in the
    # language, so it lowers as the `and` of its pairwise comparisons and
    # short-circuits on the first false one.  It also needs the SECOND
    # parameter of the dunder to be a frame the method can read a field
    # through: `self.x == other.x` is the reason an equality method exists, and
    # it was refused by name ("`other.x` is a field access through `other`")
    # until the rewritten call's argument was followed into the callee's
    # parameter list by the holder fixpoint.
    ("chain_of_two_comparisons",
     "class Tri:\n"
     "    x: int\n"
     "    y: int\n"
     "    z: int\n"
     "    def __init__(self, p, q, r):\n"
     "        self.x = p\n"
     "        self.y = q\n"
     "        self.z = r\n"
     "    def __eq__(self, other):\n"
     "        return self.x == other.x\n"
     "\n"
     "def main(n):\n"
     "    var a = Tri(1, 2, 3)\n"
     "    var b = Tri(1, 5, 6)\n"
     "    var c = Tri(9, 5, 6)\n"
     "    printf(\"chain=%d same=%d\", 1 if a == b == c else 0, 1 if a == a else 0)\n"
     "    return 0\n",
     "chain=0 same=1"),
    # The `__eq__` RESULT is a value, and it has to survive being stored,
    # returned and tested — the three positions a rewritten call can land in.
    # A rewrite that produced a boolean only in a condition would pass every
    # case above and fail this one.
    ("the_result_is_an_ordinary_value",
     "class Flag:\n"
     "    x: int\n"
     "    y: int\n"
     "    def __init__(self, p, q):\n"
     "        self.x = p\n"
     "        self.y = q\n"
     "    def __eq__(self, other):\n"
     "        return self.x < other.x\n"
     "\n"
     "def is_less(a, b):\n"
     "    return 1 if a == b else 0\n"
     "\n"
     "def main(n):\n"
     "    var a = Flag(1, 2)\n"
     "    var b = Flag(9, 9)\n"
     "    var r = is_less(a, b)\n"
     "    printf(\"r=%d back=%d\", r, 1 if is_less(b, a) else 0)\n"
     "    return 7\n",
     "r=1 back=0"),
]

# (name, source, needle the refusal must contain)
#
# AGREE-OR-REFUSE, and both of these are the shape the rule exists for: the
# name holds a different frame on each path that binds it, and only ONE of the
# candidates declares a dunder, so which call the comparison lowers to depends
# on the path and this analysis has no path sensitivity.  The pre-change tree
# answered both of them with a flag-setting compare of two addresses and no
# diagnostic — and for `cross_struct` that was a wrong answer, because CPython
# asks the RIGHT operand's `__eq__` when the left one's returns NotImplemented,
# and this path has no representation for NotImplemented to be returned as.
REFUSALS = [
    ("one_name_two_candidate_structs_is_refused",
     "class A:\n"
     "    x: int\n"
     "    y: int\n"
     "    def __init__(self, p, q):\n"
     "        self.x = p\n"
     "        self.y = q\n"
     "\n"
     "class B:\n"
     "    x: int\n"
     "    y: int\n"
     "    z: int\n"
     "    def __init__(self, p, q, r):\n"
     "        self.x = p\n"
     "        self.y = q\n"
     "        self.z = r\n"
     "    def __eq__(self, other):\n"
     "        return True\n"
     "\n"
     "def main(n):\n"
     "    var v = A(1, 2)\n"
     "    if n:\n"
     "        v = B(1, 2, 3)\n"
     "    printf(\"r=%d\", 1 if v == v else 0)\n"
     "    return 0\n",
     "compares two FRAME ADDRESSES"),
    ("two_structs_only_one_with_a_dunder_is_refused",
     "class A:\n"
     "    x: int\n"
     "    y: int\n"
     "    def __init__(self, p, q):\n"
     "        self.x = p\n"
     "        self.y = q\n"
     "\n"
     "class B:\n"
     "    x: int\n"
     "    y: int\n"
     "    z: int\n"
     "    def __init__(self, p, q, r):\n"
     "        self.x = p\n"
     "        self.y = q\n"
     "        self.z = r\n"
     "    def __eq__(self, other):\n"
     "        return True\n"
     "\n"
     "def main(n):\n"
     "    var a = A(1, 2)\n"
     "    var b = B(1, 2, 3)\n"
     "    printf(\"r=%d\", 1 if a == b else 0)\n"
     "    return 0\n",
     "does not settle it"),
]


def run_cpython(source, tmpdir, verbose):
    path = os.path.join(tmpdir, "oracle.py")
    with open(path, "w") as f:
        f.write(cpython_source(source))
    proc = subprocess.run([sys.executable, path], capture_output=True,
                          text=True, timeout=RUN_TIMEOUT)
    if verbose:
        print(f"      cpython: {proc.stdout!r} exit={proc.returncode}"
              + (f" stderr={proc.stderr.strip()[:200]}" if proc.stderr else ""))
    return proc.returncode, proc.stdout


def build_formal(src, out, backend):
    proc = subprocess.run(
        [sys.executable, FIRE, "build", "--formal", "--no-prove",
         f"--backend={backend}", "-o", out, src],
        capture_output=True, text=True, timeout=BUILD_TIMEOUT, cwd=HERE)
    return proc.returncode, (proc.stdout + proc.stderr)


def run_case(name, source, want_stdout, tmpdir, verbose):
    src = os.path.join(tmpdir, name + ".mojo")
    with open(src, "w") as f:
        f.write(source)
    want_exit, want_out = run_cpython(source, tmpdir, verbose)
    if want_out != want_stdout:
        return False, (f"the case's own expectation ({want_stdout!r}) is not "
                       f"what CPython prints ({want_out!r}); the expectation is "
                       f"the wrong half, not the image")
    for backend in ("arm64", "x86_64"):
        exe = os.path.join(tmpdir, f"{name}.{backend}")
        rc, text = build_formal(src, exe, backend)
        if rc != 0:
            return False, f"--backend={backend} refused: {text.strip()[-300:]}"
        proc = subprocess.run([exe], capture_output=True, text=True,
                              timeout=RUN_TIMEOUT)
        if proc.stdout != want_out or proc.returncode != want_exit:
            return False, (
                f"--backend={backend} answered {proc.stdout!r} exit="
                f"{proc.returncode} where CPython answers {want_out!r} exit="
                f"{want_exit}"
                + (f" (stderr {proc.stderr.strip()[:160]})" if proc.stderr
                   else ""))
        if verbose:
            print(f"      {backend}: {proc.stdout!r} exit={proc.returncode}")
    return True, ""


def run_refusal(name, source, needle, tmpdir, verbose):
    src = os.path.join(tmpdir, name + ".mojo")
    with open(src, "w") as f:
        f.write(source)
    for backend in ("arm64", "x86_64"):
        exe = os.path.join(tmpdir, f"{name}.{backend}")
        rc, text = build_formal(src, exe, backend)
        if rc == 0:
            return False, (f"--backend={backend} BUILT a comparison whose "
                           f"answer depends on which of two structs the name "
                           f"holds at run time; the binary is the real answer "
                           f"here")
        if needle not in text:
            return False, (f"--backend={backend} refused, but not naming "
                           f"{needle!r}: {text.strip()[-300:]}")
    if verbose:
        print(f"      refused identically on both architectures, naming "
              f"{needle!r}")
    return True, ""


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("-v", "--verbose", action="store_true")
    ap.add_argument("cases", nargs="*", help="subset of case names")
    args = ap.parse_args()

    if platform.machine() not in ("arm64", "aarch64"):
        print(f"SKIP: formal output is arm64-only, host is "
              f"{platform.machine()}")
        return 0

    everything = [(c, False) for c in CASES] + [(c, True) for c in REFUSALS]
    selected = [c for c in everything if not args.cases or c[0][0] in args.cases]
    known = {c[0][0] for c in everything}
    if args.cases and len(selected) != len(args.cases):
        print(f"ERROR: unknown case(s): "
              f"{sorted(set(args.cases) - known)}", file=sys.stderr)
        return 2

    passed = failed = 0
    with tempfile.TemporaryDirectory() as tmpdir:
        for entry, is_refusal in selected:
            try:
                if is_refusal:
                    ok, detail = run_refusal(entry[0], entry[1], entry[2],
                                             tmpdir, args.verbose)
                else:
                    ok, detail = run_case(entry[0], entry[1], entry[2], tmpdir,
                                          args.verbose)
            except subprocess.TimeoutExpired:
                ok, detail = False, "timed out"
            except Exception as e:  # unexpected: report, do not mask
                ok, detail = False, f"{type(e).__name__}: {e}"
                if args.verbose:
                    import traceback
                    traceback.print_exc()
            if ok:
                passed += 1
                print(f"  PASS  {entry[0]}")
            else:
                failed += 1
                print(f"  FAIL  {entry[0]}: {detail}")

    print(f"\nformal eq dispatch: PASS={passed} FAIL={failed}")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
