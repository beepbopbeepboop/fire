# `test_formal_call_proof_gen.py`'s remaining reds after merging the oct-7 formal branches

**Area:** FORMAL / proof generation — `formal/arm64_proof_gen.py` and
`lib/ProofLib.lean`'s `arm64_step` arms. **Status: OPEN — ONE of the rows below
(the `hprior` growth one) is FIXED 2026-10-13, and it was a MISCALIBRATED TEST,
not the `arm64_ext_imm12` term this doc first blamed. The `×2.2` bound it
checked was on the ratio of TOTAL fact counts, which for the current emission
(`3·2**k − 3`) is 2.33 at k=2 — above 2.2 while the memo is working perfectly.
The test now bounds the ratio of facts to SCOPES, which is exactly 1.5 per
scope at every depth with the memo and 2.5/3.6/4.9 without it. The five
Lean-dependent rows remain.** Filed by the `work/merge-formal8-oct7` merger. The
merge itself is complete; these are the failures the narrow
`test_formal_call_proof_gen.py` run still shows after every *mechanical* merge
artifact was fixed (undefined `_RLIMIT_STACK`, the `_flush_push_depth` epilogue
variant, a duplicated `for_target_tree`, a test whose `setUpClass` never
populated `cls.infos`, and so on — all fixed and committed on that branch).

## What was run

    python3 tools/memslot.py --gb 8 --label t -- \
        python3 test_formal_call_proof_gen.py

    FAILED (failures=10)

and, class by class, the ones this doc is about:

    python3 tools/memslot.py --gb 8 --label t -- \
        python3 test_formal_call_proof_gen.py TestExternCallTheRunDoesNotReach
    # 1 failure: test_the_corpus_example_that_was_false_is_proved

## What was seen

* `TestExternCallTheRunDoesNotReach.test_the_corpus_example_that_was_false_is_proved`
  — `formal/examples/mod_by_var.mojo`'s generated proof does not typecheck:

      mod_proof.lean:4899:68: error: maximum recursion depth has been reached

  The site is the application of the generated step lemma
  `mod_by_var_sr_87` (an `ADD sp, sp, #32, lsl #12`, whose RHS is
  `s.sp + UInt64.ofNat 131072`) inside the run proof. `maxRecDepth` is already
  `100000` in the generated file, so this is a looping/deep kernel reduction and
  not a low limit.
* `TestSameImageCallLean.test_the_followed_call_proves_with_no_admission` — the
  same `maximum recursion depth has been reached`, in
  `same_image_leaf_proof.lean`.
* `TestNestedConditionFactSharing.test_the_fact_count_grows_with_the_paths_and_not_with_the_branches`
  — 2 -> 3 conditions grew the `hprior_` facts by x2.33 (9 -> 21) where the test
  bounds it at x2.2 ("the per-path memo makes this x2"). **FIXED 2026-10-13
  (`work/formal374-docs`):** the `hprior_` count is emitted by
  `formal/arm64_proof_gen.py` with `check=False` and is therefore Lean-FREE —
  **no `lib/ProofLib.lean` change can move it**, so the `arm64_ext_imm12` cause
  below cannot be this row's. The count is exactly `3·2**k − 3` (9 / 21 / 45)
  because each branch LEVEL contributes `3·2**(j−1)` facts — a perfect geometric
  series with a first term — so the ratio of two TOTALS carries ~2.33 at the
  first step while the memo shares correctly. Measured directly: with the memo
  disabled, each scope proves every prior block and the facts per scope are
  2.5 / 3.6 / 4.9 (growing with depth); with it, **1.5 at every depth**. The test
  now bounds facts-per-scope at 2.0 (and still fails the pre-memo emission, at
  k=2), instead of the ratio of totals.
* `TestANarrowTypedParameterGetsItsRange.test_lean_accepts_the_three_examples`
  (`sgt8`) — a `rewrite` that no longer finds its pattern; the test's own
  message says `sgt8` "did not typecheck before this fix either", so this one is
  plausibly pre-existing.
* `TestTheZeroDivisorGuardAgainstLean` (4 rows) — the class's fixture generates
  no `q_compiles_correctly_universal`, which
  `bugs/FORMAL_the_div0_guard_measurement_class_traces_nothing_any_more.md`
  already records as the class's state on the base tree; treat those four as
  pre-existing.

## The most likely cause, and the next step

The TWO Lean-dependent new ones — `TestExternCallTheRunDoesNotReach` and
`TestSameImageCallLean` — appear after `lib/ProofLib.lean`'s ADD/SUB/CMP
immediate arms changed to read `arm64_ext_imm12` (the `sh`-field fix merged from
`work/formal108/125/131/149`). That change is correct — it is what makes
`ADD sp, sp, #32, lsl #12` compute `+131072` instead of `+32` — and it is why
the generated `mod_by_var_sr_87` states `+131072`. What it also does is put a
non-reducible `arm64_ext_imm12 w` term in `work_step_add_imm64`'s statement
(`lib/ProofLib.lean:5117`), so unifying the concrete generated step with that
lemma now reduces through `arm64_ext_imm12` and the elaborator loops instead of
closing.

**The `hprior` row was NOT this.** It is a Lean-free count of `have hprior_`
lines in a generated file, so no `arm64_ext_imm12` term can reach it, and it was
fixed on 2026-10-13 by correcting the test's bound (above). The sentence this
paragraph used to end with — "the same extra term is what makes the `hprior`
fact set grow" — was a coincidence of the two appearing in the same run.

**Next step:** state `work_step_add_imm64` (and its SUB/CMP siblings) in the
generated proof's OWN terms — the concrete `UInt64.ofNat <shifted imm>` the
generator already computes in `_step_rhs` — rather than through
`arm64_ext_imm12`, or add an `@[simp]` lemma
`arm64_ext_imm12 (w) = ((w >>> 10) &&& 0xfff).toNat <<< (12 * ((w >>> 22) &&& 1).toNat)`
that the unifier can rewrite with without unfolding. Do NOT revert the model
change: the shift is a real correctness fix and its own tests (Peephole's
`sh = 0` side conditions, `test_formal_call_proof_gen.py`'s trap rows) depend
on it.
