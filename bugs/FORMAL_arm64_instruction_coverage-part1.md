# FORMAL arm64 instruction coverage part 1: CMP-register SP-form spelling matches model

## Goal
Fix the generator's `_step_rhs` spelling for the CMP-register extended-register SP form so that, for `cmp sp, x16` (word `0xeb3063ff`, branch 88), the right-hand side reads Rn as `arm64_reg_or_sp 31 s` and uses the same shift spelling as the model's `arm64_step` arm. The generated step-RESULT lemma must state the step `arm64_step` actually computes.

## Context
`bugs/hard/FORMAL_arm64_instruction_coverage.md` (SPLIT): `TestRegister31.test_the_generator_keeps_its_own_spelling_and_why` is red because `_step_rhs` currently spells Rn as `arm64_reg 31 s` and differs in shift spelling (`arm64_reg 16 s` vs `arm64_reg 16 s <<< UInt64.ofNat 0`) for this form. `_step_rhs(0xeb3063ff, 88)` returns a right-hand side, but with the wrong spelling, so Lean would reject a generated proof that contains `cmp sp, x16`.

## Acceptance
- `_step_rhs` for the CMP-register SP form emits the model's spelling arm-for-arm (including `arm64_reg_or_sp 31 s` for Rn and matching shift spelling).
- Any generated proof/lemma text for `cmp sp, x16` states what `arm64_step` computes, not a mismatched register read.
- `TestRegister31.test_the_generator_keeps_its_own_spelling_and_why` passes.

## Done when
`python3 -m pytest test_formal_call_proof_gen.py -k "TestRegister31 and test_the_generator_keeps_its_own_spelling_and_why"`
