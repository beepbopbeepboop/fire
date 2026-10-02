#!/usr/bin/env python3
"""`self.m[T](args)` must not put `m` in the struct's FIELD SET.

`formal/model.py`'s `_self_field_names` derives a struct's instance fields from
every place a field can be introduced, and one of those places is "any name a
method of this struct reaches through its receiver".  It has always exempted the
method CALL — `self.helper()` contributes nothing — because counting it would
add a field to every class that calls one of its own methods.

It exempted only the spelling whose callee is a `MemberExpr`.  A generic's
comptime parameters are written as brackets ON the callee, so `self.helper[T](x)`
has a `SubscriptExpr` callee, the guard did not match, the walk fell through to
the generic arm, found `MemberExpr(self, helper)`, and added `helper` to the
field set.  The name is a METHOD, so nothing ever writes the slot it now
occupies, and every read of that slot is zero.

**MEASURED, on the stdlib's most-used type.**  `Optional` has exactly one
instance field, `_value`:

    self._write_to[is_repr=False](writer)          # optional.mojo, write_to
    ->  struct_field_names(Optional) == ['_value', '_write_to']
    ->  struct_field_count 2, so struct_is_framed() is True

`Optional` is a ONE-word value whose receiver IS its field
(`struct_is_one_field`), and this made it a two-field struct instead, so every
`Optional` receiver became a FRAME ADDRESS.  That is the refusal
`bugs/FORMAL_builtin_slice_optional_field_is_a_frame_holder.md` records as
blocking the 13-file `builtin_slice.mojo` row: `Slice.start` is declared
`Optional[Int]`, the backend believed that to be a frame, and it refused to let
the ctor store one in a field.

This is one half of a pair of defects in this derivation.  The other half — a
bare `self.helper` in VALUE position — IS ambiguous (an instance attribute
shadows a class method in Python), so it was settled by Python's own rule rather
than by the exemption below: `model.struct_receiver_reads` DEMOTES a name the
struct declares as a method and never stores into, and
`a_method_name_the_struct_stores_into_is_still_a_field` is the other half of
THAT (the store keeps it a field).  What the exemption below handles is the
shape where the name is unambiguously a CALL, which it already said about and
simply could not see.

CENSUS, measured by parsing all 644 structs in this repository and under
`../new-modular/Mojo/stdlib/std` and asking which ones have a method name in
`struct_field_names`:

    before:  33 structs in 29 files
    after:    3 structs in  3 files      (all three the value-position shape)
    field sets that changed: 31, ALL NARROWER, none wider

Every one of the 30 is a real instance field set that had a method's name mixed
into it: `Optional`, `List`, `Dict`, `Set`, `Array`, `Deque`, `Span`, `Tuple`,
`Counter`, `LinkedList`, `Pointer`, `Variant`, `StringSpan`, `_DLHandle`,
`OwnedDLHandle`, `UnsafeUnion`, `SIMD`, `Logger`, `BitSet`, `Coroutine`,
`VariadicPack` and six more.  Not one of them lost a field that anything writes.

WHAT DID NOT MOVE, stated because it is the honest accounting of this file's
value.  `builtin_slice.mojo` still does not build: with the frame-holder refusal
gone the next refusal is `self.step.or_else()`, an OPTIONAL UNWRAP that needs a
representation for `Optional` — a value-model change shared by both backends and
the Lean proof (`formal/model.py`'s `UNWRAP_METHODS`), not a lowering of this
call.  Measured by disabling the frame-holder branch and re-running: the row's
refusal text moves from "a Optional receiver is stored in the field 'self.start'"
to that unwrap.  So this change fixes the DERIVATION, which is what the 13-file
row is blocked on and what 30 other struct layouts were getting wrong, and the
row itself needs the representation change to finish.  Filed as
`bugs/FORMAL_stdlib_optional_needs_a_representation.md`.

Every differential case is written twice, once as Mojo and once as plain Python,
and the two are made to AGREE rather than the expectation being hand-written —
`test_formal_frame_len.py`'s discipline, for the same reason: a hand-written
expected value is a second implementation of the question.

    python3 test_formal_bracketed_method_field_set.py [-v] [case ...]
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
# The architecture whose DIFFERENTIAL cases below are run on.  It is a single
# name because the cases are the ones x86-64 REFUSED rather than answering
# wrongly, and that set was the finding when it was measured.
#
# `work/formal2-x86-parity` (`63c85e37`) then ported the ABI — the caller now
# passes the comptime arguments its callee prologue reserves a register for — so
# the x86-64 answer is no longer a refusal and
# `X86_ABI_PARITY` below is where both machines are run and their stdout
# compared. The differential cases here are NOT re-pointed at x86-64 on the
# strength of that one construct: each is a separate program and has to be run
# before it can be claimed, which is what `test_formal_x86_64_parity.py` is for.
# The measurement is in bugs/FORMAL_x86_64_comptime_specialization_abi.md.
COMPTIME_ABI = "arm64"

# ── the differential cases ──────────────────────────────────────────────────
#
# (name, mojo_source, python_source)
DIFF_CASES = [
    # THE TERMINAL CONSTRUCT, in miniature, and the case the whole file is
    # about.  `Cell` has ONE field, so it fits one word and its receiver IS that
    # field — exactly `Optional`'s shape, and exactly the shape this change
    # recovers.  `bump[7]` writes `self._value`, and `total` reads it back; the
    # bracket argument is given a distinct weight so a case that read a
    # never-written slot would print a DIFFERENT NUMBER rather than crash.
    ("bracketed_method_call_does_not_invent_a_field",
     "struct Cell:\n"
     "    var _value: Int\n"
     "    def bump[T: Int](out self, k: Int) -> Int:\n"
     "        self._value = self._value + T + k\n"
     "        return self._value\n"
     "\n"
     "def main() -> Int:\n"
     "    var c = Cell()\n"
     "    c._value = 5\n"
     '    printf("v=%d", c.bump[7](3))\n'
     "    return 0\n",
     "class Cell:\n"
     "    def __init__(self):\n"
     "        self._value = 5\n\n"
     "    def bump(self, t, k):\n"
     "        self._value = self._value + t + k\n"
     "        return self._value\n"
     "\n"
     "def main():\n"
     "    c = Cell()\n"
     '    print("v=%d" % c.bump(7, 3), end="")\n'
     "    return 0\n"
     "\n"
     "main()\n"),

    # THE SAME CALL on a TWO-field struct, where the receiver IS a frame
    # address.  The field-set defect is not about the receiver's width — the
    # method name was invented as a slot either way — so this case exists to say
    # the fix is not "one-field structs stop being wide" but "a call is not a
    # field", and it pins that `Pair` keeps BOTH of its real fields while
    # `mark` gets no slot.
    ("bracketed_method_call_on_a_two_field_struct_keeps_both_fields",
     "struct Pair:\n"
     "    var a: Int\n"
     "    var b: Int\n"
     "    def mark[T: Int](self, k: Int) -> Int:\n"
     "        return self.a * 1000 + self.b * 10 + k + T\n"
     "\n"
     "def main() -> Int:\n"
     "    var p = Pair()\n"
     "    p.a = 4\n"
     "    p.b = 5\n"
     '    printf("v=%d", p.mark[6](7))\n'
     "    return 0\n",
     "class Pair:\n"
     "    def __init__(self):\n"
     "        self.a = 4\n"
     "        self.b = 5\n\n"
     "    def mark(self, k):\n"
     "        return self.a * 1000 + self.b * 10 + k + 6\n"
     "\n"
     "def main():\n"
     "    p = Pair()\n"
     '    print("v=%d" % p.mark(7), end="")\n'
     "    return 0\n"
     "\n"
     "main()\n"),

    # TWO METHODS, ONE OF THEM REACHED ONLY THROUGH BRACKETS, and the plain one
    # reading the same field the bracketed one reads — the shape
    # `optional.mojo`'s `write_to`/`write_repr_to` pair has, where `_write_to`
    # is reached through brackets from two places and `_value` plainly.  If the
    # two spellings disagreed about what a method call is, the struct would get a
    # slot for one spelling and not the other, and the two would disagree about
    # where the field lives.
    #
    # Brackets are POSITIONAL here, and deliberately: the keyword spelling
    # `self._bump[by=4]()` is the stdlib's and it is exactly the shape
    # `KNOWN_GAPS` below records as measuring wrong for a reason this change
    # does not own (`attrs` is never read by
    # `mojo/middle/comptime.py`'s `specialization_args`).  Using it here would
    # have made this case fail for that reason and stop it testing the field set
    # at all.
    ("both_spellings_of_one_method_agree_on_the_field_set",
     "struct Cell:\n"
     "    var value: Int\n"
     "    var pad: Int\n"
     "    def _bump[T: Int](self) -> Int:\n"
     "        return self.value + T\n"
     "    def write(self) -> Int:\n"
     "        return self._bump[4]()\n"
     "    def write_repr(self) -> Int:\n"
     "        return self.value * 100 + self._bump[10]() + self.write()\n"
     "\n"
     "def main() -> Int:\n"
     "    var c = Cell()\n"
     "    c.value = 5\n"
     "    c.pad = 0\n"
     '    printf("v=%d", c.write_repr())\n'
     "    return 0\n",
     "class Cell:\n"
     "    def __init__(self, value, pad):\n"
     "        self.value = value\n"
     "        self.pad = pad\n\n"
     "    def _bump(self, t):\n"
     "        return self.value + t\n\n"
     "    def write(self):\n"
     "        return self._bump(4)\n\n"
     "    def write_repr(self):\n"
     "        return self.value * 100 + self._bump(10) + self.write()\n"
     "\n"
     "def main():\n"
     "    c = Cell(5, 0)\n"
     '    print("v=%d" % c.write_repr(), end="")\n'
     "    return 0\n"
     "\n"
     "main()\n"),

    # A BRACKETED CALL ON A FIELD OF ANOTHER STRUCT, so the receiver is a field
    # slot rather than a bare local — the shape `std/ffi/__init__.mojo` has
    # (`self._handle.get_symbol[NoneType](...)`) and the one that made
    # `_DLHandle` measure three fields where it declares one.  `Holder` is two
    # fields, so its receiver is a frame and `h.cell` is a real slot in it.
    #
    # Read from a field of a TWO-field holder and handed to a plain function, so
    # the slot it is read out of is in a frame this function owns.  Storing the
    # frame in a longer-lived field instead is refused by
    # `refuse_a_frame_address_stored_in_a_field` below.
    ("bracketed_method_call_on_a_field_of_another_struct",
     "struct Cell:\n"
     "    var value: Int\n"
     "    var pad: Int\n"
     "    def bump[T: Int](self) -> Int:\n"
     "        return self.value + T\n"
     "\n"
     "def go(c: Cell, k: Int) -> Int:\n"
     "    return c.bump[k]()\n"
     "\n"
     "def main() -> Int:\n"
     "    var c = Cell()\n"
     "    c.value = 5\n"
     "    c.pad = 0\n"
     '    printf("v=%d", go(c, 7) * 10 + c.pad)\n'
     "    return 0\n",
     "class Cell:\n"
     "    def __init__(self, value, pad):\n"
     "        self.value = value\n"
     "        self.pad = pad\n\n"
     "    def bump(self, t):\n"
     "        return self.value + t\n\n"
     "def go(c, k):\n"
     "    return c.bump(k)\n"
     "\n"
     "def main():\n"
     "    c = Cell(5, 0)\n"
     '    print("v=%d" % (go(c, 7) * 10 + c.pad), end="")\n'
     "    return 0\n"
     "\n"
     "main()\n"),
]

# ── the KNOWN GAPS: real programs this backend gets WRONG today, recorded here
#    so the file is honest about what it does and does not establish.  Each
#    names the bug doc that owns the fix.
#
# (name, mojo_source, python_source, why)
KNOWN_GAPS = [
    # THE STDLIB'S OWN SPELLING of a defaulted comptime parameter, and the reason
    # `optional.mojo`'s `_write_to[*, is_repr: Bool]` is in the census this file
    # changed.  The image answers `403` where CPython says `423`, which is
    # `scale = 0` — the keyword bracket is not read, so it is padded with the
    # "unknown compile-time value" zero.  Pre-existing and not this construct:
    # `mojo/middle/comptime.py`'s `specialization_args` reads `func.index` and
    # never `func.attrs`, and it is shared with the gimple and x86-64 paths.
    # bugs/FORMAL_keyword_comptime_parameter_is_silently_dropped.md
    ("KNOWN_GAP_keyword_comptime_parameter_is_dropped",
     "struct Cell:\n"
     "    var value: Int\n"
     "    var pad: Int\n"
     "    def show[*, scale: Int](self, n: Int) -> Int:\n"
     "        return self.value * 100 + scale * 10 + n\n"
     "\n"
     "def main() -> Int:\n"
     "    var c = Cell()\n"
     "    c.value = 4\n"
     "    c.pad = 1\n"
     '    printf("v=%d", c.show[scale=2](3))\n'
     "    return 0\n",
     "class Cell:\n"
     "    def __init__(self, value, pad):\n"
     "        self.value = value\n"
     "        self.pad = pad\n\n"
     "    def show(self, scale, n):\n"
     "        return self.value * 100 + scale * 10 + n\n"
     "\n"
     "def main():\n"
     "    c = Cell(4, 1)\n"
     '    print("v=%d" % c.show(2, 3), end="")\n'
     "    return 0\n"
     "\n"
     "main()\n",
     "the keyword comptime parameter is bound to 0"),
]


# ── the field-set cases (no image; the derivation itself) ───────────────────
#
# (name, mojo_source, expected_field_names)
#
# These assert the DERIVED field set directly, through `model.struct_field_names`
# on the parsed source, because the wrong answer this file exists to prevent is
# invisible in a program's OUTPUT on a program that happens not to read the
# phantom slot — it is a layout, and the test has to look at the layout.
FIELDSET_CASES = [
    ("a_bracketed_method_call_contributes_no_field",
     "struct Cell:\n"
     "    var _value: Int\n"
     "    def bump[T: Int](out self, k: Int) -> Int:\n"
     "        return self._value + T + k\n"
     "    def go(self) -> Int:\n"
     "        return self.bump[1](2)\n",
     ["_value"]),

    # THE STDlib SHAPE, exactly: a public plain method delegating to a private
    # bracketed one.  Before the change this was `['_value', '_write_to']` and a
    # one-word struct measured as two.
    ("the_write_to_delegation_shape_measures_one_field",
     "struct Optional:\n"
     "    var _value: Int\n"
     "    def _write_to[*, is_repr: Bool](self, w: Int):\n"
     "        w = self._value\n"
     "    def write_to(self, w: Int):\n"
     "        self._write_to[is_repr=False](w)\n"
     "    def write_repr_to(self, w: Int):\n"
     "        self._write_to[is_repr=True](w)\n",
     ["_value"]),

    # A subscript READ on a field, which is the other half of the exemption and
    # the case that says it is on the callee position only.
    ("a_subscript_on_a_field_keeps_the_field",
     "struct Cell:\n"
     "    var at: Int\n"
     "    def peek(self, i: Int) -> Int:\n"
     "        return self.at[i]\n",
     ["at"]),

    # A field written ONLY through a bracketed call's arguments — the bracket
    # position is walked, so this name is found.  The complement of the first
    # case: exempting the callee must not exempt the brackets.
    ("a_field_named_in_the_brackets_is_still_a_field",
     "struct Cell:\n"
     "    var index: Int\n"
     "    def bump[T: Int](out self, k: Int) -> Int:\n"
     "        return T + k + self.index\n"
     "    def go(self) -> Int:\n"
     "        return self.bump[self.index](2)\n",
     ["index"]),

    # A plain method call, which the exemption already made and which must stay
    # made: the two spellings cannot be allowed to drift apart.
    ("a_plain_method_call_contributes_no_field",
     "struct Cell:\n"
     "    var _value: Int\n"
     "    def bump(self, k: Int) -> Int:\n"
     "        return self._value + k\n"
     "    def go(self) -> Int:\n"
     "        return self.bump(2)\n",
     ["_value"]),

    # A VALUE-POSITION method reference, `self.helper` in a place that is not a
    # call.  This is the OTHER defect of the pair named in this file's
    # docstring, and it is a wrong answer: counting it invented a slot that
    # nothing ever writes, so the read answered ZERO — a number the source never
    # wrote, from a program that built, ran and exited.
    #
    # `model.struct_receiver_reads` DEMOTES it, so the derived set is `_value`
    # alone and the read is refused by name instead
    # (`refuse_a_value_position_method_reference_is_still_refused`, below).
    # Before that demotion this row EXPECTED `["_value", "helper"]`, and it was
    # asserting the bug.
    ("a_value_position_method_reference_is_not_a_field",
     "struct Cell:\n"
     "    var _value: Int\n"
     "    def helper(self) -> Int:\n"
     "        return 1\n"
     "    def go(self) -> Int:\n"
     "        var m = self.helper\n"
     "        return self._value\n",
     ["_value"]),

    # …and the other half of Python's rule, which is what makes the demotion
    # above safe rather than merely conservative: an instance attribute
    # SHADOWS the class's method, so a name the struct both declares as a
    # method and STORES into IS a field and stays one.  Without this row a fix
    # that demoted every method NAME would be a fix that deletes real storage,
    # and it would build — a struct with one fewer field than the source says is
    # a silent wrong answer, not a refusal.
    #
    # The store is in a DIFFERENT method from the read on purpose:
    # `struct_receiver_stores` is asked over the whole struct precisely because
    # `__init__` writes `self.helper` and `size` reads it back, so the read's own
    # method carries no evidence either way.  A demotion that asked only the
    # reading method would get this row wrong.
    ("a_method_name_the_struct_stores_into_is_still_a_field",
     "struct Cell:\n"
     "    var _value: Int\n"
     "    def helper(self) -> Int:\n"
     "        return 1\n"
     "    def __init__(self):\n"
     "        self.helper = 7\n"
     "    def go(self) -> Int:\n"
     "        return self.helper\n",
     ["_value", "helper"]),

    # DEFECT A, the keyword argument, which was the other half of that doc and
    # the direction this rule exists to get right: `CallExpr.kwargs` is
    # `list[tuple[str, Expr]]`, and the walk read `list` alone, so each `x` was a
    # tuple, a tuple has no `__dataclass_fields__`, and the whole expression was
    # invisible.  So `self._untyped_callee` — the exact spelling
    # `formal/arm64_codegen.py` uses — contributed nothing to ARM64Codegen's
    # field set.
    #
    # A field MISSED is two real fields aliased into one slot, which is the one
    # error the derivation's own docstring names.  `c` is the control: the same
    # name in an ordinary argument position, which the walk always reached, so
    # the pair says the gap was the keyword SPELLING and not the name.
    ("a_field_carried_by_a_keyword_argument_is_a_field",
     "struct Cell:\n"
     "    var a: Int\n"
     "    var b: Int\n"
     "    def check(self, op):\n"
     "        return string_binary_refusal(op, self._untyped_callee, self.c)\n",
     ["a", "b", "_untyped_callee", "c"]),

    # The CONTROL for the row above, and it is what makes that row mean
    # something: the same three names with no keyword argument at all.  If the
    # kwarg row were passing because the walk had simply stopped seeing method
    # bodies, this would fail.
    ("a_field_in_an_ordinary_argument_position_is_a_field",
     "struct Cell:\n"
     "    var a: Int\n"
     "    var b: Int\n"
     "    def check(self, op):\n"
     "        return string_binary_refusal(self._untyped_callee, self.c)\n",
     ["a", "b", "_untyped_callee", "c"]),
]

# ── the refusals that must SURVIVE ──────────────────────────────────────────
#
# (name, mojo_source, needle)
REFUSALS = [
    # The bracketed call is now recognised as a CALL, which leaves the
    # value-position reference as the shape that has no representation — and it
    # must still be REFUSED rather than lowered to a load of a slot nothing ever
    # writes.  Both halves of that defect's fix are in: `model.struct_receiver_reads`
    # DEMOTES the name out of the derived field set (see
    # `a_value_position_method_reference_is_not_a_field`), so there is no slot
    # left to load, and `build.check_value_position_method_reads` names the
    # method.  This row is the REFUSAL half of that pair, and it is the one that
    # has to hold: the demotion alone would let the read reach an emitter with no
    # slot to read, and the refusal alone would leave a load of one.
    #
    # The shape is `self.helper` as a KEYWORD ARGUMENT's value rather than a
    # `return` of it, because that is the spelling the sweep reported
    # (`checker.check_temporal_monotionality`, `job.excl`) and the one
    # `test_formal_run.py`'s `method_reference_is_not_a_frame_slot` pins.  It is
    # deliberately the kwarg SPELLING, which is defect A's position — the two
    # defects are in one construct and this row is where they meet.
    ("refuse_a_value_position_method_reference_is_still_refused",
     "class Cell:\n"
     "    __slots__ = ('value', 'pad')\n"
     "\n"
     "    def __init__(self):\n"
     "        self.value = 5\n"
     "        self.pad = 0\n"
     "\n"
     "    def helper(self):\n"
     "        return 1\n"
     "\n"
     "    def size(self, probe):\n"
     "        return probe(value=self.helper)\n"
     "\n"
     "def take(value):\n"
     "    return value()\n"
     "\n"
     "def main():\n"
     "    c = Cell()\n"
     "    return c.size(take)\n",
     "which is a METHOD of Cell rather than one of its fields"),

    # A field-of-a-field METHOD CALL on a framed struct, which is where
    # `bracketed_method_call_on_a_field_of_another_struct` above lands.  Pinned
    # so the landing place is a refusal with a TRUE reason: `h.cell` holds a
    # frame address whose frame belongs to whichever function made it, and the
    # two lifetimes are independent.  Measured identical before and after this
    # branch's change — the change moved the message in neither direction.
    ("refuse_a_frame_address_stored_in_a_field",
     "struct Cell:\n"
     "    var value: Int\n"
     "    var pad: Int\n"
     "    def bump[T: Int](self) -> Int:\n"
     "        return self.value + T\n"
     "\n"
     "struct Holder:\n"
     "    var cell: Cell\n"
     "    var pad: Int\n"
     "\n"
     "def go(h: Holder) -> Int:\n"
     "    return h.cell.bump[7]()\n"
     "\n"
     "def main() -> Int:\n"
     "    var c = Cell()\n"
     "    c.value = 5\n"
     "    c.pad = 0\n"
     "    var h = Holder()\n"
     "    h.cell = c\n"
     "    h.pad = 3\n"
     '    printf("v=%d", go(h) * 10 + h.pad)\n'
     "    return 0\n",
     "outlives the frame it names"),
]

# ── x86-64's comptime ABI, pinned ───────────────────────────────────────────
#
# (name, mojo_source, expected_stdout)
#
# BOTH machines build this and both PRINT THE SAME THING, and that is the
# assertion.  It used to be "arm64 builds and x86-64 REFUSE", because x86-64
# knew the callee's NAME (a bracket is rewritten to `bump`) without the ABI that
# goes with it — the callee's prologue reserves a register per comptime
# parameter (`formal/model.py`'s `incoming_args` is shared) and the call site did
# not pass one.  That is the state `work/formal2-x86-parity` ported
# (`63c85e37`, "the comptime-specialization ABI, which took three halves"), so
# this is now a PARITY case and the old refusal is what parity removes.
#
# The refusal was load-bearing while it stood, and the reason it was worth
# pinning is the reason this is worth pinning now: a backend that knows the name
# and not the ABI produces an image that BUILDS, LINKS and computes something
# else, and the only thing that distinguishes the two is running both and
# comparing.  So the comparison is stdout, not an exit status — the answer is
# small here, and a `printf` channel is the one that also works for the cases in
# `test_formal_x86_64_parity.py` whose answers are not.
X86_ABI_PARITY = [
    ("x86_abi_a_bracketed_specialized_method_call_builds_and_agrees",
     "struct Cell:\n"
     "    var value: Int\n"
     "    var pad: Int\n"
     "    def bump[T: Int](self) -> Int:\n"
     "        return self.value + T\n"
     "\n"
     "def main() -> Int:\n"
     "    var c = Cell()\n"
     "    c.value = 5\n"
     "    c.pad = 0\n"
     '    printf("v=%d", c.bump[7]())\n'
     "    return 0\n",
     "v=12"),
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
    the answer the case is about is a bug in the CASE.
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


def run_fieldset_case(case, tmpdir, verbose):
    """The DERIVED field set, read through `model.struct_field_names`.

    Asserted on the derivation rather than on an image because the wrong answer
    this file prevents is a LAYOUT: a program that happens not to read the
    phantom slot prints the right thing either way, and the phantom is only
    visible to the next struct that does read it.
    """
    import fire_compiler as F
    import formal.model as M

    name, source, want = case
    src = os.path.join(tmpdir, name + ".mojo")
    with open(src, "w") as f:
        f.write(source)
    stmts = (F.Parser(F.py_tokenize_named(source, src))
             .with_filename(src).parse_module())
    structs = [s for s in stmts if isinstance(s, F.StructDef)]
    if len(structs) != 1:
        return False, f"the case declares {len(structs)} structs, expected 1"
    got = M.struct_field_names(structs[0])
    if got != want:
        meth = sorted({m.name for m in M.struct_methods(structs[0])})
        phantom = sorted(set(got) & set(meth))
        return False, (f"struct_field_names == {got}, expected {want}"
                       + (f"; {phantom} is a METHOD of this struct, so it is a "
                          f"call and not a field" if phantom else ""))
    if verbose:
        print(f"      field set {got}")
    return True, ""


def run_refusal_case(case, tmpdir, verbose):
    """BOTH backends must refuse, and both must refuse with the needle.

    Both architectures, because a refusal raised by the shared build pass has to
    be the same refusal on both.
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


def run_known_gap_case(case, tmpdir, verbose):
    """The gap must STILL BE THERE, and it must still be the documented one.

    The anti-rot direction, and the reason this is not just a list of programs
    known to be wrong.  A gap that gets FIXED is a bug quietly reintroduced by
    whoever reads this file next and "cleans up" the case, so a gap case passes
    only while the image DISAGREES with CPython, and reports a FAILURE the moment
    the two agree — which is the signal to delete the case and delete its bug
    doc in the same commit, exactly as `test_formal.py`'s `EXPECTED_FAILURES`
    treats a stale entry.

    The disagreement is required to be the DOCUMENTED one and not merely any
    difference: a program that went wrong in a new way would still "differ", and
    a gap list that accepts any difference is not pinning anything.
    """
    name, source, oracle, why = case
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
        return False, (f"--backend={COMPTIME_ABI} REFUSED it; the gap recorded "
                       f"here is a WRONG ANSWER ({why}), not a refusal, so the "
                       f"case and its bug doc are stale: {text.strip()[-300:]}")
    if not os.path.isfile(out):
        return False, f"--backend={COMPTIME_ABI} built but wrote no binary"
    run = subprocess.run([out], capture_output=True, text=True,
                         timeout=RUN_TIMEOUT)
    if run.stdout == want.stdout:
        return False, (f"--backend={COMPTIME_ABI} now AGREES with CPython "
                       f"({run.stdout!r}): the gap is FIXED — delete this case "
                       f"and its bug doc in the same commit")
    if verbose:
        print(f"      --backend={COMPTIME_ABI} stdout={run.stdout!r}, CPython "
              f"{want.stdout!r}  (KNOWN-GAP: {why})")
    return True, ""


def run_x86_abi_case(case, tmpdir, verbose):
    """BOTH machines build it and both print the same thing.

    Three assertions and the third is the one that would catch a regression:
    that each backend BUILDS is a build result, and two build results can agree
    while the images disagree. `stdout` is compared, and it is the channel rather
    than the exit status because the answers in this file are read, not counted.
    """
    name, source, want = case
    src = os.path.join(tmpdir, name + ".mojo")
    with open(src, "w") as f:
        f.write(source)
    for backend in ("arm64", "x86_64"):
        out = os.path.join(tmpdir, f"{name}.{backend}")
        rc, text = build_formal(src, out, backend)
        if rc != 0:
            return False, (f"--backend={backend} did not build the "
                           f"specialization: {text.strip()[-300:]}")
        if not os.path.isfile(out):
            return False, f"--backend={backend} built but wrote no binary"
        run = subprocess.run([out], capture_output=True, text=True,
                             timeout=RUN_TIMEOUT)
        if run.stdout != want:
            return False, (f"--backend={backend} printed {run.stdout!r}, "
                           f"the case is about {want!r}")
        if verbose:
            print(f"      {backend}: {run.stdout!r}")
    return True, ""


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[1])
    ap.add_argument("-v", "--verbose", action="store_true")
    ap.add_argument("cases", nargs="*", help="case name substring filter")
    args = ap.parse_args(argv)

    def wanted(name):
        return not args.cases or any(c in name for c in args.cases)

    runners = (("differential", DIFF_CASES, run_diff_case),
               ("field set", FIELDSET_CASES, run_fieldset_case),
               ("refusal", REFUSALS, run_refusal_case),
               ("x86-64 ABI", X86_ABI_PARITY, run_x86_abi_case),
               ("known gap", KNOWN_GAPS, run_known_gap_case))
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
    print(f"\nbracketed method field set: PASS={passed} FAIL={failed}")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())