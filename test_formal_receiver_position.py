#!/usr/bin/env python3
"""A frame address at an argument position of a COMPTIME-SPECIALIZED call.

The receiver-position family (`formal/build.py`'s `_frame_receivers` /
`_check_frame_escapes` / `_check_holder_agreements`) has three cases, and this file covers the one that is not about a method call
at all: `f[T](r)` — a generic being specialized with a frame address in an
argument.

    python3 test_formal_receiver_position.py [-v] [case ...]

WHAT THE CONSTRUCT IS.  A struct of more than one field has a FRAME for its
receiver on this path (`formal/model.py`'s `struct_is_framed`): the receiver word
is the ADDRESS of a block of 8-byte slots, one per field.  Handing that address
to a callee's parameter is the hand-off the by-reference design exists for, and
wave 5 established it for a BARE-NAME callee in every position.  A
comptime-specialized callee is the same hand-off: `f[T](r)` names the function
`f`, and the brackets are a compile-time binding rather than an argument, so
call-time position `i` is the `i`th entry of `function_param_shape(f).names` —
which is the list every frame table is keyed by (`formal/model.py`'s
`call_callee_name` says this, and its docstring carries the measurement).

WHY IT WAS REFUSED, AND WHY THE REASON WAS FALSE.  The terminal message was
"a method call on a value receiver is dispatched by NAME, so `recv.m(x)` carries
no type" — about a callee that is a plain name with no receiver, no method and
no dispatch in it.  Six of the 25 files `bugs/FORMAL_sweep_work_map_2026-09-30.md`
blocks on that message have a comptime specialization at the callee
(`std/algorithm/reduction.mojo`, `std/builtin/string_literal.mojo`,
`std/collections/bitset.mojo`, `std/collections/string/format.mojo`,
`std/memory/span.mojo`, `std/python/bindings.mojo`) and not one of them contains
a method call at that site.  §4 of the handoff doc is three examples of a
refusal for a reason that was not operating; this was a fourth, in the family
that §4 exists to police.

BOTH ARCHITECTURES NOW AGREE, and getting there took THREE halves rather than
the one the filing named.  `f[1](3, 7)` returned 307 on arm64 and was REFUSED on
x86-64 with "unsupported call target on the formal x86-64 path (got
SubscriptExpr)", and the filing correctly said the fix was not a one-line
delegation of `_callee_symbol`.  Measured, in the order they had to land:

  1. the CALL SITE passes the bracket expressions ahead of the call-time
     arguments (`comptime_eval.specialization_args`, the shared reader);
  2. `_callee_symbol` answers a `SubscriptExpr` with the bare name;
  3. the CALLEE PROLOGUE allocates a home for a comptime parameter.

(3) is the one the filing recorded as already present, and it was not.  It said
"the callee prologue reserves a register per comptime parameter — yes —
`model.incoming_args` is shared and both backends' prologues read it", which was
true of arm64 and not of x86-64: this backend's prologue read `f.params`, which
does not list a comptime parameter at all.  That is invisible until (1) lands,
because before it a bare `f(3, 7)` agreed with arm64 by accident.  The moment (1)
went in, a bare `f(3, 7)` returned 3 on x86-64 against arm64's 307 — a
callee with no home for `type`, so every read fell back to the first incoming
register and `x` read the `type` slot.  Both backends now ask the shared
`model.incoming_args` in the prologue and allocate through arm64's
`_allocation_order` shape, and the two spellings agree with each other and with
CPython on both machines.

`x86_abi_refusal_is_load_bearing` is therefore gone rather than updated: what it
pinned — that x86-64 refusing was correct — is no longer true.  `every_specialized
_spelling_agrees_on_both_architectures` replaces it, and it is the anti-rot
direction: if the ABI half is ever removed from one backend alone, this case
goes red on the wrong number rather than on a refusal.

Every case is DIFFERENTIAL: the same program is written twice, once as Mojo and
once as plain Python, and the two are made to AGREE rather than the expectation
being written by hand.  `printf` is used for the Mojo side rather than the exit
status, because a process exit status is a byte on this host and some of these
answers are larger than 255.
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
DIFF_CASES = [
    # THE TERMINAL CONSTRUCT, in miniature: a frame address at a NON-FIRST
    # position of a specialized generic.  This is the shape the sweep blocks
    # `std/algorithm/reduction.mojo` on (`_reduce_generator[…](shape, init=…)`
    # with `shape: Coord`), and it is the case the position family says must be
    # followed, because a parameter is a parameter wherever it sits.
    ("generic_frame_reads_at_a_nonfirst_position",
     "struct R:\n"
     "    var a: Int\n"
     "    var b: Int\n\n"
     "def take[type: Int](x: Int, r: R) -> Int:\n"
     "    return r.a * 10 + r.b\n\n"
     "def main(n: Int) -> Int:\n"
     "    var r = R()\n"
     "    r.a = 7\n"
     "    r.b = 8\n"
     '    printf("v=%d", take[1](0, r))\n'
     "    return 0\n",
     "class R:\n"
     "    def __init__(self):\n"
     "        self.a = 7\n"
     "        self.b = 8\n\n"
     "def take(type, x, r):\n"
     "    return r.a * 10 + r.b\n\n"
     "def main():\n"
     "    r = R()\n"
     '    print("v=%d" % take(1, 0, r), end="")\n'
     "    return 0\n\n"
     "main()\n"),

    # A WRITE THROUGH THE ADDRESS, which is the half a read cannot establish: a
    # read would still come out right if the word handed over were a COPY of the
    # frame, and `put` writes `r.a` and main reads `r.a` afterwards, so the
    # answer is only 5252 if the callee's store landed in the caller's frame.
    # (The CPython twin writes the same attribute, so the comparison is of the
    # same question and not of a constant.)
    ("generic_frame_writes_through_to_the_caller",
     "struct R:\n"
     "    var a: Int\n"
     "    var b: Int\n\n"
     "def put[type: Int](x: Int, y: Int, v: Int) -> Int:\n"
     "    y.a = v\n"
     "    return y.a\n\n"
     "def main(n: Int) -> Int:\n"
     "    var r = R()\n"
     "    r.a = 1\n"
     "    r.b = 8\n"
     '    printf("got=%d back=%d", put[1](0, r, 52), r.a)\n'
     "    return 0\n",
     "class R:\n"
     "    def __init__(self):\n"
     "        self.a = 1\n"
     "        self.b = 8\n\n"
     "def put(type, x, y, v):\n"
     "    y.a = v\n"
     "    return y.a\n\n"
     "def main():\n"
     "    r = R()\n"
     '    print("got=%d back=%d" % (put(1, 0, r, 52), r.a), end="")\n'
     "    return 0\n\n"
     "main()\n"),

    # THE CREATOR ONE FRAME DEEPER.  `main` holds no frame at all here, so this
    # is the case that would catch a lifetime error rather than a missing slot
    # table: the frame is built in `build()`, and `build` is still on the stack
    # when `take` runs, which is the whole of the argument that a frame address
    # may travel down an active call chain.
    ("generic_frame_creator_one_frame_deeper",
     "struct R:\n"
     "    var a: Int\n"
     "    var b: Int\n\n"
     "def take[type: Int](x: Int, r: R) -> Int:\n"
     "    return r.a * 10 + r.b\n\n"
     "def build() -> Int:\n"
     "    var r = R()\n"
     "    r.a = 7\n"
     "    r.b = 8\n"
     "    return take[1](0, r)\n\n"
     "def main(n: Int) -> Int:\n"
     '    printf("v=%d", build())\n'
     "    return 0\n",
     "class R:\n"
     "    def __init__(self):\n"
     "        self.a = 7\n"
     "        self.b = 8\n\n"
     "def take(type, x, r):\n"
     "    return r.a * 10 + r.b\n\n"
     "def build():\n"
     "    r = R()\n"
     "    return take(1, 0, r)\n\n"
     "def main():\n"
     '    print("v=%d" % build(), end="")\n'
     "    return 0\n\n"
     "main()\n"),

    # POSITION 0 OF A SPECIALIZED CALLEE — the literal shape the sweep's row 4
    # is named for, and the one a fix to the non-first case could plausibly
    # break: a receiver as the FIRST parameter of `f[T]`.
    ("generic_frame_at_position_zero",
     "struct R:\n"
     "    var a: Int\n"
     "    var b: Int\n\n"
     "def show[type: Int](r: R) -> Int:\n"
     "    return r.a * 10 + r.b\n\n"
     "def main(n: Int) -> Int:\n"
     "    var r = R()\n"
     "    r.a = 7\n"
     "    r.b = 8\n"
     '    printf("v=%d", show[1](r))\n'
     "    return 0\n",
     "class R:\n"
     "    def __init__(self):\n"
     "        self.a = 7\n"
     "        self.b = 8\n\n"
     "def show(type, r):\n"
     "    return r.a * 10 + r.b\n\n"
     "def main():\n"
     "    r = R()\n"
     '    print("v=%d" % show(1, r), end="")\n'
     "    return 0\n\n"
     "main()\n"),

    # **GUARD** — the same program with a BARE-NAME callee, which has always
    # been followed and must stay followed.  Labelled as a guard rather than a
    # demonstration because it is correct before the change as well as after,
    # and it is here so that a fix which resolved `f[T](x)` by rewriting the
    # call into some new spelling could not pass every case above while breaking
    # the ordinary one.
    ("GUARD_bare_name_callee_is_unchanged",
     "struct R:\n"
     "    var a: Int\n"
     "    var b: Int\n\n"
     "def take(x: Int, r: R) -> Int:\n"
     "    return r.a * 10 + r.b\n\n"
     "def main(n: Int) -> Int:\n"
     "    var r = R()\n"
     "    r.a = 7\n"
     "    r.b = 8\n"
     '    printf("v=%d", take(0, r))\n'
     "    return 0\n",
     "class R:\n"
     "    def __init__(self):\n"
     "        self.a = 7\n"
     "        self.b = 8\n\n"
     "def take(x, r):\n"
     "    return r.a * 10 + r.b\n\n"
     "def main():\n"
     "    r = R()\n"
     '    print("v=%d" % take(0, r), end="")\n'
     "    return 0\n\n"
     "main()\n"),

    # **GUARD** — a specialized generic with a comptime parameter and NO frame
    # anywhere.  It was already correct on arm64 and the change must not have
    # moved it: it is what makes "the comptime ABI is unchanged" a measurement
    # rather than an assumption, and it is the case that would catch a
    # `call_callee_name` which shifted call-time positions by the number of
    # comptime parameters (the answer would be 3, not 307).
    ("GUARD_specialization_binds_its_own_arguments",
     "def f[type: Int](x: Int, y: Int) -> Int:\n"
     "    return x * 100 + y\n\n"
     "def main(n: Int) -> Int:\n"
     '    printf("v=%d", f[1](3, 7))\n'
     "    return 0\n",
     "def f(type, x, y):\n"
     "    return x * 100 + y\n\n"
     "def main():\n"
     '    print("v=%d" % f(1, 3, 7), end="")\n'
     "    return 0\n\n"
     "main()\n"),
    # **GUARD** — the advice the call-result-receiver refusal gives, and it is in
    # this table because it is a positive case: `m.make().take(r)` is refused in
    # `REFUSALS` below, and the sentence it is refused with tells the reader to
    # bind the receiver to a local of a declared struct type. If that program did
    # not build, the refusal would be a second defect wearing the first one's
    # clothes, and nothing else in the tree would say so.
    #
    # `q.combine[2](3)` is the SPECIALIZED spelling deliberately — it is the one
    # the other refusal case's twin uses, so the guard and the refusal describe
    # the same call one rewrite apart. 5045 = 5000 + 40 + 3 + 2, and every digit
    # is load bearing: `combine`'s receiver (5 and 4, swapped by `peer`), its
    # `a` (5), the argument (3) and the specialization (2).
    ("GUARD_a_call_result_receiver_bound_to_a_local_answers",
     "struct Pair:\n"
     "    var a: Int\n"
     "    var b: Int\n"
     "    def peer(self) -> Pair:\n"
     "        var q = Pair()\n"
     "        q.a = self.b\n"
     "        q.b = self.a\n"
     "        return q\n"
     "    def combine[T: Int](self, k: Int) -> Int:\n"
     "        return self.a * 1000 + self.b * 10 + k + T\n\n"
     "def main(n: Int) -> Int:\n"
     "    var p = Pair()\n"
     "    p.a = 4\n"
     "    p.b = 5\n"
     "    var q = p.peer()\n"
     '    printf("v=%d", q.combine[2](3))\n'
     "    return 0\n",
     "class Pair:\n"
     "    def __init__(self, a, b):\n"
     "        self.a = a\n"
     "        self.b = b\n"
     "    def peer(self):\n"
     "        return Pair(self.b, self.a)\n"
     "    def combine(self, T, k):\n"
     "        return self.a * 1000 + self.b * 10 + k + T\n\n"
     "def main():\n"
     "    p = Pair(4, 5)\n"
     "    q = p.peer()\n"
     '    print("v=%d" % q.combine(2, 3), end="")\n'
     "    return 0\n\n"
     "main()\n"),
    # ── THE SUBSCRIPT RECEIVER, which is `bugs/FORMAL_method_call_on_a_
    # subscribed_receiver.md`'s Done-when and the capability the receiver-type
    # predicate exists for.  `u1.mojo`, verbatim: the element type is the
    # constructor's own declaration, and the answer is 3 on both architectures
    # where the refusal it replaced was a LINK-AUDIT sentence naming a bare `get`.
    ("subscript_receiver_method_call_reads_the_element",
     "struct Box:\n"
     "    var k: Int\n"
     "    def get(self) -> Int:\n"
     "        return self.k\n\n"
     "def main(n: Int) -> Int:\n"
     "    var bs = [Box(), Box()]\n"
     "    bs[0].k = 3\n"
     '    printf("v=%d", bs[0].get())\n'
     "    return 0\n",
     "class Box:\n"
     "    def __init__(self):\n"
     "        self.k = 0\n"
     "    def get(self):\n"
     "        return self.k\n\n"
     "def main():\n"
     "    bs = [Box(), Box()]\n"
     "    bs[0].k = 3\n"
     '    print("v=%d" % bs[0].get(), end="")\n'
     "    return 0\n\n"
     "main()\n"),

    # …and a FIELD READ AND WRITE through the same subscript, which is the half
    # that used to be silently WRONG rather than refused: the load fell to the
    # emitter's "no object model, so the field reads as 0" arm and the store was
    # dropped, so this program printed 0 and exited 0.  Both element reads and
    # both element writes are in it, because a fix that made the read right and
    # left the store dropped would produce the same 0 from the other direction.
    ("subscript_element_field_read_and_write_both_land",
     "struct Box:\n"
     "    var k: Int\n\n"
     "def main(n: Int) -> Int:\n"
     "    var bs = [Box(), Box()]\n"
     "    bs[0].k = 3\n"
     "    bs[1].k = 7\n"
     '    printf("v=%d %d %d", bs[0].k, bs[1].k, bs[0])\n'
     "    return 0\n",
     "class Box:\n"
     "    def __init__(self):\n"
     "        self.k = 0\n\n"
     "def main():\n"
     "    bs = [Box(), Box()]\n"
     "    bs[0].k = 3\n"
     "    bs[1].k = 7\n"
     '    print("v=%d %d %d" % (bs[0].k, bs[1].k, bs[0].k), end="")\n'
     "    return 0\n\n"
     "main()\n"),

    # …and the SECOND of the two sources that state an element type: a parameter
    # declared `List[Box]`.  A local literal and a declared parameter are the
    # only two spellings this path can read, and a predicate that only had the
    # first would leave every function in the stdlib — which takes parameters,
    # not literals — on the old refusal.
    ("subscript_receiver_on_a_declared_element_parameter",
     "struct Box:\n"
     "    var k: Int\n"
     "    def get(self) -> Int:\n"
     "        return self.k\n\n"
     "def first(bs: List[Box]) -> Int:\n"
     "    return bs[0].get()\n\n"
     "def main(n: Int) -> Int:\n"
     "    var bs = [Box(), Box()]\n"
     "    bs[0].k = 5\n"
     '    printf("v=%d", first(bs))\n'
     "    return 0\n",
     "class Box:\n"
     "    def __init__(self):\n"
     "        self.k = 0\n"
     "    def get(self):\n"
     "        return self.k\n\n"
     "def first(bs):\n"
     "    return bs[0].get()\n\n"
     "def main():\n"
     "    bs = [Box(), Box()]\n"
     "    bs[0].k = 5\n"
     '    print("v=%d" % first(bs), end="")\n'
     "    return 0\n\n"
     "main()\n"),

    # …and an index that is a NAME rather than a literal, on the first source.
    # `bs[0].k` and `bs[i].k` are the same rewrite and must read different
    # elements, so this is what stops the identity from being written as "take
    # element 0".
    ("subscript_receiver_with_a_name_index",
     "struct Box:\n"
     "    var k: Int\n"
     "    def get(self) -> Int:\n"
     "        return self.k\n\n"
     "def main(n: Int) -> Int:\n"
     "    var bs = [Box(), Box()]\n"
     "    bs[0].k = 3\n"
     "    bs[1].k = 7\n"
     "    var i = 1\n"
     '    printf("v=%d %d", bs[i].get(), bs[i].k)\n'
     "    return 0\n",
     "class Box:\n"
     "    def __init__(self):\n"
     "        self.k = 0\n"
     "    def get(self):\n"
     "        return self.k\n\n"
     "def main():\n"
     "    bs = [Box(), Box()]\n"
     "    bs[0].k = 3\n"
     "    bs[1].k = 7\n"
     "    i = 1\n"
     '    print("v=%d %d" % (bs[i].get(), bs[i].k), end="")\n'
     "    return 0\n\n"
     "main()\n"),

    # **GUARD** — a one-field holder of a nested frame, BUILT, which is the
    # positive half of the two refusals below and the reason they are two
    # refusals rather than one: `b.inner = Opt()` puts a frame address in the
    # word `Box`'s receiver IS, and `b.get()` then reads through it. Adding the
    # refusal must not have cost this program, and it is what says the check
    # asks "did anything build it" rather than "is this a one-field holder" — a
    # rule that refused the shape outright would be green on the two refusals
    # and wrong here.
    #
    # The SECOND field on the second program is the other half of that: `var
    # pad: Int` makes `Box` a frame in its own right, its receiver is an
    # address into scratch rather than a field's storage, and the unwritten
    # slot reads 0. CPython raises `AttributeError` for that program, so 0 is
    # this path's documented answer where the source does not say what the slot
    # holds, and `test_formal_run.py`'s
    # `two_field_holder_reads_its_nested_frame_through_a_method` pins it from
    # the other direction.
    ("GUARD_a_one_field_holder_built_through_its_own_field_answers",
     "struct Opt:\n"
     "    var v: Int\n"
     "    var has: Int\n\n"
     "struct Box:\n"
     "    var inner: Opt\n\n"
     "    def get(self) -> Int:\n"
     "        return self.inner.v * 10 + self.inner.has\n\n"
     "def main() -> int:\n"
     "    var b = Box()\n"
     "    b.inner = Opt()\n"
     "    b.inner.v = 4\n"
     "    b.inner.has = 1\n"
     '    printf("v=%d", b.get())\n'
     "    return 0\n",
     "class Opt:\n"
     "    def __init__(self, v, has):\n"
     "        self.v = v\n"
     "        self.has = has\n\n"
     "class Box:\n"
     "    def __init__(self, inner):\n"
     "        self.inner = inner\n"
     "    def get(self):\n"
     "        return self.inner.v * 10 + self.inner.has\n\n"
     "def main():\n"
     "    b = Box(Opt(4, 1))\n"
     '    print("v=%d" % b.get(), end="")\n'
     "    return 0\n\n"
     "main()\n"),
    ("GUARD_a_two_field_holder_reads_its_nested_frame_as_zero",
     "struct Opt:\n"
     "    var v: Int\n"
     "    var has: Int\n\n"
     "struct Box:\n"
     "    var inner: Opt\n"
     "    var pad: Int\n\n"
     "    def get(self) -> Int:\n"
     "        return self.inner.v\n\n"
     "def main() -> int:\n"
     "    var b = Box()\n"
     '    printf("v=%d", b.get())\n'
     "    return 0\n",
     "class Opt:\n"
     "    def __init__(self, v, has):\n"
     "        self.v = v\n"
     "        self.has = has\n\n"
     "class Box:\n"
     "    def __init__(self, inner, pad):\n"
     "        self.inner = inner\n"
     "        self.pad = pad\n"
     "    def get(self):\n"
     "        return self.inner.v\n\n"
     "def main():\n"
     "    b = Box(Opt(0, 0), 0)\n"
     '    print("v=%d" % b.get(), end="")\n'
     "    return 0\n\n"
     "main()\n"),
]

# ── the refusals ────────────────────────────────────────────────────────────
#
# (name, mojo_source, needle)
#
# All of these fire in the SHARED build pass (`formal/build.py`'s
# `_check_frame_escapes` / `_check_holder_agreements`), which runs before either
# emitter is reached, so each one is required to refuse identically on arm64
# and on x86-64.  That is the right shape for these cases and the opposite of
# the differential ones above: a frame address still reaching something that may
# outlive its creator has to stop on BOTH machines whatever each emitter can do.
REFUSALS = [
    # TWO CALL SITES THAT DISAGREE — the measured SIGSEGV of wave 5, reached
    # through the new spelling.  `f[1](r, 1)` makes `x` a frame holder and
    # `f[1](2, 3)` arrives with `x = 2`, so `x.a` is a load eight bytes from
    # wherever 2 points.  The needle is the whole sentence rather than a word,
    # because the interesting part is that it names BOTH sites.
    ("refuse_two_specialized_call_sites_that_disagree",
     "struct R:\n"
     "    var a: Int\n"
     "    var b: Int\n\n"
     "def f[type: Int](x: Int, r: R) -> Int:\n"
     "    return x.a\n\n"
     "def main(n: Int) -> Int:\n"
     "    var r = R()\n"
     "    r.a = 7\n"
     "    r.b = 8\n"
     "    return f[1](r, 1) + f[1](2, 3)\n",
     "One parameter, two kinds of value"),

    # …and the two call sites are quoted the way the source spells them.  This
    # is a separate assertion from the one above because it is a different
    # defect: a spelling that printed the AST (`SubscriptExpr(r, 1)`) is a
    # refusal whose reason is still right and whose EVIDENCE is unreadable, and
    # `_call_spelling` raised on exactly these calls until `formal/build.py`'s
    # `_expr_spelling` learned a subscript.
    ("refuse_disagreement_spells_both_call_sites",
     "struct R:\n"
     "    var a: Int\n"
     "    var b: Int\n\n"
     "def g[type: Int](x: Int, r: R) -> Int:\n"
     "    return x.a\n\n"
     "def main(n: Int) -> Int:\n"
     "    var r = R()\n"
     "    r.a = 7\n"
     "    r.b = 8\n"
     "    return g[1](r, 1) + g[1](2, 3)\n",
     "at g[1](r, 1) here, and something that is not a frame address at "
     "g[1](2, 3)"),

    # A RECEIVED FRAME ADDRESS RETURNED.  The return family, not the position
    # family, and the message says so: the creator is up the call chain and

    # A CALLEE THIS PASS CANNOT NAME, and the message must NAME IT rather than
    # call it a method call.  `Box.run[1](0, r)` is a specialization of a
    # DOTTED callee: `_rewrite_method_calls` lifts `recv.m(x)` and not
    # `Struct.m[T](x)`, so there is no parameter list to read.  The needle is
    # the callee's own spelling, which is the whole point — before the change
    # this program was reported as "a method call on a value receiver is
    # A METHOD DECLARED WITH PARAMETERS AND NO RECEIVER — the sentence below is
    # the whole of what this case is about, and it replaced TWO wrong ones.
    #
    # The case used to assert that `Box.run[1](0, r)` is refused as "a
    # specialization of a dotted callee, which names no function this pass has a
    # parameter list for". That stopped being true when
    # `formal/build.py::_method_call_target` learned to look THROUGH the bracket
    # `formal/build.py::_method_call_target`, which looks THROUGH the bracket:
    # `Box.run[1]` is lifted to
    # `Box_run[1]` like any other method call, so there IS a parameter list and
    # the shape arm has nothing to fire on. What the program really is, and what
    # it was actually refused for, is that `run` declares no receiver — so
    # prepending the receiver to its argument list shifted every argument after
    # the first by one, and the two diagnoses that stood in for that were an
    # arity count ("3 for 2 parameter(s)") and a holder disagreement claiming the
    # call "passes the literal 0" where it passes `r`.
    #
    # `model.method_declares_receiver` has the measurement: across every `.mojo`
    # file in the tree, six methods declare parameters and all six spell the
    # receiver `self`, so the refusal costs nothing here.
    ("refuse_a_method_with_parameters_and_no_receiver",
     "struct R:\n"
     "    var a: Int\n"
     "    var b: Int\n\n"
     "struct Box:\n"
     "    var k: Int\n\n"
     "    def run[type: Int](x: Int, r: R) -> Int:\n"
     "        return r.a\n\n"
     "def main(n: Int) -> Int:\n"
     "    var r = R()\n"
     "    r.a = 7\n"
     "    r.b = 8\n"
     "    var bx = Box()\n"
     "    bx.k = 1\n"
     "    return bx.run[1](0, r)\n",
     "is declared with parameters and no receiver"),

    # A specialization does NOT rescue the value-only callees: `origin_of`
    # wants the object, and a frame address is not one.  `origin_of` is spelled
    # `self.origin` here because `origin_of` is a builtin on this path and the
    # A RECEIVED frame address that leaves through the ENTRY. Same construct as
    # the returned-frame suite's positive case, one destination worse: `ask`
    # returns the address it was handed and `main` returns it in turn, and the
    # convention needs a CALLER to reserve the block — `main`'s caller is the C
    # runtime, which passes no such word.
    #
    # The case used to assert the value-only sentence, and that became
    # unreachable the moment `origin_of` became `FRAME_IDENTITY_CALLS`
    # `formal/model.py`'s `FRAME_IDENTITY_CALLS`, which erased it to its operand
    # by
    # `formal/build.py::_rewrite_identity_intrinsic_calls`, so there is no
    # value-only callee here to refuse — `origin_of(r)` IS `r`, and what this
    # program does is hand a received frame address back. The refusal below is
    # that one, and every clause of it is true.
    ("refuse_a_received_frame_returned_out_of_the_entry",
     "struct R:\n"
     "    var a: Int\n"
     "    var b: Int\n\n"
     "def ask[type: Int](x: Int, r: R) -> Int:\n"
     "    return origin_of(r)\n\n"
     "def main(n: Int) -> Int:\n"
     "    var r = R()\n"
     "    r.a = 7\n"
     "    r.b = 8\n"
     "    return ask[1](0, r)\n",
     "its caller is the C runtime, which passes no such word"),

    # A method called on a SUBSCRIPTED receiver whose element type is NOT
    # DECLARED — `bs[0].get()` where `bs` is a parameter annotated only `List`.
    # Refused for the receiver's TYPE and not at the LINK LINE.
    #
    # **This case used to be the same program as `bs = [Box(), Box()]`, and the
    # CAPABILITY is what changed (2026-10-02, the now-deleted
    # `FORMAL_method_call_on_a_subscripted_receiver`): a list literal of
    # `Box()` names its element type in its own right, and a parameter declared
    # `List[Box]` names it outright, so both now lift and run. What is left is
    # the shape the source does not answer, and it is still the same refusal
    # with the same words — a predicate that claimed a struct here would be
    # inventing one, which is the failure mode a receiver's type is exactly
    # about.
    #
    # The previous answer to a subscript receiver was a link-audit sentence:
    #
    #     the image would bind 1 symbol(s) that nothing provides: get.
    #     Nothing on this link line defines them …
    #
    # which is a diagnosis about where the symbol should have come from, for a
    # defect in how the call was written — `_rewrite_method_calls` lifted
    # `recv.m(...)` to `Struct_m(recv, …)` only when `recv` was a bare name, and
    # `bs[0]` is not one, so the dotted spelling fell through to a call against a
    # symbol spelled after the METHOD. The link audit caught it only because
    # nothing else claimed `get`; had the name collided with a C library symbol
    # the image would have bound that and computed a plausible wrong number.
    ("refuse_a_method_call_on_a_subscripted_receiver",
     "struct Box:\n"
     "    var k: Int\n"
     "    def get(self) -> Int:\n"
     "        return self.k\n\n"
     "def drain(vals: List, i: Int) -> Int:\n"
     "    return vals[i].get()\n\n"
     "def main(n: Int) -> Int:\n"
     "    return 0\n",
     "What is missing is the receiver's TYPE"),

    # …and the receiver is quoted back AS THE SOURCE SPELLS IT.  `vals[i]`, not
    # `vals[IntLiteral]` — a refusal whose evidence is an AST node class name is
    # a refusal a reader has to decode before they can act on it, and this is a
    # separate assertion because a spelling fix and a refusal fix are two
    # changes that can each land alone.  The index is a NAME here rather than a
    # literal, which is the harder half of the spelling: both spellings come
    # from `model.receiver_shape_text`.
    ("refuse_a_subscripted_receiver_is_spelled_as_written",
     "struct Box:\n"
     "    var k: Int\n"
     "    def get(self) -> Int:\n"
     "        return self.k\n\n"
     "def drain(vals: List, i: Int) -> Int:\n"
     "    return vals[i].get()\n\n"
     "def main(n: Int) -> Int:\n"
     "    return 0\n",
     "`vals[i].get(…)` cannot be lowered"),

    # **GUARD** — a method the element's struct does NOT declare, while another
    # struct in the SAME MODULE does.  This is the guard the lift needs: the
    # element type is what decides the callee, so a name `owners` knows must not
    # be bound to the struct that declares it when the receiver holds another.
    # `bs[0].peek()` must be refused rather than lifted to `Other_peek(bs[0])`,
    # which would be a plausible-looking wrong answer — `Other` has the same
    # shape and the same method body, so nothing downstream would notice.
    ("refuse_a_method_the_element_struct_does_not_declare",
     "struct Box:\n"
     "    var k: Int\n"
     "    def get(self) -> Int:\n"
     "        return self.k\n\n"
     "struct Other:\n"
     "    var k: Int\n"
     "    def peek(self) -> Int:\n"
     "        return self.k\n\n"
     "def main(n: Int) -> Int:\n"
     "    var bs = [Box(), Box()]\n"
     "    return bs[0].peek()\n",
     "`bs[0].peek(…)` cannot be lowered"),

    # ── a CALL RESULT as the receiver, and the TWO SPELLINGS of that one call ──
    #
    # `m.make().take(r)` and `m.make().take[r](r)` are the same call — the
    # brackets bind a specialization, which is not part of what the callee names
    # — and before 2026-10-03 they got two different answers, neither of them a
    # refusal at the construct:
    #
    #   m.make().take(r)     the LINK AUDIT: "the image would bind 1 symbol(s)
    #                        that nothing provides: take"
    #   m.make().take[r](r)  the EMITTER: "unsupported call target on the formal
    #                        arm64 path (got SubscriptExpr)"
    #
    # The second names the compiler's node type for a call whose only problem is
    # its receiver, and the first is the sentence
    # `formal/model.py`'s `subscript_receiver_method_refusal` calls "worse than a
    # wrong number because it is usually silent": a symbol spelled after the
    # METHOD can also COLLIDE with a real one, and then the image binds that and
    # computes a plausible wrong answer with nothing reporting a failure.
    #
    # One case per spelling, and that is the whole assertion: they must refuse
    # with the SAME words. A reader who fixed only one of them would leave the
    # other reporting a link line or a node class, and the suite would be green
    # on both counts as long as each was checked alone.
    #
    # `m.make()` returns a two-field struct, so the receiver would be a FRAME
    # ADDRESS if it were established at all — the shape the family is about
    # rather than a one-word struct that would pass through unrepresentably.
    ("refuse_a_method_call_on_a_call_result_receiver",
     "struct R:\n"
     "    var a: Int\n"
     "    var b: Int\n\n"
     "struct Maker:\n"
     "    var a: Int\n"
     "    var b: Int\n"
     "    def make(self) -> Maker:\n"
     "        var q = Maker()\n"
     "        q.a = self.b\n"
     "        q.b = self.a\n"
     "        return q\n"
     "    def take(self, r: R) -> Int:\n"
     "        return self.a + r.a\n\n"
     "def main(n: Int) -> Int:\n"
     "    var m = Maker()\n"
     "    m.a = 1\n"
     "    m.b = 2\n"
     "    var r = R()\n"
     "    r.a = 3\n"
     "    r.b = 4\n"
     "    return m.make().take(r)\n",
     "`m.make().take(…)` cannot be lowered"),

    # The same call, SPECIALIZED. The needle is the one above on purpose: a
    # specialization that reported a different construct would be the defect
    # again, one level down.
    ("refuse_a_specialized_method_call_on_a_call_result_receiver_too",
     "struct R:\n"
     "    var a: Int\n"
     "    var b: Int\n\n"
     "struct Maker:\n"
     "    var a: Int\n"
     "    var b: Int\n"
     "    def make(self) -> Maker:\n"
     "        var q = Maker()\n"
     "        q.a = self.b\n"
     "        q.b = self.a\n"
     "        return q\n"
     "    def take[T: Int](self, r: R) -> Int:\n"
     "        return self.a + r.a + T\n\n"
     "def main(n: Int) -> Int:\n"
     "    var m = Maker()\n"
     "    m.a = 1\n"
     "    m.b = 2\n"
     "    var r = R()\n"
     "    r.a = 3\n"
     "    r.b = 4\n"
     "    return m.make().take[7](r)\n",
     "`m.make().take(…)` cannot be lowered"),

    # …and the OTHER call-result receiver, which is a different spelling with a
    # different reason to be refused and was reaching the LINK AUDIT instead.
    # `Box()` is a CONSTRUCTION of a struct this module declares, so its type is
    # not in question at all — the declaration settles it — and what the lift
    # still cannot do is name a RECEIVER, because the call carries none.  Before
    # this was refused at the construct, `Box().get()` built and died at the link
    # with "the image would bind 1 symbol(s) that nothing provides: get", which
    # is the sentence `formal/model.py`'s `subscript_receiver_method_refusal`
    # calls worse than a wrong number because it is silent: a symbol spelled after
    # the METHOD can collide with a real one and the image then computes a
    # plausible wrong answer with nothing reporting a failure.
    #
    # `Box` is a ONE-FIELD struct here on purpose, because that is the shape the
    # refusal's ADVICE runs into: it tells the reader to bind the receiver to a
    # local of a declared struct type, and whether that advice answers this
    # program is a separate question with its own answer
    # (`bugs/FORMAL_method_call_on_a_construction_is_not_rewritten.md`). A
    # two-field receiver builds and computes, so this row is not the only place
    # the two shapes could have been confused.
    ("refuse_a_method_call_on_a_construction_receiver",
     "struct Opt:\n"
     "    var v: Int\n"
     "    var has: Int\n\n"
     "struct Box:\n"
     "    var inner: Opt\n\n"
     "    def get(self) -> Int:\n"
     "        return self.inner.v\n\n"
     "def main() -> int:\n"
     "    return Box().get()\n",
     "`Box().get(…)` cannot be lowered"),

    # A ONE-FIELD holder's method reading the nested frame NOTHING built. The
    # same `Box` as the row above and the same ten lines without the
    # construction, and the difference is the whole of it: a one-word struct's
    # receiver IS its field's storage, `model.one_word_sole_field_frame` made
    # that storage an ADDRESS, and `Box()` fills the WORD rather than the frame
    # the word will hold — so `self.inner.v` is a load at address 0. Measured on
    # both architectures as SIGSEGV, exit 139, with no output at all.
    #
    # CPython raises `AttributeError` for this program (`Box` has no attribute
    # `inner`), so there is no number to be differential against and a REFUSAL
    # is the whole of the answer — which is why this is in this table and not
    # in the differential one. The needle is the middle of the sentence, so a
    # refusal that lost its repair would still fail the row.
    ("refuse_a_one_field_holder_reading_a_frame_nothing_built",
     "struct Opt:\n"
     "    var v: Int\n"
     "    var has: Int\n\n"
     "struct Box:\n"
     "    var inner: Opt\n\n"
     "    def get(self) -> Int:\n"
     "        return self.inner.v\n\n"
     "def main() -> int:\n"
     "    var b = Box()\n"
     "    return b.get()\n",
     "reads Box's only field 'inner', a slot whose declared type is the "
     "framed struct Opt, and nothing in this function has put a frame there"),

    # THE SAME CONSTRUCT WRITTEN THROUGH instead of read, which is the write
    # half of the pair and used to be answered by a DIFFERENT rule — one that
    # named `b.v` where the source says `b.inner.v`, so the refusal pointed at
    # an expression the reader never wrote. It is pinned here because a rule that
    # took the read half over must not have lost the write half with it, and
    # because the repair this one names (`b.inner = Opt()` before the call) is
    # the repair for both.
    ("refuse_a_store_through_a_one_field_holders_unbuilt_frame",
     "struct Opt:\n"
     "    var v: Int\n"
     "    var has: Int\n\n"
     "struct Box:\n"
     "    var inner: Opt\n\n"
     "    def get(self) -> Int:\n"
     "        return self.inner.v\n\n"
     "def main() -> int:\n"
     "    var b = Box()\n"
     "    b.inner.v = 5\n"
     "    return b.get()\n",
     "reads Box's only field 'inner', a slot whose declared type is the "
     "framed struct Opt, and nothing in this function has put a frame there"),
]

# ── the comptime ABI, now on BOTH architectures ────────────────────────────
#
# These move here from the differential table because they were the cases the
# x86-64 refusal blocked, and they are the anti-rot direction for the ABI: each
# builds on BOTH machines and its answer must equal CPython's.  If either half
# of the convention is removed from one backend alone, this goes red on a
# WRONG NUMBER rather than on a refusal — which is the whole point, since a
# refusal is a legible failure and `f(3, 7)` returning 3 instead of 307 is not.
#
# Three rows, and each one is a different way the two halves can come apart:
#
#   * `f[1](3, 7)` — the bracket expression. The callee has a home for `type`
#     and the caller fills it with 1. A prologue that ignored the comptime
#     parameter would read `x` from the register `type` was passed in.
#   * `f(3, 7)` — the BARE spelling of the same generic, which binds every
#     comptime parameter to 0 (`comptime_eval.specialization_args`'s answer, and
#     therefore the same on both). The two spellings cannot disagree about the
#     callee's arity because both go through one parameter list, and this row
#     is what proves it: it is the case that reads most wrong if a backend
#     passes only the runtime arguments.
#   * a comptime parameter that is READ in the body, so a home that exists but
#     is never stored shows up as 0 rather than as a refusal.
#
# (name, mojo_source, python_source)
COMPTIME_ABI_CASES = [
    # `printf` and a `return 0`, as every other case here: a process exit status
    # is ONE BYTE on this host, and 307 & 0xFF == 51 — so an exit-status
    # expectation for these answers would pass on a backend that returned the
    # right number for the wrong reason.
    ("comptime_abi_bracket_expression",
     "def f[type: Int](x: Int, y: Int) -> Int:\n"
     "    return x * 100 + y\n\n"
     "def main(n: Int) -> Int:\n"
     '    printf("v=%d", f[1](3, 7))\n'
     "    return 0\n",
     "def f(type, x, y):\n"
     "    return x * 100 + y\n\n"
     "def main():\n"
     '    print("v=%d" % f(1, 3, 7), end="")\n'
     "    return 0\n\n"
     "main()\n"),
    ("comptime_abi_bare_call_binds_zero",
     "def f[type: Int](x: Int, y: Int) -> Int:\n"
     "    return x * 100 + y\n\n"
     "def main(n: Int) -> Int:\n"
     '    printf("v=%d", f(3, 7))\n'
     "    return 0\n",
     "def f(type, x, y):\n"
     "    return x * 100 + y\n\n"
     "def main():\n"
     '    print("v=%d" % f(0, 3, 7), end="")\n'
     "    return 0\n\n"
     "main()\n"),
    ("comptime_abi_the_parameter_is_read",
     "def pick[type: Int](x: Int, y: Int) -> Int:\n"
     "    return type * 1000 + x * 10 + y\n\n"
     "def main(n: Int) -> Int:\n"
     '    printf("v=%d", pick[4](3, 7))\n'
     "    return 0\n",
     "def pick(type, x, y):\n"
     "    return type * 1000 + x * 10 + y\n\n"
     "def main():\n"
     '    print("v=%d" % pick(4, 3, 7), end="")\n'
     "    return 0\n\n"
     "main()\n"),
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

    Not `fire.py run` and not the interpreter in this repository.  The point of a
    differential case is that the two answers come from two independent
    implementations of the language, and `myinterpreter.py` is not one of them
    — it shares the AST, so a mistake in the AST cannot be caught by comparing
    against it.
    """
    path = os.path.join(tmpdir, "oracle.py")
    with open(path, "w") as f:
        f.write(source)
    return subprocess.run([sys.executable, path], capture_output=True, text=True,
                          timeout=RUN_TIMEOUT)


def run_diff_case(case, tmpdir, verbose):
    """CPython's answer, then the image's answer, and require the two to agree.

    The order is the order of trust: the oracle runs FIRST, so a broken
    expectation is reported as a broken expectation and not as a consistently
    wrong backend.  A case whose Python twin does not produce the answer the
    case is about is a bug in the case.

    BOTH architectures, and both must match CPython.  It was `COMPTIME_ABI`
    alone while x86-64 refused the construct; now that the two backends share
    the comptime ABI (see the module docstring), a one-sided assertion would be
    the weaker of the two and would let exactly the regression this file exists
    to catch back in: a backend whose prologue stopped allocating a home for a
    comptime parameter still builds, still runs, and returns a number no source
    wrote — a failure a refusal-shaped expectation cannot see.
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
            return False, (f"--backend={backend} did not build: "
                           f"{text.strip()[-300:]}")
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
    """BOTH backends must refuse, and both must refuse with the needle.

    Both architectures, because a refusal raised by the shared build pass has to
    be the same refusal on both — a construct one machine stops and the other
    lowers is precisely the divergence this backend's design is built to make
    impossible.
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


# ── the SPELLING cases: there is ONE spelling function, and what it says ────
#
# A refusal that quotes a call site quotes it with `_expr_spelling`, and every
# row in `REFUSALS` that pins a needle is really pinning the spelling too —
# `refuse_disagreement_spells_both_call_sites` above says so in its own comment.
# That makes the function itself worth a row, because it is the one place where
# "the message is right" and "the function is right" can come apart.
#
# THEY DID. `formal/build.py` carried
#
#     _expr_spelling = M.expr_spelling
#
# and then, three lines below, a `def _expr_spelling` that shadowed the alias —
# the older of the two, from before the model needed a spelling of its own. The
# comment above the alias claimed the model owned the one implementation, so the
# comment described a state the file was not in, and the model was the newer HALF
# of a pair rather than the whole of it. The two copies disagreed on the shape
# that matters most in this file's own corpus: the older one's `CallExpr` arm
# required a BARE `IdentExpr` callee, so `g[1](r, 1)` — which
# `refuse_disagreement_spells_both_call_sites` gets right through
# `subscript_chain_text`, because a specialization's callee is a SUBSCRIPT — and
# a dotted subscripted method call both came out as the bare text `CallExpr`.
#
# So these are UNIT rows, with no build: the defect is a second implementation
# existing, and a build can only observe it through whichever message a given
# program happens to reach. The table below is read through the SAME alias the
# build pass calls, so a second `def` shadowing it is caught by the identity
# assertion and not by any of the spellings.
SPELLINGS = [
    # (name, source, [(what to pull out of the parse, expected spelling)])
    #
    # The whole point: a callee that is not a bare name. Measured before the fix
    # (same input, both spellings, no build):
    #
    #     model.expr_spelling  : c.f[0]()
    #     build._expr_spelling : CallExpr
    ("a_call_whose_callee_is_a_subscript",
     "def g(c):\n"
     "    return c.f[0]()\n",
     [("CallExpr", "c.f[0]()"),
      ("SubscriptExpr", "c.f[0]"),
      ("MemberExpr", "c.f")]),

    ("a_call_whose_callee_is_a_specialized_member",
     "def g(m):\n"
     "    return m.reduction[0](3)\n",
     [("CallExpr", "m.reduction[0](3)")]),

    # The two arms the DELETED copy alone carried. `BinaryOp` is not cosmetic:
    # `test_formal_globals.py`'s `local_shadow_of_global_read_before_store_
    # refused` asserts the needle `at \`G + 1\``, so a deletion that dropped the
    # arm would turn that row's message into `at \`BinaryOp\`` — still a refusal,
    # still true, and still unreadable, which is why the arm is ported rather
    # than lost. `SetExpr` has no end-to-end row; it is here because a set
    # literal in a message about a stored value is a set literal the reader can
    # find in their own file.
    ("a_binary_operator_and_a_set_display",
     "def g():\n"
     "    G = 1 + 2\n"
     "    S = {1, 2}\n"
     "    return G\n",
     [("BinaryOp", "1 + 2"),
      ("SetExpr", "{1, 2}")]),

    # The shapes the MODEL's copy carried and the deleted one did not, so that
    # deleting it is not a regression in the other direction: a string literal is
    # QUOTED (`repr`) rather than printed as a bare name the file does not
    # contain, and a dict display is `{…}` rather than `DictExpr`.
    ("a_string_literal_is_quoted_and_a_dict_display_is_an_ellipsis",
     "def g():\n"
     "    A = 'hi'\n"
     "    D = {}\n"
     "    return A\n",
     [("StringLiteral", "'hi'"),
      ("DictExpr", "{…}")]),

    # `not x` rather than `notx`: the model's unary arm spells the word with a
    # space, and the deleted copy produced `f"{op}{operand}"` — `notx`, an
    # identifier the file does not contain.
    ("a_unary_not_has_its_space",
     "def g(x):\n"
     "    return not x\n",
     [("UnaryOp", "not x")]),
]


def run_spelling_case(case, tmpdir, verbose):
    """ONE spelling function, and the spellings below.

    The identity is asserted first and separately, because it is the defect: a
    second `def _expr_spelling` in `formal/build.py` restores every spelling the
    table above already pins (the copy that shadowed the alias spelled all of
    them, and `BinaryOp`/`SetExpr` are the two it alone carried) and would be
    caught by nothing else here.
    """
    import inspect

    import fire_compiler as F
    import formal.build as FB
    import formal.model as M

    if FB._expr_spelling is not M.expr_spelling:
        return False, ("formal/build.py::_expr_spelling is not "
                       "formal/model.py::expr_spelling — there are two "
                       "implementations and the build pass calls its own")
    _lines, first = inspect.getsourcelines(M.expr_spelling)
    if not _lines[0].lstrip().startswith("def "):
        return False, ("model.expr_spelling's own source does not begin with a "
                       "`def`, so the alias above it stands for something else")

    name, source, want = case
    stmts = F.Parser(F.py_tokenize_named(source, name + ".mojo")).parse_module()
    kinds = {k for k, _ in want}
    got = {}
    for node in M.iter_nodes(stmts):
        kind = type(node).__name__
        if kind in kinds and kind not in got:
            got[kind] = M.expr_spelling(node)
    for kind, expect in want:
        if kind not in got:
            return False, f"the case produced no {kind} to spell"
        if got[kind] != expect:
            return False, (f"expr_spelling({kind}) == {got[kind]!r}, expected "
                           f"{expect!r} — the source's own spelling is what a "
                           f"refusal quotes, and this is a placeholder")
    if verbose:
        print("      " + ", ".join(f"{k}={got[k]!r}" for k, _ in want))
    return True, ""


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("-v", "--verbose", action="store_true")
    ap.add_argument("cases", nargs="*", help="subset of case names")
    args = ap.parse_args()

    if platform.machine() not in ("arm64", "aarch64"):
        print(f"SKIP: formal output is arm64-only, host is {platform.machine()}")
        return 0

    diff_names = {c[0] for c in DIFF_CASES}
    refuse_names = {c[0] for c in REFUSALS}
    abi_names = {c[0] for c in COMPTIME_ABI_CASES}
    spelling_names = {c[0] for c in SPELLINGS}
    runners = [
        (DIFF_CASES, diff_names, run_diff_case),
        (REFUSALS, refuse_names, run_refusal_case),
        (COMPTIME_ABI_CASES, abi_names, run_diff_case),
        (SPELLINGS, spelling_names, run_spelling_case),
    ]
    everything = [c for group, _n, _r in runners for c in group]
    known = {c[0] for c in everything}
    selected = [c for c in everything if not args.cases or c[0] in args.cases]
    if args.cases and len(selected) != len(args.cases):
        print(f"ERROR: unknown case(s): {sorted(set(args.cases) - known)}",
              file=sys.stderr)
        return 2

    passed = failed = 0
    with tempfile.TemporaryDirectory() as tmpdir:
        for case in selected:
            name = case[0]
            runner = next(r for _g, n, r in runners if name in n)
            try:
                ok, detail = runner(case, tmpdir, args.verbose)
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
    print(f"\nformal receiver position: PASS={passed} FAIL={failed}")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
