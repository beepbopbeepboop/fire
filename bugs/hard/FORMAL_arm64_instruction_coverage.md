# FORMAL: the extended-register class is claimed by the step table but the generator has no right-hand side for it; the coverage census this doc is is missing

**Status: OPEN.** Measured 2026-11-12 on the merge of the
`gate:reg-formal-ast-bridge-two-arg` lane (work-6818). The svc fix
(90cce42a5) let guarded programs generate again, which un-masked the rows
below: until then the same classes errored in `setUpClass` on the svc
refusal and this gap was invisible. `TestRegister31` has been red on
master for part of it all along.

This is the census the docstring of `arm64_reg_or_sp` in
`lib/ProofLib.lean` (`~line 1850`) points at: "That is a coverage gap
rather than a wrong answer (the generator refuses such a word rather than
mis-reading it), and `bugs/hard/FORMAL_arm64_instruction_coverage.md` is where
the census of it belongs." The file did not exist, and the statement it
rests on is only half true (below).

## Measured

- The Python step table (`_STEP_CONDS`, 89 entries) claims entries 70-79
  for the extended-register / 3-source / LDRSW class (representative words
  `0x1e602000` .. `0x9e780000`). `_step_branch_index` resolves those words
  to idx 70-79, `_step_rhs` answers `None` for every one of them, and
  `_step_result_plan` excludes them. So a block containing such a word gets
  no step-RESULT lemma, and `_gen_run_cert` refuses the run with an `rhs is
  None` that `_cfg_decomposition_refusal` does NOT name: the word "has a
  step" (idx 70-79), so the unmodelled-word search skips it and the reader
  gets the generic "empty block runs certificate" sentence. The same
  misleading-message defect the svc fix closed for idx 35, one class over.
- `TestRegister31.test_every_row_is_reachable` fails on the three SP forms:
  `add x0, sp, x16` assembles to `0x8b3063e0` (the model decodes it, branch
  86), `sub x0, sp, x16` to `0xcb3063e0` (branch 87), `cmp sp, x16` to
  `0xeb3063ff` (branch 88) -- while the test's `SP_IN_RN_FORMS` row for
  each says "the extended-register class, which no branch claims". Table
  and model disagree about the same word; the test says "one of the rows
  lies" and does not say which.
- `_step_rhs(0xeb3063ff, 88)` DOES return a right-hand side, and it reads
  Rn through `arm64_reg_or_sp 31 s` (the SP form). So the extended-register
  CMP form IS modelled, which contradicts the docstring's "nothing in
  `arm64_step` decodes the extended-register class" -- at least for that
  form. The census must be redone per entry; the blanket statement cannot
  stand.
- `TestRegister31.test_the_generator_keeps_its_own_spelling_and_why` fails:
  the generator's `_step_rhs` CMP-register arm spells Rn as `arm64_reg 31 s`
  (which is 0) where the model's arm spells `arm64_reg_or_sp 31 s` (which is
  `s.sp`), and the shift spelling differs too (`arm64_reg 16 s` vs
  `arm64_reg 16 s <<< UInt64.ofNat 0`). For `cmp sp, x16` the generated
  step-RESULT lemma therefore states a step `arm64_step` does not compute;
  the file still looks right in Python and Lean is the only reader that
  would refuse it.
- The gap is DORMANT in current emitter output: the image of
  `def plain(a, b): return a + b` (arm64) carries ZERO words of the class in
  its executable region (measured over `_exec_code_limit`), so the gate job
  stays green and the generated proofs typecheck. It bites the moment the
  emitter emits one of these words -- the ProofLib comment names exactly
  that spelling: `cmp sp, x16` as clang assembles it is `0xeb3063ff`, the
  extended-register form.

## Red rows that measure it (all in `test_formal_call_proof_gen.py`)

- `TestRegister31.test_every_row_is_reachable` (forms: `add x0, sp, x16`,
  `sub x0, sp, x16`, `cmp sp, x16`) -- red on master, red here.
- `TestRegister31.test_the_generator_keeps_its_own_spelling_and_why` -- red
  on master, red here (the spelling mismatch above).
- `TestStepOkDerivesFromStepResult.test_the_derivation_is_total_over_the_step_table`
  (entries 70-79) and `...test_the_step_result_of_every_covered_word_is_still_emitted`
  (entries 70-79) -- un-masked 2026-11-12 by the svc fix (before it, the
  whole class errored in `setUpClass` on the svc refusal).

## What is expected

Every entry the decoder accepts has a right-hand side (that is what makes
the step-OK derivation total), or the table stops claiming words the model
does not decode (that is what `check_step_conds` cross-checks the table
against), and the generator's spelling is the model's spelling arm for arm.

## Exact next step

1. Redo the per-entry census for 70-79 (and the 86-88 branches): assemble
   the representative word, ask the model's `arm64_step` in Lean, and read
   `_step_rhs`. Decide per entry: (a) modelled -> the generator must emit
   the matching step-RESULT lemma (an arm in `_step_rhs` /
   `_WORK_STEP_BY_IDX`, spelling identical to the model, including the
   `arm64_reg_or_sp` read and the shift spelling); (b) not modelled -> drop
   the table entry so `_step_branch_index` stops claiming the word, so the
   refusal NAMES it as unmodelled instead of the generic sentence.
2. Fix the `_step_rhs` CMP-register spelling to the model's (this is a
   wrong statement in every generated proof that contains `cmp sp, x16`;
   Lean is the only reader that would catch it, so keep
   `test_the_generator_keeps_its_own_spelling_and_why` as the pin).
3. Reconcile the `arm64_reg_or_sp` docstring in `lib/ProofLib.lean` with the
   census (it says the class is unmodelled; the extended-register CMP form
   is).
4. Re-run `TestRegister31` and `TestStepOkDerivesFromStepResult`; both
   classes green before the next formal sweep.

Related: `bugs/mid/FORMAL_svc_exit_handling_incomplete.md` (the svc fix that
un-masked this; its remaining item is the dynamic `svc`, a different gap).
