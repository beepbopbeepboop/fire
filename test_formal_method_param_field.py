#!/usr/bin/env python3
"""A METHOD PARAMETER'S FIELD, established by its DECLARED TYPE and nothing
else: build the image, run it, and compare with CPython.

`bugs/FORMAL_method_param_field_access.md` is the finding.  A method's other
parameters were never seeded as frame holders, so `other.start` in

    struct Slice(Equatable):
        var start: Optional[Int]
        var end: Optional[Int]
        var step: Optional[Int]
        def __eq__(self, other: Self) -> Bool:
            return self.start == other.start

was refused by name — and refused for a fact about the PROGRAM rather than the
path: `other`'s type is written down in the parameter list.  A declared type
names the LAYOUT the callee was written against, so it holds at every call site
whether or not this image contains one, which is a different kind of evidence
from the word a call site hands a parameter and the reason the two can disagree
without either being wrong.

Two halves, because a parameter's declared type settles both questions a
field access asks:

  * a struct of more than one field has a FRAME receiver, so `other.start` is a
    load at `base + 8k` — `_frame_receivers` seeds the parameter from
    `model.parameter_declared_structs`;
  * a ONE-FIELD struct's receiver IS its field (`model.struct_is_one_field`), so
    `other.a` is `other` — the same rewrite `self.a` already got, and the same
    message for both, which is why a fix that did only the first would read as
    a wrong fix.

Every positive case here is EXECUTED on BOTH architectures and compared with
CPython running the same program, and every one of them reads AND writes through
such a parameter.  Both halves are load-bearing: arm64's `_store_var` used to
fall through to `mov x19, src` (a store into the register the next function
reads as its first parameter) and x86-64's `_load_var` read an immediate 0, so a
case that checked only a return value would pass on a build that answered
nothing.  The refusal cases are the other half: a declared type is a PROMISE,
and a call site that hands the parameter something else must be refused rather
than read through — `model.frame_declared_parameter_refusal`.

    python3 test_formal_method_param_field.py [-v] [case ...]
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

# (name, mojo, python, want_exit, want_stdout_or_None, needle_or_None)
#
# `python` is a transcription of `mojo` into the language CPython runs, and it
# is the ORACLE: nothing in this file writes down what the program should
# compute, so a case cannot pass by agreeing with a wrong expectation of mine.
# It is a transcription rather than the same bytes because `struct` and a
# method's `def` are the only things CPython cannot read, and both become a
# `class`.
CASES = [
    # ── THE HEADLINE: `Slice.__eq__`, with nothing in the image calling it ──────
    #
    # Three fields, `other: Self`, and the read is `other.start` — the exact
    # expression the sweep reported 27 files' worth of.  The answer is guarded
    # field by field rather than returned as one sum, so a build that reads the
    # wrong SLOT says which field moved: 1/10/100 are the three positions, and a
    # frame read at `base + 0` when the source means `base + 16` returns the
    # first field.
    ("eq_reads_three_slots",
     "struct Slice:\n"
     "    var start: Int\n"
     "    var end: Int\n"
     "    var step: Int\n"
     "\n"
     "    def same(self, other: Slice) -> Bool:\n"
     "        return self.start == other.start and self.end == other.end \\\n"
     "            and self.step == other.step\n"
     "\n"
     "def main(n: Int) -> Int:\n"
     "    var a = Slice()\n"
     "    var b = Slice()\n"
     "    a.start = 1\n"
     "    a.end = 2\n"
     "    a.step = 3\n"
     "    b.start = 1\n"
     "    b.end = 2\n"
     "    b.step = 3\n"
     "    if a.same(b):\n"
     "        return 0\n"
     "    return 1\n",
     "class Slice:\n"
     "    def __init__(self):\n"
     "        self.start = 0\n"
     "        self.end = 0\n"
     "        self.step = 0\n"
     "    def same(self, other):\n"
     "        return (self.start == other.start and self.end == other.end\n"
     "                and self.step == other.step)\n"
     "a = Slice()\n"
     "b = Slice()\n"
     "a.start = 1\n"
     "a.end = 2\n"
     "a.step = 3\n"
     "b.start = 1\n"
     "b.end = 2\n"
     "b.step = 3\n"
     "raise SystemExit(0 if a.same(b) else 1)\n",
     0, None, None),

    # The same method reached through a call site as well, which is the shape
    # the fixpoint already handled — so this row is the CONTROL, and it is what
    # says the declaration did not change the case that already worked.
    ("eq_with_a_call_site_agrees",
     "struct Slice:\n"
     "    var start: Int\n"
     "    var end: Int\n"
     "\n"
     "    def total(self) -> Int:\n"
     "        return self.start + self.end\n"
     "\n"
     "    def plus(self, other: Slice) -> Int:\n"
     "        return self.total() + other.start + other.end\n"
     "\n"
     "def main(n: Int) -> Int:\n"
     "    var a = Slice()\n"
     "    var b = Slice()\n"
     "    a.start = 1\n"
     "    a.end = 2\n"
     "    b.start = 10\n"
     "    b.end = 20\n"
     "    return a.plus(b)\n",
     "class Slice:\n"
     "    def __init__(self):\n"
     "        self.start = 0\n"
     "        self.end = 0\n"
     "    def total(self):\n"
     "        return self.start + self.end\n"
     "    def plus(self, other):\n"
     "        return self.total() + other.start + other.end\n"
     "a = Slice()\n"
     "b = Slice()\n"
     "a.start = 1\n"
     "a.end = 2\n"
     "b.start = 10\n"
     "b.end = 20\n"
     "raise SystemExit(a.plus(b))\n",
     33, None, None),

    # ── WRITING THROUGH THE PARAMETER, on the callee and through the caller ──
    #
    # `bump` writes `other.start` and the caller reads `b.start` afterwards, so
    # the store has to land in the CALLER's frame and not in a copy.  This is
    # the half a read-only case cannot see: arm64's `_store_var` had a
    # fall-through that turned a store with no home into `mov x19, src`, and a
    # program that only reads through the parameter never reaches it.
    ("write_through_the_parameter_is_visible_to_the_caller",
     "struct Cell:\n"
     "    var start: Int\n"
     "    var end: Int\n"
     "\n"
     "    def bump(self, other: Cell) -> Int:\n"
     "        other.start = other.start + 11\n"
     "        self.end = self.end + 1\n"
     "        return other.end\n"
     "\n"
     "def main(n: Int) -> Int:\n"
     "    var a = Cell()\n"
     "    var b = Cell()\n"
     "    a.start = 1\n"
     "    a.end = 2\n"
     "    b.start = 10\n"
     "    b.end = 20\n"
     "    var seen = a.bump(b)\n"
     "    printf(\"%d %d %d %d\", seen, b.start, a.end, b.end)\n"
     "    return b.start\n",
     "import sys\n"
     "class Cell:\n"
     "    def __init__(self):\n"
     "        self.start = 0\n"
     "        self.end = 0\n"
     "    def bump(self, other):\n"
     "        other.start = other.start + 11\n"
     "        self.end = self.end + 1\n"
     "        return other.end\n"
     "a = Cell()\n"
     "b = Cell()\n"
     "a.start = 1\n"
     "a.end = 2\n"
     "b.start = 10\n"
     "b.end = 20\n"
     "seen = a.bump(b)\n"
     "sys.stdout.write(\"%d %d %d %d\" % (seen, b.start, a.end, b.end))\n"
     "raise SystemExit(b.start)\n",
     21, "20 21 3 20", None),

    # TWO OBJECTS, so the store has to land in the right frame.  `bump(b)` and
    # `bump(c)` write to two different frames at two different addresses, and
    # the guards are the reads that say which one moved.
    ("write_through_two_parameters_does_not_alias",
     "struct Cell:\n"
     "    var start: Int\n"
     "    var end: Int\n"
     "\n"
     "    def bump(self, other: Cell) -> Int:\n"
     "        other.start = other.start * 2\n"
     "        return other.start\n"
     "\n"
     "def main(n: Int) -> Int:\n"
     "    var a = Cell()\n"
     "    var b = Cell()\n"
     "    var c = Cell()\n"
     "    a.start = 1\n"
     "    b.start = 5\n"
     "    c.start = 7\n"
     "    a.bump(b)\n"
     "    if b.start != 10:\n"
     "        return 100 + b.start\n"
     "    if c.start != 7:\n"
     "        return 200 + c.start\n"
     "    a.bump(c)\n"
     "    if b.start != 10:\n"
     "        return 300 + b.start\n"
     "    if c.start != 14:\n"
     "        return 400 + c.start\n"
     "    return 0\n",
     "class Cell:\n"
     "    def __init__(self):\n"
     "        self.start = 0\n"
     "        self.end = 0\n"
     "    def bump(self, other):\n"
     "        other.start = other.start * 2\n"
     "        return other.start\n"
     "a = Cell()\n"
     "b = Cell()\n"
     "c = Cell()\n"
     "a.start = 1\n"
     "b.start = 5\n"
     "c.start = 7\n"
     "a.bump(b)\n"
     "if b.start != 10:\n"
     "    raise SystemExit(100 + b.start)\n"
     "if c.start != 7:\n"
     "    raise SystemExit(200 + c.start)\n"
     "a.bump(c)\n"
     "if b.start != 10:\n"
     "    raise SystemExit(300 + b.start)\n"
     "if c.start != 14:\n"
     "    raise SystemExit(400 + c.start)\n"
     "raise SystemExit(0)\n",
     0, None, None),

    # ── A FREE FUNCTION's parameter: the same construct, not a method's ────────
    #
    # Restricted to methods it would leave the identical refusal standing one
    # function away with nothing in the reader's source to tell the two apart,
    # and the declaration is the same evidence either way.
    ("free_function_parameter",
     "struct P:\n"
     "    var a: Int\n"
     "    var b: Int\n"
     "\n"
     "def spread(r: P) -> Int:\n"
     "    return r.a * 100 + r.b * 10 + 5\n"
     "\n"
     "def main(n: Int) -> Int:\n"
     "    var p = P()\n"
     "    p.a = 1\n"
     "    p.b = 2\n"
     "    return spread(p)\n",
     "class P:\n"
     "    def __init__(self):\n"
     "        self.a = 0\n"
     "        self.b = 0\n"
     "def spread(r):\n"
     "    return r.a * 100 + r.b * 10 + 5\n"
     "p = P()\n"
     "p.a = 1\n"
     "p.b = 2\n"
     "raise SystemExit(spread(p))\n",
     125, None, None),

    # A PARAMETER AT A POSITION OTHER THAN THE SECOND.  Position does not
    # matter for a declaration — the annotation names the layout, not the slot
    # — and the fixpoint's "every position" rule and this one have to agree
    # about which names are holders.
    ("parameter_at_the_fourth_position",
     "struct P:\n"
     "    var a: Int\n"
     "    var b: Int\n"
     "\n"
     "def pick(x: Int, y: Int, z: Int, r: P) -> Int:\n"
     "    return r.b - r.a\n"
     "\n"
     "def main(n: Int) -> Int:\n"
     "    var p = P()\n"
     "    p.a = 4\n"
     "    p.b = 40\n"
     "    return pick(0, 0, 0, p)\n",
     "class P:\n"
     "    def __init__(self):\n"
     "        self.a = 0\n"
     "        self.b = 0\n"
     "def pick(x, y, z, r):\n"
     "    return r.b - r.a\n"
     "p = P()\n"
     "p.a = 4\n"
     "p.b = 40\n"
     "raise SystemExit(pick(0, 0, 0, p))\n",
     36, None, None),

    # A KEYWORD argument reaching the same parameter: the position a keyword
    # lands in is the parameter list's business, so this is also the case that
    # says the agreement check resolved it by NAME and not by its place in
    # `args + kwargs`.
    ("keyword_argument_reaching_a_declared_parameter",
     "struct P:\n"
     "    var a: Int\n"
     "    var b: Int\n"
     "\n"
     "def wide(r: P, tail: Int) -> Int:\n"
     "    return r.a * 100 + r.b * 10 + tail\n"
     "\n"
     "def main(n: Int) -> Int:\n"
     "    var p = P()\n"
     "    p.a = 2\n"
     "    p.b = 3\n"
     "    return wide(tail=4, r=p)\n",
     "class P:\n"
     "    def __init__(self):\n"
     "        self.a = 0\n"
     "        self.b = 0\n"
     "def wide(r, tail):\n"
     "    return r.a * 100 + r.b * 10 + tail\n"
     "p = P()\n"
     "p.a = 2\n"
     "p.b = 3\n"
     "raise SystemExit(wide(tail=4, r=p))\n",
     234, None, None),

    # ── THE ONE-FIELD HALF: the receiver IS its field ────────────────────────
    #
    # `other.a` is `other`, which is the same rewrite `self.a` gets, and the
    # reason the two halves are worth doing together is that the REFUSAL is the
    # same message: a reader who fixed only the framed half would still meet
    # `field_access_refusal` here and conclude the first half was wrong.
    ("one_field_parameter_field_is_the_parameter",
     "struct One:\n"
     "    var a: Int\n"
     "\n"
     "    def twice(self, other: One) -> Int:\n"
     "        return other.a * 2\n"
     "\n"
     "def main(n: Int) -> Int:\n"
     "    var x = One()\n"
     "    var y = One()\n"
     "    x.a = 3\n"
     "    y.a = 40\n"
     "    return x.twice(y)\n",
     "class One:\n"
     "    def __init__(self):\n"
     "        self.a = 0\n"
     "    def twice(self, other):\n"
     "        return other.a * 2\n"
     "x = One()\n"
     "y = One()\n"
     "x.a = 3\n"
     "y.a = 40\n"
     "raise SystemExit(x.twice(y))\n",
     80, None, None),

    # The one-field half's STORE, which is the same "a store with no home" case
    # as the framed half's and a different branch of the emitter.
    #
    # It is asked of the CALLEE's own copy and NOT of the caller's object, and
    # the difference is a fact about the representation rather than about this
    # change: a one-field struct's receiver is a plain word handed over BY
    # VALUE, so `other.a = 99` writes the parameter — which is what `self.a`
    # does too, and has since `struct_fits_one_word` decided a one-field
    # struct needs no frame.  The framed half above is the opposite and is
    # where a store IS visible to the caller, because there the receiver is an
    # address.  Asserting the caller's object here would be asserting CPython's
    # object semantics on a representation that does not have them, and the
    # honest form of the assertion is the returned word.
    ("one_field_parameter_write",
     "struct One:\n"
     "    var a: Int\n"
     "\n"
     "    def set(self, other: One) -> Int:\n"
     "        other.a = 99\n"
     "        return other.a\n"
     "\n"
     "def main(n: Int) -> Int:\n"
     "    var x = One()\n"
     "    var y = One()\n"
     "    x.a = 1\n"
     "    y.a = 2\n"
     "    printf(\"%d %d\", x.set(y), y.a)\n"
     "    return 0\n",
     "import sys\n"
     "class One:\n"
     "    def __init__(self):\n"
     "        self.a = 0\n"
     "    def set(self, other):\n"
     "        other.a = 99\n"
     "        return other.a\n"
     "x = One()\n"
     "y = One()\n"
     "x.a = 1\n"
     "y.a = 2\n"
     "other = One()\n"
     "other.a = y.a\n"
     "sys.stdout.write(\"%d %d\" % (x.set(other), y.a))\n"
     "raise SystemExit(0)\n",
     0, "99 2", None),

    # A NESTED FRAME handed over as an ordinary argument: `take(self.in1)` puts
    # an address on the stack like any other frame, and the callee was declared
    # against `Inner`'s field list, so it is a frame address of exactly the
    # declared struct.  This is the case that says the agreement check asks
    # `_typed_nested_frame` rather than requiring a bare name — a check that only
    # recognised a name would refuse a program that is right.
    ("placed_nested_frame_handed_over_as_an_argument",
     "struct Inner:\n"
     "    var a: Int\n"
     "    var b: Int\n"
     "\n"
     "    def total(self) -> Int:\n"
     "        return self.a * 10 + self.b\n"
     "\n"
     "struct Outer:\n"
     "    var tag: Int\n"
     "    var pad: Int\n"
     "    var in1: Inner\n"
     "\n"
     "    def go(self) -> Int:\n"
     "        return take(self.in1) + self.tag\n"
     "\n"
     "def take(r: Inner) -> Int:\n"
     "    return r.total()\n"
     "\n"
     "def main(n: Int) -> Int:\n"
     "    var o = Outer()\n"
     "    o.tag = 7\n"
     "    o.in1.a = 3\n"
     "    o.in1.b = 4\n"
     "    return o.go()\n",
     "class Inner:\n"
     "    def __init__(self):\n"
     "        self.a = 0\n"
     "        self.b = 0\n"
     "    def total(self):\n"
     "        return self.a * 10 + self.b\n"
     "class Outer:\n"
     "    def __init__(self):\n"
     "        self.tag = 0\n"
     "        self.pad = 0\n"
     "        self.in1 = Inner()\n"
     "    def go(self):\n"
     "        return take(self.in1) + self.tag\n"
     "def take(r):\n"
     "    return r.total()\n"
     "o = Outer()\n"
     "o.tag = 7\n"
     "o.in1.a = 3\n"
     "o.in1.b = 4\n"
     "raise SystemExit(o.go())\n",
     41, None, None),

    # A REFERENCE marker in front of the type is the same declaration with one
    # word of decoration, and `annotation_base_name` strips markers before it
    # looks for a struct name.  Without the strip the parameter is untyped
    # and the program is refused, which is a false diagnostic about a
    # perfectly ordinary annotation.  (`read` is a C library name — unistd —
    # and a frame address handed to a C entry point is refused before the
    # declared type is consulted at all, so the callee here is named
    # something else.)
    ("reference_annotation_names_the_same_struct",
     "struct Inner:\n"
     "    var a: Int\n"
     "    var b: Int\n"
     "\n"
     "def field_sum(ref r: Inner) -> Int:\n"
     "    return r.a + r.b\n"
     "\n"
     "def main(n: Int) -> Int:\n"
     "    var i = Inner()\n"
     "    i.a = 3\n"
     "    i.b = 4\n"
     "    return field_sum(i)\n",
     "class Inner:\n"
     "    def __init__(self):\n"
     "        self.a = 0\n"
     "        self.b = 0\n"
     "def field_sum(r):\n"
     "    return r.a + r.b\n"
     "i = Inner()\n"
     "i.a = 3\n"
     "i.b = 4\n"
     "raise SystemExit(field_sum(i))\n",
     7, None, None),

    # ── A CALL SITE THAT HANDS OVER A FRAME THE EMITTER BUILT ITSELF ─────────
    #
    # `take(P(3, 4))` passes a frame address and says so: the emitters reserve a
    # block per construction site in the prologue and a construction's VALUE is
    # that block's address (`formal/model.py`'s `struct_constructor_sites`,
    # `formal/arm64_codegen.py`'s `_emit_frame_constructor`).  The check read it
    # as "a call to 'P'", found no frame there, and refused the program as a
    # declaration no call site agrees with — which is the opposite of what the
    # call site does.  `formal/types.py`'s `mask_of(IntType(w, False))` is the
    # shipped instance (`bugs/FORMAL_declared_parameter_against_its_call_sites.md`
    # §2), and `mask_of` is `formal/types.py` in this tree.
    #
    # `p.a * 10 + p.b` rather than a sum, so a read at the wrong SLOT says which
    # field moved: 34 for (3, 4), 43 if the two were transposed.
    ("construction_in_argument_position_agrees",
     "struct P:\n"
     "    var a: Int\n"
     "    var b: Int\n"
     "\n"
     "def take(p: P) -> Int:\n"
     "    return p.a * 10 + p.b\n"
     "\n"
     "def main(n: Int) -> Int:\n"
     "    return take(P(3, 4))\n",
     "class P:\n"
     "    def __init__(self, a=0, b=0):\n"
     "        self.a = a\n"
     "        self.b = b\n"
     "def take(p):\n"
     "    return p.a * 10 + p.b\n"
     "raise SystemExit(take(P(3, 4)))\n",
     34, None, None),

    # The same agreement by the other route: a call to a function that RETURNS a
    # frame.  `model.struct_returned_frame_sites` is the caller's half of the
    # same arrangement — the callee copies into a block this function reserved —
    # so `take(make(5))` is a frame address in exactly the sense `take(p)` is.
    ("frame_returning_call_in_argument_position_agrees",
     "struct P:\n"
     "    var a: Int\n"
     "    var b: Int\n"
     "\n"
     "def make(x: Int) -> P:\n"
     "    var p = P()\n"
     "    p.a = x\n"
     "    p.b = 2\n"
     "    return p\n"
     "\n"
     "def take(p: P) -> Int:\n"
     "    return p.a * 10 + p.b\n"
     "\n"
     "def main(n: Int) -> Int:\n"
     "    return take(make(5))\n",
     "class P:\n"
     "    def __init__(self):\n"
     "        self.a = 0\n"
     "        self.b = 0\n"
     "def make(x):\n"
     "    p = P()\n"
     "    p.a = x\n"
     "    p.b = 2\n"
     "    return p\n"
     "def take(p):\n"
     "    return p.a * 10 + p.b\n"
     "raise SystemExit(take(make(5)))\n",
     52, None, None),

    # ── THE REFUSALS: a declaration is a promise a call site can break ──────
    #
    # Each of these builds and RUNS wrong if the promise is believed: the field
    # read is `ldr [word, #8k]` on a word that is not an address.  So the check
    # is not decoration on the fix — it is the half of it that makes the other
    # half safe, and it is checked on BOTH backends because a refusal that only
    # one architecture makes is a wrong answer wearing a refusal's clothes.
    ("refuse_a_plain_word_at_every_site",
     "struct P:\n"
     "    var a: Int\n"
     "    var b: Int\n"
     "\n"
     "    def get(self, other: P) -> Int:\n"
     "        return other.a\n"
     "\n"
     "def main(n: Int) -> Int:\n"
     "    var p = P()\n"
     "    p.a = 5\n"
     "    p.b = 6\n"
     "    return p.get(3)\n",
     None, None, None,
     "P_get(p, 3) passes the literal 3"),

    # A frame of ANOTHER struct is a frame address and the wrong one: `base +
    # 8k` is P's layout and Q has a third field, so the read comes from storage
    # the source never wrote.  The message says "a Q frame" for that reason.
    ("refuse_another_structs_frame",
     "struct P:\n"
     "    var a: Int\n"
     "    var b: Int\n"
     "\n"
     "struct Q:\n"
     "    var a: Int\n"
     "    var b: Int\n"
     "    var c: Int\n"
     "\n"
     "    def get(self, other: P) -> Int:\n"
     "        return other.a\n"
     "\n"
     "def main(n: Int) -> Int:\n"
     "    var q = Q()\n"
     "    q.a = 5\n"
     "    q.b = 6\n"
     "    q.c = 7\n"
     "    return q.get(q)\n",
     None, None, None,
     "passes a Q frame"),

    # The one-field half's version of the same promise.  `other.a` is `other`,
    # so a frame address handed over here is read as the field itself — a wrong
    # number rather than a wild load, and just as wrong.
    ("refuse_a_frame_where_a_one_field_struct_is_declared",
     "struct One:\n"
     "    var a: Int\n"
     "\n"
     "    def take(self, other: One) -> Int:\n"
     "        return other.a + 1\n"
     "\n"
     "struct Big:\n"
     "    var a: Int\n"
     "    var b: Int\n"
     "\n"
     "def main(n: Int) -> Int:\n"
     "    var x = One()\n"
     "    var b = Big()\n"
     "    b.a = 5\n"
     "    b.b = 6\n"
     "    return x.take(b)\n",
     None, None, None,
     "passes a Big frame"),

    # ── AND THE TWO THAT LOOK LIKE THE POSITIVES ABOVE ─────────────────────
    #
    # A call site that hands over a frame is only corroborating the declaration
    # if it is a frame OF THE DECLARED STRUCT.  These are the two ways it is
    # not, and both were reachable by the fix that taught the check about
    # constructions and frame-returning calls: `base + 8k` is P's layout, so a Q
    # address reads storage the source never wrote — Q's third field is not
    # even in P's frame.
    ("refuse_another_structs_construction",
     "struct P:\n"
     "    var a: Int\n"
     "    var b: Int\n"
     "\n"
     "struct Q:\n"
     "    var a: Int\n"
     "    var b: Int\n"
     "    var c: Int\n"
     "\n"
     "def take(p: P) -> Int:\n"
     "    return p.a\n"
     "\n"
     "def main(n: Int) -> Int:\n"
     "    return take(Q(1, 2, 3))\n",
     None, None, None,
     "passes a Q frame built here"),

    ("refuse_a_frame_returning_call_of_another_struct",
     "struct P:\n"
     "    var a: Int\n"
     "    var b: Int\n"
     "\n"
     "struct Q:\n"
     "    var a: Int\n"
     "    var b: Int\n"
     "    var c: Int\n"
     "\n"
     "def make_q(x: Int) -> Q:\n"
     "    var q = Q()\n"
     "    q.a = x\n"
     "    q.b = 2\n"
     "    q.c = 3\n"
     "    return q\n"
     "\n"
     "def take(p: P) -> Int:\n"
     "    return p.a\n"
     "\n"
     "def main(n: Int) -> Int:\n"
     "    return take(make_q(7))\n",
     None, None, None,
     "passes a Q frame from make_q()"),

    # ── a `@staticmethod` gets NO receiver, on either side of a call ──────────
    #
    # `bugs/FORMAL_staticmethod_is_compiled_as_an_instance_method.md`. Two
    # readers in `formal/build.py` consulted only the parameter list and between
    # them gave a `@staticmethod` a receiver on BOTH sides: the definition was
    # compiled as if it took one, and the call site passed one, for a function
    # whose parameter list has neither. The two call sites disagreed visibly —
    # `R__single(self, counter)` is two arguments to a one-parameter function —
    # and the arity check caught it, so this was never a wrong answer. What it
    # cost was a refusal reported against the WRONG argument, since position 0
    # of the call was the receiver the definition read as its first parameter.
    #
    # Both spellings are here because `_rewrite_method_calls` lifts
    # `recv.m(a)` to `Struct_m(recv, a)` and drops the receiver for a name in
    # `receiverless`, and the two sides of the bug were in two DIFFERENT
    # readers: `_receiverless_methods` decided whether to pass one, and the
    # holder fixpoint decided what the callee's `self` was bound to. A fix to
    # only one of them still builds a two-argument call or still compiles a
    # receiver the call never supplies, and each of those fails differently.
    #
    # The oracles are transcriptions, so a case cannot pass by agreeing with a
    # wrong expectation: `staticmethod` is spelled `@staticmethod` on the class
    # and is a plain function at module scope in the transcription.
    ("staticmethod_called_on_the_class_takes_no_receiver",
     "struct K:\n"
     "    var a: Int\n"
     "\n"
     "    @staticmethod\n"
     "    def twice(x: Int) -> Int:\n"
     "        return x + x\n"
     "\n"
     "def main(n: Int) -> Int:\n"
     "    var k = K()\n"
     "    k.a = 20\n"
     "    return K.twice(k.a)\n",
     "class K:\n"
     "    def __init__(self):\n"
     "        self.a = 0\n"
     "    @staticmethod\n"
     "    def twice(x):\n"
     "        return x + x\n"
     "k = K()\n"
     "k.a = 20\n"
     "raise SystemExit(K.twice(k.a))\n",
     40, None, None),
    ("staticmethod_called_through_an_instance_takes_no_receiver",
     "struct K:\n"
     "    var a: Int\n"
     "\n"
     "    def get(self) -> Int:\n"
     "        return K.twice(self.a)\n"
     "\n"
     "    @staticmethod\n"
     "    def twice(x: Int) -> Int:\n"
     "        return x + x\n"
     "\n"
     "def main(n: Int) -> Int:\n"
     "    var k = K()\n"
     "    k.a = 20\n"
     "    return k.get()\n",
     "class K:\n"
     "    def __init__(self):\n"
     "        self.a = 0\n"
     "    def get(self):\n"
     "        return K.twice(self.a)\n"
     "    @staticmethod\n"
     "    def twice(x):\n"
     "        return x + x\n"
     "k = K()\n"
     "k.a = 20\n"
     "raise SystemExit(k.get())\n",
     40, None, None),
    # A `@staticmethod` AND an instance method on one class, called both ways,
    # which is the pairing that makes each reader's half visible: with the
    # holder fixpoint unfixed the instance method's `self` is right and the
    # staticmethod's is a phantom, and with `_receiverless_methods` unfixed the
    # staticmethod's call gains an argument. A fix that dropped receivers for
    # EVERY method would pass both of the cases above and fail this one, which
    # is why it is here rather than being redundant.
    ("an_instance_method_still_gets_its_receiver",
     "struct K:\n"
     "    var a: Int\n"
     "\n"
     "    def get(self) -> Int:\n"
     "        return self.a + 1\n"
     "\n"
     "    @staticmethod\n"
     "    def twice(x: Int) -> Int:\n"
     "        return x + x\n"
     "\n"
     "def main(n: Int) -> Int:\n"
     "    var k = K()\n"
     "    k.a = 20\n"
     "    return k.get() + K.twice(3)\n",
     "class K:\n"
     "    def __init__(self):\n"
     "        self.a = 0\n"
     "    def get(self):\n"
     "        return self.a + 1\n"
     "    @staticmethod\n"
     "    def twice(x):\n"
     "        return x + x\n"
     "k = K()\n"
     "k.a = 20\n"
     "raise SystemExit(k.get() + K.twice(3))\n",
     27, None, None),
    # A `@staticmethod` on a struct of MORE THAN ONE FIELD, which is the shape
    # the filing's reproducer has and the one that reached the filed refusal
    # text. `counter.a` in the body is a load at `base + 8k` off a frame the
    # function does not have, so the parameter's DECLARED type is what has to be
    # believed — which is this file's subject, and the reason the staticmethod
    # cases live here rather than in a receiver-position file. Kept at two
    # fields and a scalar parameter on purpose: the filing's `Vec` reproducer
    # needs a NESTED frame placed, which is a separate construct
    # (`formal/model.py`'s `struct_nested_frame_fields` wants a plain struct
    # name and the field is spelled `SIMD[.uint32, 4]`), so pinning THAT here
    # would be asserting a fix nobody made.
    ("staticmethod_on_a_multifield_struct_body_reads_its_parameter",
     "struct Vec:\n"
     "    var a: Int\n"
     "    var b: Int\n"
     "\n"
     "struct K:\n"
     "    var v: Vec\n"
     "    var n: Int\n"
     "\n"
     "    @staticmethod\n"
     "    def add(x: Int, y: Int) -> Int:\n"
     "        return x + y\n"
     "\n"
     "    def total(self) -> Int:\n"
     "        return K.add(self.n, 1)\n"
     "\n"
     "def main(n: Int) -> Int:\n"
     "    var k = K()\n"
     "    k.n = 41\n"
     "    return k.total()\n",
     "class Vec:\n"
     "    def __init__(self):\n"
     "        self.a = 0\n"
     "        self.b = 0\n"
     "class K:\n"
     "    def __init__(self):\n"
     "        self.v = Vec()\n"
     "        self.n = 0\n"
     "    @staticmethod\n"
     "    def add(x, y):\n"
     "        return x + y\n"
     "    def total(self):\n"
     "        return K.add(self.n, 1)\n"
     "k = K()\n"
     "k.n = 41\n"
     "raise SystemExit(k.total())\n",
     42, None, None),
]


def build_formal(src, out, backend):
    """`fire.py build --formal --no-prove`, as a (returncode, output) pair."""
    cmd = [sys.executable, FIRE, "build", "--formal", "--no-prove",
           "-o", out, f"--backend={backend}", src]
    p = subprocess.run(cmd, capture_output=True, text=True,
                       timeout=BUILD_TIMEOUT, cwd=HERE)
    return p.returncode, (p.stderr or p.stdout or "")


def run_cpython(source, tmpdir, name):
    """CPython's own exit status and stdout for the transcribed program."""
    path = os.path.join(tmpdir, name + ".py")
    with open(path, "w") as f:
        f.write(source)
    p = subprocess.run([sys.executable, path], capture_output=True, text=True,
                       timeout=RUN_TIMEOUT)
    return p.returncode, p.stdout


def run_image(path, backend):
    """The built image's exit status and stdout, x86-64 under Rosetta."""
    argv = [path]
    if backend == "x86_64" and sys.platform == "darwin":
        argv = ["arch", "-x86_64", path]
    p = subprocess.run(argv, capture_output=True, text=True,
                       timeout=RUN_TIMEOUT)
    return p.returncode, p.stdout


def check(name, mojo, python_src, want_exit, want_stdout, needle, tmpdir,
          verbose):
    """One case, on BOTH backends, against CPython where there is an oracle."""
    src = os.path.join(tmpdir, name + ".mojo")
    with open(src, "w") as f:
        f.write(mojo)

    if needle is not None:
        for backend in ("arm64", "x86_64"):
            rc, text = build_formal(src, os.path.join(tmpdir, f"{name}.{backend}"),
                                    backend)
            if rc == 0:
                return False, (f"--backend={backend} BUILT a program whose "
                               f"call site contradicts the parameter's declared "
                               f"type (expected a refusal naming "
                               f"{needle!r}); the binary is the real answer here")
            if needle not in text:
                return False, (f"--backend={backend} refused, but not with the "
                               f"expected words {needle!r}: "
                               f"{text.strip()[-240:]}")
        if verbose:
            print(f"      refused identically on arm64 and x86-64: {needle!r}")
        return True, ""

    py_exit, py_out = run_cpython(python_src, tmpdir, name)
    if py_exit != want_exit:
        return False, (f"the CPython oracle disagrees with the case: wanted "
                       f"exit {want_exit}, CPython says {py_exit} (stderr: "
                       f"{'see run'})")

    for backend in ("arm64", "x86_64"):
        out = os.path.join(tmpdir, f"{name}.{backend}")
        rc, text = build_formal(src, out, backend)
        if rc != 0:
            return False, (f"--backend={backend} refused a program with a "
                           f"declared parameter type: {text.strip()[-240:]}")
        got_exit, got_out = run_image(out, backend)
        if got_exit != py_exit:
            return False, (f"--backend={backend} returned {got_exit} where "
                           f"CPython returns {py_exit}")
        if got_out != py_out:
            return False, (f"--backend={backend} printed {got_out!r} where "
                           f"CPython prints {py_out!r}")
        if want_stdout is not None and want_stdout not in got_out:
            return False, (f"--backend={backend} printed {got_out!r}, which "
                           f"does not contain {want_stdout!r}")
    if verbose:
        print(f"      both backends agree with CPython: exit {py_exit}"
              + (f", stdout {py_out.strip()!r}" if py_out.strip() else ""))
    return True, ""


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("-v", "--verbose", action="store_true")
    ap.add_argument("cases", nargs="*", help="subset of case names")
    args = ap.parse_args()

    if platform.machine() not in ("arm64", "aarch64"):
        print(f"SKIP: the formal images are arm64/x86-64 Mach-O, host is "
              f"{platform.machine()}")
        return 0

    selected = [c for c in CASES if not args.cases or c[0] in args.cases]
    known = {c[0] for c in CASES}
    if args.cases and len(selected) != len(args.cases):
        print(f"ERROR: unknown case(s): {sorted(set(args.cases) - known)}",
              file=sys.stderr)
        return 2

    passed = failed = 0
    with tempfile.TemporaryDirectory() as tmpdir:
        for name, mojo, python_src, want_exit, want_stdout, needle \
                in selected:
            try:
                ok, detail = check(name, mojo, python_src, want_exit,
                                   want_stdout, needle, tmpdir, args.verbose)
            except subprocess.TimeoutExpired:
                ok, detail = False, "timed out"
            except Exception as e:                     # noqa: BLE001
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

    print(f"\nmethod param field: PASS={passed} FAIL={failed}")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())