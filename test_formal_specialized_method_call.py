#!/usr/bin/env python3
"""`recv.m[T](args)` — a comptime-specialized METHOD call.

The sweep families "receiver passed at argument position 0" (25 files) and
"value with no representation on this path" (15 files) both name programs this
file is about, and both were refused with a sentence that was **entirely
false**.  Measured, before anything here was written:

    struct Pair:
        var a: Int
        var b: Int
        def combine[T: Int](self, k: Int) -> Int:
            return self.a * 1000 + self.b * 10 + k + T
    def main(n: Int) -> Int:
        var p = Pair(); p.a = 4; p.b = 5
        return p.combine[6](7)

    build: p.combine names 'combine', which is a METHOD of Pair rather than one
           of its fields: a value-position method reference is a bound method,
           and a method is not a word — there is no slot to read it out of and
           nothing to store it in …

Every clause about the CATEGORY is wrong.  `p.combine[6](7)` is a **call**: the
brackets are a generic's comptime parameters, bound at compile time, exactly as
`f[T](x)` is a call and not a subscript.  It arrived at the frame analysis as a
field read because `_rewrite_method_calls` recognised `recv.m(x)` — a callee
that is a `MemberExpr` — and not `recv.m[T](x)`, whose callee is a
`SubscriptExpr` over that same `MemberExpr`.  So the walk descended into the
bracket, found `p.combine` in value position, and asked for a slot.  That is
§4 of `bugs/FORMAL_frame_receiver_handoff.md` — "a refusal whose stated reason
is entirely false" — and this is the fifth example in the family that section
exists to police.

Six of the eight files the sweep reported this way are this shape, not a
bound-method value.  Measured by reading the refused expression in each:
`val.to_bits[uint_type]()` and `new_data.to_bits[.uint64]()`
(`std/memory/_poison.mojo`, `std/hashlib/_ahash.mojo`),
`resized_from.test_range[False, lo=Self.size]()`
(`std/collections/bitset.mojo`), `handle._get_ctx[_AsyncContext]()`
(`std/runtime/_asyncrt.mojo`), `self.lib.call["Py_Initialize"]()`
(`std/python/_cpython.mojo`), `a.get[i]()` (`std/utils/index.mojo`).  The other
two — `checker.check_temporal_monotonicity` in `run_type_system_tests.py` and
`job.excl` in `tools/suite.py` — ARE value-position method references, and they
are still refused, which is the correct verdict for them.

WHAT LANDED, and why it is a REWRITE rather than a new lowering
----------------------------------------------------------------
`formal/build.py`'s `_rewrite_method_calls` now lifts both spellings through
one recogniser, `_method_call_target`, and keeps the brackets on the callee when
there are any:

    recv.m(a)      ->  Struct_m(recv, a)
    recv.m[T](a)   ->  Struct_m[T](recv, a)

Keeping them is the whole of what a specialization is on this path, and it is
not a new decision: `formal/model.py`'s `incoming_args` puts a generic's
comptime parameters FIRST, and arm64's `_emit_call` passes the bracket
expressions first (`_specialization_args`).  So both spellings deliver the same
words to the same parameters, and the emitter needs no change at all — the same
argument `bugs/FORMAL_frame_receiver_handoff.md` §14 makes for `len(h)`, and the
same reason this is one function rather than two.

Measured on the program above, before the change it refused; after, it builds on
arm64 and returns **223** = 4000 + 50 + 7 + 6, which is CPython's answer for the
same program with the specialization written out.  `specialized_method_call_binds
_comptime_then_runtime_arguments` below is the case that pins the ORDER, because
a specialization lift that transposed the receiver and the comptime arguments
would produce a plausible wrong number rather than a failure.

WHY x86-64 STILL REFUSES, and why that is not a gap in this change
-------------------------------------------------------------------
`f[T](x)` builds on arm64 and is refused on x86-64 with "unsupported call target
on the formal x86-64 path (got SubscriptExpr)", because x86-64's caller does not
pass the comptime arguments while its callee prologue reserves a register for
them (`incoming_args` is shared).  That refusal is LOAD-BEARING and is measured,
with its three-half table, in `bugs/FORMAL_x86_64_comptime_specialization_abi.md`.
A specialized METHOD call inherits it exactly as a specialized free function
does — the construct needs the same missing half, and this change does not
provide it.  `x86_abi_refusal_is_load_bearing` pins it for the method spelling
so that a future change which made x86-64 "work" here by teaching it the name
alone would fail this file rather than silently produce a wrong image.

Every differential case is written twice, once as Mojo and once as plain Python,
and the two are made to AGREE rather than the expectation being hand-written —
`test_formal_frame_len.py`'s discipline, for the same reason: a hand-written
expected value is a second implementation of the question.  `printf` carries the
answer because a process exit status is a byte on this host and several of these
answers are larger than 255.

    python3 test_formal_specialized_method_call.py [-v] [case ...]
"""
import argparse
import os
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
FIRE = os.path.join(HERE, "fire.py")
BUILD_TIMEOUT = 180
RUN_TIMEOUT = 60
BACKENDS = ("arm64", "x86_64")
# The architecture whose comptime ABI has this construct.  Every case below is
# still BUILT on both: a case that builds on one and is refused on the other is
# the finding, not an accident (see the docstring), so the x86-64 answer is
# pinned explicitly rather than left unasserted.
COMPTIME_ABI = "arm64"

# ── the differential cases ──────────────────────────────────────────────────
#
# (name, mojo_source, python_source)
DIFF_CASES = [
    # THE TERMINAL CONSTRUCT, in miniature: `p.combine[6](7)`.  This is the
    # shape `std/memory/_poison.mojo` and `std/hashlib/_ahash.mojo` are refused
    # on (`val.to_bits[uint_type]()`, `new_data.to_bits[.uint64]()`), and it is
    # the one the false message was about.
    #
    # `Pair` is a TWO-FIELD struct, so its receiver is a FRAME ADDRESS rather
    # than a word (`formal/model.py`'s `struct_is_framed`).  That is deliberate:
    # the receiver hand-off is the reason this construct is in the
    # receiver-position family at all, and a one-field struct would pass this
    # case while proving nothing about the hand-off.
    ("specialized_method_call_on_a_frame_receiver",
     "struct Pair:\n"
     "    var a: Int\n"
     "    var b: Int\n"
     "    def combine[T: Int](self, k: Int) -> Int:\n"
     "        return self.a * 1000 + self.b * 10 + k + T\n"
     "\n"
     "def main(n: Int) -> Int:\n"
     "    var p = Pair()\n"
     "    p.a = 4\n"
     "    p.b = 5\n"
     '    printf("v=%d", p.combine[6](7))\n'
     "    return 0\n",
     "class Pair:\n"
     "    def __init__(self):\n"
     "        self.a = 4\n"
     "        self.b = 5\n\n"
     "    def combine(self, k):\n"
     "        return self.a * 1000 + self.b * 10 + k + 6\n"
     "\n"
     "def main():\n"
     "    p = Pair()\n"
     '    print("v=%d" % p.combine(7), end="")\n'
     "    return 0\n"
     "\n"
     "main()\n"),

    # **THE ORDER**, which is the assertion the case above cannot make.  Every
    # parameter of `mark` is read and given a distinct decimal weight, so a
    # lift that put the receiver before the comptime arguments, or bound `T` to
    # the receiver, produces a DIFFERENT NUMBER rather than a crash: 20306
    # against 23406.  A wrong-order lift is the failure mode this backend
    # exists to make impossible, and it is silent.
    #
    # `x` is the first RUNTIME parameter after `self`, so the three weights
    # between them say which of the four bindings is misplaced: T=2, x=3,
    # self.a=4, y=6.
    ("specialized_method_call_binds_comptime_then_runtime_arguments",
     "struct Pair:\n"
     "    var a: Int\n"
     "    var b: Int\n"
     "    def mark[T: Int](self, x: Int, y: Int) -> Int:\n"
     "        return T * 10000 + x * 100 + self.a * 10 + y\n"
     "\n"
     "def main(n: Int) -> Int:\n"
     "    var p = Pair()\n"
     "    p.a = 4\n"
     "    p.b = 5\n"
     '    printf("v=%d", p.mark[2](3, 6))\n'
     "    return 0\n",
     "class Pair:\n"
     "    def __init__(self):\n"
     "        self.a = 4\n"
     "        self.b = 5\n\n"
     "    def mark(self, x, y):\n"
     "        return 2 * 10000 + x * 100 + self.a * 10 + y\n"
     "\n"
     "def main():\n"
     "    p = Pair()\n"
     '    print("v=%d" % p.mark(3, 6), end="")\n'
     "    return 0\n"
     "\n"
     "main()\n"),

    # TWO SPECIALIZED CALLS OF THE SAME METHOD, which is the shape
    # `std/collections/bitset.mojo` has (`test_range[False, …]` and
    # `test_range[True, …]`) and the one a fix that cached a lifted callee
    # would get wrong.  Two different comptime bindings, one receiver.
    ("two_specializations_of_one_method",
     "struct Pair:\n"
     "    var a: Int\n"
     "    var b: Int\n"
     "    def scaled[T: Int](self) -> Int:\n"
     "        return T * 100 + self.a * 10 + self.b\n"
     "\n"
     "def main(n: Int) -> Int:\n"
     "    var p = Pair()\n"
     "    p.a = 4\n"
     "    p.b = 5\n"
     "    var q = Pair()\n"
     "    q.a = 6\n"
     "    q.b = 7\n"
     '    printf("v=%d", p.scaled[1]() * 1000 + q.scaled[2]())\n'
     "    return 0\n",
     "class Pair:\n"
     "    def __init__(self, a, b):\n"
     "        self.a = a\n"
     "        self.b = b\n\n"
     "    def scaled(self, t):\n"
     "        return t * 100 + self.a * 10 + self.b\n"
     "\n"
     "def main():\n"
     "    p = Pair(4, 5)\n"
     "    q = Pair(6, 7)\n"
     '    print("v=%d" % (p.scaled(1) * 1000 + q.scaled(2)), end="")\n'
     "    return 0\n"
     "\n"
     "main()\n"),

    # A SPECIALIZED METHOD CALLED THROUGH A PLAIN FUNCTION, so the specialized
    # callee is not reached from `main` — the compiler has to compile it and
    # bind it like any other, and this is the shape
    # `std/runtime/_asyncrt.mojo` has (`handle._get_ctx[_AsyncContext]()` called
    # from a helper).
    ("specialized_method_call_from_inside_a_function",
     "struct Pair:\n"
     "    var a: Int\n"
     "    var b: Int\n"
     "    def bump[T: Int](self) -> Int:\n"
     "        return T * 1000 + self.a * 10 + self.b\n"
     "\n"
     "def go(q: Pair) -> Int:\n"
     "    return q.bump[3]()\n"
     "\n"
     "def main(n: Int) -> Int:\n"
     "    var q = Pair()\n"
     "    q.a = 4\n"
     "    q.b = 5\n"
     '    printf("v=%d", go(q))\n'
     "    return 0\n",
     "class Pair:\n"
     "    def __init__(self):\n"
     "        self.a = 4\n"
     "        self.b = 5\n\n"
     "    def bump(self, t):\n"
     "        return t * 1000 + self.a * 10 + self.b\n"
     "\n"
     "def go(q):\n"
     "    return q.bump(3)\n"
     "\n"
     "def main():\n"
     "    q = Pair()\n"
     '    print("v=%d" % go(q), end="")\n'
     "    return 0\n"
     "\n"
     "main()\n"),

    # THE ADVICE `ambiguous_method_specialization_refusal` gives, built and
    # run.  A diagnostic that sends the reader into a SECOND refusal has moved
    # the cost rather than removed it, and the obvious-looking advice for an
    # ambiguous method name — qualifying the call as `Box.run[...]` — DOES NOT
    # work: a specialization of a DOTTED callee has no receiver to prepend, so
    # `_rewrite_method_calls` cannot lift it and it is refused again by
    # `frame_opaque_position_refusal`'s `callee_shape` arm.  Measured, which is
    # why the message offers the rename and the written-out call instead.
    #
    # So this case is the written-out call, next to the refusal case below that
    # recommends it: a change that reworded the advice into the dotted form
    # would pass every other case here and send a reader into a second refusal.
    # **It passes before this change as well as after** — the written-out
    # spelling was always lifted, which is exactly why it is the advice — so it
    # is a guard on the MESSAGE rather than a demonstration of the lift, and it
    # is not labelled GUARD because what it pins is the advice's text.
    ("the_advice_the_ambiguity_refusal_gives_works",
     "struct Box:\n"
     "    var k: Int\n"
     "    var j: Int\n"
     "    def run[T: Int](self, x: Int) -> Int:\n"
     "        return T * 100 + x + self.k\n"
     "\n"
     "struct Other:\n"
     "    var m: Int\n"
     "    var n: Int\n"
     "    def run[T: Int](self, x: Int) -> Int:\n"
     "        return x + self.m\n"
     "\n"
     "def main(n: Int) -> Int:\n"
     "    var b = Box()\n"
     "    b.k = 1\n"
     "    b.j = 2\n"
     '    printf("v=%d", Box_run[3](b, 4))\n'
     "    return 0\n",
     "class Box:\n"
     "    def __init__(self):\n"
     "        self.k = 1\n"
     "        self.j = 2\n\n"
     "    def run(self, t, x):\n"
     "        return t * 100 + x + self.k\n"
     "\n"
     "class Other:\n"
     "    def __init__(self):\n"
     "        self.m = 0\n"
     "        self.n = 0\n\n"
     "    def run(self, t, x):\n"
     "        return x + self.m\n"
     "\n"
     "def main():\n"
     "    b = Box()\n"
     '    print("v=%d" % b.run(3, 4), end="")\n'
     "    return 0\n"
     "\n"
     "main()\n"),

    # **GUARD** — the same program with a BARE-NAME callee, `p.combine(7)`,
    # which has always been lifted and must stay lifted.  Labelled a guard
    # because it is correct before this change as well as after, and it is here
    # so that a change which taught the specialization by rewriting `recv.m[T]`
    # into some NEW spelling could not pass every case above while breaking the
    # ordinary one.
    ("GUARD_unspecialized_method_call_is_unchanged",
     "struct Pair:\n"
     "    var a: Int\n"
     "    var b: Int\n"
     "    def combine[T: Int](self, k: Int) -> Int:\n"
     "        return self.a * 1000 + self.b * 10 + k + T\n"
     "\n"
     "def main(n: Int) -> Int:\n"
     "    var p = Pair()\n"
     "    p.a = 4\n"
     "    p.b = 5\n"
     '    printf("v=%d", Pair_combine[6](p, 7))\n'
     "    return 0\n",
     "class Pair:\n"
     "    def __init__(self):\n"
     "        self.a = 4\n"
     "        self.b = 5\n\n"
     "    def combine(self, k):\n"
     "        return self.a * 1000 + self.b * 10 + k + 6\n"
     "\n"
     "def main():\n"
     "    p = Pair()\n"
     '    print("v=%d" % p.combine(7), end="")\n'
     "    return 0\n"
     "\n"
     "main()\n"),

    # **GUARD** — a specialization of a FREE function with no receiver
    # anywhere, which `bugs/FORMAL_frame_receiver_handoff.md` §19 landed.  It
    # is here so that "the comptime ABI is unchanged" is a measurement rather
    # than an assumption: the answer is 307, and a lift that shifted call-time
    # positions by the number of comptime parameters would make it 723.
    ("GUARD_specialized_free_function_is_unchanged",
     "def widen[type: Int](x: Int, y: Int) -> Int:\n"
     "    return x * 100 + y\n"
     "\n"
     "def main(n: Int) -> Int:\n"
     '    printf("v=%d", widen[1](3, 7))\n'
     "    return 0\n",
     "def widen(type, x, y):\n"
     "    return x * 100 + y\n"
     "\n"
     "def main():\n"
     '    print("v=%d" % widen(1, 3, 7), end="")\n'
     "    return 0\n"
     "\n"
     "main()\n"),
]

# ── the refusals, which are the point of the two remaining families ─────────
#
# (name, mojo_source, needle)
#
# Every case here refuses for a reason that is TRUE of it, which is the property
# the false message above lost.  All of them fire in the shared build pass or in
# `formal/model.py`, so each is required to refuse identically on BOTH backends.
REFUSALS = [
    # A GENUINE VALUE-POSITION METHOD REFERENCE — `checker.check_temporal_...`
    # passed as an ARGUMENT, not called.  This is the two remaining files of the
    # sweep's eight, and it is the case the false message was written for and is
    # right about.  `a bound method is not a word` is the whole truth here: there
    # is no slot to read it out of and nothing to store it in.
    #
    # It is a refusal in this file rather than a demonstration on purpose — a
    # bound-method VALUE is a real gap on this path, and asserting that it
    # refuses for the right reason is what stops a future change from lifting it
    # by accident and producing a word that is not a method.
    ("refuse_a_value_position_method_reference",
     "struct Checker:\n"
     "    var n: Int\n"
     "    var seen: Int\n"
     "    def check(self, k: Int) -> Int:\n"
     "        return self.n + k\n"
     "\n"
     "def take(fn: Int, k: Int) -> Int:\n"
     "    return fn + k\n"
     "\n"
     "def main(n: Int) -> Int:\n"
     "    var c = Checker()\n"
     "    c.n = 3\n"
     "    c.seen = 4\n"
     "    return take(c.check, 7)\n",
     "a value-position method reference is a bound method"),

    # AN AMBIGUOUS METHOD NAME, which is the third of the eight and the reason
    # `std/runtime/_asyncrt.mojo` and `std/utils/index.mojo` are still refused
    # after this change.  Two structs in this image declare `run`, and dispatch
    # on this path is BY NAME because the receiver's type is not inferred — so
    # the lift has no single owner, and the refusal has to say that rather than
    # pick one.
    #
    # The needle is the CALL clause, and it is a distinct assertion from the
    # case above rather than a shorter version of it: before this change this
    # program was refused with the bound-method sentence, which told the reader
    # to add parentheses to a program that already had them.  The needle is
    # also what distinguishes it from a genuine value-position reference, so a
    # change that made the lift refuse for a DIFFERENT but equally untrue reason
    # would still pass.
    ("refuse_an_ambiguous_specialized_method_call_by_name",
     "struct Box:\n"
     "    var k: Int\n"
     "    var j: Int\n"
     "    def run[T: Int](self, x: Int) -> Int:\n"
     "        return x + self.k\n"
     "\n"
     "struct Other:\n"
     "    var m: Int\n"
     "    var n: Int\n"
     "    def run[T: Int](self, x: Int) -> Int:\n"
     "        return x + self.m\n"
     "\n"
     "def main(n: Int) -> Int:\n"
     "    var b = Box()\n"
     "    b.k = 1\n"
     "    b.j = 2\n"
     "    return b.run[3](4)\n",
     "is a method CALL"),
]

# ── the x86-64 half: a refusal that must STAY a refusal ───────────────────
X86_ABI_REFUSALS = [
    ("x86_abi_refusal_is_load_bearing",
     "struct Pair:\n"
     "    var a: Int\n"
     "    var b: Int\n"
     "    def combine[T: Int](self, k: Int) -> Int:\n"
     "        return self.a * 1000 + self.b * 10 + k + T\n"
     "\n"
     "def main(n: Int) -> Int:\n"
     "    var p = Pair()\n"
     "    p.a = 4\n"
     "    p.b = 5\n"
     "    return p.combine[6](7)\n",
     "unsupported call target on the formal x86-64 path (got SubscriptExpr)"),
]


def build_formal(src, out, backend):
    cmd = [sys.executable, FIRE, "build", "--formal", "--no-prove",
           f"--backend={backend}", "-o", out, src]
    p = subprocess.run(cmd, capture_output=True, text=True,
                       timeout=BUILD_TIMEOUT, cwd=HERE)
    return p.returncode, (p.stderr or p.stdout or "")


def run_cpython(source, tmpdir):
    """The oracle: the same program under CPython, whose stdout the formal
    image has to match.

    Not `mojo run` and not this repository's own interpreter: a differential
    case is worth something because the two answers come from two independent
    implementations of the language, and `myinterpreter.py` shares the AST, so a
    mistake in the AST cannot be caught by comparing against it.
    """
    path = os.path.join(tmpdir, "oracle.py")
    with open(path, "w") as f:
        f.write(source)
    return subprocess.run([sys.executable, path], capture_output=True, text=True,
                          timeout=RUN_TIMEOUT)


def run_diff_case(case, tmpdir, verbose):
    """CPython's answer first, then the image's, and require the two to agree.

    The order is the order of trust: a case whose Python twin does not produce
    the answer the case is about is a bug in the CASE, and running the oracle
    first is what makes that report say so.
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
    out = os.path.join(tmpdir, f"{name}.{COMPTIME_ABI}")
    rc, text = build_formal(src, out, COMPTIME_ABI)
    if rc != 0:
        return False, (f"--backend={COMPTIME_ABI} did not build: "
                       f"{text.strip()[-300:]}")
    if not os.path.isfile(out):
        return False, f"--backend={COMPTIME_ABI} built but wrote no binary"
    run = subprocess.run([out], capture_output=True, text=True,
                         timeout=RUN_TIMEOUT)
    if run.returncode != want.returncode:
        return False, (f"--backend={COMPTIME_ABI} exit status {run.returncode}, "
                       f"CPython {want.returncode}")
    if run.stdout != want.stdout:
        return False, (f"--backend={COMPTIME_ABI} stdout {run.stdout!r}, CPython "
                       f"{want.stdout!r}")
    if verbose:
        print(f"      --backend={COMPTIME_ABI} stdout={run.stdout!r}")
    return True, ""


def run_refusal_case(case, tmpdir, verbose):
    """BOTH backends must refuse, and both must refuse with the needle.

    Both architectures, because a refusal raised by the shared build pass has to
    be the same refusal on both: a construct one machine stops and the other
    lowers is the divergence this backend's design exists to make impossible.
    """
    name, source, needle = case
    src = os.path.join(tmpdir, name + ".mojo")
    with open(src, "w") as f:
        f.write(source)
    for backend in BACKENDS:
        rc, text = build_formal(src, os.path.join(tmpdir, f"{name}.{backend}"),
                                backend)
        if rc == 0:
            return False, (f"--backend={backend} BUILT a construct that has no "
                           f"representation (expected a refusal naming "
                           f"{needle!r}); the binary is the real answer here")
        if needle not in text:
            return False, (f"--backend={backend} refused, but not with the "
                           f"expected words {needle!r}: {text.strip()[-300:]}")
        if verbose:
            print(f"      --backend={backend} refused naming {needle!r}")
    return True, ""


def run_x86_abi_case(case, tmpdir, verbose):
    """arm64 must BUILD it and x86-64 must REFUSE it, for the same source.

    Both halves, and the second is not decoration.  The reason x86-64 has to
    refuse is that its callee prologue reserves a register per comptime
    parameter (`formal/model.py`'s `incoming_args` is shared) while its call
    site does not pass one — so a change that taught x86-64 the callee's NAME
    without the ABI would make this pass while producing a silently wrong image.
    See `bugs/FORMAL_x86_64_comptime_specialization_abi.md` for the three-half
    table.
    """
    name, source, needle = case
    src = os.path.join(tmpdir, name + ".mojo")
    with open(src, "w") as f:
        f.write(source)
    rc, text = build_formal(src, os.path.join(tmpdir, f"{name}.arm64"), "arm64")
    if rc != 0:
        return False, f"--backend=arm64 did not build the construct: {text.strip()[-300:]}"
    rc, text = build_formal(src, os.path.join(tmpdir, f"{name}.x86_64"), "x86_64")
    if rc == 0:
        return False, ("--backend=x86_64 BUILT a comptime specialization it "
                       "cannot pass arguments for; see "
                       "bugs/FORMAL_x86_64_comptime_specialization_abi.md — "
                       "the missing half is the call site, not the name")
    if needle not in text:
        return False, (f"--backend=x86_64 refused, but not naming the missing "
                       f"ABI {needle!r}: {text.strip()[-300:]}")
    if verbose:
        print("      arm64 built; x86_64 refused naming the missing ABI")
    return True, ""


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[1])
    ap.add_argument("-v", "--verbose", action="store_true")
    ap.add_argument("cases", nargs="*", help="case name substring filter")
    args = ap.parse_args(argv)

    def wanted(name):
        return not args.cases or any(c in name for c in args.cases)

    runners = (("differential", DIFF_CASES, run_diff_case),
               ("refusal", REFUSALS, run_refusal_case),
               ("x86-64 ABI", X86_ABI_REFUSALS, run_x86_abi_case))
    passed = failed = 0
    failures = []
    with tempfile.TemporaryDirectory() as tmpdir:
        for label, cases, runner in runners:
            for case in cases:
                name = case[0]
                if not wanted(name):
                    continue
                try:
                    ok, why = runner(case, tmpdir, args.verbose)
                except subprocess.TimeoutExpired as exc:
                    ok, why = False, f"timed out: {exc}"
                if ok:
                    passed += 1
                    print(f"  PASS  {name}")
                else:
                    failed += 1
                    failures.append(f"  FAIL  {name}: {why}")
                    print(f"  FAIL  {name}: {why}")
    print(f"\nspecialized method call: PASS={passed} FAIL={failed}")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
