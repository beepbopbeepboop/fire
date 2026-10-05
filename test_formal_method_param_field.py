#!/usr/bin/env python3
"""A METHOD PARAMETER'S FIELD, established by its DECLARED TYPE and nothing
else: build the image, run it, and compare with CPython.

A method's other
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

The last seven cases are the LOCAL half of the same evidence: a declared type
settles a PARAMETER, and a member read of a field declared as a framed struct
settles a LOCAL that copies it (`var t = self.inner` then `t.v`), which is the
same program as the chain spelling and was refused while the chain built.  So
`_frame_receivers` asks `_typed_nested_frame` for that read too — the same
agree-or-refuse decision the field-slot readers make, so the two cannot answer
differently — and `t` becomes a frame holder.  What separates these rows from
the parameter rows above is not a weaker kind of evidence, the slot's declared
type is as much a promise as a parameter's is, but a SECOND LIFETIME question
the parameter rows do not have: a field a METHOD of its own struct assigns
holds a frame belonging to whichever function ran that assignment
(`_typed_nested_frame`'s `_REASSIGNED`), and a name the body ALSO binds by some
other form (`for t in …`) holds a word this pass cannot account for.  Both are
refused, for opposite reasons, and both refusals are cases here — as is the
seeding's own limit, the two-copies-deep chain where a name has to be settled
before the next one is read.

The seven are: the three answers of `_typed_nested_frame` for a PLACED nested
frame, for a DELEGATING field (the exemption that keeps a caller's frame
readable, and the reason this arm cannot be a blind copy of the parameter one)
and for `_REASSIGNED`; the direct spelling in a FREE FUNCTION rather than a
method, so the local holder is a local bound to a construction and the first row
is answered by the nested-frame machinery rather than by anything about a method;
the two-copies-deep chain; and the two refusals.    python3 test_formal_method_param_field.py [-v] [case ...]
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

    # ── a struct-typed FIELD, initialised from a constructor ARGUMENT ─────────
    #
    # `bugs/FORMAL_builtin_slice_optional_field_is_a_frame_holder.md`, shape 1.
    # The refusal and the workaround its own message names, as ONE pair, because
    # the message makes a promise to the reader — "Assign the field after
    # `Box(…)`, which is the same program" — and a promise nobody checks is how a
    # refusal sends readers after a non-bug, which is the failure mode this
    # whole family documents itself as existing to prevent. If the workaround
    # regressed, the refusal would still be refusing and the advice would still
    # be wrong.
    #
    # The refusal is the lifetime half, and the pair says which half: the two
    # programs differ in ONE thing — where the frame comes from. `Box(o)` stores
    # the CALLER's frame through the object, and a frame parameter outlives
    # whatever the constructor does with it, so nothing at the store can say the
    # two lifetimes agree. The working form stores a frame the CALLEE created
    # (`mk`'s own block, returned), which the caller owns for the whole
    # expression.
    #
    # Both spellings of the same source are given, so neither case can pass by
    # agreeing with a wrong expectation — and the transcriptions are oracles,
    # not tables.
    #
    # **WHICH refusal answers `Box(o)`, and why it is the CONSTRUCTION one.**
    # The receiver rule pre-empted it for a while: `Box` here has exactly ONE
    # field, so `_rewrite_self_fields` collapses `self.inner` onto `self` before
    # anything late looks at the store, and `model.one_word_sole_field_frame`
    # (7632c881) withdrew `_collect_receiver_rebinds`'s one-field exemption for
    # exactly these owners, because `self = o` overwrites the frame address the
    # caller still holds. That sentence is FALSE about this source in three ways
    # at once — it names a rebinding of `self` the file does not contain, it
    # claims CPython rejects the shape (CPython runs
    # `def __init__(self, o): self.inner = o` all day), and it names
    # `Box___init__`, which on the `_fieldwise_ctor_synthesized` programs is a
    # name in no file the reader has open. So the rule now stands down for a
    # method that IS the constructor (`method_member_name(owner, fn) ==
    # "__init__"`), on the ground that this path never CALLS one: `init_body_stores`
    # inlines the stores into the fresh block at the CONSTRUCTION SITE, so there
    # is no callee-local `self` for a rebinding to lose — and a constructor whose
    # body is not a straight line of stores is refused by `init_body_stores`
    # itself. The needle below is therefore back to the sentence this row was
    # written with, and the same reader the message was written for.
    #
    # The exemption is narrow on purpose: `test_formal_run.py`'s
    # `refuse_a_one_word_holder_of_a_frame_stored_through_its_receiver` is the
    # same store in an ordinary METHOD (`set`), and it stays refused by the
    # receiver rule with its measured SIGSEGV behind it.
    ("refuse_a_struct_field_initialised_from_a_constructor_argument",
     "struct Opt:\n"
     "    var v: Int\n"
     "    var has: Int\n"
     "\n"
     "struct Box:\n"
     "    var inner: Opt\n"
     "\n"
     "    def __init__(out self, o: Opt):\n"
     "        self.inner = o\n"
     "\n"
     "def main() -> Int:\n"
     "    var o = Opt()\n"
     "    o.v = 41\n"
     "    o.has = 1\n"
     "    var b = Box(o)\n"
     "    printf(\"v=%d h=%d\", b.inner.v, b.inner.has)\n"
     "    return 0\n",
     "class Opt:\n"
     "    def __init__(self):\n"
     "        self.v = 0\n"
     "        self.has = 0\n"
     "\n"
     "class Box:\n"
     "    def __init__(self, o):\n"
     "        self.inner = o\n"
     "\n"
     "o = Opt()\n"
     "o.v = 41\n"
     "o.has = 1\n"
     "b = Box(o)\n"
     "print(\"v=%d h=%d\" % (b.inner.v, b.inner.has), end=\"\")\n",
     None, None,
     "constructing Box with argument 'o' as field 'inner'"),
    ("a_struct_field_assigned_after_construction_is_the_same_program",
     "struct Opt:\n"
     "    var v: Int\n"
     "    var has: Int\n"
     "\n"
     "struct Box:\n"
     "    var inner: Opt\n"
     "\n"
     "    def __init__(out self):\n"
     "        self.inner = Opt()\n"
     "\n"
     "def mk(v: Int) -> Opt:\n"
     "    var o = Opt()\n"
     "    o.v = v\n"
     "    o.has = 1\n"
     "    return o\n"
     "\n"
     "def main() -> Int:\n"
     "    var b = Box()\n"
     "    b.inner = mk(41)\n"
     "    printf(\"v=%d h=%d\", b.inner.v, b.inner.has)\n"
     "    return 0\n",
     "class Opt:\n"
     "    def __init__(self):\n"
     "        self.v = 0\n"
     "        self.has = 0\n"
     "\n"
     "class Box:\n"
     "    def __init__(self):\n"
     "        self.inner = Opt()\n"
     "\n"
     "def mk(v):\n"
     "    o = Opt()\n"
     "    o.v = v\n"
     "    o.has = 1\n"
     "    return o\n"
     "\n"
     "b = Box()\n"
     "b.inner = mk(41)\n"
     "print(\"v=%d h=%d\" % (b.inner.v, b.inner.has), end=\"\")\n",
     0, "v=41 h=1", None),
    # The boundary the pair above turns on, as its own case: a ONE-FIELD struct
    # is a WORD and not a frame, so the same constructor shape BUILDS. Without
    # this the pair would read as "a struct field from an argument is refused",
    # which is false, and the next reader would file the false version.
    ("a_one_field_struct_field_from_an_argument_is_a_word_not_a_frame",
     "struct Word:\n"
     "    var only: Int\n"
     "\n"
     "struct BoxW:\n"
     "    var inner: Word\n"
     "\n"
     "    def __init__(out self, w: Word):\n"
     "        self.inner = w\n"
     "\n"
     "def main() -> Int:\n"
     "    var w = Word()\n"
     "    w.only = 42\n"
     "    var b = BoxW(w)\n"
     "    printf(\"only=%d\", b.inner.only)\n"
     "    return 0\n",
     "class Word:\n"
     "    def __init__(self):\n"
     "        self.only = 0\n"
     "\n"
     "class BoxW:\n"
     "    def __init__(self, w):\n"
     "        self.inner = w\n"
     "\n"
     "w = Word()\n"
     "w.only = 42\n"
     "b = BoxW(w)\n"
     "print(\"only=%d\" % b.inner.only, end=\"\")\n",
     0, "only=42", None),

    # ── a `@staticmethod` gets NO receiver, on either side of a call ──────────
    #
    # `FORMAL_staticmethod_is_compiled_as_an_instance_method`. Two
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

    # ── A FREE FUNCTION WHOSE NAME IS ALSO A METHOD'S ────────────────────────
    #
    # `_prepare_functions` builds TWO method→struct maps and hands each of them
    # to a different pass.  `owners` (build.py:8840) is `{bare method name:
    # struct NAME}`, because `_rewrite_method_calls` dispatches `recv.m(...)` by
    # name alone and needs a NAME.  `method_owners` (build.py:8890) is `{lifted
    # function name: struct}`, because the passes that ask "which struct's
    # LAYOUT is this body written against" need the StructDef itself.
    #
    # `_frame_receivers` is the second kind of consumer — its parameter is
    # documented as `{function name: struct}` and both its uses read `.name` off
    # the VALUE — and it was being handed the first map.  The lookup only ever
    # HIT when a free function shares a name with some visible struct's method,
    # and then `_overridden_comptime_names` got a `str` where it wanted a
    # struct:
    #
    #   AttributeError: 'str' object has no attribute 'name'
    #     formal/build.py:6465 in _overridden_comptime_names
    #       st.name
    #     formal/build.py:6255 in publish
    #     formal/build.py:6232 in _constant_read_sites
    #
    # Measured on `std/builtin/reversed.mojo`, which the sweep classified
    # `backend-crash` — the one class that means a bug in the compiler's own
    # plumbing rather than a finding about the source, and the only one that is
    # never cached.  `reversed.mojo` declares seven module-level `reversed`
    # functions and imports a host module whose structs have a `reversed`
    # method.
    #
    # Both halves of the shape are here: `get` must HOLD A FRAME (`p` is a
    # two-field struct, so its receiver is a frame address and `_frame_receivers`
    # rewrites the class-constant read sites of exactly the functions the holder
    # fixpoint found), and the module-level `get` must SHARE ITS NAME with
    # `Pair.get` — which is what makes the wrong map's bare-name key hit.
    # Without the name collision the lookup missed and the census was silently
    # empty, which is the quieter half of the same bug.
    ("free_function_named_like_a_method_does_not_crash_the_build",
     "struct Pair:\n"
     "    var a: Int\n"
     "    var b: Int\n"
     "\n"
     "    def get(self) -> Int:\n"
     "        return self.a * 10 + self.b\n"
     "\n"
     "def get(n: Int) -> Int:\n"
     "    var p = Pair()\n"
     "    p.a = 1\n"
     "    p.b = 2\n"
     "    return p.a + p.b + n\n"
     "\n"
     "def main(k: Int) -> Int:\n"
     "    var q = Pair()\n"
     "    q.a = 3\n"
     "    q.b = 4\n"
     '    printf("v=%d", get(5) + q.get())\n'
     "    return 0\n",
     "class Pair:\n"
     "    def __init__(self):\n"
     "        self.a = 0\n"
     "        self.b = 0\n"
     "    def get(self):\n"
     "        return self.a * 10 + self.b\n"
     "def get(n):\n"
     "    p = Pair()\n"
     "    p.a = 1\n"
     "    p.b = 2\n"
     "    return p.a + p.b + n\n"
     "import sys\n"
     "q = Pair()\n"
     "q.a = 3\n"
     "q.b = 4\n"
     'sys.stdout.write("v=%d" % (get(5) + q.get()))\n',
     0, "v=42", None),
    # ── THE `_REASSIGNED` ADVICE, and why it is a case rather than a comment ──
    #
    # A frame-typed field a NON-CONSTRUCTOR method assigns is refused
    # (`_typed_nested_frame`'s `_REASSIGNED`), and the refusal used to end by
    # naming a spelling: "Assign the field to a name and read through the name"
    # at the nested-read site and "…and call the method on the name" at the
    # constructor site. BOTH were measured false on both architectures, each in
    # its own way — `var t = self.inner; t.v` is refused for want of a shape for
    # `t`, and `var t = self.inner; t.get()` is refused as a method call on a
    # value whose method is not one this path lowers. A refusal that names a
    # spelling it also refuses is a promise nobody checked, which is how a
    # diagnostic sends a reader after a non-bug, so the advice is now the form
    # that is MEASURED to build: a DELEGATING field, assigned in `__init__` from
    # a parameter of `__init__`.
    #
    # The needle is the clause that says what makes the delegating form sound —
    # "a constructor's argument is the frame the CALLER reached" — because the
    # NAME of the advice is not what a reader has to trust; the reason is.
    ("a_frame_field_assigned_by_a_method_advises_the_delegating_constructor",
     "struct Opt:\n"
     "    var v: Int\n"
     "    var has: Int\n"
     "\n"
     "struct Box:\n"
     "    var pad: Int\n"
     "    var inner: Opt\n"
     "\n"
     "    def set(out self, o: Opt):\n"
     "        self.inner = o\n"
     "\n"
     "    def get(out self) -> Int:\n"
     "        return self.inner.v * 10 + self.inner.has\n"
     "\n"
     "def mk(n: Int) -> Opt:\n"
     "    var o = Opt()\n"
     "    o.v = n\n"
     "    o.has = 1\n"
     "    return o\n"
     "\n"
     "def main() -> int:\n"
     "    var b = Box()\n"
     "    b.set(mk(4))\n"
     "    printf(\"g=%d\", b.get())\n"
     "    return 0\n",
     None, None, None,
     "a constructor's argument is the frame the CALLER reached"),
    # And the advice's own PROMISE, executed on both architectures against
    # CPython: the same program with the field assigned in `__init__` from
    # `__init__`'s own parameter. This is the half that is easy to leave out —
    # a reworded advice nobody runs is an advice nobody knows is true — and it
    # is the case that keeps `bugs/FORMAL_builtin_slice_optional_field_is_a_
    # frame_holder.md`'s remaining item (the `_REASSIGNED` question) described
    # accurately: the refusal is a LIFETIME question about which function
    # assigns, not a gap in what a frame-typed field can be.
    ("the_delegating_constructor_form_the_advice_names_builds_and_answers",
     "struct Opt:\n"
     "    var v: Int\n"
     "    var has: Int\n"
     "\n"
     "struct Box:\n"
     "    var pad: Int\n"
     "    var inner: Opt\n"
     "\n"
     "    def __init__(out self, o: Opt):\n"
     "        self.inner = o\n"
     "\n"
     "    def get(out self) -> Int:\n"
     "        return self.inner.v * 10 + self.inner.has\n"
     "\n"
     "def mk(n: Int) -> Opt:\n"
     "    var o = Opt()\n"
     "    o.v = n\n"
     "    o.has = 1\n"
     "    return o\n"
     "\n"
     "def main() -> int:\n"
     "    var b = Box(mk(4))\n"
     "    printf(\"g=%d\", b.get())\n"
     "    return 0\n",
     "class Opt:\n"
     "    def __init__(self):\n"
     "        self.v = 0\n"
     "        self.has = 0\n"
     "class Box:\n"
     "    def __init__(self, o):\n"
     "        self.pad = 0\n"
     "        self.inner = o\n"
     "    def get(self):\n"
     "        return self.inner.v * 10 + self.inner.has\n"
     "def mk(n):\n"
     "    o = Opt()\n"
     "    o.v = n\n"
     "    o.has = 1\n"
     "    return o\n"
     "import sys\n"
     "sys.stdout.write(\"g=%d\" % Box(mk(4)).get())\n",
     0, "g=41", None),

    # ── A LOCAL BOUND TO A NESTED FRAME FIELD READ ─────────────────────────
    #
    # The two rows above agree on one thing and it is worth stating: they read
    # `self.inner.v` THROUGH the field.  Naming the same value in a local first
    # — `var t = self.inner; return t.v * 10 + t.has` — was REFUSED on both
    # architectures with `field_access_refusal`, "'t.v' is a field access
    # through 't', and this path has no way to say what 't' holds", while every
    # other reading of the same program built and answered `g=41`.  The
    # binding is a member read whose declared type is a framed struct of this
    # module, and `_frame_receivers` had no arm that turns such a read into a
    # holder: the parameter arm above and the constructor arm both seed from a
    # CONSTRUCTION or a DECLARATION, and a member read is neither.
    #
    # So the arm is seeded beside the name-copy edge in `_frame_receivers`'s
    # fixpoint and it is asked ONE question — `_typed_nested_frame` — which is
    # what makes it the same decision the field-slot readers already make rather
    # than a second rule that could answer differently.  Three answers, three
    # cases, and the three rows here are exactly the three:
    #
    #   * a PLACED nested frame (`struct_nested_frame_fields`) — the first row;
    #   * a DELEGATING field (`init_stores_a_parameter_struct`), the second,
    #     which is the exemption that keeps a caller's frame readable and the
    #     reason this arm cannot be a blind copy of the parameter one;
    #   * `_REASSIGNED` — the third, and the answer that says the declared type
    #     is a frame of this unit AND some executed method writes the field, so
    #     the word in the slot is a frame belonging to whichever function ran
    #     the assignment.  Skipping it is the SIGSEGV
    #     `FORMAL_one_field_holder_of_a_frame_is_not_a_holder` records for the
    #     analogous receiver-seeding mistake.
    #
    # The refusal row's writer stores a WORD into a frame-typed slot, and that
    # is deliberate rather than a type error: no frame ever enters the slot, so
    # this is the writer shape that reaches the arm on the strength of the
    # READER's evidence alone.  It is the pin that the seeding declines — which
    # is the property, rather than the fact that some refusal fires — and it is
    # a different program from the frame-storing writer two rows below, which is
    # what `FORMAL_wide_receiver_by_reference` refuses on its own account.
    #
    # The NEEDLE is `DELEGATING_FIELD_ADVICE` rather than the emitter's
    # "'t.v' is a field access through 't'", and that is a merge, not a
    # preference.  `formal/build.py`'s `_nested_frame_bindings` (new on
    # `work/merge-formal27a-r2`) reports this program as `reassigned` and hands
    # the reader the real reason; its own docstring says why, and it is the same
    # sentence: the emitter's text "is true and names a type inference rather
    # than the lifetime question that is actually there".  So the row keeps its
    # program and its property and its needle moves to the message the tree now
    # emits — which is the same clause
    # `a_local_copy_of_a_field_a_method_reassigns_names_the_lifetime` pins,
    # because `_REASSIGNED` is ONE refusal and these are two programs that
    # reach it.
    ("a_local_bound_to_a_nested_frame_field_read_builds_and_answers",
     "struct Opt:\n"
     "    var v: Int\n"
     "    var has: Int\n"
     "\n"
     "struct Box:\n"
     "    var pad: Int\n"
     "    var inner: Opt\n"
     "\n"
     "    def get(out self) -> Int:\n"
     "        var t = self.inner\n"
     "        return t.v * 10 + t.has\n"
     "\n"
     "def mk(n: Int) -> Opt:\n"
     "    var o = Opt()\n"
     "    o.v = n\n"
     "    o.has = 1\n"
     "    return o\n"
     "\n"
     "def main() -> int:\n"
     "    var b = Box()\n"
     "    b.inner = mk(4)\n"
     '    printf("g=%d", b.get())\n'
     "    return 0\n",
     "class Opt:\n"
     "    def __init__(self):\n"
     "        self.v = 0\n"
     "        self.has = 0\n"
     "class Box:\n"
     "    def __init__(self):\n"
     "        self.pad = 0\n"
     "        self.inner = None\n"
     "    def get(self):\n"
     "        t = self.inner\n"
     "        return t.v * 10 + t.has\n"
     "def mk(n):\n"
     "    o = Opt()\n"
     "    o.v = n\n"
     "    o.has = 1\n"
     "    return o\n"
     "import sys\n"
     "b = Box()\n"
     "b.inner = mk(4)\n"
     'sys.stdout.write("g=%d" % b.get())\n',
     0, "g=41", None),
    ("a_local_bound_to_a_delegating_nested_frame_field_answers_too",
     "struct Opt:\n"
     "    var v: Int\n"
     "    var has: Int\n"
     "\n"
     "struct Box:\n"
     "    var pad: Int\n"
     "    var inner: Opt\n"
     "\n"
     "    def __init__(out self, o: Opt):\n"
     "        self.inner = o\n"
     "\n"
     "    def get(out self) -> Int:\n"
     "        var t = self.inner\n"
     "        return t.v * 10 + t.has\n"
     "\n"
     "def mk(n: Int) -> Opt:\n"
     "    var o = Opt()\n"
     "    o.v = n\n"
     "    o.has = 1\n"
     "    return o\n"
     "\n"
     "def main() -> int:\n"
     "    var b = Box(mk(4))\n"
     '    printf("g=%d", b.get())\n'
     "    return 0\n",
     "class Opt:\n"
     "    def __init__(self):\n"
     "        self.v = 0\n"
     "        self.has = 0\n"
     "class Box:\n"
     "    def __init__(self, o):\n"
     "        self.pad = 0\n"
     "        self.inner = o\n"
     "    def get(self):\n"
     "        t = self.inner\n"
     "        return t.v * 10 + t.has\n"
     "def mk(n):\n"
     "    o = Opt()\n"
     "    o.v = n\n"
     "    o.has = 1\n"
     "    return o\n"
     "import sys\n"
     'sys.stdout.write("g=%d" % Box(mk(4)).get())\n',
     0, "g=41", None),
    ("a_local_bound_to_a_field_a_method_reassigns_is_still_refused",
     "struct Opt:\n"
     "    var v: Int\n"
     "    var has: Int\n"
     "\n"
     "struct Box:\n"
     "    var pad: Int\n"
     "    var inner: Opt\n"
     "\n"
     "    def get(out self) -> Int:\n"
     "        var t = self.inner\n"
     "        return t.v * 10 + t.has\n"
     "\n"
     "    def blank(out self, k: Int) -> Int:\n"
     "        self.inner = k\n"
     "        return 0\n"
     "\n"
     "def main() -> int:\n"
     "    var b = Box()\n"
     '    printf("g=%d", b.get())\n'
     "    return 0\n",
     None, None, None,
     "a frame belonging to whichever function ran the assignment"),
    # The DIRECT spelling of the first row, in a FREE FUNCTION rather than a
    # method, so the local holder is a local bound to a construction rather than
    # a receiver.  It is the control that says the first row is answered by the
    # nested-frame machinery and not by anything about a method: without this
    # case, a fix that answered `t.v` in a method and left `b.inner.v` in a free
    # function alone would look like the same fix.
    ("a_nested_frame_field_read_through_a_local_holder_answers_directly",
     "struct Opt:\n"
     "    var v: Int\n"
     "    var has: Int\n"
     "\n"
     "struct Box:\n"
     "    var pad: Int\n"
     "    var inner: Opt\n"
     "\n"
     "def mk(n: Int) -> Opt:\n"
     "    var o = Opt()\n"
     "    o.v = n\n"
     "    o.has = 1\n"
     "    return o\n"
     "\n"
     "def main() -> int:\n"
     "    var b = Box()\n"
     "    b.inner = mk(4)\n"
     '    printf("g=%d", b.inner.v * 10 + b.inner.has)\n'
     "    return 0\n",
     "class Opt:\n"
     "    def __init__(self):\n"
     "        self.v = 0\n"
     "        self.has = 0\n"
     "class Box:\n"
     "    def __init__(self):\n"
     "        self.pad = 0\n"
     "        self.inner = None\n"
     "def mk(n):\n"
     "    o = Opt()\n"
     "    o.v = n\n"
     "    o.has = 1\n"
     "    return o\n"
     "import sys\n"
     "b = Box()\n"
     "b.inner = mk(4)\n"
     'sys.stdout.write("g=%d" % (b.inner.v * 10 + b.inner.has))\n',
     0, "g=41", None),
    # ── AND THE THREE ROWS THIS BLOCK GREW ──────────────────────────────────
    #
    # `work/merge-formal27a-r2` added six rows here for the same arm, three of
    # which are the SAME PROGRAM as the first, second and fourth rows above
    # under other names — `local_copy_of_a_nested_frame_field_reads_through_the_
    # name`, `the_same_slot_read_through_the_field_in_the_caller` and
    # `a_delegating_field_copied_to_a_local_still_reads_through_the_name`. One
    # row per program is the whole point of a case list, so those three are not
    # duplicated here and their role is stated where the rows live: the first is
    # the COPY spelling whose refusal the row above records, the second is the
    # control that says the answer comes from the nested-frame machinery and not
    # from anything about a method, and the third is the DELEGATING exemption.
    # The other three are programs of their own and are kept.
    #
    # Two copies deep, and the second one reads a field of the frame the first
    # copy addresses — the shape that needs the seeding to settle `m` before it
    # can ask about `m.deep`.
    ("a_chain_of_two_local_copies_of_nested_frames",
     "struct Inner:\n"
     "    var a: Int\n"
     "    var b: Int\n"
     "\n"
     "struct Mid:\n"
     "    var pad: Int\n"
     "    var deep: Inner\n"
     "\n"
     "struct Outer:\n"
     "    var pad: Int\n"
     "    var mid: Mid\n"
     "\n"
     "    def get(out self) -> Int:\n"
     "        var m = self.mid\n"
     "        var i = m.deep\n"
     "        return i.a * 10 + i.b\n"
     "\n"
     "def main() -> int:\n"
     "    var o = Outer()\n"
     "    o.mid.deep.a = 4\n"
     "    o.mid.deep.b = 1\n"
     "    printf(\"g=%d\", o.get())\n"
     "    return 0\n",
     "class Inner:\n"
     "    def __init__(self):\n"
     "        self.a = 0\n"
     "        self.b = 0\n"
     "class Mid:\n"
     "    def __init__(self):\n"
     "        self.pad = 0\n"
     "        self.deep = Inner()\n"
     "class Outer:\n"
     "    def __init__(self):\n"
     "        self.pad = 0\n"
     "        self.mid = Mid()\n"
     "    def get(self):\n"
     "        m = self.mid\n"
     "        i = m.deep\n"
     "        return i.a * 10 + i.b\n"
     "import sys\n"
     "o = Outer()\n"
     "o.mid.deep.a = 4\n"
     "o.mid.deep.b = 1\n"
     "sys.stdout.write(\"g=%d\" % o.get())\n",
     0, "g=41", None),
    # ── THE TWO REFUSALS, and they are refusals for OPPOSITE reasons ────────
    #
    # The copy of a field a METHOD assigns: the word in the slot IS an address
    # and the frame behind it belongs to whichever function ran that assignment,
    # so there is nothing to place.  The needle is the lifetime clause and not
    # the emitter's "this path has no way to say what 't' holds" — that one is
    # true and names a type inference rather than the question that is actually
    # there, and the two spellings of this refusal (the chain, and the copy) now
    # raise ONE text, which is what makes this needle the right thing to assert.
    ("a_local_copy_of_a_field_a_method_reassigns_names_the_lifetime",
     "struct Opt:\n"
     "    var v: Int\n"
     "    var has: Int\n"
     "\n"
     "struct Box:\n"
     "    var pad: Int\n"
     "    var inner: Opt\n"
     "\n"
     "    def set(out self, o: Opt):\n"
     "        self.inner = o\n"
     "\n"
     "    def get(out self) -> Int:\n"
     "        var t = self.inner\n"
     "        return t.v * 10 + t.has\n"
     "\n"
     "def mk(n: Int) -> Opt:\n"
     "    var o = Opt()\n"
     "    o.v = n\n"
     "    o.has = 1\n"
     "    return o\n"
     "\n"
     "def main() -> int:\n"
     "    var b = Box()\n"
     "    b.set(mk(4))\n"
     "    printf(\"g=%d\", b.get())\n"
     "    return 0\n",
     None, None, None,
     "a frame belonging to whichever function ran the assignment"),
    # …and the name the loop also binds.  `t` is bound twice — once to the
    # slot's address and once by the loop — so after the loop it holds the
    # LOOP's word and not the address, and a seeding that classified it from the
    # first binding builds an image that reads `[7 + 8·slot]`.  Measured on both
    # backends as a SIGSEGV, which is `FORMAL_one_field_holder_of_a_frame_is_not
    # _a_holder` wearing a different name; the needle is the REBIND sentence
    # because THAT is what this program must still get, and a build is the
    # failure this case exists to catch.
    #
    # The needle moved on the merged tree, and the move is what the merge is for.
    # `formal/build.py`'s `_nested_frame_bindings` (new on
    # `work/merge-formal27a-r2`) does not claim a name whose bindings are MIXED,
    # so this row is not `reassigned` and never reaches the lifetime refusal; it
    # reaches `formal/model.py`'s rebind refusal instead, whose own subject is
    # exactly this program — "`t` also holds the address of an `Opt` frame … and
    # this path has no way to say that a later binding changes what the name is"
    # — and which then names the three assignments that would be sound, none of
    # which a `for` target is.  The old needle was the emitter's "this path has
    # no way to say what 't' holds", which the merged tree still spells only in a
    # `formal/build.py` COMMENT saying it names a type inference rather than the
    # question that is actually there.
    ("a_loop_target_shadowing_a_local_copy_is_still_not_a_holder",
     "struct Opt:\n"
     "    var v: Int\n"
     "    var has: Int\n"
     "\n"
     "struct Box:\n"
     "    var pad: Int\n"
     "    var inner: Opt\n"
     "\n"
     "    def get(out self) -> Int:\n"
     "        var t = self.inner\n"
     "        for t in [7]:\n"
     "            t = t + 1\n"
     "        return t.v * 10 + t.has\n"
     "\n"
     "def main() -> int:\n"
     "    var b = Box()\n"
     "    b.inner.v = 4\n"
     "    b.inner.has = 1\n"
     "    printf(\"g=%d\", b.get())\n"
     "    return 0\n",
     None, None, None,
     "this path has no way to say that a later binding changes what the "
     "name is"),
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