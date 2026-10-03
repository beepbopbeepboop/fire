#!/usr/bin/env python3
"""`len(x)` where `x` is a struct FRAME ADDRESS: it is `x.__len__()`.

The 35-file sweep finding, tested.  Every case here is a differential one: the
same program is written twice, once as Mojo and once as plain Python, and the
two are made to AGREE rather than the expectation being written by hand.  That
is the discipline `test_interp_oracle.py` established for the other engine and
it applies here for the reason `CLAUDE.md` gives — a hand-written expected value
is a second implementation of the question, and two implementations that were
written from the same reading agree on the cases nobody thought about.

    python3 test_formal_frame_len.py [-v] [case ...]

WHAT THE CONSTRUCT IS.  A struct of more than one field has a FRAME for its
receiver on this path (`formal/model.py`'s `struct_is_framed`): the receiver word
is the ADDRESS of a block of 8-byte slots, one per field, in declaration order.
So `len(h)` cannot be the count-word load `len` is for a blob, and it cannot be
`strlen` — the slot at offset 0 is the struct's FIRST FIELD, so a count-field
read produces a plausible number meaning nothing.  It is `h.__len__()`, a method
of the receiver's OWN struct, which is the one hand-off a frame address makes and
which `formal/build.py` rewrites to an ordinary call whose first argument is the
address.

WHY A REWRITE AND NOT A NEW LOWERING, which is the design decision this file is
really about.  `h.__len__()` was already lowered, by
`build._rewrite_method_calls`, to `Struct___len__(h)` — and that is why the
change is small.  Two spellings of one question going through two implementations
is the defect the last three waves of this backend keep finding (`_emit_binop` vs
`_emit_branch_unless`; the two backends' private copies of the `len` decision).
So there is exactly one lowering, it is the one that was already there, and what
was added is the knowledge of WHICH `__len__` — a decision in
`model.struct_dunder_len_candidates`, shared by every reader.

WHY THE HOST IS arm64-ONLY BUT BOTH BACKENDS ARE BUILT.  The host is arm64
(macOS), so an x86-64 image runs under Rosetta and an arm64 one does not need
anything; every non-refusal case is therefore built AND EXECUTED for BOTH
architectures and both answers are compared against CPython's.  A case that
passed on one architecture only would be exactly the class of bug this suite
exists for.

WHAT IS DELIBERATELY NOT HERE.  A frame address in a `__len__` RETURN, in a
container, or through a subscript: those are refused by name and are a different
family (`formal/build.py`'s `_check_frame_escapes` and the three refusals it
raises).
"""
import argparse
import os
import platform
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
FIRE = os.path.join(HERE, "fire.py")
BUILD_TIMEOUT = 180
RUN_TIMEOUT = 60
BACKENDS = ("arm64", "x86_64")

# ── the differential cases ──────────────────────────────────────────────────
#
# (name, mojo_source, python_source)
#
# Every python_source is the SAME program with `struct` spelled as a class, and
# it must produce byte-identical stdout under CPython.  `printf` is used for the
# Mojo side rather than the exit status because a process exit status is a byte
# on this host and every answer here is bigger than 255 in some case; a stdout
# comparison has no such cap and is the stronger assertion.
DIFF_CASES = [
    # THE TERMINAL CONSTRUCT, in miniature.  `len(c)` on a `Counter` frame, the
    # same call `std/collections/binary_heap.mojo` makes four times on
    # `len(self)`, before it moved to a `List[...] has no home` refusal.
    #
    # `c.add(4)` is the half that makes this a real test rather than a
    # demonstration: `__len__` reads `self.n` through the address it was handed,
    # and `add` WROTE that slot.  A copy of the frame rather than its address
    # would still read 3 here — a wrong-address lowering that this case cannot
    # tell from a right one is the failure mode, and the write is what tells
    # them apart.
    ("len_frame_calls_the_struct_dunder_len",
     "struct Counter:\n"
     "    var n: Int\n"
     "    var limit: Int\n"
     "    def __len__(self) -> Int:\n"
     "        return self.n\n"
     "    def add(mut self, v: Int):\n"
     "        self.n = self.n + v\n"
     "    def scaled(self, k: Int) -> Int:\n"
     "        return len(self) * k\n"
     "\n"
     "def main(k: Int) -> Int:\n"
     "    var c = Counter()\n"
     "    c.n = 3\n"
     "    c.limit = 9\n"
     "    c.add(4)\n"
     '    printf("a=%d b=%d c=%d", len(c), c.scaled(3), c.__len__())\n'
     "    return 0\n",
     "class Counter:\n"
     "    def __init__(self):\n"
     "        self.n = 3\n"
     "        self.limit = 9\n"
     "    def __len__(self):\n"
     "        return self.n\n"
     "    def add(self, v):\n"
     "        self.n = self.n + v\n"
     "    def scaled(self, k):\n"
     "        return len(self) * k\n"
     "\n"
     "def main():\n"
     "    c = Counter()\n"
     "    c.add(4)\n"
     '    print("a=%d b=%d c=%d" % (len(c), c.scaled(3), c.__len__()), end="")\n'
     "    return 0\n"
     "\n"
     "main()\n"),

    # THE FRAME CROSSES AN ACTIVATION, which is the claim the whole design rests
    # on and the one a same-function test cannot make.  `fill` is a PLAIN
    # function that receives the frame as its first parameter — the holder
    # fixpoint is what makes `c` a frame in it — and it WRITES through the
    # address.  So both directions of the hand-off are exercised in one program:
    # the write proves the word is the caller's frame rather than a copy, and
    # the `len` afterwards reads through it.
    ("len_frame_written_from_another_activation",
     "struct Counter:\n"
     "    var n: Int\n"
     "    var limit: Int\n"
     "    def __len__(self) -> Int:\n"
     "        return self.n\n"
     "    def add(mut self, v: Int):\n"
     "        self.n = self.n + v\n"
     "    def scaled(self, k: Int) -> Int:\n"
     "        return len(self) * k\n"
     "\n"
     "def fill(c: Counter):\n"
     "    c.n = 7\n"
     "    c.limit = 5\n"
     "\n"
     "def main(k: Int) -> Int:\n"
     "    var c = Counter()\n"
     "    c.n = 3\n"
     "    c.limit = 9\n"
     "    fill(c)\n"
     "    c.add(1)\n"
     '    printf("a=%d b=%d", len(c), c.scaled(3))\n'
     "    return 0\n",
     "class Counter:\n"
     "    def __init__(self, n, limit):\n"
     "        self.n = n\n"
     "        self.limit = limit\n"
     "    def __len__(self):\n"
     "        return self.n\n"
     "    def add(self, v):\n"
     "        self.n = self.n + v\n"
     "    def scaled(self, k):\n"
     "        return len(self) * k\n"
     "\n"
     "def fill(c):\n"
     "    c.n = 7\n"
     "    c.limit = 5\n"
     "\n"
     "def main():\n"
     "    c = Counter(3, 9)\n"
     "    fill(c)\n"
     "    c.add(1)\n"
     '    print("a=%d b=%d" % (len(c), c.scaled(3)), end="")\n'
     "    return 0\n"
     "\n"
     "main()\n"),

    # THE CREATOR IS ONE FRAME DEEPER, which is the case that would catch a
    # LIFETIME error rather than a missing slot table.  `main` holds the frame and
    # `ask` — two calls deep — is where `len` is read.  If the analysis reasoned
    # "the frame belongs to the function that made it and this one did not, so it
    # must be gone", the read would be of reclaimed stack and the answer would be
    # whatever those bytes hold now.  This is the use-after-free guard, and it is
    # the case `test_formal_returned_frame.py` argues for in general
    # terms and nobody had measured for this construct.
    ("len_frame_creator_one_frame_deeper",
     "struct Counter:\n"
     "    var n: Int\n"
     "    var limit: Int\n"
     "    def __len__(self) -> Int:\n"
     "        return self.n\n"
     "\n"
     "def ask(c: Counter) -> Int:\n"
     "    return len(c) * 10\n"
     "\n"
     "def mid(c: Counter) -> Int:\n"
     "    return ask(c) + 1\n"
     "\n"
     "def main(k: Int) -> Int:\n"
     "    var c = Counter()\n"
     "    c.n = 3\n"
     "    c.limit = 9\n"
     '    printf("a=%d", mid(c))\n'
     "    return 0\n",
     "class Counter:\n"
     "    def __init__(self):\n"
     "        self.n = 3\n"
     "        self.limit = 9\n"
     "    def __len__(self):\n"
     "        return self.n\n"
     "\n"
     "def ask(c):\n"
     "    return len(c) * 10\n"
     "\n"
     "def mid(c):\n"
     "    return ask(c) + 1\n"
     "\n"
     "def main():\n"
     "    c = Counter()\n"
     '    print("a=%d" % mid(c), end="")\n'
     "    return 0\n"
     "\n"
     "main()\n"),

    # NESTED POSITIONS, because `len(self)` in the corpus is never the whole
    # expression: it is `len(self) - 1`, `len(self) > 0` inside an assert, and
    # `printf("...", len(self))`.  A rewrite that only handled the bare
    # whole-expression shape would pass the cases above and fail on every one of
    # these, which is why they are here as one case rather than three.
    #
    # The `printf` arm is also the one that would expose a register-clobbering
    # bug: the rewritten call has to leave its answer in the result register and
    # return from the method for the following arithmetic to be right.
    ("len_frame_in_nested_positions",
     "struct Bag:\n"
     "    var n: Int\n"
     "    var tag: Int\n"
     "    def __len__(self) -> Int:\n"
     "        return self.n\n"
     "    def describe(self) -> Int:\n"
     "        if len(self) > 4:\n"
     "            return len(self) - 4\n"
     "        return 0\n"
     "    def shown(self) -> Int:\n"
     '        printf("len=%d ", len(self))\n'
     "        return len(self)\n"
     "\n"
     "def main(k: Int) -> Int:\n"
     "    var b = Bag()\n"
     "    b.n = 6\n"
     "    b.tag = 0\n"
     '    printf("a=%d", b.describe() + b.shown())\n'
     "    return 0\n",
     "class Bag:\n"
     "    def __init__(self, n):\n"
     "        self.n = n\n"
     "        self.tag = 0\n"
     "    def __len__(self):\n"
     "        return self.n\n"
     "    def describe(self):\n"
     "        if len(self) > 4:\n"
     "            return len(self) - 4\n"
     "        return 0\n"
     "    def shown(self):\n"
     '        print("len=%d " % len(self), end="")\n'
     "        return len(self)\n"
     "\n"
     "def main():\n"
     "    b = Bag(6)\n"
     '    print("a=%d" % (b.describe() + b.shown()), end="")\n'
     "    return 0\n"
     "\n"
     "main()\n"),

    # A NESTED FRAME, `len(self.inner)`.  A different spelling of the same
    # question, reached by a different route: here the frame lives in a slot of
    # the OUTER object's own block, placed by this compiler, so its lifetime is
    # the outer object's and the hand-off is sound for the same reason the bare
    # one is.  `build._rewrite_len_on_nested_frames` settles the struct with the
    # SAME `_typed_nested_frame` the method-call rewrite uses, because
    # `struct_nested_frame_fields` — the write-once placement list — is what
    # makes a nested frame's bytes live, and a second recogniser of "is this a
    # frame I placed" is the kind of pair that agrees until the day it does not.
    ("len_nested_frame_calls_the_inner_structs_dunder_len",
     "struct Bag:\n"
     "    var n: Int\n"
     "    var tag: Int\n"
     "    def __len__(self) -> Int:\n"
     "        return self.n\n"
     "\n"
     "struct Holder:\n"
     "    var inner: Bag\n"
     "    var t: Int\n"
     "    def total(self) -> Int:\n"
     "        return len(self.inner) + self.t\n"
     "\n"
     "def main(k: Int) -> Int:\n"
     "    var h = Holder()\n"
     "    h.inner.n = 6\n"
     "    h.inner.tag = 0\n"
     "    h.t = 2\n"
     '    printf("a=%d", h.total())\n'
     "    return 0\n",
     "class Bag:\n"
     "    def __init__(self, n):\n"
     "        self.n = n\n"
     "        self.tag = 0\n"
     "    def __len__(self):\n"
     "        return self.n\n"
     "\n"
     "class Holder:\n"
     "    def __init__(self, n, t):\n"
     "        self.inner = Bag(n)\n"
     "        self.t = t\n"
     "    def total(self):\n"
     "        return len(self.inner) + self.t\n"
     "\n"
     "def main():\n"
     "    h = Holder(6, 2)\n"
     '    print("a=%d" % h.total(), end="")\n'
     "    return 0\n"
     "\n"
     "main()\n"),

    # GUARD — and it passes BEFORE this change as well as after, which is the
    # sense in which every other case in this file is not.  A file that declares
    # a `__len__` and also takes the length of a string and a list and calls the
    # dunder directly, in one program: a rewrite that fired on `len` as a NAME
    # rather than on `len` of a frame address would call `Bag___len__("hello")`
    # and `Bag___len__(xs)` and produce wrong numbers rather than failures, and a
    # rewrite that missed the `x.__len__()` spelling entirely would compute
    # 3 + 5 + 4 where the source says 3 + 5 + 4 — the last number coming from a
    # different path.  This is the counterweight to the cases above, and it is
    # why the rewrite is keyed on the HOLDER SET rather than on the callee's
    # name.
    ("guard_len_on_a_string_and_a_blob_is_unchanged",
     "struct Bag:\n"
     "    var n: Int\n"
     "    var tag: Int\n"
     "    def __len__(self) -> Int:\n"
     "        return self.n\n"
     "\n"
     "def main(k: Int) -> Int:\n"
     '    var s = "hello"\n'
     "    var xs = [1, 2, 3]\n"
     "    var b = Bag()\n"
     "    b.n = 4\n"
     "    b.tag = 0\n"
     '    printf("%d %d %d", len(s), len(xs), b.__len__())\n'
     "    return 0\n",
     "class Bag:\n"
     "    def __init__(self):\n"
     "        self.n = 4\n"
     "        self.tag = 0\n"
     "    def __len__(self):\n"
     "        return self.n\n"
     "\n"
     "def main():\n"
     '    s = "hello"\n'
     "    xs = [1, 2, 3]\n"
     "    b = Bag()\n"
     '    print("%d %d %d" % (len(s), len(xs), b.__len__()), end="")\n'
     "    return 0\n"
     "\n"
     "main()\n"),
]

# ── the refusals, and each one has a CPython twin too ───────────────────────
#
# (name, mojo_source, python_source, needle)
#
# The python_source is not decorative: it must raise `TypeError`, which is what
# CPython says about every one of these programs and therefore the independent
# statement that there IS no length to read.  A refusal is only honest if the
# thing it refuses genuinely has no answer, and the way to know that here is to
# ask the language the case is written in — not to read this repository's own
# table and believe it.
REFUSALS = [
    # A struct with no `__len__`.  There is no count in a frame and no method to
    # call, and the message says WHICH of those two is the reason, because the
    # old message said only the first and a reader who then added the `__len__`
    # was told they had to change the program instead.
    ("refuse_len_on_a_frame_whose_struct_declares_no_dunder_len",
     "struct P:\n"
     "    var a: Int\n"
     "    var b: Int\n"
     "\n"
     "    fn n(self) -> Int:\n"
     "        return len(self)\n"
     "\n"
     "def main(n: Int) -> Int:\n"
     "    var p = P()\n"
     "    return p.n()\n",
     "class P:\n"
     "    def n(self):\n"
     "        return len(self)\n"
     "\n"
     "P().n()\n",
     "declares no `__len__`"),

    # THE AGREE-OR-REFUSE case, and it is the one a "does it have a `__len__`?"
    # test written as a boolean over the candidate list gets wrong.  `x` holds an
    # `A` on one path and a `B` on the other, only `A` declares a `__len__`, and
    # which frame is live at the `len` depends on the branch.  Emitting either
    # call would build, run, and answer with the other struct's length — so this
    # is refused and the message names which candidate declares one, because
    # "they disagree" without that sends the reader to look at the wrong
    # declaration.
    ("refuse_len_when_the_candidates_disagree_about_dunder_len",
     "struct A:\n"
     "    var v: Int\n"
     "    var pad: Int\n"
     "    def __len__(self) -> Int:\n"
     "        return self.v\n"
     "\n"
     "struct B:\n"
     "    var pad: Int\n"
     "    var w: Int\n"
     "\n"
     "def pick(c: Int):\n"
     "    var x = A()\n"
     "    if c > 0:\n"
     "        x = B()\n"
     "    n = len(x)\n"
     "    return 0\n"
     "\n"
     "def main(k: Int) -> Int:\n"
     "    return pick(1)\n",
     "class A:\n"
     "    def __len__(self):\n"
     "        return self.v\n"
     "\n"
     "class B:\n"
     "    pass\n"
     "\n"
     "def pick(c):\n"
     "    x = A()\n"
     "    if c > 0:\n"
     "        x = B()\n"
     "    n = len(x)\n"
     "    return 0\n"
     "\n"
     "pick(1)\n",
     "A declares one; B declares none"),

    # A `__len__` THAT TAKES NO RECEIVER.  `def __len__():` inside a class is a
    # function that happens to be spelled like a method, and the language gives
    # it no `self` — the same rule `struct_receivers` applies to a field read and
    # `build._receiverless_methods` applies to a call.  There is nothing for a
    # frame ADDRESS to be handed to, so `len(q)` is refused for the same reason a
    # struct with no `__len__` at all is, and the refusal says so rather than
    # calling a method that does not exist.
    ("refuse_len_when_dunder_len_declares_no_receiver",
     "struct Q:\n"
     "    var a: Int\n"
     "    var b: Int\n"
     "    def __len__() -> Int:\n"
     "        return 3\n"
     "\n"
     "def main(k: Int) -> Int:\n"
     "    var q = Q()\n"
     "    return len(q)\n",
     "class Q:\n"
     "    def __len__():\n"
     "        return 3\n"
     "\n"
     "len(Q())\n",
     "declares no `__len__`"),

    # THE ARITY, and this case exists to hold a DEAD BRANCH out.  There is a
    # shape where a frame address reaches the hand-off check and its struct DOES
    # declare a `__len__`: `len(b, b)`.  The rewrite is keyed on the one-
    # argument spelling, so this reaches the check — and a refusal written for it
    # that says "this operand is not a bare name" would be false in its first
    # clause, because the operand IS the bare name `b`.  The fault here is the
    # arity, and the needle pins that the program is left on the PRE-EXISTING
    # value-only message rather than on a new one written for a case that should
    # have a different diagnostic.  (The emitter's own "len() takes exactly one
    # argument" would be better still, but reaching it means the frame
    # hand-off must stop firing on a wrong-arity call, which is a separate
    # ordering question and not this case's.)
    #
    # It failed on the pre-change tree too — with the same words — so it is a
    # GUARD against a regression, not a demonstration.
    ("guard_a_wrong_arity_len_is_not_the_frame_refusal",
     "struct Bag:\n"
     "    var n: Int\n"
     "    var tag: Int\n"
     "    def __len__(self) -> Int:\n"
     "        return self.n\n"
     "\n"
     "def main(k: Int) -> Int:\n"
     "    var b = Bag()\n"
     "    b.n = 2\n"
     "    b.tag = 0\n"
     "    return len(b, b)\n",
     "class Bag:\n"
     "    def __len__(self):\n"
     "        return self.n\n"
     "\n"
     "len(Bag(), Bag())\n",
     "is lowered as an operation on a VALUE"),
]


def build_formal(src, out, backend):
    cmd = [sys.executable, FIRE, "build", "--formal", "--no-prove",
           f"--backend={backend}", "-o", out, src]
    p = subprocess.run(cmd, capture_output=True, text=True,
                       timeout=BUILD_TIMEOUT, cwd=HERE)
    return p.returncode, (p.stderr or p.stdout or "")


def run_cpython(source, tmpdir):
    """The oracle: the same program under CPython, whose exit status and stdout
    the formal image has to match.

    Not `mojo run` and not the interpreter in this repository.  The point of a
    differential case is that the two answers come from two independent
    implementations of the language, and `myinterpreter.py` is not one of them —
    it shares the AST, so a mistake in the AST cannot be caught by comparing
    against it.
    """
    path = os.path.join(tmpdir, "oracle.py")
    with open(path, "w") as f:
        f.write(source)
    return subprocess.run([sys.executable, path], capture_output=True, text=True,
                          timeout=RUN_TIMEOUT)


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("-v", "--verbose", action="store_true")
    ap.add_argument("cases", nargs="*", help="subset of case names")
    args = ap.parse_args()

    if platform.machine() not in ("arm64", "aarch64"):
        print(f"SKIP: formal output is arm64-only, host is {platform.machine()}")
        return 0

    everything = DIFF_CASES + REFUSALS
    known = {c[0] for c in everything}
    selected = [c for c in everything if not args.cases or c[0] in args.cases]
    if args.cases and len(selected) != len(args.cases):
        print(f"ERROR: unknown case(s): {sorted(set(args.cases) - known)}",
              file=sys.stderr)
        return 2
    diff_names = {c[0] for c in DIFF_CASES}

    passed = failed = 0
    with tempfile.TemporaryDirectory() as tmpdir:
        for case in selected:
            name, source = case[0], case[1]
            try:
                if name in diff_names:
                    ok, detail = run_diff_case(case, tmpdir, args.verbose)
                else:
                    ok, detail = run_refusal_case(case, tmpdir, args.verbose)
            except subprocess.TimeoutExpired:
                ok, detail = False, "timed out"
            except Exception as e:  # unexpected: report, do not mask
                ok, detail = False, f"{type(e).__name__}: {e}"
                if args.verbose:
                    import traceback
                    traceback.print_exc()
            if ok:
                passed += 1
                print(f"  PASS  {name}")
            else:
                failed += 1
                print(f"  FAIL  {name}: {detail}")
    print(f"\nformal frame len: PASS={passed} FAIL={failed}")
    return 1 if failed else 0


def run_diff_case(case, tmpdir, verbose):
    """CPython's answer, then both images' answers, and require all three to
    agree.

    The order is the order of trust: the oracle is run FIRST so that a broken
    expectation is reported as a broken expectation and not as three
    consistently wrong backends.  A case whose Python twin does not produce the
    answer the case is about is a bug in the case, and saying so is what keeps
    the suite from being a machine for confirming whatever it asserts.
    """
    name, source, oracle = case
    want = run_cpython(oracle, tmpdir)
    if want.returncode != 0:
        return False, (f"the CPython oracle itself failed (exit "
                       f"{want.returncode}): "
                       f"{(want.stderr or '').strip()[-200:]}")
    src = os.path.join(tmpdir, name + ".mojo")
    with open(src, "w") as f:
        f.write(source)
    for backend in BACKENDS:
        out = os.path.join(tmpdir, f"{name}.{backend}")
        rc, text = build_formal(src, out, backend)
        if rc != 0:
            return False, f"--backend={backend} did not build: {text.strip()[-300:]}"
        if not os.path.isfile(out):
            return False, f"--backend={backend} built but wrote no binary"
        run = subprocess.run([out], capture_output=True, text=True,
                             timeout=RUN_TIMEOUT)
        if run.returncode != want.returncode:
            return False, (f"--backend={backend} exit status {run.returncode}, "
                           f"CPython {want.returncode}")
        if run.stdout != want.stdout:
            return False, (f"--backend={backend} stdout {run.stdout!r}, CPython "
                           f"{want.stdout!r}")
        if verbose:
            print(f"      --backend={backend} stdout={run.stdout!r}")
    return True, ""


def run_refusal_case(case, tmpdir, verbose):
    """CPython must refuse too, and BOTH backends must refuse with the needle.

    Both halves are required and they are different assertions.  "The backends
    refuse" pins this compiler's decision; "CPython raises TypeError" pins that
    the decision is right, independently of anything this repository believes
    about the language.
    """
    name, source, oracle, needle = case
    want = run_cpython(oracle, tmpdir)
    if want.returncode == 0:
        return False, ("the CPython oracle SUCCEEDED on a program this case says "
                       "has no length; the case is wrong, not the backend")
    if "TypeError" not in (want.stderr or ""):
        return False, ("the CPython oracle failed for a reason other than the "
                       f"length: {(want.stderr or '').strip()[-200:]}")
    src = os.path.join(tmpdir, name + ".mojo")
    with open(src, "w") as f:
        f.write(source)
    for backend in BACKENDS:
        rc, text = build_formal(src, os.path.join(tmpdir, f"{name}.{backend}"),
                                backend)
        if rc == 0:
            return False, (f"--backend={backend} BUILT a construct with no "
                           f"representation (expected a refusal naming "
                           f"{needle!r}); the binary is the real answer here")
        if needle not in text:
            return False, (f"--backend={backend} refused, but not with the "
                           f"expected words {needle!r}: {text.strip()[-200:]}")
        if verbose:
            print(f"      --backend={backend} refused naming {needle!r}")
    return True, ""


if __name__ == "__main__":
    sys.exit(main())
