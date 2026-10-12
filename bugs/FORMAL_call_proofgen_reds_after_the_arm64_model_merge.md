# `test_formal_call_proof_gen.py`'s remaining reds after merging the oct-7 formal branches

**Area:** FORMAL / proof generation — `formal/arm64_proof_gen.py` and
`lib/ProofLib.lean`'s `arm64_step` arms. **Status: OPEN.** Filed by the
`work/merge-formal8-oct7` merger. The merge itself is complete; these are the
failures the narrow `test_formal_call_proof_gen.py` run still shows after every
*mechanical* merge artifact was fixed (undefined `_RLIMIT_STACK`, the
`_flush_push_depth` epilogue variant, a duplicated `for_target_tree`, a test
whose `setUpClass` never populated `cls.infos`, and so on — all fixed and
committed on that branch).

## Status 2026-10-12 (`work/formal275-docs`): the reds are unchanged, the
## `arm64_ext_imm12` cause below is DISPROVEN, and the real site is in the
## CFG RUN proof

Re-measured on master with the library built
(`test_formal_call_proof_gen.py`'s four classes, `TestTheZeroDivisorGuardAgainstLean`
included — 8 failures of 15). The failure named below is still, byte for byte,
`mod_proof.lean:4899:68: error: maximum recursion depth has been reached`, and
the Lean verdict is a cache REPLAY (the whole class runs in 0.7 s), so the
proof bytes are unchanged.

**It is not `arm64_ext_imm12`, and this is measurable without Lean.** The
generated `mod_by_var` proof contains **zero** occurrences of
`arm64_ext_imm12`; the only construct that names it is the step-RESULT lemma's
proof (`sr_87`'s `exact work_step_add_imm64 …`, which reads the model term by
DEFEQ), and that theorem is declared at line 2753 and accepted. The failing
declaration is the run proof's `b6_self1`:

```
4899  rw [runs_cons_seq st (mod_by_var_b6_qT0 st) mod_by_var_code 0 hs0 rfl,
4900      show st.pc + 4 = 4294968608 from by rw [hpc]]
```

so the recursion is in the `rw`'s matching over the CFG block state defs
(`qS0`/`qT0`/`qS1`), not in reducing the immediate. The next reader should
start at `runs_cons_seq` and the generated `{name}_{tag}_self{k}` chain
(`formal/arm64_proof_gen.py`, the `self{k}` emitter around the `runs_cons_seq`
call), NOT at `lib/ProofLib.lean`.

The other three reds are still present and were confirmed in the same run:
`TestSameImageCallLean.test_the_followed_call_proves_with_no_admission` (the
same `maximum recursion depth`, in `same_image_leaf_proof.lean`),
`TestNestedConditionFactSharing.test_the_fact_count_grows_with_the_paths_and_not_with_the_branches`
(2 → 3 conditions grow the `hprior_` facts 9 → 21, and the count is
`3 * (2**k - 1)` over k conditions — `9, 21, 45` — so the growth is above the
test's `x2.2` for the small-k step only; this is a property of the generated
path/scope tree and has nothing in it that names the model), and
`TestANarrowTypedParameterGetsItsRange.test_lean_accepts_the_three_examples`
(`sgt8`). `TestTheZeroDivisorGuardAgainstLean`'s rows are the class's own
"the fixture generates no `q_compiles_correctly_universal`" guard, i.e. the
pre-existing div0 residual recorded elsewhere, not a new failure.

**This doc's fix is NOT the same as `lib/ProofLib.lean`'s imm12 arms.** Not
fixed here — a light worker cannot iterate on a proof this deep without a Lean
run per attempt, and the corrected site above is the next step.

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
