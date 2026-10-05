# The contract ladder cannot do arithmetic on `UInt64`, because `UInt64` is a
# `Fin` and `omega` has none for it

**Status: the limit is MEASURED, named per example, and reported UNKNOWN. Not
fixed. The next step is §4.**

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
makes a comparison signed and therefore what CPython means for an `Int`
(`bugs/FORMAL_contract_work_handoff.md` §3 records the measurement: `(n if
n > 3 else 0) * 3` at `n = 2^63` answers 0, the signed reading).

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