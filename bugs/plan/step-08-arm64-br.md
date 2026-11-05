# plan/step-08: arm64 indirect `br`

**Source:** `bugs/FORMAL_arm64_instruction_coverage.md` (`encode_br_xn` is
uncalled; the 359 `br` occurrences are a genuine gap, deliberately not in
`ASSEMBLER_EMITTED`).
**Master plan:** `doc/finish-formal.md` §"Step 08".

## Goal

Make `br` reachable (or decline it with a measured reason) and model it.

## What to add

- The `arm64_step` arm for `BR Xn`: a pc-only branch whose successor pc is the
  register's value (`t = { s with pc := arm64_reg … }`).
- The proof-table row.
- A lowering for the construct that needs an indirect branch, or a measured
  refusal if nothing in the corpus does.
- `encode_blr_xn` (`blr`) is the sibling; the audit records its earlier mapping
  bug, so keep both families in the same table-row shape.

## Structure-only rule

The step theorem may be `by sorry`; the value side is the register read, so it
is likely `rfl`-shaped.

## Files

`lib/ProofLib.lean`, `formal/arm64_proof_gen.py`, `formal/arm64_codegen.py`,
`test_arm64_encoders.py`, ledger.

## Verification

`test_arm64_encoders.py`; the annotate audit (`br` leaves the
"encoders no lowering emits" list, or the decline is recorded);
`test_formal_proof_gaps.py`.

## Done when

- [ ] `br` emitted or declined with a measured reason
- [ ] model arm with a counted hole
- [ ] audit list updated

## Dependencies

step-01.
