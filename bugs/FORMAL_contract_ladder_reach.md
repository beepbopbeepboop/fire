# The contract ladder cannot do arithmetic on `UInt64`, and its conjunction was
# split against the wrong nesting

**Status 2026-10-05 (`work/formal40-4`): the SUBJECT is FIXED — `bounds_index`,
the "smallest failure, the whole of it", closes in Lean, and it closes because
the ladder now does arithmetic on `UInt64`.** `formal/contracts.py` carries
`_ORDER_BRIDGE` (`UInt64.lt_iff_toNat_lt`, `UInt64.le_iff_toNat_le`,
`Nat.le_of_lt`) in the `simp_all` rung's set, and `bounds_index.mojo` and
`clamped.mojo` both moved from exit 1 to exit 0 in `formal/contracts/*.mojo`'s
census. Two defects, both real and both measured:

| | was | is |
|---|---|---|
| the ladder's arithmetic over `UInt64` | `omega` reports "No usable constraints found … which may also involve … modular remainder" with **both** preconditions already in context | the three bridge names turn the sign-flipped words into `Nat` and `Nat.le_of_lt` closes `<` into `≤` |
| a contract with **more than one** postcondition | emitted `intro … · ladder constructor · ladder …`, and Lean answers "No goals to be solved" — the exit status of an unproved theorem, for a theorem the ladder had proved | a `constructor` before every bullet but the last, which is the shape that matches `_lean_of`'s right-nested conjunction |

**`mini.mojo` and `abspos.mojo` are still UNREACHED, for reasons that have
nothing to do with either** — §3 gives each one its own measured cause and §4
the exact next step for each. So this document stays, and what it now records
is a **reach** measurement rather than a bug: the ladder closes 4 of the 6
contract examples and refuses 2 of them honestly.

**What is NOT claimed.** `wrong_clampv.mojo` — the negative control — still
exits 1, and still has both of its postconditions named, which is the
anti-rot: a ladder that got stronger at proving must not get stronger at
refusing nothing. And no swept file moves: contracts are not in the sweep's
scope, and the corpus of `formal/contracts/*.mojo` is eight files.

---

## 1. What I ran, and what I saw

The census is one Lean file per example holding the REAL
`formal/arm64_proof_gen.py::_gen_go` model and the REAL
`formal/contracts.py::contract_theorems` output, run through
`formal/lean.py::run_lean` — the same two halves
`test_formal_contracts.py::_lean_file` writes, over **every** example rather
than the two the `--lean` row checks.

| example | contract | Lean, before | Lean, now |
|---|---|---|---|
| `mini2.mojo` | `@requires(a <= b) @ensures(result <= b)` | **exit 0** | **exit 0** |
| `wrong_clampv.mojo` | three clauses, one false | exit 1, and it names the theorem | exit 1, and it names **both** postconditions |
| `bounds_index.mojo` | `@requires(i >= 0) @requires(i < n) @ensures(result <= n)` | exit 1 — UNREACHED | **exit 0** |
| `clamped.mojo` | `@ensures(result >= lo)`, `(<= hi)`, `(== clamp(…))` | exit 1 — UNREACHED | **exit 0** |
| `mini.mojo` | `@ensures(result <= max(n, 3))`, `(>= min(n, 3))` | exit 1 — UNREACHED | exit 1 — UNREACHED |
| `abspos.mojo` | `@ensures(result == abs(n))` | exit 1 — UNREACHED | exit 1 — UNREACHED |

**1.1 The smallest failure, which was the whole of the old document.**

    error: unsolved goals
    i n : UInt64
    hpre0 : 9223372036854775808 ≤ i ^^^ 9223372036854775808
    hpre1 : i ^^^ 9223372036854775808 < n ^^^ 9223372036854775808
    ⊢ i ^^^ 9223372036854775808 ≤ n ^^^ 9223372036854775808

Both hypotheses ARE in context — that was the first bug, §2 — and the goal still
did not close. It closes now, and the three names are the whole of it:

```lean
-- the goal, after the bridge rewrites hypothesis and goal alike
hpre1 : i.toNat ^^^ 9223372036854775808 < n.toNat ^^^ 9223372036854775808
⊢     i.toNat ^^^ 9223372036854775808 ≤ n.toNat ^^^ 9223372036854775808
```

**1.2 The second defect, which the old document did not know existed.**

`clamped.mojo`'s exit 1 was NOT an unreached contract. Its only diagnostic was

```
error: No goals to be solved
```

which is what Lean says when a tactic is handed nothing. The cause was the
emission: with **no** `constructor` before the first bullet, the single
`· first | … | … | …` is handed the whole `P ∧ Q ∧ R`, `simp_all` discharges
all three conjuncts in one go, and the `constructor` + `· …` bullets after it
have no goal. Fixing that by adding a `constructor` before *every* bullet is
worse and fails differently — `_lean_of` renders the conjunction RIGHT-nested,
so the peel leaves `P ∧ Q ∧ (R ∧ S)` after two rounds and the third bullet is
handed `R ∧ S` instead of `R`. Measured on four postconditions:

```
constructor
· exact hP
constructor
· exact hQ
· exact hR      ← this is `R ∧ S`, so this is its own "No goals to be solved"
constructor
· exact hS
```

The shape that matches both is a `constructor` before every bullet but the LAST:
bullet `i` is handed `Pi`, and what the next `constructor` splits is
`Pi+1 ∧ … ∧ Pn-1`. For a single postcondition there is nothing to split, which
is why the rule is about the LAST bullet rather than the first.

**This is worth stating on its own**: a proof-generation bug that can only
present as *weakness*. Both spellings report a closed theorem as unproved, and
`classify` turns that into `UNKNOWN` — the verdict this whole module is built
so it can never confuse with a pass.

## 2. The first bug, which was in the EMITTER and was already fixed

Kept because the residual failure looked IDENTICAL to it from the outside —
both are "exit 1" — and a reader who does not know §2 was fixed will
re-diagnose it. The theorem did not `intro` its preconditions, so the
assumptions were never in context, `decide` had nothing to decide, and `omega`
was handed an unconstrained goal:

```lean
-- was:  simp +decide [at_offset_go, sKey] <;> omega
  intro hpre0
  · first
    | (simp_all [hpre0, at_offset_go, sKey, …])
    | omega
    | decide
```

## 3. The two rows that are still UNREACHED, each with its own measured cause

**The old document concluded that the residual failure "is a LIMIT and not a
bug", on the grounds that `mini2` closes only because its case split makes
every branch a ground fact while `bounds_index`'s does not.** `bounds_index`
now closes, so that characterisation is falsified: the ladder's reach is not
"the goal becomes ground", it is "the goal becomes arithmetic `omega` and the
simplifier can see". These two rows are still out, and neither is that.

**`mini.mojo` — the split is over the MODEL's conditions and the goal's `if`
is a different one.** `@ensures(result <= max(n, 3))` renders as
`(if 3 < n then n else 3)`, and the body is `if n < 3`. The ladder splits over
the body's own conditions (`model_conditions`), so on the branch `n < 3` it
holds `3 ≤ n` — which does not decide `3 < n` (both hold at `n = 3`), so `simp`
cannot reduce the selection:

```
hpre0 : 9223372036854775808 ≤ n.toNat ^^^ 9223372036854775808
h0 : 9223372036854775811 ≤ n.toNat ^^^ 9223372036854775808      -- 3 ≤ sKey n
⊢ 9223372036854775811 ≤ (if 9223372036854775811 < n.toNat ^^^ 9223372036854775808
                          then n else 3).toNat ^^^ 9223372036854775808
```

**`abspos.mojo` — the goal is an EQUALITY, and the bridge is an ORDER bridge.**
After the split the goal is `(0 : UInt64) - n = n` under `n ≤ 0`, and nothing in
the simp set touches a `UInt64` equality. The route is visible and it is not a
simp set: `Nat` has **no** order lemma about `^^^` at all in this toolchain
(`Nat.xor_le_iff`, `Nat.xor_le`, `Nat.le_xor`, `Nat.xor_lt`, `Nat.le_of_xor_le`
are all `Unknown constant` — measured, not assumed), so getting from
`n.toNat ^^^ 2^63 ≤ 2^63` to `n.toNat = 0` needs a **proved lemma**, and then
`UInt64.toNat_inj` / `UInt64.toNat_sub` / `UInt64.toNat_xor` plus arithmetic on a
literal `2^64 % 2^64`.

## 4. The next step, precisely

1. **`mini.mojo`: split over the CLAUSE's own selections, not only the model's.**
   `contract_theorems` already holds the clause IRs (`pres`/`posts`) before it
   builds `by_cases`; their `ITE`/`MAX`/`MIN` conditions are what the goal's
   `if`s test. Either read them off the IR the same way `model_conditions` reads
   the body's, or add a `split <;> simp_all [ … ]` rung — which is generic and
   needs no IR reading, and costs one rung of the ladder's spine plus an
   adjustment to `test_the_ladder_is_generated_from_the_list_it_reports`, whose
   `script.count(rung) == 1` assertion counts tactic NAMES and would see
   `simp_all` twice. Measure the goal-count growth before taking it: the split
   multiplies, and `clamped.mojo`'s third postcondition alone would go from 4
   branches to 8.
2. **`abspos.mojo`: one lemma in `lib/work.lean`, beside `work_cset_lt_false_iff`,
   and it is `lib/` work** —

   ```lean
   /-- `x ^^^ 2^63 ≤ 2^63` is `x = 0`: flipping the top bit up puts a word in
       the top half, so at most the boundary itself is still `≤`. -/
   theorem nat_xor_sign_bit_le_one (x : Nat) : x ^^^ 0x8000000000000000 ≤ 0x8000000000000000 → x = 0
   ```

   which is arithmetic over `Nat` with `Nat.xor_lt_two_pow` / a case split on
   `x < 2^63` vs `x ≥ 2^63`. **It cannot be landed by a worker that may not run
   Lean** (`bugs/PERF_memory_over_4gb_is_a_bug.md` and the eight disabled
   Lean-checking gate tests), so it is recorded rather than attempted.
3. **The doc's original prescription, and why it was not what fixed this.**
   §4 of the previous revision said to add `sKey_lt_iff` / `sKey_le_iff` to
   `lib/work.lean` and to the ladder's `simp_all` set. That is a proof about
   the sign flip being an involution — and the goal is ALREADY stated over
   flipped words (`hpre1` above), so the flip is not what is in the way, the
   ORDER is. Adding the lemma would also have meant editing `lib/work.lean`,
   whose `.olean` is the one module in the library whose build peaks at 7.82 GB
   (`formal/lean.py`'s own measured table) — above the 8 GB ceiling a light
   worker works under. The three names are in this module's own simp set, cost
   no library build, and work for any goal over `UInt64` rather than for the
   three shapes they were found on.

## 5. Verifying

```sh
export PATH=/opt/homebrew/bin:$PATH
python3 tools/memslot.py --gb 8 --label t -- python3 test_formal_contracts.py --lean
# 330 passed, 0 failed
```

The two rows that do not need Lean are the durable ones —
`test_a_multi_postcondition_contract_is_split_before_its_first_bullet` reads the
`constructor`/`· ` SEQUENCE off the emitted script for 1…5 postconditions (and
off `mini.mojo` and `clamped.mojo` themselves), and
`test_the_ladders_simp_set_carries_the_UInt64_order_bridge` reads the bridge out
of the emitted `simp_all [ … ]` rather than off the module attribute. Both were
verified by undoing each half of the fix in process: the first version of the
split row indexed every other line of a MULTI-line ladder block and therefore
passed with the fix undone, and the first version of every `check` call passed
the label where the boolean goes, so a `PASS False` row proved nothing. All
four are fixed and all four now fail as predicted when the fix is removed.