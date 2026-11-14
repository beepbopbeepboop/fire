# FORMAL arm64 instruction coverage part 2: reconcile SP-form branches 86-88 reachability and census

## Goal
Reconcile the extended-register SP forms `add x0, sp, x16` (`0x8b3063e0`, branch 86), `sub x0, sp, x16` (`0xcb3063e0`, branch 87), and `cmp sp, x16` (`0xeb3063ff`, branch 88) so the step table, `_step_branch_index`, the model's decoding, and `TestRegister31` agree on which branch claims each word and that each row is reachable/modelled as intended.

## Context
`bugs/hard/FORMAL_arm64_instruction_coverage.md` (SPLIT): `TestRegister31.test_every_row_is_reachable` fails for these three SP forms because table/test rows and model claims disagree (rows described as "extended-register class, which no branch claims" while the model decodes them). The per-entry census for 86-88 must be redone and reflected in code/tests; update the `arm64_reg_or_sp` / extended-register census comment in `lib/ProofLib.lean` where it concerns these forms so it no longer contradicts the resolved behavior.

## Acceptance
- For branches 86-88, `_step_branch_index`/step-table claims and model decoding are consistent per representative word.
- `TestRegister31` rows for `add x0, sp, x16`, `sub x0, sp, x16`, and `cmp sp, x16` accurately describe reachability/modeling and the test's expectations match reality.
- `lib/ProofLib.lean` census/docstring text relevant to these SP forms is reconciled with the implemented/modelled behavior (no blanket claim that contradicts the extended-register CMP/SP forms that are modeled).
- `TestRegister31.test_every_row_is_reachable` passes.

## Done when
`python3 -m pytest test_formal_call_proof_gen.py -k "TestRegister31 and test_every_row_is_reachable"`
