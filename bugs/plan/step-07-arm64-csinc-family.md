# plan/step-07: arm64 `csinc` / `csinv` / `csneg`

**Source:** `bugs/FORMAL_arm64_instruction_coverage.md` (the remaining three
fifths of the `CSEL` family; `csinc` alone is 3,014 occurrences of gap).
**Master plan:** `doc/finish-formal.md` §"Step 07".

## Goal

The encoders exist (`encode_csinc_xd_xm_cond`, `encode_csinv_xd_xm_cond`,
`encode_csneg_xd_xm_cond`) and nothing references them — a table nobody calls.
Wire the model arms, the proof tables and a lowering.

## What to add

- The `arm64_step` arms and the `hne_` facts in every earlier `work_step_*`.
- The proof-table rows in `formal/arm64_proof_gen.py`.
- A lowering for the shapes that are one conditional select, with the existing
  `CSEL` lowering as the template.
- State once that `CSINC` with `Rn = Rm = XZR` is the mode-of-`CSET` the
  existing `encode_cset_*` is expressed from — do not re-implement it.

## Structure-only rule

Encoders already exist; the work is model + proof table + lowering. Model arms
and their step theorems may be `by sorry` (ledger).

## Files

`lib/ProofLib.lean`, `formal/arm64_proof_gen.py`, `formal/arm64_codegen.py`,
`test_arm64_emission.py`, ledger.

## Verification

`test_arm64_emission.py`; the annotate audit re-run;
`test_formal_proof_gaps.py`.

## Done when

- [ ] each of the three is emitted for at least one real shape or declined with a
      measured reason
- [ ] model arms exist with counted holes
- [ ] the "encoders no lowering emits" list no longer names them

## Dependencies

step-01, and step-06 for the flag-test chord if the lowering shares it.
