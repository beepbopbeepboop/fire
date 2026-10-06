# The contract ladder cannot do arithmetic on `UInt64`, because `UInt64` is a
# `Fin` and `omega` has none for it

**Status: `bounds_index` is FIXED and the diagnosis is CORRECTED — the §4 lemma
it prescribed is FALSE and the real cause is two defects, neither of which is
the one this file named. `mini`, `clamped` and `abspos` are still UNREACHED, and
the reason is now MEASURED rather than guessed: they need the sign-flip XOR
evaluated, which is a library proof this tree has no lemma for. §"What landed"
and §"The next step, precisely" are the current text; everything above them is
kept because it is what the reader has to check the new text against.**

**Not fixed: three of the four rows. Fixed: `bounds_index.mojo` (exit 1 → exit
0), plus the ladder defect that this file's own §1 measurement could not have
found because the measurement was taken with it in place.**

## What landed, and the two defects behind it

### Defect 1: the emitted `first | … | …` was not a ladder at all

`formal/contracts.py::_ladder_script` emitted

```lean
first
  | (simp_all [h0, hpre0, m_go, sKey, u64_lt_iff_false_of_le, u64_le_iff_false_of_lt])
  | omega
  | decide
```

and **Lean's `first | t1 | t2 | …` is `t1 <|> t2 <|> …`: it takes the first
alternative that does not THROW, and a tactic that leaves the goal open does not
throw.** `simp_all` on a goal it cannot fully close is exactly such a tactic —
it simplifies what it can and returns. So `omega` and `decide` were
**unreachable for every goal `simp_all` did not close by itself**, while
`Verdict.why` named all three as the rungs that ran. This file's own comment —
*"`first` takes the first rung that CLOSES the goal"* — described a script that
did not do that, and `LADDER` named rungs that never ran.

Every rung's spelling now ends in `<;> done`, which is what makes an alternative
that left the goal open **throw**, so that `first` moves on to the next rung.
Pinned by `test_formal_contracts.py`'s
`test_every_ladder_rung_is_a_first_alternative_that_can_FALL_THROUGH`, which
asserts the property against `_LADDER_SPELLINGS` rather than against
hand-written strings, so a new rung cannot quietly reintroduce it.

**This defect is invisible to every measurement in §1, and that is why §1's
diagnosis was wrong.** Every row there was measured *with the defect in place*,
so "exit 1" could not distinguish "the tactic ladder cannot reach this" from
"`omega` and `decide` never ran".

### Defect 2: `omega` cannot see a `UInt64` comparison at all

`UInt64`'s order is `BitVec 64`'s, which is `Nat`'s behind **two** structures,
and `omega` does linear arithmetic over `Nat`/`Int` and nothing else. `decide`
cannot decide a symbolic one. Every goal this module states is made of
`UInt64` comparisons, because the signed reading of a source comparison is
spelled `x ^^^ 0x8000000000000000`.

The library had the two bridges that conclude **`False`**
(`u64_lt_iff_false_of_le`, `u64_le_iff_false_of_lt` — "discharge a comparison
the hypothesis has already ruled out") and **nothing that goes the other way**,
which is why `bounds_index`'s `sKey i ≤ sKey n` from `sKey i < sKey n` was
unreachable no matter what tactic ran. Added, beside them in
`lib/ProofLib.lean`:

```lean
theorem u64_lt_iff_toNat_lt (a b : UInt64) : a < b ↔ a.toNat < b.toNat
theorem u64_le_iff_toNat_le (a b : UInt64) : a ≤ b ↔ a.toNat ≤ b.toNat
```

and a new `u64_order` rung in `LADDER` that opens the order into `Nat`'s and
hands the goal to `omega`. That is the whole fix for `bounds_index`, and it is
**not a bigger tactic**: the ladder already ran `omega`; `omega` just could not
see the goal.

### What §4 prescribed is FALSE, and it is worth knowing why

§4's next step was

```lean
theorem sKey_lt_iff (a b : UInt64) : sKey a < sKey b ↔ a < b
```

**This is a false statement.** `sKey` is `x ^^^ 0x8000000000000000`, and xor is
not order-preserving: `1 < 10` but `sKey 1 = 2^63 + 1 > 2^63 + 10 = sKey 10`.
More carefully, `sKey a < sKey b ↔ u64_toS64 a < u64_toS64 b` — it is the
**signed** order, which is the whole point of `sKey`, and `sKey a ≤ sKey b ↔
u64_toS64 a ≤ u64_toS64 b` is false for the same reason. §3's "the clause is
stated over the SIGN-FLIPPED words … which is what makes a comparison signed"
is right; §4 then asked for a lemma that would make the flip disappear.

Nobody following §4 would have got a compile error — `simp [sKey]` fails
*silently*, leaving the `^^^`-shaped goal, and a lemma stated over a false
statement is a `sorry` this file would have spent a day learning was a `sorry`.

**`bounds_index` never needed a bit of that.** Its goal is
`sKey i ≤ sKey n` from `sKey i < sKey n` — one COMPARISON from another, at the
same two terms, with **no arithmetic at all**. It is `≤` from `<`, and the only
thing standing in the way was that no tactic in the ladder could see the
comparison.

## The measurement, before and after

Same six examples, same REAL model (`formal/arm64_proof_gen.py::_gen_go`) and
same REAL emitted theorem (`formal/contracts.py::contract_theorems`), through
`formal/lean.py::run_lean`:

| example | contract | before | after |
|---|---|---|---|
| `mini2.mojo` | `@requires(a <= b) @ensures(result <= b)` | exit 0 | **exit 0** |
| `bounds_index.mojo` | `@requires(i >= 0) @requires(i < n) @ensures(result <= n)` | exit 1 | **exit 0** |
| `wrong_clampv.mojo` | three clauses, one false | exit 1, names the theorem | **exit 1, names the theorem** |
| `mini.mojo` | `@ensures(result <= max(n, 3))` | exit 1 | exit 1 |
| `clamped.mojo` | three postconditions over a two-way selection | exit 1 | exit 1 |
| `abspos.mojo` | `@ensures(result == abs(n))` | exit 1 | exit 1 |

`wrong_clampv` is the anti-rot for the whole change: a ladder that got stronger
must still refuse a **false** contract, and it does. `bounds_index.mojo` is now
in `test_formal_contracts.py --lean`'s closing list, which is what stops the
`u64_order` rung from being unmeasured by anything.

`mini2` is unchanged byte for byte, which matters: it is the case that was
already reached, so a rung added to the ladder cannot have moved it.

## Why `mini`, `clamped` and `abspos` are still UNREACHED — measured

§3 said these "become ground after splitting over the model's own branches".
**That is not what is happening, and the reduced goals say so.** After the
`by_cases` split every one of their goals is a **comparison between `sKey`
words**, not a ground fact:

```
case pos                                            -- mini.mojo
n : UInt64
hpre0 : 9223372036854775808 ≤ n ^^^ 9223372036854775808
h0    : n ^^^ 9223372036854775808 < 3 ^^^ 9223372036854775808
⊢ n ^^^ 9223372036854775808 ≤
    (if 3 ^^^ 9223372036854775808 < n ^^^ 9223372036854775808 then n else 3)
      ^^^ 9223372036854775808
```

Three separate obstructions, each measured:

1. **The clause's own builtin renders as a SELECTION over the flipped words.**
   `max(n, 3)` is emitted as `if sKey n > sKey 3 then n else 3`, and that `ite`
   sits inside the `^^^`. Resolving it needs `sKey n > sKey 3` or its negation,
   and from `sKey 3 ≤ sKey n` (§3's `h0` in the other branch) one gets `≥`, not
   `>`. So the `ite` cannot be resolved by any order fact in the context.
2. **`omega` cannot evaluate `^^^`.** It reports so: *"No usable constraints
   found … which may also involve … modular remainder"*. The two terms of the
   comparison are opaque atoms.
3. **Lean 4.32.2's core has no `xor` order lemma.** Measured: `Nat` ships
   `xor_lt_two_pow`, `xor_div_two_pow`, `xor_mod_two_pow`,
   `shiftLeft_xor_distrib` and nothing that compares two xors;
   `Nat.xor_lt_iff`, `BitVec.xor_lt_iff`, `Nat.xor_succ_succ` and
   `xor_two_pow_add` do not exist. `grind` gets most of a `Nat.xor_one_bit`
   proof and fails on the residual `x - 2^k` case.

## The next step, precisely

**One lemma, and it is a library proof.** It belongs in `lib/ProofLib.lean`
beside `u64_lt_iff_toNat_lt`, and `nat_xor_one_bit` is the statement:

```lean
/-- XOR with a single bit `2^k` adds that bit when it is clear and removes it
    when it is set -- the fact `sKey` is built on, and the only bit-level fact
    these three goals need. -/
theorem nat_xor_one_bit {x k : Nat} :
    x ^^^ 2 ^ k = if x.testBit k then x - 2 ^ k else x + 2 ^ k
```

and the 64-bit specialisation the ladder actually wants:

```lean
theorem sKey_xor_top {x : Nat} (h : x < 2 ^ 64) :
    x ^^^ 9223372036854775808 =
      if x < 9223372036854775808 then x + 9223372036854775808
      else x - 9223372036854775808
```

Proved from `Nat.eq_of_testBit_eq` + `Nat.testBit_two_pow_add_eq` /
`Nat.testBit_two_pow_add_gt` / `Nat.testBit_lt_two_pow` (all in
`Init/Data/Nat/Bitwise/Lemmas.lean`); the arithmetic after the rewrite is
`omega`'s, and the `0 < n` / `n < 0` case splits the goals need come from
`by_cases`, not from new tactics.

Then, in `formal/contracts.py`, the `u64_order` rung gains one more step and the
`by_cases` prelude gains a split per selection the clause introduced:

1. `nat_xor_one_bit` + `sKey_xor_top` into `lib/ProofLib.lean`.
2. `u64_order`'s spelling becomes
   `simp_all […] <;> simp_all only [u64_lt_iff_toNat_lt, u64_le_iff_toNat_le,
   sKey_xor_top] <;> omega`, with the `toNat_lt` bounds
   (`have := UInt64.toNat_lt _`) introduced for every term the goal names —
   `sKey_xor_top` needs them and `omega` cannot supply them.
3. `mini`/`clamped`/`abspos` re-measured. The honest expectation is that
   `abspos` closes (its goal is `0 - n = n` from `0 ≤ n ∧ n ≤ 0`, so `n = 0` and
   it is `rfl`) and that `clamped` (three postconditions over a two-way
   selection on two parameters, so `2^2 · 3` branches) needs the split as well.
   **Measure it; do not assume it.**

**Until then the verdict is UNKNOWN and says so**, with `Verdict.ok` False and
the skipped-input count attached. That is the load-bearing half of this
document: the ladder's reach grew from "the goal becomes ground after splitting
over the model's own branches" to "the goal is a comparison between sign-flipped
words, and a sign flip is add-or-subtract 2^63" — which is a bigger reach, not
a proof of everything, and the requirement it must meet is not "proves
everything" but "never reports a reach as a pass".

## What is NOT the cause, so nobody re-derives it

* **Not §2.** The `intro hpre` / `obtain ⟨hpre0, hpre1⟩` fix from 2026-10-05 is
  in and is correct; both hypotheses are in context in every goal above.
* **Not the ladder's shape.** §3's "`bounds_index`'s body has no branch, so
  there is nothing to split on" was an observation about `bounds_index` that
  generalised wrongly: `mini`'s body *does* branch, `mini2`'s does, and only
  `mini2` was reached. The thing the three share is not the absence of a branch
  — it is that their goal compares `sKey` words.
* **Not a missing transitivity lemma.** `sKey a ≤ sKey b` from `sKey a < sKey b`
  needs no lemma about `sKey`: `u64_le_iff_toNat_le` + `omega` is the whole of
  it, which is what closed `bounds_index`.

## ── everything below is the 2026-10-05 diagnosis, kept for the reader to
## check the section above against.  §4's lemma is FALSE (see above); §1's
## numbers were measured with defect 1 in place; §3's "the goal becomes ground"
## does not generalise. ──

## 1. What I ran and what I saw

`test_formal_contracts.py --lean` writes, for each example, a file holding the
REAL `formal/arm64_proof_gen.py::_gen_go` model and the REAL
`formal/contracts.py::contract_theorems` output, and runs
`formal/lean.py::run_lean` on it.  Measured 2026-10-05:

| example | contract | Lean |
|---|---|---|
| `mini2.mojo` | `@requires(a <= b) @ensures(result <= b)` | **exit 0** |
| `wrong_clampv.mojo` | three clauses, one false | exit 1, and it names the theorem |
| `mini.mojo` | `@ensures(result <= max(n, 3))` | exit 1 — UNREACHED |
| `clamped.mojo` | `@ensures(result >= lo)`, `(<= hi)`, `(== clamp(...))` | exit 1 — UNREACHED |
| `abspos.mojo` | `@ensures(result == abs(n))` | exit 1 — UNREACHED |
| `bounds_index.mojo` | `@requires(i >= 0) @requires(i < n) @ensures(result <= n)` | exit 1 — UNREACHED |

The smallest failure, `bounds_index.mojo`, is the whole of it:

```
error: unsolved goals
i n : UInt64
hpre0 : 9223372036854775808 ≤ i ^^^ 9223372036854775808
hpre1 : i ^^^ 9223372036854775808 < n ^^^ 9223372036854775808
⊢ i ^^^ 9223372036854775808 ≤ n ^^^ 9223372036854775808
```

Both hypotheses ARE in context — that was the first bug, §2 — and the goal
still does not close.

## 2. The first bug, which was in the EMITTER and is fixed

The theorem did not `intro` its preconditions.  The emitted proof was

```lean
  simp +decide [at_offset_go, sKey] <;> omega
```

on a goal `pre → post`, so the assumptions were never in context, `decide` had
nothing to decide, and `omega` was handed an unconstrained `Fin` goal.  It is
now

```lean
  intro hpre0
  · first
    | (simp_all [hpre0, at_offset_go, sKey, ...])
    | omega
    | decide
```

which is what `mini2` closes with.  Recorded here rather than only in the commit
because the residual failure looks IDENTICAL to the fixed one from the outside
— both are "exit 1" — and a reader who does not know §2 was fixed will
re-diagnose it.

## 3. Why the residual failure is a LIMIT and not a bug

`Lean.UInt64` is `Fin (2^64)`, and the clause is stated over the SIGN-FLIPPED
words — `(i ^^^ 0x8000000000000000) ≤ (n ^^^ 0x8000000000000000)`, which is what
makes a comparison signed and therefore what CPython means for an `Int`:
`(n if n > 3 else 0) * 3` at `n = 2^63` answers 0, the signed reading. **The
document that recorded that measurement,
`FORMAL_contract_work_handoff.md`, was folded into
`FORMAL_a_conditional_value_in_a_dylib_export.md` on 2026-10-05 and is gone**;
the measurement stands here, and `FORMAL_a_conditions_operand_read_through_an_
earlier_stores_slot.md` is the live document that carries the same sign-flip
reading for the same reason.

Closing `bounds_index` needs transitivity of `<` from `i < n`, through a
sign-flip involution, into `≤` on `Fin`.  Every rung fails for its own reason:

* `simp_all` cannot, because `^^^` on `Fin` is not a simp-normal form and the
  goal has two distinct variables with one relation between them;
* `omega` cannot, and says so — *"No usable constraints found … which may also
  involve … modular remainder"* — because it has no arithmetic over `Fin`;
* `decide` cannot, because `i` and `n` are variables.

`mini2` closes for the opposite reason: its case split `by_cases (a < b)` makes
every branch a **ground** fact, and ground facts on `Fin` are decidable.  So the
ladder's reach is exactly *"the contract's goal becomes ground after splitting
over the model's own branches"*, and `bounds_index`'s does not, because its
body has no branch at all — there is nothing to split on.

`abspos` is the interesting boundary case: its body DOES branch, and its goal
does not become ground, because `abs` in the CLAUSE is a selection the ladder
renders and the simplifier has to evaluate at a symbolic `n`.

## 4. The next step, precisely

The fix is a **lemma**, not a bigger tactic, and it belongs in `lib/work.lean`
next to the other `UInt64` helper facts (`u64_lt_iff_false_of_le`,
`u64_le_iff_false_of_lt`, `work_cset_lt_false_iff`, all of which already exist
for exactly this reason):

```lean
/-- The sign flip is an involution, so a signed order on the flipped words is
    the same order as on the originals. -/
theorem sKey_lt_iff (a b : UInt64) :
    sKey a < sKey b ↔ a < b
```

and a transitivity rung over it.  With `sKey` a `def` that `simp only [sKey]`
unfolds, `simp only [sKey] at *` turns every hypothesis and the goal back into
comparisons on `UInt64` proper, and the existing `u64_*_iff` lemmas then apply.
That is a `simp` set change, not a new tactic, and it is the cheapest thing to
try first:

1. add `sKey_lt_iff` / `sKey_le_iff` to `lib/work.lean`;
2. add them to the ladder's `simp_all` set in
   `formal/contracts.py::contract_theorems`;
3. re-run `python3 test_formal_contracts.py --lean` and see how many of the four
   rows above flip from exit 1 to exit 0.

The honest expectation is that this closes `bounds_index` and `abspos` and
leaves `clamped` (three postconditions over a two-way selection on two
parameters, so `2^2 · 3` branches) for a later pass.  Measure it; do not assume
it.

**Until then the verdict is UNKNOWN and says so**, with `Verdict.ok` False and
the skipped-input count attached.  That is the load-bearing half of this
document: the ladder's reach is small, and the requirement it must meet is not
"proves everything" but "never reports a reach as a pass".