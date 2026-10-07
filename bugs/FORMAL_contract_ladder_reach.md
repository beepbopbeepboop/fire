# The contract ladder cannot do arithmetic on `UInt64`, and its conjunction was
# split against the wrong nesting

**Status 2026-10-05 (`work/formal40-4`): the SUBJECT is FIXED — `bounds_index`,
the "smallest failure, the whole of it", closes in Lean, and it closes because
the ladder now does arithmetic on `UInt64`.** `formal/contracts.py` carries
`_ORDER_BRIDGE` (`UInt64.lt_iff_toNat_lt`, `UInt64.le_iff_toNat_le`,
`Nat.le_of_lt`) in the `simp_all` rung's set, and `bounds_index.mojo` and
`clamped.mojo` both moved from exit 1 to exit 0 in `formal/contracts/*.mojo`'s
census. Two defects, both real and both measured — the `UInt64` arithmetic and
the conjunction split. `work/formal52-docs` reached the same `Fin`-to-`Nat`
bridge by a second route (a leading `simp_all_toNat` rung); the merged ladder
carries both, and since `first` restores the goal when a rung fails, reach is
monotonic in those rungs.

**Status 2026-10-05 (`work/formal52-docs`): the same `Fin`-versus-`Nat` half is
FIXED (`f21e44cf`), and the ladder is
no longer limited to ground goals. Of the four rows §3 lists as UNREACHED, TWO
now close — `bounds_index` AND `clamped`, which the `work/formal40-4` status
above already recorded — and the other two, `mini` and `abspos`, fail on a
MISSING LIBRARY LEMMA that is named in §6. (This line said "one of the four …
the other three" until 2026-10-07; the "three" was stale, and §1's table and §6
below are corrected to the measured state, re-run on this tree through the real
generator and `formal/lean.py::run_lean`. §4's prescribed fix is REFUTED and is
not what landed — read §5 before implementing anything from it.)**

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

**`bounds_index.mojo` now CLOSES (`f21e44cf`), and this is the whole of the
table's movement:**

| example | contract | Lean, before | Lean, after `f21e44cf` |
|---|---|---|---|
| `mini2.mojo` | `@requires(a <= b) @ensures(result <= b)` | **exit 0** | **exit 0** |
| `wrong_clampv.mojo` | three clauses, one false | exit 1, names the theorem | exit 1, names the theorem |
| `bounds_index.mojo` | `@requires(i >= 0) @requires(i < n) @ensures(result <= n)` | exit 1 — UNREACHED | **exit 0** |
| `clamped.mojo` | `@ensures(result >= lo)`, `(<= hi)`, `(== clamp(...))` | exit 1 — UNREACHED | **exit 0** — re-measured 2026-10-07; the conjunction split plus the order bridge close it, and `test_formal_contracts.py --lean` pins it |
| `mini.mojo` | `@ensures(result <= max(n, 3))` | exit 1 — UNREACHED | exit 1 — a MISSING xor-cancellation lemma, §6 |
| `abspos.mojo` | `@ensures(result == abs(n))` | exit 1 — UNREACHED | exit 1 — the same MISSING xor-cancellation lemma, §6 |

**exit 0: 1/6 → 3/6**, measured the way §1 describes (the REAL `_gen_go` model
and the REAL `contract_theorems` theorem, through `formal/lean.py::run_lean`) and
pinned by `test_formal_contracts.py --lean`, whose case list names `mini2`,
`bounds_index`, `clamped` as closing and `mini`, `abspos`, `wrong_clampv` as not
closing — so a rung that reached either of the last two turns that test red
rather than silently widening the claim.

`wrong_clampv` staying at exit 1 is the load-bearing half of that number: the
new rung reasons about the goal and CANNOT close a false one. That was also
checked on its own, outside the corpus — the same rung against a
`result >= n` goal with an `i < n` hypothesis fails, which is the property that
makes the rung a rung and not an `assume`-shaped hole.

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
ladder's reach was exactly *"the contract's goal becomes ground after splitting
over the model's own branches"*, and `bounds_index`'s did not, because its
body has no branch at all — there was nothing to split on.

`abspos` is the interesting boundary case: its body DOES branch, and its goal
does not become ground, because `abs` in the CLAUSE is a selection the ladder
renders and the simplifier has to evaluate at a symbolic `n`.

**§3's diagnosis of the three rungs is CORRECT and is what `f21e44cf` acted on.**
Each rung fails for the reason stated. What was wrong was §4's conclusion about
what to do about it — the next section.

## 4. The prescribed fix is REFUTED — `sKey_lt_iff` is false

§4 (as originally written) prescribed a lemma:

```lean
/-- The sign flip is an involution, so a signed order on the flipped words is
    the same order as on the originals. -/
theorem sKey_lt_iff (a b : UInt64) :
    sKey a < sKey b ↔ a < b
```

**That lemma is false, and it is false in the direction the prescription used it
in.** `sKey x` is `x ^^^ 0x8000000000000000` — it flips the TOP BIT — so
`sKey a < sKey b` (read on the `Fin`/unsigned order, which is the only order
`Fin` has) is the **SIGNED** reading of `a < b`, not the unsigned one. The
prescription wanted to turn a signed hypothesis into an unsigned goal; the lemma
would have turned one signed reading into *another* signed reading.

Measured, on the pinned toolchain, in one line:

```lean
example : sKey 0 < sKey 0xffffffffffffffff ↔ 0 < 0xffffffffffffffff := by
  decide +kernel
-- Tactic `decide` proved that the proposition is false
```

At `a = 0`, `b = 2^64 - 1`: flipping the top bit makes `sKey a = 2^63` the
LARGER of the pair, so `sKey a < sKey b` is **False**, while `a < b` is **True**.
So `sKey_lt_iff` is not merely unnecessary — landing it would have put a FALSE
theorem in `lib/work.lean`, behind a `[simp]` attribute, where it would rewrite
comparisons in every proof in the tree.

The doc's *reasoning* about the failure is right and §3 above is the record of
it; only this conclusion was wrong, and it is wrong because the doc treated
`sKey` as order-preserving when it is order-REVERSING. **The three hunks in §4's
code block were written and measured and were correctly not committed**; the
error was in the lemma's statement, which nothing had checked.

## 5. What landed instead (`f21e44cf`), and why it is not a bigger tactic

The goal `bounds_index` wants is transitivity of `<` into `≤` over `UInt64`:

```
hpre1 : i ^^^ 0x8000000000000000 < n ^^^ 0x8000000000000000
⊢     i ^^^ 0x8000000000000000 ≤ n ^^^ 0x8000000000000000
```

and it needs no sign-flip lemma at all, because **`Lean.UInt64`'s order already
IS `Nat`'s** — `Fin n`'s `LT`/`LE` go through `.val`. What was missing was the
library's own two bridges from that order to `Nat`'s,
`UInt64.lt_iff_toNat_lt` and `UInt64.le_iff_toNat_le`, which
`lib/ProofLib.lean` already uses throughout (`u64_sub_one_toNat_le`,
`mem_read_*`'s bound proofs, and so on). Adding them to the ladder's simp set
turns the hypothesis and the goal into `Nat` inequalities, which is the
arithmetic `omega` has, and `Nat.le_of_lt` — core, not a new lemma — is the
transitivity fact the goal asks for.

So the fix is **a rung whose simp set carries those two bridges, with `omega` in
the SAME rung**:

```python
("simp_all_toNat", "simp_all [{lemmas}, {extra}] <;> omega")
```

The `<;>` is load-bearing and was measured, not guessed: a rung that makes
progress without closing the goal does not hand its rewrites to the next rung
(`first` restores the goal), so the rewrite and the arithmetic it enables have
to be one rung. **For the same reason this rung LEADS the ladder** — with the
bare `simp_all` rung first, `simp_all_toNat` never gets to run and the corpus
is back to 1 of 6. Both orders were measured.

Two things changed shape to carry it, and both are in `f21e44cf`:

* `LADDER` is a tuple of `(NAME, SPELLING)` pairs, because a rung is a tactic
  SEQUENCE and only its first tactic is a name. `Verdict.why` prints the NAME
  (`simp_all_toNat → simp_all → omega → decide`) and `_ladder_script` emits the
  SPELLING.
* `test_formal_contracts.py`'s ladder row now asserts on the **spelling**
  rather than the name, which is strictly stronger: a name can be present in a
  script that runs a *different* tactic under it, which is the exact drift that
  row was written for.

## 6. What is still open, and it is a DIFFERENT limit

`mini` and `abspos` are still exit 1, still honestly reported
UNKNOWN with `Verdict.ok` False. (`clamped` was in this sentence until
2026-10-07; it closes, and it closes because the conjunction split and the order
bridge both landed — see §1. This section is about the two that remain.)
**They no longer fail for §3's reason.** The `Fin`-versus-`Nat` gap is closed
for both; what is left is a missing library lemma, and it is small and specific.

`mini.mojo`'s emitted goal, after the split, is:

```
h0 : n ^^^ 0x8000000000000000 < 3 ^^^ 0x8000000000000000
⊢ n ^^^ 0x8000000000000000 ≤ (if 3 ^^^ … < n ^^^ … then n else 3) ^^^ …
```

The hypothesis is `n < 3` and the goal's own test is `n > 3` — the same fact
**in the other direction**, which is why the `if` cannot be decided and the
goal never becomes a `Nat` inequality for `omega` to use. `abspos`'s is the same
shape over an **equality**: its `case neg` ends at

```
h0 : n.toNat ^^^ 0x8000000000000000 ≤ 0x8000000000000000
⊢ -n = n
```

where the hypotheses force `n.toNat ^^^ 2^63 = 2^63`, i.e. `n = 0` (or `n = 2^63`
on the other branch), and the goal is a `UInt64` equality the ladder's bridges
do not touch.

**Re-measured on this tree (2026-10-07), and the shape of the gap is now
pinned rather than described.** The ladder already carries every order fact §3
named — `u64_lt_iff_false_of_le`, `u64_le_iff_false_of_lt`, and the two
`UInt64.*_iff_toNat_*` bridges plus `Nat.le_of_lt` — and `mini`/`abspos` still do
not close, which says the missing thing is **not** another order direction. Three
facts, each checked with `#check` against the real `ProofLib`:

* `UInt64.toNat_inj : a.toNat = b.toNat ↔ a = b` **EXISTS**, so an equality
  *can* be turned into a `Nat` equality. But as a simp lemma it is oriented the
  wrong way (it rewrites `a.toNat = b.toNat` *to* `a = b`), so the ladder's
  `simp_all` never uses it, and `abspos`'s goal is never put in `toNat` form.
* `UInt64.toNat_xor : (a ^^^ b).toNat = a.toNat ^^^ b.toNat` exists, but
  **there is no cancellation lemma for `Nat.xor`** — `Nat.xor_eq_zero`,
  `Nat.xor_right_eq_zero`, `Nat.xor_right_inj` are all absent (measured). So even
  with the goal in `toNat` form, `n.toNat ^^^ 2^63 = 2^63` does not yield
  `n.toNat = 0` for `omega`, and that step is the whole of both goals: it is the
  fact that flipping the top bit twice is the identity, stated as a cancellation
  rather than as an involution.
* `UInt64.ge_iff_toNat_ge` and `UInt64.eq_iff_toNat_eq` are still absent, but
  `UInt64.toNat_inj` is the equality bridge they would have been.

So the honest next step is **one library fact**, and it is the xor cancellation
above (equivalently a `sKey`-involution lemma, which is what §4 prescribed for a
different reason and got wrong in the *statement*), plus a ladder rung that
applies it to an equality — the bridges the ladder has are all about `<`/`≤`, and
`abspos`'s goal is neither. `mini` needs the same fact on the branch where the
`if`'s two directions must be reconciled.

**All of that is a `lib/ProofLib.lean` change plus a rebuild, so it is not this
worker's to land.** The blocker is memory alone and it is now measured here
rather than cited: **9.8 GB** — a `ProofLib.olean` build run exactly as `formal/lean.py::ensure_library` runs it, on this tree, measured 2026-10-05 — over a bounded worker's 8 GB ceiling and under the tree's own `LIBRARY_MEMORY_MB = 12288`. Memory alone, and the library is NOT broken.

**And the measurement has a trap in it that will cost the next session the same
hour it cost this one.** `formal/lean.py::run_lean`'s `heartbeats` argument
becomes a **`-T <n>` flag**, and `heartbeats=0` — which reads as "no limit" —
sets `maxHeartbeats 0`. A `ProofLib` build under `-T 0` does not report a bound:
it reports a cascade of

```
error: Tactic `bv_decide` failed. Error: failed to compile definition,
compiler IR check failed at `work_step_add_imm32._native.bv_decide…`.
Error: unknown join point 'block_0'
```

at a **7.1 GB** peak, identically at an 8 GB ceiling and at a 20 GB one, which
reads exactly like a library that cannot build on this toolchain. **It builds**:
the same command without the flag exits 0 at 9.8 GB.
`tools/formal_model_fuzz.py` passes `heartbeats=0` on purpose (its `#eval`s want
no bound), so any script copied from it inherits the flag and the illusion.

**The verdict stays UNKNOWN for all three and says so.** That is still the
load-bearing half of this document, and it is now a weaker requirement than it
was: the ladder's reach is no longer "ground goals only", but the requirement
it must meet was never "proves everything" — it is "never reports a reach as a
pass", and `wrong_clampv` still refusing is what holds that line.