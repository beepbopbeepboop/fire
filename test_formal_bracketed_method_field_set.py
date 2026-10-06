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
than by the exemption below: `model.struct_method_receiver_reads` DEMOTES a name the
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
# `X86_ABI_PARITY` below is the one construct here that IS claimed on both
# machines, because it was the one that was measured on both.
COMPTIME_ABI = "arm64"

# ── the differential cases ──────────────────────────────────────────────────
#
# (name, mojo_source, python_source)
DIFF_CASES = [
    # THE TERMINAL CONSTRUCT, in miniature, and the case the whole file is
    # about.  `Cell` has ONE field, so it fits one word and its receiver IS that
    # field — exactly `Optional`'s shape, and exactly the shape this change
    # recovers.  `bump[7]` writes `self._value`; the bracket argument is given a
    # distinct weight so a case that read a never-written slot would print a
    # DIFFERENT NUMBER rather than crash.
    #
    # `bump` MUTATES AND RETURNS NOTHING, and that is load-bearing rather than
    # incidental.  It used to `return self._value` and print the return value,
    # which is the shape `model.one_field_mutating_methods` refuses by name —
    # a one-field mutator hands its receiver back on every path, and one that
    # ALSO returns a value has no single answer ("both changes its receiver and
    # returns a value").  That rule landed after this row was written, so the
    # row stopped being about the field set and became about the mutator rule;
    # the program below is the same construct without the return, so it still
    # asks the question this file is named for, and the refused shape is pinned
    # separately as `refuse_a_one_field_mutator_that_also_returns_a_value` so
    # the interaction between the two features is a row rather than an accident.
    ("bracketed_method_call_does_not_invent_a_field",
     "struct Cell:\n"
     "    var _value: Int\n"
     "    def bump[T: Int](out self, k: Int):\n"
     "        self._value = self._value + T + k\n"
     "\n"
     "def main() -> Int:\n"
     "    var c = Cell()\n"
     "    c._value = 5\n"
     "    c.bump[7](3)\n"
     '    printf("v=%d", c._value)\n'
     "    return 0\n",
     "class Cell:\n"
     "    def __init__(self):\n"
     "        self._value = 5\n\n"
     "    def bump(self, t, k):\n"
     "        self._value = self._value + t + k\n"
     "\n"
     "def main():\n"
     "    c = Cell()\n"
     "    c.bump(7, 3)\n"
     '    print("v=%d" % c._value, end="")\n'
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
#
# EMPTY, and kept as a mechanism rather than deleted with its last entry: this is
# where a program this backend gets WRONG goes, so a reader who finds one has
# somewhere to put it, and `run_known_gap_case` is the anti-rot half — a gap
# case passes only while the image DISAGREES with CPython, and FAILS the moment
# the two agree, which is the signal to delete the case and its bug doc in the
# same commit.
#
# It held exactly one case until 2026-10-01, and that case is now a differential
# assertion in `test_formal_specialized_method_call.py`
# (`keyword_comptime_parameter_is_bound_by_name`, plus the two-keyword
# `keyword_comptime_parameters_bind_by_name_not_by_bracket_order` that says the
# binding is by NAME): a keyword comptime bracket parameter used to bind to 0 —
# `mojo/middle/comptime.py`'s `specialization_args` read `func.index` and never
# `func.attrs` — so `c.show[scale=2](3)` printed 403 where CPython printed 423.
# Its bug doc was deleted with that fix.
KNOWN_GAPS = []


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
    # `model.struct_method_receiver_reads` DEMOTES it, so the derived set is `_value`
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
    # writes.  Both halves of that defect's fix are in: `model.struct_method_receiver_reads`
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
    # The by-reference RECEIVER on the one shape the bracketing makes hardest,
    # and the row that replaces the refusal this file used to pin here.
    # `def bump[T: Int](out self, k: Int) -> Int` is a one-field mutator that
    # both changes its receiver and returns a value AND has a comptime
    # parameter, so its receiver is NOT argument 0: comptime parameters are
    # LEADING arguments (`model.incoming_args`), the cell address arrives in X1,
    # and X19 already holds the bracket's value.
    #
    # That last fact is what this row is for. The prologue reads the receiver
    # out of the cell into X19, which is right when the receiver IS argument 0
    # (X19 is argument 0's home, by the unconditional save) and wrong when it is
    # not — the callee then added the receiver's value where the bracket's went
    # and both machines printed `v=13` where the source says 15. So a row that
    # only had the non-generic shape would have shipped that.
    #
    # `v=15 15` is the whole convention in one line: the declared value came back
    # out of the specialization (the first number) AND the cell write-back
    # reached the caller (the second), on both machines.
    #
    # Two statements rather than one `printf`, and that is not style: reading the
    # receiver in the SAME argument list as the call that changes it is
    # `model.mutating_receiver_order_refusal`, because this path evaluates a
    # call's arguments before it makes the call. `test_formal_run.py`'s
    # `one_field_mutator_read_in_its_own_argument_list_is_refused` is that
    # program; this row is the same fact with the read moved out of the way.
    ("x86_abi_a_bracketed_one_field_mutator_that_also_returns_a_value",
     "struct Cell:\n"
     "    var _value: Int\n"
     "    def bump[T: Int](out self, k: Int) -> Int:\n"
     "        self._value = self._value + T + k\n"
     "        return self._value\n"
     "\n"
     "def main() -> Int:\n"
     "    var c = Cell()\n"
     "    c._value = 5\n"
     "    var got = c.bump[7](3)\n"
     '    printf("v=%d %d", got, c._value)\n'
     "    return 0\n",
     "v=15 15"),
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


# ── the CENSUS: one walk per struct, and the same answers it gave ───────────
#
# (name, mojo_source, expected_field_names)
#
# `model.struct_method_receiver_reads` exists because the per-method question
# behind every row above was answered by re-running the whole-struct store
# census once PER METHOD: `struct_receiver_reads(st, receivers, method)` called
# `struct_receiver_stores(st, receivers)`, and both of its callers ask it in a
# loop over `st`'s methods.  That is what put 361 of the 644 files in the
# 2026-10-02 sweep's `tool` class with no verdict at all — every one a timeout
# at `-t 30`, none a memory kill.
#
# So these rows assert THREE things, and the third is the one that would catch
# the next re-introduction:
#
#   1. the derived field set is what the rows above already pin;
#   2. each method's demoted set equals the formula the per-method question
#      used to compute, spelled out here independently of the implementation
#      (`_receiver_names` less `struct_demoted_method_names`) — the differential
#      direction, so a change that made the fast path answer something else
#      fails rather than passing by agreeing with itself;
#   3. deriving the whole field set asks `struct_receiver_stores` EXACTLY ONCE,
#      whatever the method count.  A row that only checked (1) and (2) would
#      pass on the quadratic version, which is the whole reason it existed.
#
# The sources are chosen for the shapes the rule turns on, not for size:
CENSUS_CASES = [
    # A DECLARED name that is also a method name.  This is the row that pins the
    # difference between the two questions the derivation asks: `size`'s read of
    # `self.helper` is a BOUND METHOD and is demoted out of `size`'s field set,
    # while the class body's own `var helper` is storage the language spells out,
    # so the name is in the struct's field list anyway.  Getting this wrong in
    # either direction is a layout change, and the undemoted union the
    # class-level clause uses is now derived from the same walk as the per-method
    # sets — so the pair is what says those two answers came from one walk.
    ("a_declared_name_that_is_also_a_method_stays_a_field",
     "struct C:\n"
     "    var helper: Int = 2\n"
     "    var other: Int = 3\n"
     "    def helper(self) -> Int:\n"
     "        return self.other\n"
     "    def size(self) -> Int:\n"
     "        return self.helper\n",
     ["helper", "other"]),

    # The store half of Python's shadowing rule, in a DIFFERENT method from the
    # read: `__init__` writes `self.helper`, so every method of this struct sees
    # `helper` as an instance attribute.  With three methods the old shape ran
    # the census three times here, and this is the row where a census that ran
    # once but read only the CALLING method's body would delete real storage.
    ("a_store_in_another_method_keeps_the_name_a_field",
     "struct Cell:\n"
     "    var _value: Int\n"
     "    def helper(self) -> Int:\n"
     "        return 1\n"
     "    def __init__(self):\n"
     "        self.helper = 7\n"
     "    def go(self) -> Int:\n"
     "        return self.helper\n",
     ["_value", "helper"]),

    # `this` rather than `self`, and the store inside a NESTED def.  Both are
    # about the CENSUS rather than about the walk: `struct_receivers` has to
    # name the receiver for a store to be seen at all, and the store census
    # (`iter_nodes`) descends into a nested `FunctionDef` while the read walk
    # (`_self_field_names`) deliberately does not — a nested `def`'s `self` is a
    # closure over the same object, so `this.v = …` there IS an instance store,
    # and a census that stopped descending would report `v` as never written.
    ("a_store_through_this_and_inside_a_nested_def_is_a_field",
     "struct D:\n"
     "    var v: Int\n"
     "    def bump(this):\n"
     "        def inner():\n"
     "            this.v = this.v + 1\n"
     "        inner()\n"
     "        return this.v\n",
     ["v"]),

    # The three assignment SPELLINGS the census recognises — a chain, an
    # augmented assign and a tuple target — because a store census that missed
    # one of them would demote a real field name on any struct that also
    # declares a method by that name.
    ("chained_augmented_and_tuple_stores_are_all_stores",
     "struct E:\n"
     "    var a: Int\n"
     "    var b: Int\n"
     "    def set_both(self):\n"
     "        self.a = self.b = 0\n"
     "        self.a += 1\n"
     "        self.a, self.b = self.b, self.a\n",
     ["a", "b"]),
]

# ── `_constant_read_sites`: only the sites the body can spell ───────────────
#
# (name, mojo_source, function_name, expected_site_keys)
#
# A site is keyed `"<base>.<name>"` and the only things that ever look one up are
# `_constant_read_spelling`, which builds the key from a `MemberExpr` over an
# `IdentExpr`, and `_apply_constant_sites`, which matches exactly that shape —
# both over the body being rewritten.  So a struct whose name the body never
# spells has no site anybody can reach, and `formal/build.py` used to ask every
# struct in the module for its class constants once per function anyway (400,000
# such questions on `gimple_codegen.py`, 87% of that build's time).
#
# The first row is the direction that MATTERS — every site the body can spell is
# still there, which is what a too-eager filter would lose — and the second is
# the direction that pays: the unread one is gone.  A filter that dropped both
# would pass the second and fail the first.
SITE_FILTER_CASES = [
    ("every_class_constant_the_body_spells_is_still_a_site",
     "struct A:\n"
     "    comptime K: Int = 3\n"
     "    var n: Int\n"
     "    def get(self) -> Int:\n"
     "        return self.n + A.K\n"
     "\n"
     "struct B:\n"
     "    comptime J: Int = 4\n"
     "    var m: Int\n"
     "    def get(self) -> Int:\n"
     "        return self.m + B.J\n"
     "\n"
     "def go(a) -> Int:\n"
     "    return A.K + B.J\n",
     "go", ["A.K", "B.J"]),

    ("a_struct_the_body_never_spells_contributes_no_site",
     "struct A:\n"
     "    comptime K: Int = 3\n"
     "    var n: Int\n"
     "    def get(self) -> Int:\n"
     "        return self.n + A.K\n"
     "\n"
     "struct B:\n"
     "    comptime J: Int = 4\n"
     "    var m: Int\n"
     "    def get(self) -> Int:\n"
     "        return self.m + B.J\n"
     "\n"
     "def go(a) -> Int:\n"
     "    return A.K\n",
     "go", ["A.K"]),
]

# ── a MODULE-level table asked from a per-FUNCTION pass, asked once ──────────
#
# `_prepare_functions`' per-function loop derives two tables that are properties
# of the MODULE and used to derive them itself, once per function:
#
#   * which structs are FRAMED (`formal/model.py`'s `struct_is_framed`, whose
#     field count walks every method body of the struct), read by
#     `_bound_receiver_structs` — 43 508 derivations on `myinterpreter.py`;
#   * which structs are ENUMS (`struct_is_enum`, whose inheritance fixed point
#     walks every struct in the module), read by `_enum_member_sites` — 876 575.
#
# Both are now derived once beside each other and threaded, which is only the
# same answer if the derivation does not move under the loop that mutates method
# bodies in place. These cases pin the COUNT (the thing that regressed) and the
# ANSWER (the thing that must not), and the count is asserted by instrumenting
# the predicate and driving the whole pipeline rather than by timing: a build
# that got slower again would be noticed by nobody, and one that got faster by
# answering a different question would pass every refusal test in the tree.
#
# The last row is the correctness guard for `struct_derived_names`. This change
# removed that function's own final filter — `{n for n in derived if n in
# set(names)}` — on the argument that it could not remove anything, because
# `derived` only ever receives a name from the collection it was built from. The
# filter was dead; what is NOT dead is the FIXED POINT beside it, and the row
# below pins the closure through something observable rather than through the
# helper's return value: `struct Reg(MyBase)` with `struct MyBase(Enum)` is an
# enum, and if the closure stopped being transitive `struct_is_enum` would say
# False, `Reg.RAX.value` would lose its accessor site, and the read would be
# answered as an ordinary member access of a word — which prints 0 where the
# source says the member's value. That is the silent wrong answer
# `_enum_member_sites` exists to prevent, so a lost site is a wrong program and
# not a missing diagnostic.
#
# (name, mojo_source, expected_enum_struct_names)
PER_MODULE_TABLE_CASES = [
    ("the_framed_table_is_derived_once_per_struct_not_once_per_function",
     "struct Wide:\n"
     "    var a: Int\n"
     "    var b: Int\n"
     "    var c: Int\n"
     "    def total(self) -> Int:\n"
     "        return self.a + self.b + self.c\n"
     "    def bump(self):\n"
     "        self.a = self.a + 1\n"
     "\n"
     "struct Narrow:\n"
     "    var n: Int\n"
     "    def get(self) -> Int:\n"
     "        return self.n\n"
     "    def set(self, v: Int):\n"
     "        self.n = v\n"
     "\n"
     "def one(x: Int) -> Int:\n"
     "    var w = Wide()\n"
     "    var v = Narrow()\n"
     "    v.set(x)\n"
     "    return w.total() + v.get()\n"
     "\n"
     "def two(x: Int) -> Int:\n"
     "    var w = Wide()\n"
     "    var v = Narrow()\n"
     "    v.set(x)\n"
     "    return w.total() + v.get()\n"
     "\n"
     "def three(x: Int) -> Int:\n"
     "    var w = Wide()\n"
     "    var v = Narrow()\n"
     "    v.set(x)\n"
     "    return w.total() + v.get()\n"
     "\n"
     "def four(x: Int) -> Int:\n"
     "    var w = Wide()\n"
     "    var v = Narrow()\n"
     "    v.set(x)\n"
     "    return w.total() + v.get()\n"
     "\n"
     "def five(x: Int) -> Int:\n"
     "    var w = Wide()\n"
     "    var v = Narrow()\n"
     "    v.set(x)\n"
     "    return w.total() + v.get()\n"
     "\n"
     "def six(x: Int) -> Int:\n"
     "    var w = Wide()\n"
     "    var v = Narrow()\n"
     "    v.set(x)\n"
     "    return w.total() + v.get()\n"
     "\n"
     "def seven(x: Int) -> Int:\n"
     "    var w = Wide()\n"
     "    var v = Narrow()\n"
     "    v.set(x)\n"
     "    return w.total() + v.get()\n"
     "\n"
     "def eight(x: Int) -> Int:\n"
     "    var w = Wide()\n"
     "    var v = Narrow()\n"
     "    v.set(x)\n"
     "    return w.total() + v.get()\n",
     []),

    ("the_enum_table_is_derived_once_per_struct_and_agrees_with_the_derivation",
     "class Reg(Enum):\n"
     "    RAX = 0\n"
     "    R15 = 15\n"
     "\n"
     "class Plain:\n"
     "    var v: Int\n"
     "    def get(self) -> Int:\n"
     "        return self.v\n"
     "\n"
     "def one(x: Int) -> Int:\n"
     "    return Reg.RAX.value + Reg.R15.name.__len__() + x\n"
     "\n"
     "def two(x: Int) -> Int:\n"
     "    var p = Plain()\n"
     "    p.v = x\n"
     "    return p.get() + Reg.R15.value\n"
     "\n"
     "def three(x: Int) -> Int:\n"
     "    var p = Plain()\n"
     "    p.v = x\n"
     "    return p.get() + Reg.R15.value\n"
     "\n"
     "def four(x: Int) -> Int:\n"
     "    var p = Plain()\n"
     "    p.v = x\n"
     "    return p.get() + Reg.R15.value\n",
     ["Reg"]),

    ("an_enum_through_two_levels_of_inheritance_is_still_an_enum",
     # `struct Reg(MyBase)` with `struct MyBase(Enum)`: `Reg` names `MyBase` in
     # its bases, NOT `Enum`, so nothing but the TRANSITIVE closure says `Reg` is
     # an enum. A derivation that read direct bases, or that made one pass in
     # declaration order, would drop `Reg` from the table — and `Reg.RAX.value`
     # would then have no accessor site, so the read would fall through to the
     # member-access lowering and print 0 where the source says the member's
     # value. Both are declared in the order that makes the fixed point
     # necessary (the intermediate base first), so a one-pass derivation misses
     # the grandchild.
     "struct MyBase(Enum):\n"
     "    A = 0\n"
     "\n"
     "struct Reg(MyBase):\n"
     "    RAX = 0\n"
     "    R15 = 15\n"
     "\n"
     "struct Plain:\n"
     "    var v: Int\n"
     "    def get(self) -> Int:\n"
     "        return self.v\n"
     "\n"
     "def use(x: Int) -> Int:\n"
     "    var p = Plain()\n"
     "    p.v = x\n"
     "    return Reg.R15.value + p.get()\n",
     ["MyBase", "Reg"]),
]

# Padding functions, appended by the runner to change the FUNCTION count while
# leaving the struct set alone — so the same struct table can be asked about
# with a module that has few functions and one that has many.
_PAD_FN = ("\ndef pad{i}(x: Int) -> Int:\n"
           "    return x + {i}\n")


def _struct_asks(source: str, pad: int) -> dict:
    """`{struct name: {question: [answers]}}` for one `_prepare_functions`.

    Instruments the two module-level predicates the per-function loop used to
    derive itself and returns, per struct, every answer each one gave — so a
    caller can compare COUNTS (did the ask count move with the function count?)
    and ANSWERS (did threading the table change what it says?) from one run.
    """
    import fire_compiler as F
    import formal.build as FB
    import formal.model as M

    text = source + "".join(_PAD_FN.format(i=i) for i in range(pad))
    stmts = FB.parse_module(text, "padded.mojo")
    seen = {}

    def record(label, real):
        def counted(struct_def, *a, **k):
            answer = real(struct_def, *a, **k)
            row = seen.setdefault(getattr(struct_def, "name", None), {})
            row.setdefault(label, []).append(answer)
            return answer
        return counted

    saved = {name: getattr(M, name) for name in ("struct_is_framed",
                                                 "struct_is_one_field",
                                                 "struct_is_enum")}
    try:
        M.struct_is_framed = record("framed", saved["struct_is_framed"])
        M.struct_is_one_field = record("one_field",
                                       saved["struct_is_one_field"])
        M.struct_is_enum = record("enum", saved["struct_is_enum"])
        try:
            FB._prepare_functions(stmts, synthetic=True,
                                  source_path="padded.mojo")
        except (FB.FormalBuildError, M.CodegenError):
            # A refusal is a fine outcome: the questions were still asked, and
            # the count is the thing under test.
            pass
    finally:
        for name, fn in saved.items():
            setattr(M, name, fn)
    return seen


def run_per_module_table_case(case, tmpdir, verbose):
    """Adding functions must not add module-level derivations, or change them.

    Two runs of the SAME source, one with 8 padding functions and one without,
    and the assertion is on BOTH what was asked and what it said. The count is
    the regression this exists for — `#functions × #structs` whole-struct walks
    is what `bugs/FORMAL_build_cost_2026-10-03.md` measures — and the answers are
    what makes the count safe to assert: threading a table is only the same
    answer if the derivation does not move while the loop rewrites method bodies,
    so a table that changed under the loop would show up here as a differing
    answer list rather than as a silent layout difference.
    """
    import fire_compiler as F
    import formal.build as FB
    import formal.model as M

    name, source, want_enums = case
    few = _struct_asks(source, 0)
    many = _struct_asks(source, 8)
    if set(few) != set(many):
        return False, (f"{set(few) ^ set(many)}: the two runs saw different "
                       f"structs, so there is nothing to compare")
    for st in sorted(few, key=str):
        for question in sorted(few[st]):
            a, b = few[st][question], many[st][question]
            if a != b:
                return False, (
                    f"struct {st}: {question} answered {a[:2]}… with 0 padding "
                    f"functions and {b[:2]}… with 8, so the derivation moves "
                    f"under the per-function loop")
            if len(a) != len(b):
                return False, (
                    f"struct {st}: {question} was asked {len(a)} times with the "
                    f"8 padding functions and {len(b)} times without them — a "
                    f"module-level table is being derived per FUNCTION again")
    # The threaded table and the derivation it replaced must agree, site for
    # site, for every function in the unit. `_enum_member_sites`' `None` is the
    # derivation; the table is what `_prepare_functions` passes.
    stmts = FB.parse_module(source, name + ".mojo")
    structs = {s.name: s for s in stmts if isinstance(s, F.StructDef)}
    table = {n: st for n, st in structs.items()
             if M.struct_is_enum(structs, n)}
    if sorted(table) != sorted(want_enums):
        return False, (f"the enum table is {sorted(table)}, expected "
                       f"{sorted(want_enums)}; `model.struct_derived_names` is a "
                       f"FIXED POINT over the base closure and not a pass over "
                       f"the direct bases, so this is where a non-transitive "
                       f"derivation shows")
    fns = [s for s in stmts if getattr(s, "name", None)
           and not isinstance(s, F.StructDef)]
    if not fns:
        return False, "the case declares no function to compare the table over"
    # Every enum member's accessor must be a site, with `bound` EMPTY so no
    # local can shadow the class name — `.value` and `.name` are the two
    # attributes CPython puts on a member and the only two this path answers.
    for ename, est in sorted(table.items()):
        sites = FB._enum_member_sites(structs, set(), table)
        for cname, _default in M.struct_class_constants(est):
            for accessor in ("value", "name"):
                if f"{ename}.{cname}.{accessor}" not in sites:
                    return False, (
                        f"{ename}.{cname}.{accessor} is not a site, so the read "
                        f"would be answered as an ordinary member access of a "
                        f"word — which prints 0 where the source says the "
                        f"member's value")
    for fn in fns:
        bound = FB._names_bound_in(fn)
        derived = FB._enum_member_sites(structs, bound)
        threaded = FB._enum_member_sites(structs, bound, table)
        if sorted(derived) != sorted(threaded):
            return False, (f"{fn.name}: threaded enum sites {sorted(threaded)} "
                           f"are not the derived ones {sorted(derived)}")
    # The ONE-FIELD table, which is the third predicate of the same partition
    # and was threaded on 2026-10-03 (`bugs/FORMAL_build_cost_2026-10-03.md`
    # §6's first residue). The assertion is the same shape as the enum half
    # above and for the same reason: `one_field_answer(st, table)` is what the
    # per-function askers now read, so a table that disagreed with
    # `struct_is_one_field` would be a silent layout difference rather than a
    # failure, and `struct_is_one_field` is a whole-struct walk of bodies —
    # 1 541 of them on `myinterpreter.py` against 146 for the derivation.
    one_field = M.one_field_struct_names(structs.values())
    if sorted(one_field) != sorted(
            n for n, st in structs.items() if M.struct_is_one_field(st)):
        return False, (
            f"the one-field table is {sorted(one_field)}, which is not the set "
            f"of structs `struct_is_one_field` accepts — so the threaded reads "
            f"and the derivation are two answers to one question")
    for st_name, st in sorted(structs.items()):
        if M.one_field_answer(st, one_field) != M.struct_is_one_field(st):
            return False, (
                f"{st_name}: `one_field_answer` with the table says "
                f"{M.one_field_answer(st, one_field)} and the predicate says "
                f"{M.struct_is_one_field(st)}")
    # …and with NO table, which is what every caller without a module context
    # gets: the same answer, by the other path. A caller that reads a function's
    # answer with no unit in hand must not be able to tell the two apart.
    for st_name, st in sorted(structs.items()):
        if M.one_field_answer(st, None) != M.struct_is_one_field(st):
            return False, (
                f"{st_name}: `one_field_answer` with no table says "
                f"{M.one_field_answer(st, None)} and the predicate says "
                f"{M.struct_is_one_field(st)}")
    if verbose:
        print(f"      {len(few)} structs, per-struct asks "
              f"{ {s: {q: len(a) for q, a in v.items()} for s, v in few.items()} }")
    return True, ""


def run_census_case(case, tmpdir, verbose):
    """The field set, the per-method sets against the old formula, ONE census.

    Read through `formal.build.parse_module` rather than `fire_compiler` alone
    because the evidence `_split_declaration` needs is attached there — a struct
    with no evidence attached reports no split at all, and this file's other
    field-set rows go through `struct_field_names` with that evidence absent on
    purpose (`_pre_rule_field_names`), which is a DIFFERENT rule with a
    different answer for a declared name that is also a method.
    """
    import fire_compiler as F
    import formal.build as FB
    import formal.model as M

    name, source, want = case
    # THE CENSUS IS COUNTED WHERE IT IS MADE, which is `parse_module` and not
    # the read below.  `FB.parse_module` attaches the unit's field evidence and
    # then resolves inheritance (`attach_inherited_fields` → `_merged_field_names`
    # → `_own_field_names` → `_split_declaration` → `struct_receiver_stores`), and
    # that is the ONE derivation.  `struct_field_names` answers from what that
    # published (`struct_merged_field_names`) and so asks nothing at all — measured,
    # and it is why an ask counter wrapped around a second `struct_field_names`
    # sees zero rather than one.  `myinterpreter.py` reads both
    # `M._own_field_names` and `struct_field_names`, so the whole point of the
    # per-function-asker work is that neither is O(methods).
    #
    # Asserting the ask COUNT rather than only the answer LISTS is the point of
    # the group: a derivation that re-walked every method body once per method
    # would answer identically and still be the pre-fix shape.  Three call sites
    # and three costs, because there are three paths and each is a place a
    # per-method asker could reappear:
    #
    #   * `parse_module`, which derives each struct's OWN field names once to
    #     publish the merge — 1, for a struct of ANY number of methods;
    #   * the READERS of what it published (`struct_field_names`,
    #     `struct_field_count`, `struct_sole_field_name`,
    #     `struct_fits_one_word`)
    #     — 0, because a regression that stopped publishing the merge or stopped
    #     threading the table would make these n_methods again; and
    #   * `_own_field_names`, which is what `struct_field_names` FALLS THROUGH to
    #     for a struct nothing published a merge for — a struct read without
    #     `formal.build`, which is how a module imported from another image is
    #     asked.  1, and its ANSWER is asserted equal to what was published, so a
    #     change that made the two disagree fails here rather than in whichever
    #     reader happened to see it.
    #
    # Measured on `a_declared_name_that_is_also_a_method_stays_a_field` (a
    # 2-method struct): 1 ask during the parse, 1 from `_own_field_names`, 0
    # from a second `struct_field_names`.
    calls = []
    real = M.struct_receiver_stores

    def counted(struct_def, receivers_arg):
        calls.append(getattr(struct_def, "name", None))
        return real(struct_def, receivers_arg)

    M.struct_receiver_stores = counted
    try:
        stmts = FB.parse_module(source, name + ".mojo")
    finally:
        M.struct_receiver_stores = real
    structs = [s for s in stmts if isinstance(s, F.StructDef)]
    if len(structs) != 1:
        return False, f"the case declares {len(structs)} structs, expected 1"
    st = structs[0]
    if calls != [st.name]:
        return False, (f"attaching this unit's field evidence asked "
                       f"struct_receiver_stores {len(calls)} times for its one "
                       f"struct {calls!r}; the store census is a property of the "
                       f"STRUCT, so it is made once")
    got = M.struct_field_names(st)
    if got != want:
        return False, f"struct_field_names == {got}, expected {want}"

    receivers = M.struct_receivers(st)
    demoted = M.struct_demoted_method_names(st, receivers)
    per_method = M.struct_method_receiver_reads(st, receivers)
    if len(per_method) != len(M.struct_methods(st)):
        return False, (f"{len(per_method)} read sets for "
                       f"{len(M.struct_methods(st))} methods")
    for method, reached, fields in per_method:
        spelled = M._receiver_names(getattr(method, "body", None), receivers)
        if reached != spelled:
            return False, (f"{method.name}: reached {sorted(reached)} is not "
                           f"what the body spells {sorted(spelled)}")
        if fields != spelled - demoted:
            return False, (f"{method.name}: demoted set {sorted(fields)} is not "
                           f"the old per-method formula "
                           f"{sorted(spelled - demoted)}")

    # The path that is NOT the parse: the DERIVATION every reader falls through
    # to when `parse_module` published no merge for this struct. Counted, and
    # its ANSWER asserted against the list the readers returned, because a count
    # and an answer can be right for different reasons.
    #
    # **And the readers themselves are deliberately NOT counted here.** The
    # earlier form of this row wrapped `struct_field_names` and asserted 0 asks,
    # on the strength of "`struct_field_names` answers from what `parse_module`
    # published and so asks nothing at all" — which is true only for a struct
    # that HAS a published merge, i.e. one that inherits. Four of the cases in
    # this group do not inherit, nothing is published for them, and their readers
    # ask exactly once, through the documented fall-through
    # (`formal/model.py::_own_field_names`). Asserting 0 there was asserting a
    # fact about the tree's shape rather than about its cost, and it was red on
    # four rows for that reason. The per-function asker this row exists to catch
    # is caught by the count below: a derivation that walked every method body
    # once per method would answer IDENTICALLY and still make this n_methods.
    del calls[:]               # the parse's ask is counted above, not here
    n_methods = len(M.struct_methods(st))
    M.struct_receiver_stores = counted
    try:
        own = M._own_field_names(st)
    finally:
        M.struct_receiver_stores = real
    if len(calls) != 1:
        return False, (f"deriving {st.name}'s OWN field names asked "
                       f"struct_receiver_stores {len(calls)} times; it is a "
                       f"property of the STRUCT, so it is asked once")
    if own != got:
        return False, (f"{st.name}'s own field names {own} are not the list "
                       f"struct_field_names published for it ({got})")
    if verbose:
        print(f"      field set {got}; {n_methods} methods, 1 census")
    return True, ""


def run_site_filter_case(case, tmpdir, verbose):
    """The sites a rewrite could consult are exactly the ones it could match."""
    import fire_compiler as F
    import formal.build as FB

    name, source, fn_name, want = case
    stmts = FB.parse_module(source, name + ".mojo")
    structs = {s.name: s for s in stmts if isinstance(s, F.StructDef)}
    fns = [s for s in stmts if getattr(s, "name", None) == fn_name]
    if len(fns) != 1:
        return False, f"the case declares {len(fns)} functions named {fn_name}"
    sites = FB._constant_read_sites(fns[0], structs, None, None)
    got = sorted(sites)
    if got != sorted(want):
        return False, f"constant-read sites {got}, expected {sorted(want)}"
    if verbose:
        print(f"      sites {got}")
    return True, ""


def build_formal(src, out, backend):
    cmd = [sys.executable, FIRE, "build", "--formal", "--no-prove",
           f"--backend={backend}", "-o", out, src]
    p = subprocess.run(cmd, capture_output=True, text=True,
                       timeout=BUILD_TIMEOUT, cwd=HERE)
    return p.returncode, (p.stderr or p.stdout or "")


def run_cpython(source, tmpdir):
    """The oracle: the same program under CPython, whose stdout the formal
    image has to match.

    Not `fire.py run` and not this repository's own interpreter: a differential
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
    stmts = F.Parser(F.py_tokenize_named(source, src)).with_filename(src).parse_module()
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
               ("census", CENSUS_CASES, run_census_case),
               ("site filter", SITE_FILTER_CASES, run_site_filter_case),
               ("module table", PER_MODULE_TABLE_CASES,
                run_per_module_table_case),
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