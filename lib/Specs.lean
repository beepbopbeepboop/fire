import ProofLib

/-!
# `Specs` — INDEPENDENT specifications for the classic example programs

Every generated proof in this repository states, at best,

    (match runProg <prog> n with | some s => s.x0 = mojo n | none => False)

where `mojo` is the generator's own model of the SOURCE.  That is a real
theorem, and it is also a **self-consistency** theorem: the machine code and the
semantic model are two readings of one source file, so a mistake in the reading
is invisible to it.  What it does not say is anything about what the program was
*supposed* to compute.

This module is that missing half.  Everything here is written **by hand, in
Lean's own mathematics** (`Nat`, `Int`, `List`), with no reference to
`ProofLib`'s machine model, to a generated file, or to another specification
here.  It is what `formal/examples/*.mojo` are *supposed* to compute, stated
over the mathematics rather than over 64-bit words, and `main_refines_spec` in
a generated proof is the theorem that the compiled program agrees with it.

## Two domains, deliberately not one

* the **mathematical** definitions (`fib`, `gcd`, `factorial`, `sumTo`, …) are
  the specification proper, stated over `Nat`/`Int`/`List`;
* the **`…64` word readings** (`fib64`, `abs64`, …) are those same definitions
  read at the machine's argument domain, so a generated proof can name one in
  an `@refines(...)` annotation and Lean can put it on both sides of an
  equation with `mojo`.

A word reading is `UInt64.ofNat` of a mathematical value, and that is the
identity only while the value FITS in a word — so a refinement theorem is
stated over a RANGE, and the range is a range the generated proof *proves*
(`main_spec_fits`) rather than one this file asserts about a program it has not
seen.  `fitsWord` is what both sides speak.

Writing a specification here and emitting `mojo` there are different acts by
different machinery, and that is the entire value of the layer: the only thing
that can make a generated refinement theorem fail is the two disagreeing.
-/

namespace Specs

/-! ## The word domain

What fits in a machine word, and how a word's bit pattern is read as a signed
integer.  `asInt` is the reading a Mojo `int` gets; it is stated here, in the
specification layer, rather than imported from `ProofLib`, because `abs64` below
is `abs` of an `Int` and not a claim about the high bit. -/

/-- `2^64`, one past the largest value a word holds.

Spelled as the POWER and not as the decimal literal, because the proofs below
compare against `UInt64.toNat_ofNat'`, which says `(UInt64.ofNat n).toNat =
n % 2 ^ 64`; a decimal literal and `2 ^ 64` are two atoms to `omega` and one
atom is one thing less for it to know.  `wordLimit_eq` is how a reader gets the
number back. -/
def wordLimit : Nat := 2 ^ 64

/-- `2^64 - 1`, the largest value a word holds. -/
def wordMax : Nat := wordLimit - 1

/-- `2^63`: the first bit pattern that reads as a NEGATIVE two's-complement
integer, and therefore the first input a signed comparison sees as `< 0`. -/
def signBit : Nat := 2 ^ 63

theorem wordLimit_eq : wordLimit = 18446744073709551616 := by decide

/-- Reading a literal word back gives the literal.  `UInt64.ofNat` is
truncating, so this is false for `n ≥ 2^64` and needs the bound — and it is the
fact every generated refinement theorem needs when it puts `n ∈ List.range N`
next to a universal theorem whose own side condition is stated over
`(UInt64.ofNat n).toNat`. -/
theorem ofNat_toNat (n : Nat) (h : n < wordLimit) :
    (UInt64.ofNat n).toNat = n := by
  rw [UInt64.toNat_ofNat']
  exact Nat.mod_eq_of_lt h

/-- `1024` fits in a word, which is what every refinement range in this tree is
bounded by (`formal/specs.py::MAX_RANGE`) and why the bound a generated proof has
to discharge is a pair of decimal literals rather than a comparison against
`2 ^ 64` that `omega` cannot see through. -/
theorem small_lt_wordLimit (n : Nat) (h : n < 1024) : n < wordLimit := by
  show n < 2 ^ 64
  have hp : 2 ^ 10 ≤ 2 ^ 64 :=
    Nat.pow_le_pow_right (n := 2) (by decide) (i := 10) (j := 64) (by decide)
  have hten : (2 ^ 10 : Nat) = 1024 := by decide
  omega

/-- The `ofNat_toNat` a generated refinement theorem uses: reading a word built
from a `Nat` below `1024` gives that `Nat` back.  `1024` is the literal rather
than `MAX_RANGE` so the caller's side condition is `n < 1024`, which follows
from `n ∈ List.range 1024` by `omega` alone. -/
theorem ofNat_toNat_small (n : Nat) (h : n < 1024) : (UInt64.ofNat n).toNat = n :=
  ofNat_toNat n (small_lt_wordLimit n h)
theorem wordMax_eq : wordMax = 18446744073709551615 := by decide
theorem signBit_eq : signBit = 9223372036854775808 := by decide

/-- Does a mathematical value fit in a machine word? -/
def fitsWord (v : Nat) : Prop := v < wordLimit

theorem wordMax_lt_wordLimit : wordMax < wordLimit := by
  show 2 ^ 64 - 1 < 2 ^ 64
  omega

theorem fitsWord_of_le_wordMax {v : Nat} (h : v ≤ wordMax) : fitsWord v := by
  unfold fitsWord
  exact Nat.lt_of_le_of_lt h wordMax_lt_wordLimit

/-- A word's bit pattern read as a two's-complement signed `Int`. -/
def asInt (w : UInt64) : Int :=
  if signBit ≤ (w.toNat : Int) then (w.toNat : Int) - wordLimit else (w.toNat : Int)

/-- The absolute value of an `Int`, as a `Nat`.  `Int.natAbs` is the same
function; this is spelled out because the point of the module is that a
specification is READABLE, not that it is novel. -/
def absInt (n : Int) : Nat := if 0 ≤ n then n.toNat else (-n).toNat

@[simp] theorem absInt_nonneg (n : Int) : 0 ≤ absInt n := by
  unfold absInt
  split <;> omega

@[simp] theorem absInt_of_nonneg {n : Int} (h : 0 ≤ n) : absInt n = n.toNat := by
  unfold absInt
  rw [if_pos h]

@[simp] theorem absInt_of_neg {n : Int} (h : n < 0) : absInt n = (-n).toNat := by
  unfold absInt
  rw [if_neg (by omega)]

/-- An unsigned word below the sign bit reads as itself, so the signed reading
of a small non-negative input is that input — which is what makes `abs64`
`abs` on the whole word domain and not only on the low half. -/
theorem asInt_ofNat_of_lt {n : Nat} (h : n < signBit) :
    asInt (UInt64.ofNat n) = (n : Int) := by
  have hlim : signBit ≤ wordLimit := by
    show 2 ^ 63 ≤ 2 ^ 64
    exact Nat.pow_le_pow_right (n := 2) (by decide) (i := 63) (j := 64) (by decide)
  have hw : (UInt64.ofNat n).toNat = n := by
    rw [UInt64.toNat_ofNat']
    exact Nat.mod_eq_of_lt (Nat.lt_of_lt_of_le h hlim)
  rw [asInt, hw, if_neg (by omega : ¬ (signBit : Int) ≤ (n : Int))]

/-! ## A small arithmetic fact the closed forms need -/

/-- `n ≤ n * n`, which is the one nonlinear fact `sumTo_eq` needs and which
`omega` will not supply on its own: it sees `n * n` as an atom and cannot know
an atom is at least `n`. -/
theorem le_self_mul (n : Nat) : n ≤ n * n := by
  rcases n with _ | n
  · decide
  · rw [Nat.succ_mul]
    omega

/-! ## The identity -/

/-- The identity: what `formal/examples/identity.mojo` computes. -/
def idNat (n : Nat) : Nat := n

/-- Its word reading.  Total and exact, so `identity`'s refinement needs no
range. -/
def id64 (w : UInt64) : UInt64 := w

/-! ## Fibonacci -/

/-- Fibonacci, over `Nat`, by the two-step recursion the examples use:
`fib 0 = 0`, `fib 1 = 1`, `fib (n + 2) = fib n + fib (n + 1)`. -/
def fib : Nat → Nat
  | 0 => 0
  | 1 => 1
  | n + 2 => fib n + fib (n + 1)

@[simp] theorem fib_zero : fib 0 = 0 := rfl
@[simp] theorem fib_one : fib 1 = 1 := rfl
@[simp] theorem fib_succ_succ (n : Nat) : fib (n + 2) = fib n + fib (n + 1) := rfl

/-- Each term is at least the one before it. -/
theorem fib_step : ∀ n, fib (n + 1) ≥ fib n := by
  intro n
  induction n with
  | zero => decide
  | succ n ih => rw [fib_succ_succ n]; omega

/-- Its word reading.  It is `fib` truncated at `2^64`, and a generated proof
that uses it states the range inside which the two are the same
(`main_spec_fits`) — which is the honest way to say "and here the truncation
does not bite". -/
def fib64 (w : UInt64) : UInt64 := UInt64.ofNat (fib w.toNat)

/-! ## Greatest common divisor -/

/-- The gcd, over `Nat`.  `Nat.gcd` is core Lean's own Euclidean algorithm and
this names it rather than reimplementing it: the specification layer's job is
to be INDEPENDENT of the compiler's model, and a second Euclidean algorithm
written here would be a second thing to get wrong without adding a single
independent check. -/
def gcd (a b : Nat) : Nat := Nat.gcd a b

theorem gcd_comm (a b : Nat) : gcd a b = gcd b a := Nat.gcd_comm a b

theorem gcd_le_left {a b : Nat} (h : 0 < a) : gcd a b ≤ a := by
  exact Nat.gcd_le_left b h

theorem gcd_le_right {a b : Nat} (h : 0 < b) : gcd a b ≤ b := by
  exact Nat.gcd_le_right a h

/-- Its word reading.  A gcd is at most its smaller argument, so this never
truncates for an input a machine can produce. -/
def gcd64 (a b : UInt64) : UInt64 := UInt64.ofNat (gcd a.toNat b.toNat)

/-! ## Factorial -/

/-- `n!`, over `Nat`. -/
def factorial : Nat → Nat
  | 0 => 1
  | n + 1 => (n + 1) * factorial n

@[simp] theorem factorial_zero : factorial 0 = 1 := rfl
@[simp] theorem factorial_succ (n : Nat) : factorial (n + 1) = (n + 1) * factorial n := rfl

/-- `n!` is never zero, which is the fact a word reading needs and the reason
`factorial64` is not vacuously the identity for large inputs. -/
theorem factorial_pos : ∀ n, 0 < factorial n := by
  intro n
  induction n with
  | zero => decide
  | succ n ih => simp only [factorial]; exact Nat.mul_pos (by omega) ih

/-- Its word reading.  `20! = 2432902008176640000` is the largest factorial a
word holds, so the range a generated proof can use is 21 inputs wide. -/
def factorial64 (w : UInt64) : UInt64 := UInt64.ofNat (factorial w.toNat)

/-! ## The sum of a range -/

/-- The sum of `0, 1, …, n - 1`: the specification of `sum_range.mojo`'s loop
and of `sum.mojo`'s recursion, which are two ways to compute it. -/
def sumTo : Nat → Nat
  | 0 => 0
  | n + 1 => n + sumTo n

@[simp] theorem sumTo_zero : sumTo 0 = 0 := rfl
@[simp] theorem sumTo_succ (n : Nat) : sumTo (n + 1) = n + sumTo n := rfl

/-- The closed form.  A specification is supposed to say WHAT it computes and
not require the reader to run it, and `2 * sumTo n = n * (n - 1)` is the
sentence; the recursive definition above is only how a machine would arrive at
it. -/
theorem sumTo_eq (n : Nat) : 2 * sumTo n = n * (n - 1) := by
  induction n with
  | zero => decide
  | succ n ih =>
      have h0 : (n + 1) - 1 = n := by omega
      have h1 : (n + 1) * ((n + 1) - 1) = n * n + n := by rw [h0, Nat.succ_mul]
      have h2 : 2 * (n + sumTo n) = 2 * n + 2 * sumTo n := by omega
      have h3 : n * (n - 1) = n * n - n * 1 := Nat.mul_sub n n 1
      have hnn := le_self_mul n
      rw [sumTo, h2, ih, h3, Nat.mul_one, h1]
      omega

/-- The sum of `0, 1, …, n` — `sumTo` one input further along.

This is a SEPARATE specification and not a re-spelling, and the reason is the
best worked example in this module of what the layer is for.  `sum_range.mojo`
and `sum.mojo` are the same function written two ways — a `for` loop over
`range(n)` and a recursion — and they compute DIFFERENT things at the ends:
`for i in range(n)` visits `0 … n-1`, while `if n == 0: 0 else: n + sum(n - 1)`
visits `1 … n`.  Annotating `sum.mojo` with `sumTo64` therefore failed the build
with

    Tactic `native_decide` evaluated that the proposition
      ∀ n, n ∈ List.range 64 → mojo (UInt64.ofNat n) = Specs.sumTo64 (UInt64.ofNat n)
    is false

which is the layer working: the two readings disagreed at `n = 1`, and the
build said so instead of believing either.  `sumThrough64` is the right
specification for the recursion, and `sumTo64` is still the right one for the
loop. -/
def sumThrough (n : Nat) : Nat := sumTo (n + 1)

/-- Its closed form, which is `sumTo_eq` one input along. -/
theorem sumThrough_eq (n : Nat) : 2 * sumThrough n = (n + 1) * n := by
  show 2 * sumTo (n + 1) = (n + 1) * n
  exact sumTo_eq (n + 1)

/-- Its word reading. -/
def sumTo64 (w : UInt64) : UInt64 := UInt64.ofNat (sumTo w.toNat)

/-- Its word reading — the one `sum.mojo` refines. -/
def sumThrough64 (w : UInt64) : UInt64 := UInt64.ofNat (sumThrough w.toNat)

/-! ## max and min -/

/-- The larger of two naturals. -/
def maxNat (a b : Nat) : Nat := if a < b then b else a

/-- The smaller of two naturals. -/
def minNat (a b : Nat) : Nat := if a < b then a else b

@[simp] theorem maxNat_self (a : Nat) : maxNat a a = a := by simp [maxNat]
@[simp] theorem minNat_self (a : Nat) : minNat a a = a := by simp [minNat]

theorem le_maxNat (a b : Nat) : a ≤ maxNat a b ∧ b ≤ maxNat a b := by
  simp only [maxNat]
  split <;> omega

theorem minNat_le (a b : Nat) : minNat a b ≤ a ∧ minNat a b ≤ b := by
  simp only [minNat]
  split <;> omega

/-- Their word readings.  `max`/`min` of two word values is a word value. -/
def maxNat64 (a b : UInt64) : UInt64 := UInt64.ofNat (maxNat a.toNat b.toNat)
def minNat64 (a b : UInt64) : UInt64 := UInt64.ofNat (minNat a.toNat b.toNat)

/-! ## Products, powers, and the small affine maps

The word readings of the arithmetic the other examples in the corpus compute.
They are here for the same reason `id64` is: a specification layer is only
useful against programs somebody actually wrote, and `localmul`, `pair`,
`chain` and `udivmod` are programs somebody actually wrote. -/

/-- The product of two consecutive naturals, `n * (n + 1)`. -/
def consecutiveProduct (n : Nat) : Nat := n * (n + 1)

/-- Its word reading. -/
def consecutiveProduct64 (w : UInt64) : UInt64 :=
  UInt64.ofNat (consecutiveProduct w.toNat)

/-- The square of `n + 1`. -/
def succSquare (n : Nat) : Nat := (n + 1) * (n + 1)

/-- Its word reading. -/
def succSquare64 (w : UInt64) : UInt64 := UInt64.ofNat (succSquare w.toNat)

/-- `2n + 1`: doubling and adding one, which is what a shift-and-add program
computes. -/
def doubleSuccOne (n : Nat) : Nat := 2 * n + 1

/-- Its word reading. -/
def doubleSuccOne64 (w : UInt64) : UInt64 := UInt64.ofNat (doubleSuccOne w.toNat)

/-- Euclid's division, as the SUM of its two parts: `n / d + n % d`.  Stated over
`Nat` because that is where `Nat.div`/`Nat.mod` are the classical operations;
the machine's own `/` on a word is a truncating divide by the same theorem. -/
def quotPlusRem (d n : Nat) : Nat := n / d + n % d

/-- Its word reading, at the divisor `d`. -/
def quotPlusRem64 (d w : UInt64) : UInt64 :=
  UInt64.ofNat (quotPlusRem d.toNat w.toNat)

/-- Euclid's division is exact: the quotient and the remainder account for `n`.
Stated over `n / d` rather than over `quotPlusRem` because the multiplication
`d * (n / d)` is not something `omega` can reason about — and it is Lean's own
theorem, so restating it would say nothing. -/
theorem quotRem_reconstruct (d n : Nat) :
    n = d * (n / d) + n % d := (Nat.div_add_mod n d).symm

/-- `quotPlusRem` really is the quotient plus the remainder: subtracting the
remainder recovers the quotient.  This is the statement a `divmod`
specification exists to make, and it is stated about the SPECIFICATION's own
function rather than about any program's code. -/
theorem quotPlusRem_left (d n : Nat) :
    quotPlusRem d n - n % d = n / d := by
  rw [quotPlusRem]
  exact Nat.add_sub_cancel_right _ _

/-- `n` is nonzero, as a `Bool` — what a machine comparison's answer becomes
when it is returned as a word. -/
def isNonzero (n : Nat) : Bool := n != 0

/-- Its word reading: `1` and `0`. -/
def isNonzero64 (w : UInt64) : UInt64 := if isNonzero w.toNat then 1 else 0

@[simp] theorem isNonzero_zero : isNonzero 0 = false := rfl
@[simp] theorem isNonzero_one : isNonzero 1 = true := by decide
theorem isNonzero_true_iff {n : Nat} : isNonzero n = true ↔ n ≠ 0 := by
  simp [isNonzero]

/-- `(n << 3) + (n >> 2)`: a left shift, a right shift, and their sum — the
classic "combine two bit fields" arithmetic. -/
def shiftMix (n : Nat) : Nat := Nat.shiftLeft n 3 + Nat.shiftRight n 2

/-- Its word reading.  `8n + n/4 ≤ 8n + n`, so it is exact for every input
below `2^61`. -/
def shiftMix64 (w : UInt64) : UInt64 := UInt64.ofNat (shiftMix w.toNat)

/-- `(n & 0xff) + (n | 0xf0) + (n ^ 0x55)`: masking, setting and inverting
three different bit fields and adding the results. -/
def maskedMix (n : Nat) : Nat :=
  (n &&& 0xff) + (n ||| 0xf0) + (n ^^^ 0x55)

/-- Its word reading.  Each term is below `0x100`, so the sum is below `0x300`
and never truncates. -/
def maskedMix64 (w : UInt64) : UInt64 := UInt64.ofNat (maskedMix w.toNat)

/-- `100000 + n` for positive `n` and `0` otherwise — a step function with a
dead zone, which is what `if n <= 0: 0 else: C + n` computes. -/
def stepConst (n : Nat) : Nat := if n = 0 then 0 else 100000 + n

/-- Its word reading. -/
def stepConst64 (w : UInt64) : UInt64 := UInt64.ofNat (stepConst w.toNat)

theorem stepConst_zero : stepConst 0 = 0 := by decide
theorem stepConst_one : stepConst 1 = 100001 := by decide

/-! ## Absolute value -/

/-- `abs` of a word's SIGNED value, as a non-negative word.  This is the
specification `formal/examples/absval.mojo` computes, and it is the honest one:
`absval` branches on a SIGNED comparison, so a specification over the unsigned
reading would be a claim about a different language.  It is TOTAL
(`absInt_fits`), so a refinement theorem against it needs no range. -/
def abs64 (w : UInt64) : UInt64 := UInt64.ofNat (absInt (asInt w))

/-! ## Binary search over a sorted array -/

/-- Drop the first `i` elements. -/
def listDrop : Nat → List Nat → List Nat
  | 0, a => a
  | _ + 1, [] => []
  | i + 1, _ :: cs => listDrop i cs

/-- Keep the first `i` elements. -/
def listTake : Nat → List Nat → List Nat
  | 0, _ => []
  | _ + 1, [] => []
  | i + 1, a :: cs => a :: listTake i cs

/-- The element at index `i`, or `none`. -/
def listAt (a : List Nat) (i : Nat) : Option Nat := (listDrop i a).head?

/-- Binary search over a SORTED array: `some i` when the target is at index `i`,
and `none` when it is absent.

The recursion is on an explicit `fuel` rather than on the list, which is what
makes it a total definition with no termination obligation to discharge — and a
specification whose own well-foundedness is an open question is a bad place to
put the meaning of "binary search".  The fuel is the array's own length, which
is more than enough: every step either answers or halves what is left. -/
def binarySearchAux : Nat → List Nat → Nat → Option Nat
  | 0, _, _ => none
  | fuel + 1, a, x =>
    let mid := a.length / 2
    match listAt a mid with
    | none => none
    | some v =>
      if x < v then binarySearchAux fuel (listTake mid a) x
      else if x = v then some mid
      else (binarySearchAux fuel (listDrop (mid + 1) a) x).map (fun i => mid + 1 + i)

/-- Binary search over a SORTED array, with the budget set to the array's length. -/
def binarySearch (a : List Nat) (x : Nat) : Option Nat :=
  binarySearchAux a.length a x

@[simp] theorem binarySearch_nil (x : Nat) : binarySearch [] x = none := rfl

/-- The target is found in a one-element array, at index 0. -/
@[simp] theorem binarySearch_single (x : Nat) : binarySearch [x] x = some 0 := by
  simp [binarySearch, binarySearchAux, listAt, listDrop]

/-- A worked case, so that the halving is visible rather than asserted: the
middle of a three-element sorted array. -/
@[simp] theorem binarySearch_middle : binarySearch [1, 2, 3] 2 = some 1 := rfl

/-- And a worked case of the LEFT half. -/
@[simp] theorem binarySearch_left : binarySearch [1, 2, 3] 1 = some 0 := rfl

/-- An absent target is `none`, not an index — which is the distinction a
"return 0 for not found" implementation cannot make. -/
@[simp] theorem binarySearch_absent_small : binarySearch [1, 2, 3] 0 = none := rfl

/-- Its word reading: an index, or `0` for "absent" — which is the encoding a
`UInt64 → UInt64` machine function can return, and why `binarySearchResult` is
spelled out rather than left as an `Option`. -/
def binarySearchResult (r : Option Nat) : UInt64 :=
  match r with
  | some i => UInt64.ofNat i
  | none => 0

/-- `binarySearch` read at the machine's argument domain. -/
def binarySearch64 (a : List UInt64) (x : UInt64) : UInt64 :=
  binarySearchResult (binarySearch (a.map (fun w => w.toNat)) x.toNat)

/-! ## Primality by trial division -/

/-- The odd divisors `d, d + 1, …` of `n` that a trial division would try:
every `k` with `d + k ≤ n` and `(d + k)² ≤ n`. -/
def trialDivisors (d n : Nat) : List Nat :=
  ((List.range (n + 1)).map (fun k => d + k)).filter
    (fun e => e ≤ n && e * e ≤ n)

/-- Does `d` divide `n`?  A `Bool` because that is what a machine function
returns; the honesty of that answer is the theorem below, not the definition. -/
def divides (n d : Nat) : Bool := n % d == 0

/-- `isPrime n` by trial division. -/
def isPrime (n : Nat) : Bool :=
  if n < 2 then false else !(trialDivisors 2 n).any (fun d => divides n d)

@[simp] theorem isPrime_zero : isPrime 0 = false := by decide
@[simp] theorem isPrime_one : isPrime 1 = false := by decide
@[simp] theorem isPrime_two : isPrime 2 = true := by decide
@[simp] theorem isPrime_four : isPrime 4 = false := by decide
@[simp] theorem isPrime_six : isPrime 6 = false := by decide

/-- A `true` answer is not about 0 or 1.  Stated because a `Bool`
specification whose soundness nobody writes down is a claim about a `Bool`. -/
theorem isPrime_true_ne_small {n : Nat} (h : isPrime n = true) : 2 ≤ n := by
  rcases n with _ | _ | n
  · simp at h
  · simp at h
  · omega

/-- Its word reading: `1` for prime, `0` for composite, which is what a program
returning a truth value as an integer returns. -/
def isPrime64 (w : UInt64) : UInt64 :=
  if isPrime w.toNat then 1 else 0

/-! ## Collatz -/

/-- One Collatz step: halve an even number, triple-and-add an odd one. -/
def collatzStep (n : Nat) : Nat :=
  if n % 2 ≤ 0 then n / 2 else 3 * n + 1

@[simp] theorem collatzStep_zero : collatzStep 0 = 0 := by decide
@[simp] theorem collatzStep_one : collatzStep 1 = 4 := by decide
@[simp] theorem collatzStep_two : collatzStep 2 = 1 := by decide

@[simp] theorem collatzStep_even {n : Nat} : collatzStep (2 * n) = n := by
  have hmod : (2 * n) % 2 = 0 := by simp
  rw [collatzStep, if_pos (by omega), Nat.mul_div_right n (by decide : (0 : Nat) < 2)]

/-- `k` steps from `n`, WITHOUT any termination claim.  This is the deliberate
difference from `n ↦ (the number of steps to reach 1)`: that function is the
Collatz conjecture, and a specification of it would be a conjecture written in
Lean and called a definition. -/
def collatzIter (n : Nat) : Nat → Nat
  | 0 => n
  | k + 1 => collatzStep (collatzIter n k)

@[simp] theorem collatzIter_zero (n : Nat) : collatzIter n 0 = n := rfl
@[simp] theorem collatzIter_succ (n k : Nat) :
    collatzIter n (k + 1) = collatzStep (collatzIter n k) := rfl

/-- Whether `n` reaches 1 within `k` steps.  Bounded, so total, so decidable,
so a generated proof can check a machine's Collatz against it. -/
def collatzReachesOneWithin (n k : Nat) : Bool := collatzIter n k == 1

@[simp] theorem collatzReachesOneWithin_zero (n : Nat) :
    collatzReachesOneWithin n 0 = (n == 1) := by
  simp [collatzReachesOneWithin, collatzIter]

/-- Its word reading. -/
def collatzStep64 (w : UInt64) : UInt64 := UInt64.ofNat (collatzStep w.toNat)

/-! ## Strings over ASCII -/

/-- The length of a string given as its characters. -/
def asciiLength : List Char → Nat
  | [] => 0
  | _ :: cs => asciiLength cs + 1

/-- Reversing a string, over `List`. -/
def asciiReverse : List Char → List Char
  | [] => []
  | c :: cs => asciiReverse cs ++ [c]

@[simp] theorem asciiLength_nil : asciiLength [] = 0 := rfl
@[simp] theorem asciiLength_cons (c : Char) (cs : List Char) :
    asciiLength (c :: cs) = asciiLength cs + 1 := rfl

/-- Length over a concatenation, which is what makes `asciiReverse` readable:
it appends one character at a time. -/
theorem asciiLength_append (a b : List Char) :
    asciiLength (a ++ b) = asciiLength a + asciiLength b := by
  induction a with
  | nil => simp [asciiLength]
  | cons c cs ih => simp [asciiLength, ih]; omega

/-- Reversing preserves length — the first thing a spec for `reverse` has to
say, and the thing a one-character-at-a-time implementation gets wrong. -/
theorem asciiLength_reverse (s : List Char) :
    asciiLength (asciiReverse s) = asciiLength s := by
  induction s with
  | nil => rfl
  | cons c cs ih =>
      simp only [asciiReverse, asciiLength_append, ih, asciiLength]

/-- Reversing a concatenation, which is the equation the double reversal is
made of. -/
theorem asciiReverse_append (a b : List Char) :
    asciiReverse (a ++ b) = asciiReverse b ++ asciiReverse a := by
  induction a with
  | nil => simp [asciiReverse]
  | cons c cs ih => simp [asciiReverse, ih, List.append_assoc]

/-- Reversing twice is the identity. -/
theorem asciiReverse_reverse (s : List Char) : asciiReverse (asciiReverse s) = s := by
  induction s with
  | nil => rfl
  | cons c cs ih => simp [asciiReverse, asciiReverse_append, ih, asciiReverse]

/-- A length is a count, and a reversed string is not a word at all — so what a
`UInt64 → UInt64` machine function can be compared against is the LENGTH, and
its word reading is the identity on it.  Stating that here is what stops the
annotation from promising a comparison the machine's own domain cannot carry. -/
def asciiLength64 (w : UInt64) : UInt64 := w

/-! ## Population count -/

/-- The number of set bits of `n`, by the standard two-step recursion. -/
def popcount : Nat → Nat
  | 0 => 0
  | 1 => 1
  | n + 2 => popcount ((n + 2) / 2) + popcount ((n + 2) % 2)

@[simp] theorem popcount_zero : popcount 0 = 0 := by simp [popcount]
@[simp] theorem popcount_one : popcount 1 = 1 := by simp [popcount]
@[simp] theorem popcount_two : popcount 2 = 1 := by simp [popcount]
@[simp] theorem popcount_three : popcount 3 = 2 := by simp [popcount]

/-- Its word reading.  A popcount of a 64-bit value is at most 64, so this
never truncates and needs no range. -/
def popcount64 (w : UInt64) : UInt64 := UInt64.ofNat (popcount w.toNat)

end Specs