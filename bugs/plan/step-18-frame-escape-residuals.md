# plan/step-18: by-reference frame-escape residuals and their Lean contract

**Source:** `bugs/FORMAL_known_limits.md` §6.3 (lever #2, 97 direct / 68
actionable) and `bugs/OPEN_WORK.md`'s row for
`FORMAL_a_one_field_mutator_has_no_method_contract.md` (no longer in `bugs/`).
**Master plan:** `doc/finish-formal.md` §"Step 18".

## Goal

The receiver convention landed: a mutating method of a one-field struct receives
the address of its caller's one-word cell and writes the receiver back on every
exit (`work/formal15-mutator-return-abi`). What is left is the **Lean contract**,
which `formal/arm64_proof_gen.py`'s `_frame_methods` currently excludes by name.
The three things it would have to say, none with an answer today:

1. the cell is the CALLER's frame and nothing bounds its depth;
2. constant propagation starts from "x0 arrives as the receiver" and has to
   learn a load-first rule;
3. the write-back repeats on every exit, so the frame-store peel needs a case
   obligation.

The x86-64 backend has no frame-contract machinery at all.

## What to add

- The contract **stated** (with `sorry` where the answer is genuinely unknown),
  the load-first constant-propagation rule, and the write-back peel obligation.
- Where the answer is unknown (the depth bound), refuse rather than invent an
  axiom — `FORMAL_known_limits.md`'s rule that a refusal must be true.
- Un-exclude the mutating method from `_frame_methods` only where the contract
  is truthful enough to support it.

## Structure-only rule

Scaffold only. The contract's open questions are stated as open in the step's
notes; do not guess them.

## Files

`formal/arm64_proof_gen.py`, `lib/Refine.lean`, `lib/Contracts.lean`,
`formal/contracts.py`, ledger.

## Verification

`test_formal_proof_gaps.py`; the relevant `test_formal_dylib.py` /
`test_formal_cross_module.py` rows; a sweep delta on the 68.

## Done when

- [ ] contract stated truthfully with counted holes
- [ ] any remaining refusal names the unknown
- [ ] the frame-escape family count moves or the step records by how much

## Dependencies

step-01.
