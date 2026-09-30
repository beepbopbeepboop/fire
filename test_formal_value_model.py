#!/usr/bin/env python3
"""The formal value model's shapes, measured against CPython rather than pinned.

Two families, both of which were wrong on at least one of the two architectures
and neither of which any existing suite could see:

  * `a == b` did not reach the struct's OWN `__eq__`.  On two struct receivers it
    was one flag-setting compare of two WORDS, and for a multi-field struct a
    word is the ADDRESS of a frame of 8-byte slots — so the operator answered
    "are these the same object", which is CPython's INHERITED `__eq__` and is
    correct for a struct that declares none, and a silent bypass of the one it
    does.  The method was found, called and ignored: a class whose `__eq__`
    returned unconditionally True gave `eq=0 direct=1` against CPython's
    `eq=1 direct=1`, so a program took the wrong branch and said nothing about
    it, on both architectures.
  * `h.a, h.b = x, y` was refused on x86-64 while arm64 lowered it, which is the
    one thing two architectures of one language implementation are not allowed to
    do about a legitimate program.  See `TUPLE_STORE_CASES`.

    python3 test_formal_value_model.py [-v] [case ...]

**Why this file exists separately from `test_formal_run.py`**, which also builds
and runs and also covers these programs with fixed expected values: this one
holds no expectations of its own.  It derives the CPython program from the SAME
text, runs it, and requires the image's stdout and exit status to be identical —
so a case cannot be pinned to a value that was wrong in the first place, which is
exactly the failure mode of the bugs it guards (a hardcoded `1` where the source
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
#
# ── the comparison dunders ──
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

# ── the tuple-store target shapes ──
#
# `a, b = rhs` is one construct with four target shapes, and the two
# architectures used to disagree about two of them.  arm64's `_tup_slot` already
# routed a `MemberExpr` element through `_store_var`, which is the frame-slot
# store; x86-64's `_emit_tuple_assign` built a list of NAMES and refused anything
# that was not one, so `h.x, h.y = p, q` was refused by name on x86-64 and
# answered correctly on arm64.  The fix is that the target element becomes
# whatever `_store_var` can store into — the same store, through the same
# function, so a tuple unpack and a plain `h.x = v` cannot disagree about where a
# field's value lands.
TUPLE_STORE_CASES = [
    # A receiver-relative field target OUTSIDE any constructor, which is the
    # reproducer the filing used and the shape `_store_var`'s frame-slot arm is
    # for.  Three targets so an off-by-one in the element pairing would show: the
    # answer is 3 + 4 + 7 and nothing else.
    ("tuple_store_to_receiver_fields",
     "class Tail:\n"
     "    x: int\n"
     "    y: int\n"
     "    z: int\n"
     "    def __init__(self):\n"
     "        self.x = 0\n"
     "        self.y = 0\n"
     "        self.z = 0\n"
     "    def total(self):\n"
     "        return self.x + self.y + self.z\n"
     "def main(n):\n"
     "    var t = Tail()\n"
     "    t.x, t.y, t.z = 3, 4, 7\n"
     "    printf(\"total=%d\", t.total())\n"
     "    return 0\n",
     "total=14"),
    # The same statement with `self` as the receiver, which is the spelling in
    # this repository's own code (`tools/procrun.py` has
    # `self.limit, self._chunks, self._size = limit, [], 0`) and which reaches a
    # DIFFERENT store: the method's own receiver frame rather than a local
    # holder's.  Pair it with a field target on a local too, so a pass that
    # handled only one of the two receiver shapes would answer one and not the
    # other.
    ("tuple_store_to_self_and_to_a_local",
     "class Pair:\n"
     "    x: int\n"
     "    y: int\n"
     "    def __init__(self, p, q):\n"
     "        self.x = p\n"
     "        self.y = q\n"
     "    def swap(self, p, q):\n"
     "        self.x, self.y = p, q\n"
     "    def total(self):\n"
     "        return self.x + self.y\n"
     "def main(n):\n"
     "    var a = Pair(1, 2)\n"
     "    a.swap(9, 8)\n"
     "    var b = Pair(0, 0)\n"
     "    b.x, b.y = 5, 6\n"
     "    printf(\"a=%d b=%d\", a.total(), b.total())\n"
     "    return 0\n",
     "a=17 b=11"),
    # A MIXED target: one field and one plain name.  The two shapes have
    # different homes (a frame slot and a register) and the pairing has to hold
    # across them, which is the case that would catch a rewrite that turned every
    # element into a field store.
    ("tuple_store_mixes_a_field_and_a_name",
     "class Pair:\n"
     "    x: int\n"
     "    y: int\n"
     "    def __init__(self, p, q):\n"
     "        self.x = p\n"
     "        self.y = q\n"
     "    def total(self):\n"
     "        return self.x + self.y\n"
     "def main(n):\n"
     "    var a = Pair(0, 0)\n"
     "    var b = 0\n"
     "    a.x, b = 7, 8\n"
     "    printf(\"a=%d b=%d\", a.total(), b)\n"
     "    return 0\n",
     "a=7 b=8"),
    # A NESTED group, which is the third shape and the one that was silently
    # miscounted rather than refused: x86-64 flattened it, so the outer arity
    # check compared the RHS blob's count (2) against a target count that
    # included the group's own elements (3) and the image exited(1) with nothing
    # printed — where arm64 and CPython both answer a=1 b=2 c=3.  Now the group
    # is a second unpack against the element at its position, and the arity
    # check at each level counts that level's elements and no other.
    ("tuple_store_to_a_nested_group",
     "def main(n):\n"
     "    var a = 0\n"
     "    var b = 0\n"
     "    var c = 0\n"
     "    a, (b, c) = 1, (2, 3)\n"
     "    printf(\"a=%d b=%d c=%d\", a, b, c)\n"
     "    return 0\n",
     "a=1 b=2 c=3"),
]

# ── what a holder MAY be assigned, which is what the refusal above is about ──
#
# The check exists because a name that holds a frame address is never removed
# from the holder set, so a later store of a plain word leaves every field access
# through it reading `[word + 8·slot]`.  These three are the shapes that must
# keep working, and each is one of the three the refusal names: a CONSTRUCTION
# under a branch (a frame the analysis cannot see the path to, so it must be
# accepted on both paths), a COPY under a different name, and a field write
# through a method's own `self` — which is a `self.x` store and not a rebinding
# of `self`, and is the shape a too-eager check would break first.
HOLDER_ASSIGN_CASES = [
    ("holder_may_be_construction_copy_and_self_write",
     "class R:\n"
     "    def __init__(self, v):\n"
     "        self.a = v\n"
     "        self.b = 0\n"
     "    def get(self):\n"
     "        return self.a\n"
     "    def swap(self, other):\n"
     "        self.a = other.a\n"
     "        self.b = other.b\n"
     "    def total(self):\n"
     "        return self.a + self.b\n"
     "\n"
     "def pick(r, n):\n"
     "    if n:\n"
     "        var r2 = R(9)\n"
     "        return r2.get()\n"
     "    return r.get()\n"
     "\n"
     "def main(n):\n"
     "    var r = R(7)\n"
     "    var s = R(3)\n"
     "    t = s\n"
     "    r.swap(s)\n"
     "    printf(\"a=%d b=%d c=%d\", pick(r, n), t.get(), r.total())\n"
     "    return 0\n",
     "a=9 b=3 c=3"),
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
    # A NAME THAT STOPS BEING A FRAME.  The holder set is additive — nothing
    # ever removes a name from it — so `r = 5` after `r = R()` leaves every
    # `r.<field>` lowered as a load at `[5 + 8·slot]`.  Measured on both
    # architectures from a green build: SIGSEGV, exit 139, where the source says
    # 5.  Refused, by name, with the binding that disagrees in the message.
    #
    # The CONDITIONAL form is in the same case on purpose: `if n: r = 5` is the
    # same finding, because the analysis has no path sensitivity and the whole
    # refusal family rests on that rather than on it.
    ("holder_rebound_from_a_word_is_refused",
     "class R:\n"
     "    def __init__(self):\n"
     "        self.a = 0\n"
     "        self.b = 0\n"
     "def main(n):\n"
     "    var r = R()\n"
     "    r.a = 7\n"
     "    r = 5\n"
     "    printf(\"a=%d\", r.a)\n"
     "    return 0\n",
     "r is assigned 5 in main()"),
    ("holder_rebound_under_a_condition_is_refused",
     "class R:\n"
     "    def __init__(self):\n"
     "        self.a = 0\n"
     "        self.b = 0\n"
     "def main(n):\n"
     "    var r = R()\n"
     "    r.a = 7\n"
     "    if n:\n"
     "        r = 5\n"
     "    printf(\"a=%d\", r.a)\n"
     "    return 0\n",
     "r is assigned 5 in main()"),
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

    everything = ([(c, False) for c in CASES]
                  + [(c, False) for c in TUPLE_STORE_CASES]
                  + [(c, False) for c in HOLDER_ASSIGN_CASES]
                  + [(c, True) for c in REFUSALS])
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

    print(f"\nformal value model: PASS={passed} FAIL={failed}")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
