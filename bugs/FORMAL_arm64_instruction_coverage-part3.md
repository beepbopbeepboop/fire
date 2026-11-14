# FORMAL arm64 instruction coverage part 3: resolve extended-register entries 70-79 step RHS/coverage

## Goal
Complete the per-entry census for step-table entries 70-79 (extended-register / 3-source / LDRSW class, representative words `0x1e602000` .. `0x9e780000`) and make the generator/table consistent with the model: for each word that `arm64_step` decodes, provide a matching `_step_rhs` / `_WORK_STEP_BY_IDX` and emit the step-RESULT lemma with spelling identical to the model; for each word not modeled, stop claiming it in the step table so `_step_branch_index` no longer treats it as having a step and the run refusal names the word as unmodeled instead of the generic "empty block runs certificate" sentence.

## Context
`bugs/hard/FORMAL_arm64_instruction_coverage.md` (SPLIT): `_STEP_CONDS` claims entries 70-79, `_step_branch_index` resolves those words to idx 70-79, but `_step_rhs` returns `None` for all of them and `_step_result_plan` excludes them. `TestStepOkDerivesFromStepResult` is red for entries 70-79 (unmasked by the svc fix). The misleading refusal path is the same class of defect as the svc/idx-35 case: a claimed-but-unhandled word yields a generic message. Reconcile related `lib/ProofLib.lean` census/docstring text for this class if it becomes inaccurate after the change.

## Acceptance
- Every entry 70-79 word is either (a) modeled with a model-identical step RHS/result emitted in generated proofs, or (b) removed/unclaimed so unmodeled words are named explicitly in refusal output.
- Step-OK derivation/coverage over the step table is total for the resolved entries (no claimed entry left with missing RHS).
- `TestStepOkDerivesFromStepResult.test_the_derivation_is_total_over_the_step_table` passes.

## Done when
`python3 -m pytest test_formal_call_proof_gen.py -k "TestStepOkDerivesFromStepResult and test_the_derivation_is_total_over_the_step_table"`
