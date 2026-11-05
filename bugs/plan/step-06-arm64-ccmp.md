# plan/step-06: arm64 `ccmp` / `ccmn`

**Source:** `bugs/FORMAL_arm64_instruction_coverage.md` (top of the gap list:
13,842 occurrences, no encoder at all).
**Master plan:** `doc/finish-formal.md` §"Step 06".

## Goal

Close the top genuine gap: "compare and set flags conditionally", the family
whose absence forces `if a != b:` into a branch where a single instruction would
do.

## What to add — the four-things rule

1. **Encoders** in `formal/arm64.py` (`ccmp`/`ccmn`, register and immediate
   forms), byte-exact against `as` in `test_arm64_encoders.py`.
2. **Machine model**: the `arm64_step` arm in `lib/ProofLib.lean`, with the
   "condition not met leaves the flags alone" semantics stated truthfully, or the
   arm is *not* added and the step records why.
3. **Proof tables** in `formal/arm64_proof_gen.py`: `_STEP_CONDS` entries
   (appended, so no hard-coded index moves), the `_step_rhs` rows,
   `_regs_written`, the block-scanner entry, and the `hne_` fact in every
   earlier `work_step_*` theorem that negates its class.
4. **Lowering** in `formal/arm64_codegen.py` recognising the condition that
   becomes one `ccmp`/`ccmn`, declining every shape it cannot make cheaper.

## Structure-only rule

The encoder, table rows and lowering are real; the model arm and its step
theorem may be `by sorry` (step-01 ledger). A false model arm is worse than the
gap, so if the conditional-flag semantics cannot be stated truthfully, refuse to
add the arm.

## Files

`formal/arm64.py`, `formal/arm64_codegen.py`, `formal/arm64_proof_gen.py`,
`lib/ProofLib.lean`, `test_arm64_encoders.py`, `test_arm64_emission.py`, ledger.

## Verification

`test_arm64_encoders.py`, `test_arm64_emission.py` (assert the ANSWER, not the
bytes — see the doc's "an operand pair is not an operand" lesson), and the
thirteen-condition probe style the doc uses. `test_formal_proof_gaps.py`.

## Done when

- [ ] encoder byte-exact; lowering emits for recognised shapes, declines the rest
- [ ] every answer matches CPython on the probe, both backends
- [ ] model arm + proof-table rows exist with a counted hole
- [ ] the annotate audit's "encoders no lowering emits" no longer names `ccmp`

## Dependencies

step-01.
