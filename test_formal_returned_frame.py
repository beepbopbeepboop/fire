#!/usr/bin/env python3
"""The returned-frame convention: build it, RUN it, and compare with CPython.

A multi-field struct's receiver on this path is the ADDRESS of a frame of
8-byte slots in the function's own scratch, so `return p` used to hand the
caller a pointer into reclaimed stack — which is why `formal/build.py` refused
it, correctly, and why 11 of this repository's own arm64 sweep findings named
that one line. The refusal is gone because the block is now COPIED into a
block the CALLER reserves and passes the address of as one hidden trailing
argument (`model.struct_returned_frame_sites`,
`model.returned_frame_convention_refusal`).

Lifting a refusal is half the work: the image that builds in its place has to be
RIGHT, and "right" here means it runs and computes the program's answer. So
every positive case is built for BOTH architectures, EXECUTED, and its answer
compared against CPython — not against a number typed in here, because a wrong
answer that matches a mistyped constant is still a wrong answer.

**TWO ORACLES, and neither of them is a hand-written expectation.** The first
is one text read by two runtimes, which is why every `CASES` entry is written
in the `class` / `def __init__` spelling: it is a Python program, so CPython
can run it. The channel is the EXIT STATUS, and that is not a limitation — a
formal image's status is its entry function's return value masked to a byte, and
`sys.exit(int)` is masked to a byte by CPython's own exit path, so the two
runtimes share an oracle exactly.

The second is for the answers that do not fit in a byte: `DIFF_CASES` carries
the program twice, once as Mojo and once as plain Python, and compares STDOUT
and the status across both images and the oracle. That is the discipline
`test_formal_frame_len.py` set for the neighbouring construct and
`test_interp_oracle.py` for the other engine — two independent implementations
of the language that have to agree, rather than a third reading of the spec that
agrees with the wrong one exactly where nobody thought about it. `printf` is the
channel there because a process exit status is one byte and some of these
answers are bigger than 255.

The `refuse` cases are the other half: the shapes the convention still cannot
describe must not build on either machine, and must say why in the same words.

    python3 test_formal_returned_frame.py [-v] [case ...]
"""
import argparse
import os
import platform
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
FIRE = os.path.join(HERE, "fire.py")
BACKENDS = ("arm64", "x86_64")
BUILD_TIMEOUT = 180
RUN_TIMEOUT = 60

# The argument the entry function is called with. `formal/build.py`'s
# `test_input` default is 10 and the startup stub is what passes it, so the
# oracle calls `main` with the same number rather than with whatever is
# convenient here. No case below reads it.
ENTRY_ARG = 10

# The two-field struct every case below is written in terms of.
#
# The `class` / `def __init__` SPELLING, and the reason every positive case
# uses it: it is also a Python program, so CPython can be the reference rather
# than a number written by hand. `struct R: var a: Int` is not Python syntax,
# so a case written that way has to carry its own expectation — which is the
# `expect` mode below, used exactly once, for the one shape whose reference
# Python cannot provide.
R2 = ("class R:\n"
      "    def __init__(self):\n"
      "        self.a = 0\n"
      "        self.b = 0\n"
      "    def total(self):\n"
      "        return self.a * 10 + self.b\n")

# (name, source, mode, expectation) — `ok` compares against CPython on the same
# text, `expect` is a hand-computed value with the arithmetic in the case's own
# comment, and `refuse` must fail to build on both machines naming `expectation`.
CASES = [
    # ── the plain shape, with the use-after-free it replaces ────────────
    # `clobber` builds two frames of its own between the call and the read.
    # Without the copy, the block the caller holds names the callee's reclaimed
    # scratch, and this returns one of the two frames clobber wrote instead of
    # the caller's — measured on the pre-convention tree as 10 on arm64 and 0 on
    # x86-64 where the source says 78.
    ("returned_frame_outlives_its_creator",
     R2 +
     "def mk():\n"
     "    p = R()\n"
     "    p.a = 7\n"
     "    p.b = 8\n"
     "    return p\n"
     "\n"
     "def clobber(k):\n"
     "    q = R()\n"
     "    r = R()\n"
     "    q.a = 111\n"
     "    r.a = 222\n"
     "    return k + q.a + r.a\n"
     "\n"
     "def main(n):\n"
     "    s = mk()\n"
     "    k = clobber(0)\n"
     "    return s.total() + k\n", "ok", 0),

    # ── three fields, and a THREE-SLOT copy ─────────────────────────────
    # The width is the point: the block is `8 * n` rounded up, so a copy that
    # hard-coded two slots would leave the third field at its default and this
    # would be 340 rather than 345.
    ("returned_frame_three_fields",
     "class W:\n"
     "    def __init__(self):\n"
     "        self.p = 0\n"
     "        self.q = 0\n"
     "        self.r = 0\n"
     "\n"
     "def mk(k):\n"
     "    w = W()\n"
     "    w.p = k\n"
     "    w.q = k + 1\n"
     "    w.r = k + 2\n"
     "    return w\n"
     "\n"
     "def main(n):\n"
     "    w = mk(3)\n"
     "    return w.p * 100 + w.q * 10 + w.r\n", "ok", 0),

    # ── a NESTED frame, which is the half that is easy to get wrong ─────
    # `inner` is a framed struct of this module and nothing writes it, so the
    # constructor PLACES its frame inside `Outer`'s own block and the slot
    # holds its address. A returned block has to carry those bytes AND
    # re-point the slot at the COPY: copying the bytes without re-pointing
    # leaves the caller's `o.inner` naming a frame in the callee's reclaimed
    # scratch. Two reads of the same nested field, with a call in between, is
    # what tells a re-point from a copy.
    #
    # The one `expect` case: the nested placement needs the field's DECLARED
    # type and only a `struct` field declaration carries one, so this program is
    # not a Python program and CPython cannot be its reference. The arithmetic,
    # once: `o.inner.a * 100 + o.inner.b * 10 + o.z` is 9*100 + 4*10 + 3 = 943,
    # read twice and added is 1886, and 1886 masked to a byte is 94. A copy
    # without the re-point reads the clobbered 111s and gives 22446 -> 174.
    ("returned_frame_carries_its_nested_frame",
     "struct Inner:\n"
     "    var a: Int\n"
     "    var b: Int\n"
     "struct Outer:\n"
     "    var inner: Inner\n"
     "    var z: Int\n"
     "def mk() -> Outer:\n"
     "    var o = Outer()\n"
     "    o.inner.a = 9\n"
     "    o.inner.b = 4\n"
     "    o.z = 3\n"
     "    return o\n"
     "def clobber(k: Int) -> Int:\n"
     "    var q = Inner()\n"
     "    q.a = 111\n"
     "    q.b = 111\n"
     "    return k + q.a\n"
     "def main(n: Int) -> Int:\n"
     "    var o = mk()\n"
     "    var s = o.inner.a * 100 + o.inner.b * 10 + o.z\n"
     "    var k = clobber(0)\n"
     "    var t = o.inner.a * 100 + o.inner.b * 10 + o.z\n"
     "    return s + t\n", "expect", 94),

    # ── a frame RECEIVED as a parameter, handed straight back ───────────
    # The creator is the caller, and the copy happens while the caller's frame
    # is still live — which is the whole of what makes this sound, and the
    # reason the old refusal ("returned from a function that did not create
    # it") named the right hazard and the wrong remedy.
    ("returned_frame_from_a_parameter",
     R2 +
     "def fwd(r):\n"
     "    return r\n"
     "\n"
     "def main(n):\n"
     "    r = R()\n"
     "    r.a = 4\n"
     "    r.b = 5\n"
     "    return fwd(r).a * 10 + fwd(r).b\n", "ok", 0),

    # …and through a method's receiver, which is the same copy with the
    # address arriving in the receiver's home.
    ("returned_frame_from_a_method_receiver",
     R2 +
     "    def give(self):\n"
     "        return self\n"
     "\n"
     "def main(n):\n"
     "    r = R()\n"
     "    r.a = 4\n"
     "    r.b = 5\n"
     "    return r.give().a * 10 + r.give().b\n", "ok", 0),

    # ── two live results at once, which is what killed a fixed slot ─────
    # The design rejected "the callee computes the caller's block itself"
    # precisely because one fixed slot collides here: the inner and outer
    # results must both be readable after the outer call returns. With the
    # per-call-site blocks the two are distinct addresses, and a fixed slot
    # would make both reads see the inner result.
    ("returned_frame_nested_calls_two_blocks",
     R2 +
     "def inner(k):\n"
     "    r = R()\n"
     "    r.a = k\n"
     "    r.b = 1\n"
     "    return r\n"
     "\n"
     "def outer(k):\n"
     "    t = inner(k)\n"
     "    t.b = 2\n"
     "    return t\n"
     "\n"
     "def main(n):\n"
     "    a = inner(3)\n"
     "    b = outer(7)\n"
     "    return a.total() * 100 + b.total()\n", "ok", 0),

    # ── a returned frame in a LOOP ──────────────────────────────────────
    # The block is per CALL SITE and reserved in the prologue, so a call inside
    # a loop reuses one block and the stack cannot grow without bound. Read
    # immediately, which is the only lifetime the reserved block has.
    ("returned_frame_in_a_loop",
     R2 +
     "def mk(k):\n"
     "    r = R()\n"
     "    r.a = k\n"
     "    r.b = 1\n"
     "    return r\n"
     "\n"
     "def main(n):\n"
     "    s = 0\n"
     "    for i in range(4):\n"
     "        t = mk(i)\n"
     "        s = s + t.total()\n"
     "    return s\n", "ok", 0),

    # ── a frame returned through a NON-FIRST parameter, three levels deep ──
    ("returned_frame_three_levels",
     R2 +
     "def stash(x, y):\n"
     "    return y\n"
     "\n"
     "def mid(r):\n"
     "    return stash(1, r)\n"
     "\n"
     "def main(n):\n"
     "    r = R()\n"
     "    r.a = 6\n"
     "    r.b = 7\n"
     "    p = mid(r)\n"
     "    return p.a * 10 + p.b\n", "ok", 0),

    # ── a function with more locals than callee-saved registers ─────────
    # The hidden word is an ordinary local, so it has the same two homes every
    # other local has, and this is the case that says the SPILLED home is
    # addressed the same way the register home is. Eleven locals is past
    # arm64's ten callee-saved registers and well past x86-64's five, so the
    # word spills on both. It caught a real bug: the spill half of the
    # prologue's parameter path stored the ADDRESS of the slot through the
    # register holding the value, and that path had been unreachable only
    # because nothing could make an eleventh local.
    ("returned_frame_with_spilled_locals",
     R2 +
     "def mk(k):\n" +
     "".join(f"    v{i} = {i}\n" for i in range(11)) +
     "    r = R()\n"
     "    r.a = k + v10\n"
     "    r.b = 1\n"
     "    return r\n"
     "\n"
     "def main(n):\n"
     "    s = mk(2)\n"
     "    return s.total()\n", "ok", 0),

    # ── a METHOD called on a returned frame ─────────────────────────────
    # The result is a frame, so `q.total()` is a method call whose receiver is
    # a frame address — the by-reference convention's own shape, reached
    # through the return.
    ("method_on_a_returned_frame",
     R2 +
     "    def bump(self, v):\n"
     "        self.a = self.a + v\n"
     "        return self.a\n"
     "\n"
     "def mk():\n"
     "    r = R()\n"
     "    r.a = 1\n"
     "    r.b = 2\n"
     "    return r\n"
     "\n"
     "def main(n):\n"
     "    q = mk()\n"
     "    q.bump(5)\n"
     "    return q.total() * 10 + q.bump(1)\n", "ok", 0),

    # ── the ENTRY, which has no caller to give it a block ───────────────
    ("refuse_entry_returning_a_frame",
     "struct R:\n"
     "    var a: Int\n"
     "    var b: Int\n"
     "def main(n: Int) -> Int:\n"
     "    var r = R()\n"
     "    r.a = 1\n"
     "    return r\n", "refuse",
     "is this image's ENTRY"),

    # ── a frame on one path and a value on another ──────────────────────
    # One function cannot have two return conventions in one image: the caller
    # has to decide BEFORE the call whether to reserve a block, and there is no
    # reading of this program under which both branches are right.
    ("refuse_a_frame_and_a_value_on_two_paths",
     "struct R:\n"
     "    var a: Int\n"
     "    var b: Int\n"
     "def mk(c: Int) -> Int:\n"
     "    var r = R()\n"
     "    r.a = 1\n"
     "    r.b = 2\n"
     "    if c:\n"
     "        return r\n"
     "    return 7\n"
     "def main(n: Int) -> Int:\n"
     "    return mk(1)\n", "refuse",
     "one function cannot have two return conventions"),

    # ── a frame on one path and the body ENDS on another ─────────────────
    # The caller's block would be read without ever being written, and the one
    # thing this path must never invent is a struct's contents. A second
    # `return` would be the previous case; this one is the shape where there is
    # nothing to return at all.
    ("refuse_a_frame_that_falls_off_the_end",
     "struct R:\n"
     "    var a: Int\n"
     "    var b: Int\n"
     "def mk(c: Int) -> Int:\n"
     "    var r = R()\n"
     "    r.a = 1\n"
     "    r.b = 2\n"
     "    if c:\n"
     "        return r\n"
     "    printf(\"%d\\n\", c)\n"
     "def main(n: Int) -> Int:\n"
     "    return mk(1)\n", "refuse",
     "falls off the end of its body on another"),

    # ── the hidden word has nowhere to go ────────────────────────────────
    # Six source arguments is the whole budget on the machine with the smaller
    # one (x86-64 passes integer arguments in six registers), so the seventh
    # word — the caller's block — has no register. Refused by name on both
    # machines rather than dropped, because a dropped word is a copy into
    # whatever the register held.
    # SIX source arguments is the whole budget, and the reason is the hidden
    # word rather than the arity: both ABIs put arguments past the register file
    # in the caller's frame (`_MAX_INCOMING_ARGS` in both backends, 2026-10-02),
    # so `mk` could take twenty-three and still be given its block — by a
    # different path, which does not exist.  The hidden word is moved home by
    # each backend's REGISTER path and nothing else, so what runs out is the
    # registers and not the frame.  This row is the anti-rot for that decision
    # (`model.RETURNED_FRAME_MAX_ARGS` and `test_returned_frame_layout.py` carry
    # the reasoning); it is stated first because it is the one a reader meets
    # first, and the eight-argument row below is now its sibling rather than the
    # other half of a machine-dependent budget.
    ("refuse_a_callee_with_no_argument_register_left",
     "struct R:\n"
     "    var a: Int\n"
     "    var b: Int\n"
     "def mk(p0: Int, p1: Int, p2: Int, p3: Int, p4: Int, p5: Int) -> Int:\n"
     "    var r = R()\n"
     "    r.a = p0 + p1 + p2 + p3 + p4 + p5\n"
     "    r.b = 2\n"
     "    return r\n"
     "def main(n: Int) -> Int:\n"
     "    return mk(1, 2, 3, 4, 5, 6).a\n", "refuse",
     "one hidden word for the caller's block"),

    # A DIFFERENT program from `refuse_entry_returning_a_frame` above, and the
    # gap is one step further out: that one has the entry build the frame
    # itself, this one has the entry RECEIVE one and return it. The startup stub
    # still has no block to give `main`, so the refusal is the entry's either
    # way — but the object being handed back came out of a callee, which is the
    # shape a fix that taught only the local case would get wrong.
    #
    # The NEEDLE is this tree's message rather than `formal-frame-escape`'s, and
    # the two refusals are the same decision asked from two sides: theirs was
    # "the entry returns a frame, and nothing can supply the block", this one
    # is "the entry has nowhere to put the COPY, so the address it would hand
    # back names a frame that dies here".  Both are true of this program, and
    # naming the one this tree actually raises is what makes the case a
    # regression detector rather than a description of another branch.
    ("refuse_the_entry_returning_a_frame_a_callee_built",
     "struct Point:\n"
     "    var x: Int\n"
     "    var y: Int\n"
     "\n"
     "def make():\n"
     "    var p = Point()\n"
     "    p.x = 1\n"
     "    p.y = 2\n"
     "    return p\n"
     "\n"
     "def main(n):\n"
     "    var p = make()\n"
     "    return p\n",
     "refuse",
     "the address it would return names a frame that dies with this "
     "function"),
    ("refuse_a_call_in_a_position_that_binds_no_name",
     "struct Point:\n"
     "    var x: Int\n"
     "    var y: Int\n"
     "\n"
     "def make(a):\n"
     "    var p = Point()\n"
     "    p.x = a\n"
     "    p.y = 1\n"
     "    return p\n"
     "\n"
     "def take(p):\n"
     "    return p.x\n"
     "\n"
     "def main(n):\n"
     "    return take(make(5))\n",
     "refuse",
     "this path has no way to say what 'p' holds"),
    # THE SUBSCRIPT SPELLING, and the one of theirs' cases whose refusal this
    # tree did NOT have.  `formal-frame-escape` refused it by name; here the
    # block is reserved for EVERY call site of a frame-returning callee, so the
    # escape check saw an ordinary assignment — the right-hand side is a CALL,
    # and it was looking for a NAME — and the emitter's subscript store does not
    # lower a frame address, so the store was dropped.  Measured on the merged
    # tree before the fix: builds, runs, exits 0 where the source says 5.
    #
    # So the case stays a refusal, with THIS tree's message: `q[0] = r` and
    # `xs[1] = make(5)` are the same escape with the frame one lifetime further
    # out, and `_defer_subscript_escape` now reads the fixpoint's by-name
    # returned-frame table so it can see the second shape.
    ("refuse_a_returned_frame_stored_through_a_subscript",
     "struct Point:\n"
     "    var x: Int\n"
     "    var y: Int\n"
     "\n"
     "def make(a):\n"
     "    var p = Point()\n"
     "    p.x = a\n"
     "    p.y = 1\n"
     "    return p\n"
     "\n"
     "def main(n):\n"
     "    var xs = [0, 0, 0]\n"
     "    xs[1] = make(5)\n"
     "    return xs[1]\n",
     "refuse",
     "is stored through 'xs[1]' in main()"),

    # EIGHT arguments, which is arm64's register count and used to be the
    # machine-dependent half of this budget.  It is not a second budget now: both
    # backends pass source arguments in the caller's frame past the register
    # file, so EIGHT and SIX are refused for the ONE reason above, and this row
    # exists to say that a change which gave the hidden word a stack slot would
    # have to move both. `main` deliberately does not CALL `make` here: the
    # budget is counted from the DECLARED parameter list, so this refuses on both
    # architectures without depending on which of them is over budget for some
    # other reason.
    ("refuse_a_callee_declaring_eight_arguments",
     "struct Point:\n"
     "    var x: Int\n"
     "    var y: Int\n"
     "\n"
     "def make(a, b, c, d, e, f, g, h):\n"
     "    var p = Point()\n"
     "    p.x = a + b + c + d + e + f + g + h\n"
     "    p.y = 1\n"
     "    return p\n"
     "\n"
     "def main(n):\n"
     "    return 7\n",
     "refuse",
     "it needs one hidden word for the caller's block"),
    ("refuse_a_container_written_into_the_returned_block",
     "struct Point:\n"
     "    var x: Int\n"
     "    var items: List\n"
     "\n"
     "def make():\n"
     "    var p = Point()\n"
     "    p.x = 1\n"
     "    p.items = [1, 2, 3]\n"
     "    return p\n"
     "\n"
     "def main(n):\n"
     "    var p = make()\n"
     "    p.items.append(4)\n"
     "    return p.x\n",
     "refuse",
     "whose block outlives this function"),
    ("refuse_a_container_reached_through_a_name",
     "struct Point:\n"
     "    var x: Int\n"
     "    var items: List\n"
     "\n"
     "def make():\n"
     "    var p = Point()\n"
     "    p.x = 1\n"
     "    var xs = [1, 2, 3]\n"
     "    p.items = xs\n"
     "    return p\n"
     "\n"
     "def main(n):\n"
     "    var p = make()\n"
     "    return p.x\n",
     "refuse",
     "whose block outlives this function"),
    ("refuse_a_returned_name_with_two_layouts",
     "struct A:\n"
     "    var u: Int\n"
     "    var v: Int\n"
     "\n"
     "struct B:\n"
     "    var u: Int\n"
     "    var v: Int\n"
     "    var w: Int\n"
     "\n"
     "def pick(c):\n"
     "    var p = A()\n"
     "    p.u = 1\n"
     "    p.v = 2\n"
     "    if c > 0:\n"
     "        p = B()\n"
     "        p.u = 3\n"
     "        p.v = 4\n"
     "        p.w = 5\n"
     "    return p\n"
     "\n"
     "def main(n):\n"
     "    var p = pick(n)\n"
     "    return p.u\n",
     "refuse",
     "a slot index computed from either would read the wrong word on the "
     "other"),

    # THE ONE THIS TREE ANSWERS, and the counterpart of
    # `returned_frame_from_a_parameter` and `returned_frame_from_a_method_receiver`
    # above rather than a second refusal of it. `formal-land`'s convention copies
    # a RECEIVED frame OUT while the caller's frame is still live, which is sound
    # for exactly the reason the copy in general is, so `fwd(p)` computes.
    # `formal-frame-escape` built the other convention — build IN the caller's
    # block — and left this shape refused; both conventions are on this tree and
    # the copy wins, because a copy can hand back a frame it did not build and
    # building cannot. The GUARD this case was written as, something to fail if
    # the widening were wrong, is therefore `p.x` reading 7 below instead of
    # reclaimed stack: the same check, with an answer instead of a message.
    ("a_received_frame_handed_on",
     "struct Point:\n    var x: Int\n    var y: Int\n\ndef fwd(p):\n    return p\n\ndef main(n):\n    var p = Point()\n    p.x = 7\n    p.y = 8\n    var q = fwd(p)\n    return q.x\n",
     "expect", 7),
]


# ── the same convention, against a PYTHON twin, with `printf` as the channel ─
#
# Everything above is one text read by two runtimes, and that is the strongest
# oracle available: it is why the positive cases are written in the
# `class` / `def __init__` spelling. It has one limit, and it is the size of the
# channel — an exit status is a byte, and some of these answers are bigger than
# 255. So the cases below carry the program TWICE, once as Mojo and once as
# plain Python, and compare STDOUT (and the status) across the two images and
# the oracle. Two implementations of the language, written independently, that
# have to agree; a hand-written expected value is a third reading of the same
# spec and agrees with the wrong one exactly where nobody thought about it.
#
# (name, mojo_source, python_source[, backends]) — the optional fourth element
# names the architectures a case is about, which the two whose premise is an
# ABI's ARGUMENT BUDGET need, because that budget differs between the machines.
DIFF_CASES = [
    # A RECEIVED frame address handed back, through a COMPTIME-PARAMETERIZED
    # callee, and it is here rather than in the receiver-position suite because
    # that suite carried it as a REFUSAL until 2026-10-03 and the refusal was
    # lifted by decision (`model.struct_returned_frame_sites`: the creator is
    # an ancestor of the CALLER, so handing the address back is safe, and every
    # channel that would let it outlive the creator is still refused). What is
    # new here and was never covered is that a comptime parameter SHIFTS the
    # argument positions — `incoming_args` puts it first — and the hidden
    # trailing word the convention adds has to land after the LAST of them. A
    # callee that read its `r` from the wrong slot would either refuse with a
    # holder disagreement or return the block's address where the frame was
    # meant.
    ("received_frame_handed_back_through_a_specialized_parameter",
     "struct R:\n"
     "    var a: Int\n"
     "    var b: Int\n\n"
     "def stash[type: Int](x: Int, r: R) -> Int:\n"
     "    return r\n\n"
     "def main(n):\n"
     "    var r = R()\n"
     "    r.a = 7\n"
     "    r.b = 8\n"
     '    printf("a=%d,b=%d", stash[1](0, r).a, stash[1](0, r).b)\n'
     "    return 0\n",
     "class R:\n"
     "    def __init__(self):\n"
     "        self.a = 0\n"
     "        self.b = 0\n\n"
     "def stash(x, r):\n"
     "    return r\n\n"
     "def main():\n"
     "    r = R()\n"
     "    r.a = 7\n"
     "    r.b = 8\n"
     '    print("a=%d,b=%d" % (stash(0, r).a, stash(0, r).b), end="")\n'
     "    return 0\n\n"
     "main()\n"),

    # THE CONSTRUCT, in miniature: a factory that builds an object and returns
    # it.  `q.x * 10 + q.y` rather than a field read of `q` alone, so a block
    # that is the RIGHT SIZE and the right layout is the only thing that
    # produces it — a block sized from the wrong struct reads the second slot
    # past the end.
    ("returned_frame_is_the_object_the_caller_asked_for",
     "struct Point:\n"
     "    var x: Int\n"
     "    var y: Int\n\n"
     "def make(a, b):\n"
     "    var p = Point()\n"
     "    p.x = a\n"
     "    p.y = b\n"
     "    return p\n\n"
     "def main(n):\n"
     "    var q = make(3, 4)\n"
     '    printf("q=%d,%d", q.x, q.y)\n'
     "    return 0\n",
     "class Point:\n"
     "    def __init__(self):\n"
     "        self.x = 0\n"
     "        self.y = 0\n\n"
     "def make(a, b):\n"
     "    p = Point()\n"
     "    p.x = a\n"
     "    p.y = b\n"
     "    return p\n\n"
     "def main():\n"
     "    q = make(3, 4)\n"
     '    print("q=%d,%d" % (q.x, q.y), end="")\n'
     "    return 0\n\n"
     "main()\n"),

    # TWO OBJECTS IN ONE FUNCTION, and the case that found the real bug: the
    # caller half sized each block from the callee's `(holder, struct)` PLAN
    # rather than from the struct, so `struct_frame_block_bytes` was handed a
    # tuple and answered zero, every site got offset 0, and the second
    # `make()` overwrote the first.  `p` is READ AFTER `q` is built, which is
    # what makes it the difference between two blocks and one.
    ("two_returned_frames_in_one_function_are_two_blocks",
     "struct Point:\n"
     "    var x: Int\n"
     "    var y: Int\n\n"
     "def make(a, b):\n"
     "    var p = Point()\n"
     "    p.x = a\n"
     "    p.y = b\n"
     "    return p\n\n"
     "def main(n):\n"
     "    var p = make(3, 4)\n"
     "    var q = make(10, 20)\n"
     '    printf("p=%d,%d q=%d,%d", p.x, p.y, q.x, q.y)\n'
     "    return 0\n",
     "class Point:\n"
     "    def __init__(self):\n"
     "        self.x = 0\n"
     "        self.y = 0\n\n"
     "def make(a, b):\n"
     "    p = Point()\n"
     "    p.x = a\n"
     "    p.y = b\n"
     "    return p\n\n"
     "def main():\n"
     "    p = make(3, 4)\n"
     "    q = make(10, 20)\n"
     '    print("p=%d,%d q=%d,%d" % (p.x, p.y, q.x, q.y), end="")\n'
     "    return 0\n\n"
     "main()\n"),

    # THE OBJECT SURVIVES THE CALLEE'S OWN SCRATCH BEING REUSED, which is the
    # use-after-free this whole convention exists to prevent.  The loop calls
    # the factory four times, so the callee's activation — and everything it
    # reserved — comes and goes four times, and `p` is read after each.  If the
    # object were built in the callee's block the answer would be the LAST
    # iteration's, and the program would exit 0 while being wrong.
    ("returned_frame_outlives_the_callees_activation",
     "struct Point:\n"
     "    var x: Int\n"
     "    var y: Int\n\n"
     "def make(a, b):\n"
     "    var p = Point()\n"
     "    p.x = a\n"
     "    p.y = b\n"
     "    return p\n\n"
     "def main(n):\n"
     "    var p = make(1, 2)\n"
     "    var i = 0\n"
     "    while i < 4:\n"
     "        var q = make(10 + i, 20)\n"
     "        p.x = p.x + q.x\n"
     "        p.y = p.y + q.y\n"
     "        i = i + 1\n"
     '    printf("p=%d,%d", p.x, p.y)\n'
     "    return 0\n",
     "class Point:\n"
     "    def __init__(self):\n"
     "        self.x = 0\n"
     "        self.y = 0\n\n"
     "def make(a, b):\n"
     "    p = Point()\n"
     "    p.x = a\n"
     "    p.y = b\n"
     "    return p\n\n"
     "def main():\n"
     "    p = make(1, 2)\n"
     "    i = 0\n"
     "    while i < 4:\n"
     "        q = make(10 + i, 20)\n"
     "        p.x = p.x + q.x\n"
     "        p.y = p.y + q.y\n"
     "        i = i + 1\n"
     '    print("p=%d,%d" % (p.x, p.y), end="")\n'
     "    return 0\n\n"
     "main()\n"),

    # A FORWARDER: `twice` builds nothing and returns a frame its own callee
    # built, so it hands its CALLER's block straight down.  The write through
    # `q` after the inner call is what proves the word is the block and not a
    # copy of one — and it is the shape most real code has, which is why the
    # forwarding rule exists rather than a refusal.
    ("forwarded_frame_is_built_in_the_outermost_callers_block",
     "struct Point:\n"
     "    var x: Int\n"
     "    var y: Int\n\n"
     "def make(a):\n"
     "    var p = Point()\n"
     "    p.x = a\n"
     "    p.y = 1\n"
     "    return p\n\n"
     "def twice(a):\n"
     "    var q = make(a)\n"
     "    q.x = q.x + 1\n"
     "    return q\n\n"
     "def main(n):\n"
     "    var q = twice(5)\n"
     '    printf("q=%d,%d", q.x, q.y)\n'
     "    return 0\n",
     "class Point:\n"
     "    def __init__(self):\n"
     "        self.x = 0\n"
     "        self.y = 0\n\n"
     "def make(a):\n"
     "    p = Point()\n"
     "    p.x = a\n"
     "    p.y = 1\n"
     "    return p\n\n"
     "def twice(a):\n"
     "    q = make(a)\n"
     "    q.x = q.x + 1\n"
     "    return q\n\n"
     "def main():\n"
     "    q = twice(5)\n"
     '    print("q=%d,%d" % (q.x, q.y), end="")\n'
     "    return 0\n\n"
     "main()\n"),

    # A THREE-LINK CHAIN, and the read at the bottom is from `main` — so the
    # object has to have been built three activations below the function that
    # finally returns it.  A copy at any link would leave the caller's block
    # holding whatever the link above it last wrote.
    ("forwarded_through_three_activations",
     "struct Point:\n"
     "    var x: Int\n"
     "    var y: Int\n\n"
     "def make(a, b):\n"
     "    var p = Point()\n"
     "    p.x = a\n"
     "    p.y = b\n"
     "    return p\n\n"
     "def mid(a, b):\n"
     "    var q = make(a, b)\n"
     "    return q\n\n"
     "def outer(a, b):\n"
     "    var r = mid(a, b)\n"
     "    return r\n\n"
     "def main(n):\n"
     "    var q = outer(6, 7)\n"
     '    printf("q=%d,%d", q.x, q.y)\n'
     "    return 0\n",
     "class Point:\n"
     "    def __init__(self):\n"
     "        self.x = 0\n"
     "        self.y = 0\n\n"
     "def make(a, b):\n"
     "    p = Point()\n"
     "    p.x = a\n"
     "    p.y = b\n"
     "    return p\n\n"
     "def mid(a, b):\n"
     "    q = make(a, b)\n"
     "    return q\n\n"
     "def outer(a, b):\n"
     "    r = mid(a, b)\n"
     "    return r\n\n"
     "def main():\n"
     "    q = outer(6, 7)\n"
     '    print("q=%d,%d" % (q.x, q.y), end="")\n'
     "    return 0\n\n"
     "main()\n"),

    # THE THREE CONSTRUCTION SHAPES, in one function each, because each one
    # writes into the block differently: `S(a, b)` stores one word per argument,
    # `S(a, b)` on a struct with `__init__` first brings the class-level
    # defaults up and then the constructor's own stores, and `S(x)` is a
    # shallow `n`-slot copy.  The block is the CALLER's for all three, so a
    # shape that silently fell back to this function's own scratch would show up
    # as the previous case's clobber rather than as a failure here.
    ("positional_init_and_copy_constructions_all_land_in_the_block",
     "struct Wide:\n"
     "    var a: Int\n"
     "    var b: Int\n"
     "    var c: Int\n\n"
     "struct Point:\n"
     "    var x: Int\n"
     "    var y: Int\n"
     "    def __init__(self, x0, y0):\n"
     "        self.x = x0\n"
     "        self.y = y0\n\n"
     "def pos(a, b):\n"
     "    var w = Wide(a, b, 7)\n"
     "    return w\n\n"
     "def init(p, q):\n"
     "    var s = Point(p, q)\n"
     "    return s\n\n"
     "def copyit(a, b):\n"
     "    var t = Wide(a, b, 1)\n"
     "    var u = Wide(t)\n"
     "    return u\n\n"
     "def main(n):\n"
     "    var w = pos(1, 2)\n"
     "    var s = init(3, 4)\n"
     "    var u = copyit(5, 6)\n"
     '    printf("w=%d,%d,%d ", w.a, w.b, w.c)\n'
     '    printf("s=%d,%d ", s.x, s.y)\n'
     '    printf("u=%d,%d,%d", u.a, u.b, u.c)\n'
     "    return 0\n",
     "class Wide:\n"
     "    def __init__(self):\n"
     "        self.a = 0\n"
     "        self.b = 0\n"
     "        self.c = 0\n\n"
     "class Point:\n"
     "    def __init__(self, x0, y0):\n"
     "        self.x = x0\n"
     "        self.y = y0\n\n"
     "def pos(a, b):\n"
     "    w = Wide()\n"
     "    w.a = a\n"
     "    w.b = b\n"
     "    w.c = 7\n"
     "    return w\n\n"
     "def init(p, q):\n"
     "    s = Point(p, q)\n"
     "    return s\n\n"
     "def copyit(a, b):\n"
     "    t = Wide()\n"
     "    t.a = a\n"
     "    t.b = b\n"
     "    t.c = 1\n"
     "    u = Wide()\n"
     "    u.a = t.a\n"
     "    u.b = t.b\n"
     "    u.c = t.c\n"
     "    return u\n\n"
     "def main():\n"
     "    w = pos(1, 2)\n"
     "    s = init(3, 4)\n"
     "    u = copyit(5, 6)\n"
     '    print("w=%d,%d,%d " % (w.a, w.b, w.c), end="")\n'
     '    print("s=%d,%d " % (s.x, s.y), end="")\n'
     '    print("u=%d,%d,%d" % (u.a, u.b, u.c), end="")\n'
     "    return 0\n\n"
     "main()\n"),

    # A NESTED FRAME INSIDE THE RETURNED BLOCK.  The nested frame's ADDRESS
    # lives in a slot of the outer block and its bytes live inside the same
    # block, so a block built anywhere but the caller's would need every one of
    # those addresses re-based — and `o.inner.a = 3` after the return is what
    # shows they were not.
    ("a_nested_frame_inside_the_returned_block_is_reachable",
     "struct Inner:\n"
     "    var a: Int\n"
     "    var b: Int\n\n"
     "struct Outer:\n"
     "    var inner: Inner\n"
     "    var pad: Int\n\n"
     "def make(x, y):\n"
     "    var o = Outer()\n"
     "    o.pad = y\n"
     "    o.inner.a = x\n"
     "    o.inner.b = x + 1\n"
     "    return o\n\n"
     "def main(n):\n"
     "    var o = make(3, 4)\n"
     '    printf("a=%d b=%d p=%d", o.inner.a, o.inner.b, o.pad)\n'
     "    return 0\n",
     "class Inner:\n"
     "    def __init__(self):\n"
     "        self.a = 0\n"
     "        self.b = 0\n\n"
     "class Outer:\n"
     "    def __init__(self):\n"
     "        self.inner = Inner()\n"
     "        self.pad = 0\n\n"
     "def make(x, y):\n"
     "    o = Outer()\n"
     "    o.pad = y\n"
     "    o.inner.a = x\n"
     "    o.inner.b = x + 1\n"
     "    return o\n\n"
     "def main():\n"
     "    o = make(3, 4)\n"
     '    print("a=%d b=%d p=%d" % (o.inner.a, o.inner.b, o.pad), end="")\n'
     "    return 0\n\n"
     "main()\n"),

    # A METHOD that builds and returns a frame.  The hidden word goes in the
    # argument register PAST the method's own `self`, and the receiver's frame
    # is the CALLER's block while the returned object's is `main`'s — two
    # different blocks in one activation, which is the case where an emitter
    # that kept one base register for "the frame" would write the object over
    # the receiver.
    ("a_method_can_return_a_frame_it_builds",
     "struct Point:\n"
     "    var x: Int\n"
     "    var y: Int\n\n"
     "struct Box:\n"
     "    var k: Int\n"
     "    var t: Int\n"
     "    def build(self, a):\n"
     "        var q = Point()\n"
     "        q.x = a + self.k\n"
     "        q.y = self.t\n"
     "        return q\n\n"
     "def main(n):\n"
     "    var b = Box()\n"
     "    b.k = 5\n"
     "    b.t = 9\n"
     "    var p = b.build(3)\n"
     '    printf("p=%d,%d b=%d,%d", p.x, p.y, b.k, b.t)\n'
     "    return 0\n",
     "class Point:\n"
     "    def __init__(self):\n"
     "        self.x = 0\n"
     "        self.y = 0\n\n"
     "class Box:\n"
     "    def __init__(self):\n"
     "        self.k = 0\n"
     "        self.t = 0\n"
     "    def build(self, a):\n"
     "        q = Point()\n"
     "        q.x = a + self.k\n"
     "        q.y = self.t\n"
     "        return q\n\n"
     "def main():\n"
     "    b = Box()\n"
     "    b.k = 5\n"
     "    b.t = 9\n"
     "    p = b.build(3)\n"
     '    print("p=%d,%d b=%d,%d" % (p.x, p.y, b.k, b.t), end="")\n'
     "    return 0\n\n"
     "main()\n"),

    # THE RETURNED OBJECT IS AN ORDINARY HAND-OFF FROM THERE ON: a method of
    # its OWN struct reads and writes it, which is the by-reference receiver
    # doing what it always did.  This is the case that says the convention did
    # not replace the receiver design but plugged a hole in it.
    ("the_returned_object_is_then_an_ordinary_receiver",
     "struct Point:\n"
     "    var x: Int\n"
     "    var y: Int\n"
     "    def scaled(self, k):\n"
     "        return self.x * 100 + self.y + k\n\n"
     "def make(a, b):\n"
     "    var p = Point()\n"
     "    p.x = a\n"
     "    p.y = b\n"
     "    return p\n\n"
     "def main(n):\n"
     "    var q = make(3, 4)\n"
     '    printf("s=%d x=%d", q.scaled(1), q.x)\n'
     "    return 0\n",
     "class Point:\n"
     "    def __init__(self):\n"
     "        self.x = 0\n"
     "        self.y = 0\n"
     "    def scaled(self, k):\n"
     "        return self.x * 100 + self.y + k\n\n"
     "def make(a, b):\n"
     "    p = Point()\n"
     "    p.x = a\n"
     "    p.y = b\n"
     "    return p\n\n"
     "def main():\n"
     "    q = make(3, 4)\n"
     '    print("s=%d x=%d" % (q.scaled(1), q.x), end="")\n'
     "    return 0\n\n"
     "main()\n"),

    # AN EIGHT-ARGUMENT CALL TO A CALLEE THAT RETURNS NOTHING.  This is the case
    # that found the second bug in this change's own code, and it is the only
    # one of the 18 that would have FAILED rather than merely been wrong: the
    # caller half takes a `(callee, bound_name) -> struct` predicate, and
    # `dict.get` — which is `(key, default)` — was passed as one.  A module that
    # declares a multi-field struct therefore treated EVERY call as returning a
    # frame, reserved a zero-byte block for each, and pushed its address as a
    # ninth argument.  Eight arguments plus one is nine, so this program was
    # refused for an argument it never had.  The answers were unaffected
    # everywhere else — the callee never reads that register — so nothing but an
    # arity case could have told.
    # (name, mojo, python, backends) — the two arity cases below are pinned to
    # ONE architecture each, because the budget is a property of the ABI: eight
    # argument registers on arm64 and six on x86-64.  An eight-argument call is
    # a refusal on x86-64 and has always been, so running it there would be
    # testing the arity check rather than the convention.
    ("an_eight_argument_call_to_a_plain_callee_still_builds",
     "struct Point:\n"
     "    var x: Int\n"
     "    var y: Int\n\n"
     "def wide(a, b, c, d, e, f, g, h):\n"
     "    return a + b * 2 + c * 3 + d * 4 + e * 5 + f * 6 + g * 7 + h * 8\n\n"
     "def main(n):\n"
     "    var p = Point()\n"
     "    p.x = 1\n"
     "    var r = wide(1, 2, 3, 4, 5, 6, 7, 8)\n"
     '    printf("r=%d", r + p.x)\n'
     "    return 0\n",
     "class Point:\n"
     "    def __init__(self):\n"
     "        self.x = 0\n"
     "        self.y = 0\n\n"
     "def wide(a, b, c, d, e, f, g, h):\n"
     "    return a + b * 2 + c * 3 + d * 4 + e * 5 + f * 6 + g * 7 + h * 8\n\n"
     "def main():\n"
     "    p = Point()\n"
     "    p.x = 1\n"
     "    r = wide(1, 2, 3, 4, 5, 6, 7, 8)\n"
     '    print("r=%d" % (r + p.x), end="")\n'
     "    return 0\n\n"
     "main()\n",
     ("arm64",)),

    # …and the x86-64 half of the same bug: six argument registers, so a
    # SIX-argument call is the one the spurious seventh crosses.  Same program,
    # one fewer parameter.
    ("a_six_argument_call_to_a_plain_callee_still_builds",
     "struct Point:\n"
     "    var x: Int\n"
     "    var y: Int\n\n"
     "def wide(a, b, c, d, e, f):\n"
     "    return a + b * 2 + c * 3 + d * 4 + e * 5 + f * 6\n\n"
     "def main(n):\n"
     "    var p = Point()\n"
     "    p.x = 1\n"
     "    var r = wide(1, 2, 3, 4, 5, 6)\n"
     '    printf("r=%d", r + p.x)\n'
     "    return 0\n",
     "class Point:\n"
     "    def __init__(self):\n"
     "        self.x = 0\n"
     "        self.y = 0\n\n"
     "def wide(a, b, c, d, e, f):\n"
     "    return a + b * 2 + c * 3 + d * 4 + e * 5 + f * 6\n\n"
     "def main():\n"
     "    p = Point()\n"
     "    p.x = 1\n"
     "    r = wide(1, 2, 3, 4, 5, 6)\n"
     '    print("r=%d" % (r + p.x), end="")\n'
     "    return 0\n\n"
     "main()\n",
     ("x86_64",)),

    # A FUNCTION THAT DOES NOT RETURN A FRAME IS UNCHANGED, byte for byte in
    # what it computes.  A convention that spent a register on every function
    # rather than only on the ones that need one would move this answer, and
    # this is the row that says it did not.
    ("a_function_that_returns_no_frame_is_unchanged",
     "struct Point:\n"
     "    var x: Int\n"
     "    var y: Int\n\n"
     "def build(a, b):\n"
     "    var p = Point()\n"
     "    p.x = a\n"
     "    p.y = b\n"
     "    return p.x * 10 + p.y\n\n"
     "def make(a, b):\n"
     "    var p = Point()\n"
     "    p.x = a\n"
     "    p.y = b\n"
     "    return p\n\n"
     "def main(n):\n"
     "    var q = make(1, 2)\n"
     '    printf("r=%d q=%d,%d", build(3, 4), q.x, q.y)\n'
     "    return 0\n",
     "class Point:\n"
     "    def __init__(self):\n"
     "        self.x = 0\n"
     "        self.y = 0\n\n"
     "def build(a, b):\n"
     "    p = Point()\n"
     "    p.x = a\n"
     "    p.y = b\n"
     "    return p.x * 10 + p.y\n\n"
     "def make(a, b):\n"
     "    p = Point()\n"
     "    p.x = a\n"
     "    p.y = b\n"
     "    return p\n\n"
     "def main():\n"
     "    q = make(1, 2)\n"
     '    print("r=%d q=%d,%d" % (build(3, 4), q.x, q.y), end="")\n'
     "    return 0\n\n"
     "main()\n"),

    # THE HIDDEN WORD REACHES THE CALLEE, and it is here as a case rather than
    # folded into the ones above because those four facts were each correct on
    # their own: the block's storage was right (a returned struct never read
    # exited 0), the field READ was right (`return q.x + q.y` gave 3), a struct
    # built in `main` had its fields passed to `printf` correctly, and a
    # returned struct's field handed to a plain callee SEGFAULTED. Only the
    # composition failed, and nothing above isolates WHICH register.
    #
    # `twice` is a plain typed Mojo callee, so nothing in this program is
    # `printf` and nothing is variadic: it is the case that says the defect was
    # the CALL SITE's argument register rather than the C runtime's. It reads
    # the field of a returned frame directly in the call (`twice(make(1, 2).x)`)
    # AND through a named holder (`q.x`), because the two reach the block base
    # differently — the first re-derives it from the call site, the second from
    # the call's result register — and both have to work.
    ("a_returned_frames_field_reaches_a_plain_callee",
     "struct Point:\n"
     "    var x: Int\n"
     "    var y: Int\n\n"
     "def make(a, b):\n"
     "    var p = Point()\n"
     "    p.x = a\n"
     "    p.y = b\n"
     "    return p\n\n"
     "def twice(v: Int) -> Int:\n"
     "    return v * 2\n\n"
     "def main(n):\n"
     "    var q = make(1, 2)\n"
     '    printf("a=%d b=%d", twice(make(3, 4).x), twice(q.y) + q.x)\n'
     "    return 0\n",
     "class Point:\n"
     "    def __init__(self):\n"
     "        self.x = 0\n"
     "        self.y = 0\n\n"
     "def make(a, b):\n"
     "    p = Point()\n"
     "    p.x = a\n"
     "    p.y = b\n"
     "    return p\n\n"
     "def twice(v):\n"
     "    return v * 2\n\n"
     "def main():\n"
     "    q = make(1, 2)\n"
     '    print("a=%d b=%d" % (twice(make(3, 4).x), twice(q.y) + q.x), end="")\n'
     "    return 0\n\n"
     "main()\n"),
    # ── TWO live returned frames, in the four arrangements the ONE defect this
    # suite was missing a guard for produced ────────────────────────────────
    #
    # `two_returned_frames_in_one_function_are_two_blocks` above pins two
    # returned frames in SEQUENCE. These four pin the arrangements around it,
    # and they are here because that case could pass with the defect in place:
    # the x86-64 call site DROPPED the hidden trailing word (the block's address)
    # from its argument pop loop, so the callee wrote its result through whatever
    # the previous call had left in the callee-saved register the callee reads it
    # from.  With two sequential calls to the SAME factory that happens to be one
    # block used twice, so the sequential case reads the second object's values
    # under both names and DOES fail -- but the three arrangements below reached
    # it differently, and none of them had a case:
    #
    #   * an ORDINARY CALL between the two, which is not involved at all (its
    #     own result stayed correct while both frames went wrong) and so says the
    #     clobber is not "any call";
    #   * both results live at once as ARGUMENTS of one call, which is the
    #     cheapest confirmation of the whole thing -- no holder names at all, so
    #     a "fix" that repaired the binding and not the block would pass every
    #     other row here and fail this one;
    #   * a comparison, where a field-wise `__eq__` over two operands that are
    #     really ONE block reports two DISTINCT values as equal. This is the
    #     silent-wrong-answer shape: the image exits 0 and prints a plausible
    #     integer.
    #
    # All four were measured against the tree with `6cae9e4b`'s `continue` put
    # back: arm64 right on every row, x86-64 wrong on every row.
    ("two_returned_frames_around_an_ordinary_call",
     "struct Point:\n"
     "    var x: Int\n"
     "    var y: Int\n\n"
     "def make(a, b):\n"
     "    var p = Point()\n"
     "    p.x = a\n"
     "    p.y = b\n"
     "    return p\n\n"
     "def plain(v):\n"
     "    return v\n\n"
     "def main(n):\n"
     "    var t = make(1, 2)\n"
     "    var k = plain(9)\n"
     "    var u = make(10, 20)\n"
     '    printf("t=%d,%d k=%d u=%d,%d", t.x, t.y, k, u.x, u.y)\n'
     "    return 0\n",
     "class Point:\n"
     "    def __init__(self):\n"
     "        self.x = 0\n"
     "        self.y = 0\n\n"
     "def make(a, b):\n"
     "    p = Point()\n"
     "    p.x = a\n"
     "    p.y = b\n"
     "    return p\n\n"
     "def plain(v):\n"
     "    return v\n\n"
     "def main():\n"
     "    t = make(1, 2)\n"
     "    k = plain(9)\n"
     "    u = make(10, 20)\n"
     '    print("t=%d,%d k=%d u=%d,%d" % (t.x, t.y, k, u.x, u.y), end="")\n'
     "    return 0\n\n"
     "main()\n"),
    # The SECOND row is printed FIRST on purpose.  With one block shared, "the
    # last block wins" and "the second name wins" are the same answer here and
    # different answers in the sequential case above, and this is the row that
    # separates "both names name one block" from anything name-shaped.
    ("two_returned_frames_printed_in_the_other_order",
     "struct Point:\n"
     "    var x: Int\n"
     "    var y: Int\n\n"
     "def make(a, b):\n"
     "    var p = Point()\n"
     "    p.x = a\n"
     "    p.y = b\n"
     "    return p\n\n"
     "def main(n):\n"
     "    var t = make(1, 2)\n"
     "    var u = make(10, 20)\n"
     '    printf("u=%d,%d t=%d,%d", u.x, u.y, t.x, t.y)\n'
     "    return 0\n",
     "class Point:\n"
     "    def __init__(self):\n"
     "        self.x = 0\n"
     "        self.y = 0\n\n"
     "def make(a, b):\n"
     "    p = Point()\n"
     "    p.x = a\n"
     "    p.y = b\n"
     "    return p\n\n"
     "def main():\n"
     "    t = make(1, 2)\n"
     "    u = make(10, 20)\n"
     '    print("u=%d,%d t=%d,%d" % (u.x, u.y, t.x, t.y), end="")\n'
     "    return 0\n\n"
     "main()\n"),
    # No holder names anywhere: both blocks are live at the moment of the outer
    # call, and `two` reads a field out of each.  A frame-returning call in an
    # ARGUMENT position is the shape the convention's per-CALL-SITE block was
    # chosen for, so it is the row that says the reservation is per site.
    ("two_returned_frames_live_at_once_as_arguments",
     "struct Point:\n"
     "    var x: Int\n"
     "    var y: Int\n\n"
     "def make(a, b):\n"
     "    var p = Point()\n"
     "    p.x = a\n"
     "    p.y = b\n"
     "    return p\n\n"
     "def total(p: Point, q: Point) -> Int:\n"
     "    return p.x * 100 + q.x\n\n"
     "def main(n):\n"
     '    printf("v=%d", total(make(1, 2), make(10, 20)))\n'
     "    return 0\n",
     "class Point:\n"
     "    def __init__(self):\n"
     "        self.x = 0\n"
     "        self.y = 0\n\n"
     "def make(a, b):\n"
     "    p = Point()\n"
     "    p.x = a\n"
     "    p.y = b\n"
     "    return p\n\n"
     "def total(p, q):\n"
     "    return p.x * 100 + q.x\n\n"
     "def main():\n"
     '    print("v=%d" % total(make(1, 2), make(10, 20)), end="")\n'
     "    return 0\n\n"
     "main()\n"),
    # The SILENT one: two DISTINCT values, one field-wise comparison, `eq=0`.
    # There is no crash and no wrong exit status anywhere in this row, which is
    # why it is the one worth having: every other arrangement here fails loudly
    # enough to be noticed by a status comparison.
    #
    # `make` carries a DECLARED return type and that is not decoration: without
    # it the comparison is refused, because a call whose result kind nothing
    # states cannot be classified as a frame (`model`'s frame-vs-value refusal,
    # which is right and is not this row's subject).  The Mojo column may be
    # annotated because it is not the column CPython runs -- that is the whole
    # point of carrying the program twice.
    ("a_returned_frame_compared_with_a_returned_frame_call",
     "struct Point:\n"
     "    var x: Int\n"
     "    var y: Int\n\n"
     "    def __eq__(self, other: Point) -> Bool:\n"
     "        return self.x == other.x and self.y == other.y\n\n"
     "def make(a: Int, b: Int) -> Point:\n"
     "    var p = Point()\n"
     "    p.x = a\n"
     "    p.y = b\n"
     "    return p\n\n"
     "def main(n):\n"
     "    var t = make(1, 2)\n"
     '    printf("eq=%d", 1 if t == make(10, 20) else 0)\n'
     "    return 0\n",
     "class Point:\n"
     "    def __init__(self):\n"
     "        self.x = 0\n"
     "        self.y = 0\n\n"
     "    def __eq__(self, other):\n"
     "        return self.x == other.x and self.y == other.y\n\n"
     "def make(a, b):\n"
     "    p = Point()\n"
     "    p.x = a\n"
     "    p.y = b\n"
     "    return p\n\n"
     "def main():\n"
     "    t = make(1, 2)\n"
     '    print("eq=%d" % (1 if t == make(10, 20) else 0), end="")\n'
     "    return 0\n\n"
     "main()\n"),
]


def build(src, out, backend):
    cmd = [sys.executable, FIRE, "build", "--formal", "--no-prove", "-o", out,
           f"--backend={backend}", src]
    p = subprocess.run(cmd, capture_output=True, text=True,
                       timeout=BUILD_TIMEOUT, cwd=HERE)
    return p.returncode, (p.stderr or p.stdout or "")



def check_predicate_is_two_argument():
    """Neither backend may hand `dict.get` to `struct_returned_frame_sites`.

    Structural rather than behavioural, and it is here because the behavioural
    consequence is invisible in every case except an eight-argument call: the
    predicate's contract is `(callee, bound_name) -> struct`, `dict.get`'s is
    `(key, default)`, and a missing callee therefore answers with the bound
    NAME.  Both backends read the predicate from
    `formal/model.py`'s `frame_returning_predicate`, whose comment carries the
    measurement; this checks that neither of them grew a private one.
    """
    ok = True
    for backend in ("formal/arm64_codegen.py", "formal/x86_64_codegen.py"):
        path = os.path.join(HERE, backend)
        with open(path) as fh:
            src = fh.read()
        if "frame_returning_predicate" not in src:
            ok = False
            print(f"FAIL  {backend} does not build the returns-a-frame "
                  f"predicate from the model")
        if "_returns_frame.get)" in src:
            ok = False
            print(f"FAIL  {backend} hands dict.get to a two-argument predicate")
    if ok:
        print("  PASS  neither_backend_passes_dict_get_as_the_predicate")
    return ok


def check_sret_word_reaches_the_callee():
    """Every backend that pushes the hidden word must also MOVE it.

    The convention has two ends and they can drift apart without either end
    looking wrong: the callee reads the block address out of an argument
    register (`ARG_REGS[len(params)]` on x86-64, X-`len(incoming)` on arm64),
    and the call site pushes the address and then has to put it in that same
    register. x86-64 dropped it — the popped word was skipped, on the reasoning
    that being popped first meant it was already in RAX, which is true of
    arm64's X0 and of no register on this ABI.

    It is a SIGSEGV rather than a wrong value because the hidden word lands in
    a callee-SAVED register, so the callee's prologue keeps whatever the
    previous call left there and dereferences it as a block address. Every
    case that does not read a returned frame's field PASSED with that in place:
    the block's storage was right, the field read was right, a struct built
    locally was right. So the differential cases cannot be the only guard, and
    neither can a source-shaped check on `"sret"` — the dropped entry carried
    the class name and only lacked the move.

    What is checked is therefore the strongest thing available without
    building: the popped word has a use. `continue` inside the pop loop is
    refused outright, and the pop loop is located by the pushes that feed it
    rather than by a line number.
    """
    ok = True
    for backend in ("formal/arm64_codegen.py", "formal/x86_64_codegen.py"):
        path = os.path.join(HERE, backend)
        with open(path) as fh:
            src = fh.read()
        # The pop loop: it pops and moves, in both backends, in the shape the
        # two architectures share. Find it as the loop that pops.
        pop_loop = None
        lines = src.splitlines()
        for i, line in enumerate(lines):
            if "for " in line and ("reversed(reg_plan)" in line
                                   or "range(min(nargs" in line
                                   or "range(nargs" in line):
                pop_loop = lines[i:i + 12]
                break
        if pop_loop is None:
            ok = False
            print(f"FAIL  {backend}: no argument pop loop found, so the "
                  f"hidden word's move cannot be checked")
            continue
        body = "\n".join(pop_loop)
        if "continue" in body:
            ok = False
            print(f"FAIL  {backend}: the argument pop loop skips a popped "
                  f"word with `continue`; the returned-frame hidden word was "
                  f"dropped exactly that way, and the callee then read "
                  f"whatever the previous call left in its argument register")
        if not any(m in body for m in ("encode_mov_r64_r64(ARG_REGS",
                                       "encode_mov_zr_xn",
                                       "_load_home_from_reg",
                                       "encode_mov_zr_xn")):
            ok = False
            print(f"FAIL  {backend}: the argument pop loop moves no popped "
                  f"word into an argument register")
    if ok:
        print("  PASS  every_popped_argument_word_reaches_its_register")
    return ok

def run_cpython(source):
    """The oracle: the same program under CPython, whose exit status and stdout
    the formal image has to match.

    Not `fire.py run` and not the interpreter in this repository.  The point of a
    differential case is that the two answers come from two independent
    implementations of the language, and `myinterpreter.py` is not one of them —
    it shares the AST, so a mistake in the AST cannot be caught by comparing
    against it.
    """
    with tempfile.TemporaryDirectory(prefix="cpython_") as own:
        path = os.path.join(own, "oracle.py")
        with open(path, "w") as f:
            f.write(source)
        return subprocess.run([sys.executable, path], capture_output=True,
                              text=True, timeout=RUN_TIMEOUT)


def cpython_answer(source):
    """The exit status CPython gives the same source.

    Mojo is a Python superset, which is what makes this possible at all — the
    same text is both the program's source and its reference — and a
    `SystemExit(int)` is masked to a byte by CPython's own exit path, exactly
    as a formal image's status is.

    `run_cpython` is the one that runs the oracle, for both the cases above and
    the ones with a Python twin below: the two oracles differ in what they
    COMPARE, not in how they run CPython, and two copies of a subprocess call
    that must agree is two places for them to stop agreeing.
    """
    p = run_cpython(source + f"\nimport sys\nsys.exit(main({ENTRY_ARG}))\n")
    if p.returncode < 0:
        return f"CPython died with signal {-p.returncode}: {p.stderr[-200:]}"
    return p.returncode


def run_diff_case(case, tmpdir, verbose):
    """CPython's answer, then both images' answers, and require all three to
    agree.

    The order is the order of trust: the oracle is run FIRST so that a broken
    expectation is reported as a broken expectation and not as two consistently
    wrong backends.  A case whose Python twin does not produce the answer the
    case is about is a bug in the case.
    """
    name, source, oracle = case[0], case[1], case[2]
    # An optional fourth element names the architectures this case is about,
    # for the two whose premise is an ABI's ARGUMENT BUDGET and therefore
    # differs between the two machines.
    backends = case[3] if len(case) > 3 else BACKENDS
    want = run_cpython(oracle)
    if want.returncode != 0:
        return False, (f"the CPython oracle itself failed (exit "
                       f"{want.returncode}): "
                       f"{(want.stderr or '').strip()[-200:]}")
    src = os.path.join(tmpdir, name + ".mojo")
    with open(src, "w") as f:
        f.write(source)
    for backend in backends:
        out = os.path.join(tmpdir, f"{name}.{backend}")
        rc, text = build(src, out, backend)
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

def run_case(name, source, mode, expectation, tmpdir, verbose):
    src = os.path.join(tmpdir, name + ".mojo")
    with open(src, "w") as f:
        f.write(source)

    if mode == "refuse":
        # Both machines, and the same words: one construct, one language, and a
        # backend that answers it differently is the one thing this pair must
        # not do.
        for backend in BACKENDS:
            rc, text = build(src, os.path.join(tmpdir, f"{name}.{backend}"),
                             backend)
            if rc == 0:
                return False, (f"--backend={backend} BUILT a construct the "
                               f"convention cannot describe; the binary is "
                               f"the real answer here")
            if expectation not in text:
                return False, (f"--backend={backend} refused, but not naming "
                               f"{expectation!r}: {text.strip()[-200:]}")
        if verbose:
            print(f"      refused identically on both: {expectation!r}")
        return True, ""

    want = cpython_answer(source) if mode == "ok" else expectation
    if not isinstance(want, int):
        return False, want
    for backend in BACKENDS:
        out = os.path.join(tmpdir, f"{name}.{backend}")
        rc, text = build(src, out, backend)
        if rc != 0:
            return False, f"--backend={backend}: {text.strip()[-300:]}"
        run = subprocess.run([out], capture_output=True, text=True,
                             timeout=RUN_TIMEOUT)
        if run.returncode != want:
            return False, (f"--backend={backend} exit {run.returncode} where "
                           f"{'CPython' if mode == 'ok' else 'the source'} "
                           f"gives {want}"
                           + (f"; stderr: {run.stderr.strip()[:120]}"
                              if run.stderr.strip() else ""))
        if verbose:
            print(f"      {backend}: exit={run.returncode} "
                  f"stdout={run.stdout!r}")
    if verbose and mode == "ok":
        print(f"      CPython: exit={want}")
    return True, ""


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("-v", "--verbose", action="store_true")
    ap.add_argument("cases", nargs="*", help="subset of case names")
    args = ap.parse_args()

    if platform.machine() not in ("arm64", "aarch64", "x86_64"):
        print(f"SKIP: formal output needs an arm64 or x86-64 host, "
              f"this is {platform.machine()}")
        return 0

    # Two case SHAPES, and they are dispatched separately rather than forced
    # into one table: `CASES` is four columns and carries a MODE, and
    # `DIFF_CASES` is three or four and carries a second PROGRAM rather than a
    # mode. A sentinel in the mode column and a branch that reads a sentinel as
    # if it were one is how a case ends up asserting nothing.
    diff_names = {c[0] for c in DIFF_CASES}
    everything = CASES + DIFF_CASES
    known = {c[0] for c in everything}
    selected = [c for c in everything if not args.cases or c[0] in args.cases]
    if args.cases and len(selected) != len(args.cases):
        print(f"no such case(s): {sorted(set(args.cases) - known)}")
        return 2

    passed = failed = 0
    # One shape check that needs no image, and it is a case like any other: the
    # returns-a-frame predicate has a stated contract `(callee, bound_name) ->
    # struct` and a `dict.get` handed to it answers with the bound NAME, which
    # reads as a missing callee. Both backends read the predicate out of
    # `formal/model.py`'s `frame_returning_predicate`, so neither may grow a
    # private one.
    if not args.cases:
        if check_predicate_is_two_argument():
            passed += 1
        else:
            failed += 1

    # …and the second shape check, for the same reason: the convention's two
    # ends are in two functions in the same file, a SIGSEGV-only-when-composed
    # defect survives every differential case, and this one does not need a
    # build to see.
    if not args.cases:
        if check_sret_word_reaches_the_callee():
            passed += 1
        else:
            failed += 1

    with tempfile.TemporaryDirectory() as tmpdir:
        for case in selected:
            name = case[0]
            try:
                if name in diff_names:
                    ok, detail = run_diff_case(case, tmpdir, args.verbose)
                else:
                    ok, detail = run_case(case[0], case[1], case[2], case[3],
                                          tmpdir, args.verbose)
            except subprocess.TimeoutExpired:
                ok, detail = False, "timed out"
            except Exception as e:                      # report, do not mask
                ok, detail = False, f"{type(e).__name__}: {e}"
                if args.verbose:
                    import traceback
                    traceback.print_exc()
            if ok:
                passed += 1
                label = "diff" if name in diff_names else case[2]
                print(f"  PASS  {name} ({label})")
            else:
                failed += 1
                print(f"  FAIL  {name}: {detail}")

    print(f"\nformal returned-frame: PASS={passed} FAIL={failed}")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
