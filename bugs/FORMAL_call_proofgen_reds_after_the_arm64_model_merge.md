# `test_formal_call_proof_gen.py`'s remaining reds after merging the oct-7 formal branches

**Area:** FORMAL / proof generation — `formal/arm64_proof_gen.py` and
`lib/ProofLib.lean`'s `arm64_step` arms. **Status: PARTIALLY FIXED
(2026-10-12, `work/formal319-docs`) — items 1, 2 and 3 are FIXED; items 4 and 5
remain, and they are pre-existing (this doc said so for both). §"the most likely
cause" below is measured wrong about items 1–3.** The merge itself is complete;
these are the failures the narrow `test_formal_call_proof_gen.py` run still
shows after every *mechanical* merge artifact was fixed (undefined
`_RLIMIT_STACK`, the `_flush_push_depth` epilogue variant, a duplicated
`for_target_tree`, a test whose `setUpClass` never populated `cls.infos`, and so
on — all fixed and committed on that branch).

## 2026-10-12, second pass: items 1 and 2 are the `runs` side condition, and it is NOT `arm64_ext_imm12`

With `lib/ProofLib.olean` built, the Lean rows run and items 1 and 2 reproduce
exactly as written: `mod_proof.lean:4899:68: error: maximum recursion depth has
been reached` (and the same in `same_image_leaf_proof.lean`). **The cause is the
argument to `runs_cons_seq`, not the step lemma or `arm64_ext_imm12`:**

* the error column is the `rfl` in
  `rw [runs_cons_seq st (mod_by_var_b6_qT0 st) mod_by_var_code 0 hs0 rfl, …]`,
  the proof of `(qT0 st).pc = st.pc`;
* `rfl` on `(qT st).pc = (qS st).pc` reaches the kernel's recursion limit once
  the block's `sp` adjust is a `UInt64` literal at or above **512** — measured
  on a four-field toy structure:
  `{ st with sp := st.sp + (1024 : UInt64) }.pc = st.pc` fails under `rfl`
  while `+ 257` succeeds. `ADD sp, sp, #32, lsl #12` is `+131072`, inserted by
  the div0 guard arm, so `mod_by_var_b6_self1` is exactly the first block over
  the line. **This is why the `sh`-field fix is what exposed it and why reverting
  the fix is not the repair** — before it the immediate was `32`;
* `work_step_add_imm64` and `mod_by_var_sr_87` themselves elaborate fine (no
  error at their own lines), so §"The most likely cause" is wrong about this.

**Fixed in the emitter** (generator side, no `lib/` change): the side condition
is now `(by simp only [<qS>, <qT>, arm64_set_reg])` instead of `rfl`, at the six
`runs_cons_seq`/`runs_cons_jump` sites (`arm64_proof_gen.py`'s block run-theorem
emission). Unfolding `qS`/`qT` closes the `{ … with sp := … }` shape by
projection without reducing the `sp` term, and unfolding `arm64_set_reg` is what
keeps the register-setting transitions `rfl` DID handle working. Verified:
`mod_by_var` and `same_image_leaf` now elaborate; running
`test_formal_call_proof_gen.py` drops from 8 failures to 6, and the two that go
are exactly items 1 and 2. Pinned by
`TestARunsSideConditionUnfoldsItsBlocks` (generation only, no Lean) and by the
two Lean rows that now pass (`TestExternCallTheRunDoesNotReach.test_the_corpus_
example_that_was_false_is_proved`, `TestSameImageCallLean.test_the_followed_
call_proves_with_no_admission`).

## 2026-10-12: item 3 is a miscalibrated TEST, not the generator

The one non-Lean red, and it is not the `arm64_ext_imm12` change either:

* the `hprior_*` emission is **byte-identical** to `cfd550b5` (the commit that
  introduced the per-path memo and where the bound was calibrated), verified by
  diffing `git show cfd550b5:formal/arm64_proof_gen.py` against HEAD in the
  emission region;
* the counts are now `c_k = 2 * c_{k-1} + 3`, i.e. `3 * (2**k - 1)` — **the PATH
  count (x2) plus one fixed startup constant**, measured 9 / 21 / 45 / 93 for
  k = 2/3/4/5, residual exactly 3 at every step;
* the old ratio bound of 2.2 was calibrated on `3 * 2**(k+1)` (24 / 48 / 96 /
  192 at `cfd550b5`), where the ratio is exactly 2. The counts are ~2x smaller
  now (a block-layout change after `cfd550b5`, not a memo change), so the fixed
  startup alone puts the k=2 -> 3 ratio at 2.33 while it falls back to 2.03 by
  k=6. **A ratio cannot distinguish "x2 plus a constant" from "exponential" at
  three samples of a small integer.**

**Fixed test-side, and the new assertion is the stronger one.**
`test_the_fact_count_grows_with_the_paths_and_not_with_the_branches` now reads
the RESIDUAL `c_k - 2*c_(k-1)` over FIVE programs (k = 2..5) and requires it to
be one constant across three independent steps: a generator that had gone
exponential shows a GROWING residual and fails, which the old single-ratio
bound could not see at these counts. No generator behaviour changed. **The
`CONDS` tuple grew one disjoint-bit condition so k=5 is a real 5-condition
program**; the two classes above still build their own programs from it.

## What is NOT fixed, and whose it is

Item 4 (`sgt8`'s `rewrite` that no longer finds its pattern) and item 5
(`TestTheZeroDivisorGuardAgainstLean`'s rows) remain, **and the filing already
marked both pre-existing** ("did not typecheck before this fix either", and "the
class's state on the base tree"). They are Lean elaboration failures, not the
`runs` side condition, and the six remaining failures of the file are exactly
these two rows' subtests. Measured after the fix: **180 tests, 6 failures** (all
in `TestANarrowTypedParameterGetsItsRange` and
`TestTheZeroDivisorGuardAgainstLean`), down from 8.


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
  bounds it at x2.2 ("the per-path memo makes this x2").
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

**CORRECTED 2026-10-12: this section is measured WRONG for items 1–3.** The
recursion depth is in the `runs_cons_seq` side condition's `rfl`
(`(qT st).pc = (qS st).pc`) and is a `UInt64`-literal-width limit, not
`arm64_ext_imm12` (the step lemmas themselves elaborate — there is no error at
their own lines); and the `hprior` counts are `3 * (2**k - 1)`, which is the path
count, not an "extra term". Both are fixed above. **The hypothesis below is kept
for the history and for items 4/5, which it may still describe.** The
`arm64_ext_imm12` `sh`-field correction is right and must not be reverted for any
of them.

The three new ones all appear after `lib/ProofLib.lean`'s ADD/SUB/CMP immediate
arms changed to read `arm64_ext_imm12` (the `sh`-field fix merged from
`work/formal108/125/131/149`). That change is correct — it is what makes
`ADD sp, sp, #32, lsl #12` compute `+131072` instead of `+32` — and it is why
the generated `mod_by_var_sr_87` states `+131072`. What it also does is put a
non-reducible `arm64_ext_imm12 w` term in `work_step_add_imm64`'s statement
(`lib/ProofLib.lean:5117`), so unifying the concrete generated step with that
lemma now reduces through `arm64_ext_imm12`; the elaborator loops instead of
closing, and the same extra term is what makes the `hprior` fact set grow.

**Next step:** state `work_step_add_imm64` (and its SUB/CMP siblings) in the
generated proof's OWN terms — the concrete `UInt64.ofNat <shifted imm>` the
generator already computes in `_step_rhs` — rather than through
`arm64_ext_imm12`, or add an `@[simp]` lemma
`arm64_ext_imm12 (w) = ((w >>> 10) &&& 0xfff).toNat <<< (12 * ((w >>> 22) &&& 1).toNat)`
that the unifier can rewrite with without unfolding. Do NOT revert the model
change: the shift is a real correctness fix and its own tests (Peephole's
`sh = 0` side conditions, `test_formal_call_proof_gen.py`'s trap rows) depend
on it.
