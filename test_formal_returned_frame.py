#!/usr/bin/env python3
"""`return <frame>`: the block the object is built in belongs to the CALLER.

The 30-file sweep family (rows 5 and 9 of
`bugs/FORMAL_sweep_work_map_2026-09-30.md`) tested.  A struct of more than one
field has a FRAME for its receiver on this path (`formal/model.py`'s
`struct_is_framed`): the receiver word is the ADDRESS of a block of 8-byte
slots, one per field, in declaration order.  That block is carved out of the
function's own scratch, so a frame that function built died when it returned —
which is why `return p` used to be refused by one line in `formal/build.py`.

The convention that gives it a lifetime is a hidden TRAILING argument: a
function that returns a frame is handed the address of a block the CALLER
reserved, builds the object IN that block, and returns its address.  Building in
place rather than copying into it is the whole of why it is cheap — a copy
would have to re-base the address of every nested frame in the block, at every
depth, or hand back an object whose nested fields point into scratch that is
about to be reclaimed.

**Every case here is a DIFFERENTIAL one**: the same program is written twice,
once as Mojo and once as plain Python, and the two are made to AGREE.  That is
the discipline `test_formal_frame_len.py` set for the neighbouring construct and
`test_interp_oracle.py` for the other engine, and it is here for the reason
`CLAUDE.md` gives: a hand-written expected value is a second implementation of
the question, and two implementations written from the same reading agree on
exactly the cases nobody thought about.  The `printf` form rather than the exit
status is because a process exit status is one byte and some of these answers
are bigger than 255.

**Both architectures are BUILT and EXECUTED**, and the host is arm64, so the
x86-64 image runs under Rosetta.  A case that passed on one architecture only
would be exactly the class of bug this file exists for, and one DID: the caller
half read the callee's `(holder, struct)` plan where it wanted the struct,
sized every block from a tuple — so every block was zero bytes, every call site
in a function got the SAME address, and the second object overwrote the first.
`two_returned_frames_in_one_function_are_two_blocks` is that case.

WHAT IS DELIBERATELY NOT HERE.  A frame that arrived as a PARAMETER and is
handed back (`def fwd(p): return p`) is refused, and stays refused: the creator
is not a function this analysis can name.  It is a different construct from this
one — nothing about the caller's block settles it — and the two cases are
`byref_refuse_returned_from_a_receiver` and
`byref_refuse_returned_from_a_method_receiver` in `test_formal_run.py`.

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
BUILD_TIMEOUT = 180
RUN_TIMEOUT = 60
BACKENDS = ("arm64", "x86_64")

# ── the differential cases ──────────────────────────────────────────────────
#
# (name, mojo_source, python_source)
DIFF_CASES = [
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
]


# ── the refusals ────────────────────────────────────────────────────────────
#
# (name, mojo_source, needle)
#
# Each of these is a thing the convention CANNOT do, and each is a case where
# building would be a wrong number rather than a failure.  They are here because
# a convention that quietly approximated them would be worse than one that
# refuses: the whole point of the returned-frame design is that the object
# outlives its creator, and each of these is a way for it not to.
REFUSALS = [
    # The ENTRY POINT has no caller.  The startup stub branches to it with one
    # word — the test input — so a hidden block word would be whatever the
    # second argument register happened to hold, and the object would be built
    # there.
    ("refuse_the_entry_function_returning_a_frame",
     "struct Point:\n"
     "    var x: Int\n"
     "    var y: Int\n\n"
     "def make():\n"
     "    var p = Point()\n"
     "    p.x = 1\n"
     "    p.y = 2\n"
     "    return p\n\n"
     "def main(n):\n"
     "    var p = make()\n"
     "    return p\n",
     "is this image's entry point and returns a frame address"),

    # A POSITION THAT BINDS NO NAME.  `f(g())` needs a block for `g`'s result
    # as well as for `f`'s, and this path cannot say how long that one has to
    # live or which site owns it.
    ("refuse_a_call_in_a_position_that_binds_no_name",
     "struct Point:\n"
     "    var x: Int\n"
     "    var y: Int\n\n"
     "def make(a):\n"
     "    var p = Point()\n"
     "    p.x = a\n"
     "    p.y = 1\n"
     "    return p\n\n"
     "def take(p):\n"
     "    return p.x\n\n"
     "def main(n):\n"
     "    return take(make(5))\n",
     "a position that binds no name"),

    # …and the SUBSCRIPT spelling of the same gap, which is a different program
    # with a different reason: the list's element is a heap cell, so the address
    # outlives the block by however long the list lives.
    ("refuse_a_returned_frame_stored_through_a_subscript",
     "struct Point:\n"
     "    var x: Int\n"
     "    var y: Int\n\n"
     "def make(a):\n"
     "    var p = Point()\n"
     "    p.x = a\n"
     "    p.y = 1\n"
     "    return p\n\n"
     "def main(n):\n"
     "    var xs = [0, 0, 0]\n"
     "    xs[1] = make(5)\n"
     "    return xs[1]\n",
     "the right-hand side of a subscript assignment"),

    # NO ARGUMENT REGISTER LEFT.  The hidden word is an argument, and this path
    # passes eight in registers on arm64 and six on x86-64; a callee that
    # already takes that many cannot be given one.
    ("refuse_a_callee_with_no_argument_register_left",
     "struct Point:\n"
     "    var x: Int\n"
     "    var y: Int\n\n"
     "def make(a, b, c, d, e, f, g, h):\n"
     "    var p = Point()\n"
     "    p.x = a + b + c + d + e + f + g + h\n"
     "    p.y = 1\n"
     "    return p\n\n"
     "def main(n):\n"
     "    return 7\n",
     "it needs one hidden word for the caller's block"),

    # A CONTAINER IN THE RETURNED BLOCK.  A list is bump-allocated in the
    # function that made it, and the block outlives that function, so the slot
    # would name bytes the caller is already using and the first append through
    # it would write into reclaimed stack.
    ("refuse_a_container_written_into_the_returned_block",
     "struct Point:\n"
     "    var x: Int\n"
     "    var items: List\n\n"
     "def make():\n"
     "    var p = Point()\n"
     "    p.x = 1\n"
     "    p.items = [1, 2, 3]\n"
     "    return p\n\n"
     "def main(n):\n"
     "    var p = make()\n"
     "    p.items.append(4)\n"
     "    return p.x\n",
     "whose block outlives this function"),

    # …and the one-hop version of the same thing, which is the shape the
    # premise's own gap describes: a NAME this function bound to a container.
    ("refuse_a_container_reached_through_a_name",
     "struct Point:\n"
     "    var x: Int\n"
     "    var items: List\n\n"
     "def make():\n"
     "    var p = Point()\n"
     "    p.x = 1\n"
     "    var xs = [1, 2, 3]\n"
     "    p.items = xs\n"
     "    return p\n\n"
     "def main(n):\n"
     "    var p = make()\n"
     "    return p.x\n",
     "whose block outlives this function"),

    # A NAME WITH TWO LAYOUTS.  The caller's block is sized from the struct the
    # callee builds, and a name bound by two constructors on two paths has no
    # single width — the field read past the end is a number nobody wrote.
    ("refuse_a_returned_name_with_two_layouts",
     "struct A:\n"
     "    var u: Int\n"
     "    var v: Int\n\n"
     "struct B:\n"
     "    var u: Int\n"
     "    var v: Int\n"
     "    var w: Int\n\n"
     "def pick(c):\n"
     "    var p = A()\n"
     "    p.u = 1\n"
     "    p.v = 2\n"
     "    if c > 0:\n"
     "        p = B()\n"
     "        p.u = 3\n"
     "        p.v = 4\n"
     "        p.w = 5\n"
     "    return p\n\n"
     "def main(n):\n"
     "    var p = pick(n)\n"
     "    return p.u\n",
     "bound by more than one constructor"),

    # THE OTHER HALF OF THE FAMILY, and it stays refused: a frame that arrived
    # as a PARAMETER names a block this function did not create, and the
    # function that did is not one this analysis can name.  Nothing about the
    # caller's block settles it, which is why it is not this construct.
    #
    # **This one is a GUARD and not a demonstration.**  Measured on the
    # pre-change tree (`git archive HEAD~1` into a scratch root, this file
    # dropped in): `PASS=1 FAIL=17`, and this is the 1.  It was refused before
    # and it is refused now, for the same reason — and it is here so that a
    # change which widened the convention to cover a RECEIVED frame would have
    # something to fail against, because that widening is the neighbouring
    # construct and a silent version of it is a use-after-free.
    ("refuse_a_received_frame_handed_on",
     "struct Point:\n"
     "    var x: Int\n"
     "    var y: Int\n\n"
     "def fwd(p):\n"
     "    return p\n\n"
     "def main(n):\n"
     "    var p = Point()\n"
     "    p.x = 7\n"
     "    p.y = 8\n"
     "    var q = fwd(p)\n"
     "    return q.x\n",
     "returned from a function that did not create it"),
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
            name = case[0]
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
    print(f"\nformal returned frame: PASS={passed} FAIL={failed}")
    return 1 if failed else 0


def run_diff_case(case, tmpdir, verbose):
    """CPython's answer, then both images' answers, and require all three to
    agree.

    The order is the order of trust: the oracle is run FIRST so that a broken
    expectation is reported as a broken expectation and not as two consistently
    wrong backends.  A case whose Python twin does not produce the answer the
    case is about is a bug in the case.
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
    """BOTH backends must refuse, and name the reason.

    "The backends refuse" pins this compiler's decision and "with these words"
    pins that it is the RIGHT reason: a refusal that fires for a different
    cause than the one the message names is the defect class
    `bugs/FORMAL_frame_receiver_handoff.md` §4 is three examples of.
    """
    name, source, needle = case
    src = os.path.join(tmpdir, name + ".mojo")
    with open(src, "w") as f:
        f.write(source)
    for backend in BACKENDS:
        rc, text = build_formal(src, os.path.join(tmpdir, f"{name}.{backend}"),
                                backend)
        if rc == 0:
            return False, (f"--backend={backend} BUILT a construct this case "
                           f"says has no representation (expected a refusal "
                           f"naming {needle!r}); the binary is the real answer "
                           f"here")
        if needle not in text:
            return False, (f"--backend={backend} refused, but not with the "
                           f"expected words {needle!r}: {text.strip()[-200:]}")
        if verbose:
            print(f"      --backend={backend} refused naming {needle!r}")
    return True, ""


if __name__ == "__main__":
    sys.exit(main())
