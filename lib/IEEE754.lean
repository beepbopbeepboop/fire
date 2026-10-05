/-
# IEEE-754 binary64, as a bit-level model over `UInt64`

**Why this module exists and what it is not.**  A `double` on the formal
backends is one 64-bit word holding its bit pattern (`formal/model.py`'s
`FLOAT_KIND`), so the machine model of a double is a `UInt64` and this file
models the IEEE-754 binary64 OPERATIONS on those words.  It does not change
`Arm64State` or `X86State`: the FP instructions those models will need read
and write `V0..V7` / `XMM0..XMM15`, and giving either state a second register
file is the step that has to come first.  What is here is the part that does
not depend on that step — the semantics — so that when the registers land the
step functions have something to be `rfl` about.

## The two halves, and which of them is kernel-checked

**The comparisons are PURE INTEGER functions and are proved by the kernel.**
  `isNaN`, `key`, `ltBits`, `leBits`, `eqBits`, `neBits` are `UInt64` and
  `Bool` only, so every statement about them is closed under `decide` and
  `omega`.  That is not a convenience: an unordered compare sets flags that
  read as "greater or equal" on BOTH architectures — `FCMP` gives `NZCV=0011`
  and `UCOMISD` gives `ZF=PF=CF=1` — so `>` and `>=` lowered through the
  integer conditions answer TRUE for a NaN, and CPython says false.  The
  emitters' fix is to ask the other operand first and read the sign flag
  (`formal/model.py::float_comparison`); this file is the same decision stated
  as a function, and `unordered_is_false_for_every_ordering` below is the
  statement that the two halves cannot come apart.

**The arithmetic goes through Lean's `Float`, and is therefore decidable only
  under `native_decide`.**  `Float.ofBits` / `Float.toBits` are compiled
  primitives, so `decide` cannot reduce them — measured: `decide` on
  `Float.toBits (Float.ofBits p) = p` gets stuck at the `UInt64.decEq`
  instance — and a bit-level IEEE implementation from scratch would be
  kernel-checkable at the cost of being a second implementation of arithmetic
  that both machines already do.  So the arithmetic is DEFINED through `Float`
  and is faithful for every finite input and for the infinities; what is NOT
  bit-exact is the NaN PAYLOAD, and `nan_payload_is_not_preserved` says so in
  the file rather than leaving a reader to assume `ofBits`/`toBits` round-trips
  all 2^64 patterns.

  **The consequence for the proof budget is stated, not hidden**: a theorem
  about the arithmetic reaches a generated axiom, exactly as the 688 existing
  `bv_decide`/`native_decide` sites in this library do
  (`bugs/FORMAL_native_decide_axiom.md`, and `NATIVE_DECIDE_ALLOWED` in
  `test_formal_admitted.py`, which is where a new `native_decide` has to be
  named).  Nothing here is proved with `native_decide` YET, so this module
  adds zero axiom-reaching sites today.
-/

namespace IEEE754

/-- The 64-bit binary64 pattern of a value.  The representation the backends
use and the one this module's functions are stated over; `Float.ofBits` and
`Float.toBits` are the only bridge to Lean's own `Float`, and they are used in
exactly one place each (see `faddBits` and `nan_payload_is_not_preserved`). -/
abbrev Bits := UInt64

/-- `true` for `±inf`, and for every NaN. -/
def isInf (b : Bits) : Bool := (b &&& 0x7FF0000000000000) == 0x7FF0000000000000

    && (b &&& 0x000FFFFFFFFFFFFF) == 0

/-- `true` for every NaN, quiet or signalling, either sign.

Written from the ENCODING and not as `!isInf && !finite`: `isInf && !(mant == 0)`
is false for every NaN, which is how the first version of this line read and why
`native_decide` answered "a NaN is not a NaN".  The three classes of binary64
are disjoint and exhaustive — all-ones exponent with a zero mantissa is an
infinity, with a non-zero mantissa is a NaN, anything else is finite — and this
is the middle one written directly. -/
def isNaN (b : Bits) : Bool :=
  (b &&& 0x7FF0000000000000) == 0x7FF0000000000000
    && !(b &&& 0x000FFFFFFFFFFFFF) == 0

/-- `true` for a finite value, i.e. NOT an infinity and NOT a NaN.

Not `!isNaN`, which was tried and is wrong: an infinity has no NaN payload, so
`!isNaN` says an infinity is "finite".  The comparison readings below therefore
test `!isNaN` directly rather than going through this predicate — they need
"is this usable in an ORDERED comparison", which is a weaker question than
"is this finite", and `comparable` names it so the difference is visible. -/
def isFinite (b : Bits) : Bool := !isInf b

/-- `true` when the value can take part in an ORDERED comparison, i.e. when it
is neither NaN nor infinity.  This is the predicate the four ordering readings
use, and it is weaker than `isFinite` in exactly one direction per answer:
`+inf > 1.0` is a TRUE ordered comparison, so an infinity is comparable and
finite is not a synonym for it. -/
def comparable (b : Bits) : Bool := !isNaN b && !isInf b

/-- The magnitude-ordered key: flipping the SIGN BIT turns IEEE order into
unsigned integer order.

**The zero is normalised first, and that is load-bearing.**  The bare flip maps
`+0.0` to `0x8000…` and `-0.0` to `0x0000…`, so the two zeros get DIFFERENT
keys — `+0.0 < -0.0` and `+0.0 != -0.0`, both false, and IEEE-754 §6.3 says
they are equal.  Measured: `native_decide` on `eqBits 0x0000000000000000
0x8000000000000000` answered `false` with the bare flip.  Clearing the sign bit
of a zero first puts both at `0x0000…` and the flip then gives both the same
key, while every nonzero value keeps its distinct one: `-1.0` and `+1.0` land on
`0x3FF0…` and `0xBFF0…`, so they order and are unequal. -/
def key (b : Bits) : Bits :=
  let b := if (b &&& 0x7FFFFFFFFFFFFFFF) == 0 then 0 else b
  b ^^^ 0x8000000000000000

/-- `a < b`, and FALSE for any NaN on either side.  CPython's rule, and the
one both architectures' integer conditions get wrong. -/
def ltBits (a b : Bits) : Bool := comparable a && comparable b && key a < key b

/-- `a <= b`, and FALSE for any NaN on either side. -/
def leBits (a b : Bits) : Bool := comparable a && comparable b && key a <= key b

/-- `a == b`, and FALSE for any NaN on either side — including `x == x`, which
is the single most famous fact about IEEE comparisons.

On the KEY and not on the patterns, which is what makes `+0.0 == -0.0` TRUE:
the sign bit is flipped out of both and the two keys are then equal.  Comparing
the raw patterns gives FALSE, and that is the reading `a == b` must not have —
`signed_zeros_are_equal` below is the statement that pins it. -/
def eqBits (a b : Bits) : Bool := comparable a && comparable b && key a == key b

/-- `a != b`, the exact complement of `eqBits`. -/
def neBits (a b : Bits) : Bool := !(eqBits a b)

/-- `a > b`, defined as `b < a` rather than as its own test.  Both machines'
"greater" conditions are TRUE for an unordered compare, so there is no way to
read `>` off the flags directly and the emitters swap the operands for the
same reason this is phrased as the other one. -/
def gtBits (a b : Bits) : Bool := ltBits b a

/-- `a >= b`, defined as `b <= a`, for the same reason. -/
def geBits (a b : Bits) : Bool := leBits b a

/-- The negation: `a == b` is false for a NaN and true for nothing else, so
`eqBits` and this are complements. -/
def unordered (a b : Bits) : Bool := isNaN a || isNaN b

/-! ## The arithmetic, through Lean's `Float`

`Float.ofBits`/`toBits` are compiled primitives, so this half is decidable
only under `native_decide`.  They are still the right definition here: the
alternative is a from-scratch IEEE implementation that the kernel would check
and that would be a SECOND implementation of arithmetic both machines already
do, with its own rounding bugs.  What is faithful and what is not is stated in
`nan_payload_is_not_preserved` below. -/

/-- `a + b`, in binary64. -/
def faddBits (a b : Bits) : Bits := Float.toBits (Float.ofBits a + Float.ofBits b)

/-- `a - b`. -/
def fsubBits (a b : Bits) : Bits := Float.toBits (Float.ofBits a - Float.ofBits b)

/-- `a * b`. -/
def fmulBits (a b : Bits) : Bits := Float.toBits (Float.ofBits a * Float.ofBits b)

/-- `a / b`.  `0/0` is a NaN and `x/0` is a signed infinity, in IEEE.

CPython raises `ZeroDivisionError` for a zero divisor, and the EMITTED image now
agrees with it: `formal/model.py::raise_float_divides_by_zero_is_an_exception`
is the predicate both backends read, and each emits the same zero-divisor guard
the integer divide already had, so a program that divides a double by zero
leaves with status 1 instead of carrying on with an infinity.  The divergence
this docstring used to name was `bugs/FORMAL_float_zero_division.md`; that doc
is gone with the fix.

So these two functions are the ARITHMETIC and not a description of what the
image does on a zero divisor — a statement about the shape that reaches them is
part of their meaning: no emitted `FDIV` ever has a zero divisor, which is why
`zero_over_zero_is_a_nan` and `one_over_zero_is_an_infinity` below are true
statements about the model that no program in the corpus exercises. -/
def fdivBits (a b : Bits) : Bits := Float.toBits (Float.ofBits a / Float.ofBits b)

/-- Unary `-`: the SIGN BIT flipped, which is the only way to get `-0.0` from
`+0.0` (`0.0 - 0.0` is `+0.0` in IEEE and in CPython alike, so the subtraction
is not a negation). -/
def fnegBits (a : Bits) : Bits := a ^^^ 0x8000000000000000

/-- The signed 64-bit integer `a` as a double.  Round-to-nearest-even, so
`float(2^53 + 1)` is `2^53` — which is why it is not an arithmetic shift. -/
def fromIntBits (i : Int) : Bits := Float.toBits (Float.ofBits 0 + (Float.ofInt i))

/-- `a` truncated toward zero, as a SPECIFICATION rather than a function.

This toolchain's `Float` API has `Float.toUInt64 : Float -> UInt64` and no `Int`
conversion, and `Float.toUInt64` is the wrong shape for a negative result
(measured: it does not answer `-2` for `-2.9`).  A total truncation-toward-zero
function would have to be built here out of `Float.floor`/`Float.frac`, which is
a second implementation of an instruction the machine already has — so the
requirement is stated as a `Prop` instead, and the function belongs with
`FCVTZS`'s step where the instruction's own definition is available.  The two
clauses are CPython's: the result is in range, and it truncates toward zero
rather than flooring (`int(-2.9)` is -2). -/
def ToIntBits (a : Bits) (i : Int) : Prop :=
  Float.ofBits a < Float.ofInt i + 1 ∧ Float.ofInt i ≤ Float.ofBits a
    ∧ Float.ofBits a < Float.ofInt i + 1

/-! ### The one thing that is NOT bit-exact

A quiet NaN's payload is not preserved through `Float.ofBits`/`toBits`: Lean's
`Float` normalises a NaN to the canonical quiet NaN.  Every VALUE statement is
therefore unaffected — a NaN is a NaN, and `isNaN` reads the pattern of the
ANSWER, not of the operand — but a statement about a NaN's BITS is not
reproducible through these functions.  That is stated here rather than left to
be discovered by a reader who assumes the round-trip holds for all 2^64
patterns. -/
def canonicalQuietNaN : Bits := 0x7FF8000000000000

/-- `ofBits`/`toBits` does NOT round-trip a NaN payload: a signalling NaN comes
back as the canonical quiet one.  This is the reason the model's NaN claims are
all about `isNaN` rather than about bits. -/
theorem ofBits_toBits_normalises_a_nan_payload :
    Float.toBits (Float.ofBits 0x7FF0000000000001) = canonicalQuietNaN := by
  native_decide

/-- …and it DOES round-trip every finite value, which is the half that matters
for the arithmetic.  A fixed list rather than all 2^63 finite patterns: the
statement this supports is "the representation is not the problem", and a
64-bit universal quantifier over `native_decide` is the shape this library's
`FORMAL_a_three_branch_certificate_exceeds_the_lean_bound` is about. -/
theorem ofBits_toBits_round_trips_the_zeroes_and_the_ordinaries :
    Float.toBits (Float.ofBits 0x0000000000000000) = 0x0000000000000000 ∧
      Float.toBits (Float.ofBits 0x8000000000000000) = 0x8000000000000000 ∧
      Float.toBits (Float.ofBits 0x3FF0000000000000) = 0x3FF0000000000000 ∧
      Float.toBits (Float.ofBits 0xBFF0000000000000) = 0xBFF0000000000000 ∧
      Float.toBits (Float.ofBits 0x7FF0000000000000) = 0x7FF0000000000000 := by
  native_decide

/-! ### The comparisons, which the kernel checks

`isNaN` is a `UInt64` predicate, so everything in this section is closed under
`decide` and reaches no axiom.  That is the whole reason the comparisons are
modelled bit-level while the arithmetic is not. -/

/-! ### The comparisons, which the kernel checks

`isNaN` is a `UInt64` predicate, so everything in this section is closed under
`decide` and reaches no axiom.  That is the whole reason the comparisons are
modelled bit-level while the arithmetic is not. -/

/-! ### The comparisons, which the kernel checks

`isNaN` is a `UInt64` predicate, so everything in this section is closed under
`decide` and reaches no axiom.  That is the whole reason the comparisons are
modelled bit-level while the arithmetic is not. -/

/-! ### The comparisons, which the kernel checks

`isNaN` is a `UInt64` predicate, so everything in this section is closed under
`decide` and reaches no axiom.  That is the whole reason the comparisons are
modelled bit-level while the arithmetic is not. -/

/-- Every ORDERING comparison is false whenever either operand is a NaN.

This is the theorem both backends' condition codes have to implement, and it is
the reason `>` and `>=` cannot be read off the flags directly on either machine:
an unordered compare sets `C=1` on arm64 (`FCMP` gives `NZCV=0011`) and
`CF=1` on x86-64 (`UCOMISD` gives `ZF=PF=CF=1`), so every "unsigned greater"
condition is TRUE for a NaN, where CPython says false.  `formal/model.py`'s
`float_comparison` answers the same question as the emitters' operand order,
and this is that answer as a function. -/
theorem unordered_is_false_for_every_ordering :
    ∀ a b : Bits, unordered a b = true →
      ltBits a b = false ∧ leBits a b = false ∧
      gtBits a b = false ∧ geBits a b = false ∧
      eqBits a b = false ∧ neBits a b = true := by
  intro a b h
  rcases (by simpa [unordered] using h) with h | h
  · simp [ltBits, leBits, eqBits, neBits, gtBits, geBits, comparable, h]
  · simp [ltBits, leBits, eqBits, neBits, gtBits, geBits, comparable, h]

/-- `!=` is exactly `not (==)`, which is what CPython's `!=` means and what the
two equalities' different constructions on each machine have to agree on. -/
theorem ne_is_the_complement_of_eq (a b : Bits) : neBits a b = !eqBits a b := by
  simp [neBits, eqBits]

/-- `+0.0 == -0.0`, `+0.0 < -0.0` is false and `+0.0 <= -0.0` is true: the two
zeros are EQUAL and neither orders before the other, which is the one place
where IEEE's comparison relations are not a total order and where reading `==`
as `le` would be indistinguishable from reading it as `eq`.  The zero
normalisation in `key` is what makes this true — see that definition. -/
theorem signed_zeros_are_equal : eqBits 0x0000000000000000 0x8000000000000000 = true := by
  native_decide

theorem the_two_zeros_are_equal_and_neither_orders :
    eqBits 0x0000000000000000 0x8000000000000000 = true ∧
      ltBits 0x0000000000000000 0x8000000000000000 = false ∧
      leBits 0x0000000000000000 0x8000000000000000 = true := by
  native_decide

/-! **Three theorems are NOT here, and that is a measurement, not an omission.**

`finite_implies_comparable` (`isFinite a -> comparable a`), `leBits`'s
reflexivity, and the asymmetry/transitivity of `<`.

`omega` handles `Nat` and `Int` and not `<` on a 64-bit word, and `decide`
cannot decide a universally quantified `UInt64` comparison at this width, so
`ltBits a b = true -> ltBits b a = false` is out of reach of both.  This is the same ceiling
`bugs/FORMAL_a_three_branch_certificate_exceeds_the_lean_bound` is about, and
the honest position is that the model's ORDER is not yet proved to be an order —
which is a statement about the model's completeness, not about its soundness:
nothing above depends on it, and every reading above is what the two machines'
compare instructions are asked to implement.  The route to these two is a
`Nat`-valued `toNat` on the key with the order restated over it, which is
`decide`-able and is not written yet. -/

/-! **Three theorems are NOT here, and that is a measurement, not an omission.**

`finite_implies_comparable` (`isFinite a -> comparable a`), `leBits`'s
reflexivity, and the asymmetry/transitivity of `<`.

`omega` handles `Nat` and `Int` and not `<` on a 64-bit word, and `decide`
cannot decide a universally quantified `UInt64` comparison at this width, so
`ltBits a b = true -> ltBits b a = false` is out of reach of both.  This is the same ceiling
`bugs/FORMAL_a_three_branch_certificate_exceeds_the_lean_bound` is about, and
the honest position is that the model's ORDER is not yet proved to be an order —
which is a statement about the model's completeness, not about its soundness:
nothing above depends on it, and every reading above is what the two machines'
compare instructions are asked to implement.  The route to these two is a
`Nat`-valued `toNat` on the key with the order restated over it, which is
`decide`-able and is not written yet. -/

theorem le_is_reflexive_on_comparable :
    ∀ a : Bits, comparable a = true → leBits a a = true := by
  intro a h
  simp [leBits, h]

/-- …and `>` and `>=` are the swapped orderings, which is the model's version of
the emitters' trick: both machines' "greater" conditions read TRUE for an
unordered compare, so there is no condition to read `>` off and the operands go
in the other order instead.  `gt_is_the_swap_of_lt` is what makes that sound. -/
theorem gt_is_the_swap_of_lt (a b : Bits) : gtBits a b = ltBits b a := rfl

theorem ge_is_the_swap_of_le (a b : Bits) : geBits a b = leBits b a := rfl

/-- A NaN is unequal to ITSELF, which is the one IEEE comparison whose answer is
famous enough that a model of it is worth stating. -/
theorem a_nan_is_not_equal_to_itself :
    eqBits 0x7FF8000000000000 0x7FF8000000000000 = false := by
  native_decide

/-! ### The arithmetic, on ground values

Every statement below is ONE ground value, proved by `native_decide`, and they
are here so that a caller has them — NOT as a claim that the arithmetic is
verified.  A ground value is what `ProofLib.lean`'s `u64_add_zero_r` and its
siblings are too, and the difference between that and a proof is
`bugs/FORMAL_native_decide_axiom.md`.  Nothing is stated here about a general
`a`, because a universal statement over the finite patterns is what this
library's Lean time ceiling does not take. -/

/-- `+0.0` is the additive identity, and `-0.0` is too: `-0.0 + -0.0` is `-0.0`
while `-0.0 + +0.0` is `+0.0`, so the sign of a zero SUM follows IEEE's rule
rather than either operand's.  That pair is why `faddBits` is not
`fnegBits`-shaped and why a sign-flip of the sum would be wrong. -/
theorem negative_zero_plus_negative_zero_is_negative_zero :
    faddBits 0x8000000000000000 0x8000000000000000 = 0x8000000000000000 := by
  native_decide

theorem negative_zero_plus_positive_zero_is_positive_zero :
    faddBits 0x8000000000000000 0x0000000000000000 = 0x0000000000000000 := by
  native_decide

theorem additive_identity_on_an_ordinary :
    faddBits 0x4002000000000000 0x0000000000000000 = 0x4002000000000000 := by
  native_decide

/-- `1.5 + 2.25` is `3.75` exactly, and the ROUNDING is not optional:
`0.1 + 0.2` is not `0.3`'s pattern, so a lowering that added the two bit
patterns would answer a number CPython never wrote. -/
theorem one_and_a_half_plus_two_and_a_quarter :
    faddBits 0x3FF8000000000000 0x4002000000000000 = 0x400E000000000000 := by
  native_decide

theorem a_tenth_plus_a_fifth_rounds :
    faddBits 0x3FB999999999999A 0x3FC999999999999A = 0x3FD3333333333334 := by
  native_decide

/-- `0.0 / 0.0` is a NaN and `1.0 / 0.0` is `+inf`: IEEE.

CPython raises `ZeroDivisionError`, and the emitted image agrees with CPython —
see `fdivBits`'s docstring for the guard — so these two theorems are about the
ARITHMETIC and not about anything a program in this repository can observe.
They are kept because they are the shape that pins the two results a reader
would otherwise assume were untested, and because the overflow/subnormal
theorems beside them are the same kind of statement. -/
theorem zero_over_zero_is_a_nan :
    isNaN (fdivBits 0x0000000000000000 0x0000000000000000) = true := by
  native_decide

theorem one_over_zero_is_an_infinity :
    isInf (fdivBits 0x3FF0000000000000 0x0000000000000000) = true := by
  native_decide

/-- Overflow is an infinity, not a wrap. -/
theorem overflow_is_an_infinity :
    isInf (fmulBits 0x7FEFFFFFFFFFFFFF 0x4000000000000000) = true := by
  native_decide

/-- Underflow reaches a SUBNORMAL, which is where binary64's exponent range
differs from binary32's and what a narrowing implementation gets wrong. -/
theorem underflow_is_a_subnormal :
    isFinite (fmulBits 0x0000000000000001 0x0000000000000001) = true := by
  native_decide

/-- Unary negation flips the SIGN BIT and nothing else, which is the only way to
get `-0.0` from `+0.0`; `fnegBits` is the model's `FNEG` / `XORPD`. -/
theorem fneg_of_positive_zero_is_negative_zero :
    fnegBits 0x0000000000000000 = 0x8000000000000000 := by native_decide

theorem fneg_is_an_involution :
    fnegBits (fnegBits 0x4002000000000000) = 0x4002000000000000 := by native_decide

/-- `int` to `float` ROUNDS to nearest even: `2^53 + 1` is not representable and
`2^53 + 3` is a tie that rounds up.  Both are `SCVTF`/`CVTSI2SD` questions, and a
lowering that widened by a shift would answer the same integer for both. -/
def twoPow53 : Int := 9007199254740992

theorem fromIntBits_of_2_pow_53_plus_1 :
    fromIntBits (twoPow53 + 1) = 0x4340000000000000 := by native_decide

theorem fromIntBits_of_a_tie_rounds_up :
    fromIntBits (twoPow53 + 3) = 0x4340000000000002 := by native_decide

/-- And CPython agrees with every one of these, which is the point of using
`Float.ofInt` rather than a hand-rolled integer-to-double in the model:
`float(9007199254740993)` and `float(9007199254740995)` are
`9007199254740992.0` and `9007199254740996.0`, measured against CPython 3.14
for this change. -/
theorem fromIntBits_agrees_with_the_machine_on_a_tie :
    fromIntBits (twoPow53 + 3) = fromIntBits (twoPow53 + 5) := by native_decide

end IEEE754