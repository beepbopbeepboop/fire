# CODEGEN_tagged_generator_mixed_type_step4

SPLIT: CODEGEN_tagged_generator_mixed_type_step4-part1, CODEGEN_tagged_generator_mixed_type_step4-part2

## Parent plan
docs/tagged_generator_mixed_type-plan.md

## Scope
Step 4 of the plan. See plan for details.

## Files
See plan.

## Test
See plan.

## Acceptance
Step 4 complete per plan.

## Status (2026-11-12)
Floats and strs are done (steps 2 parts 2-3). The mixed container case was closed as option 2
(2026-11-12 corpus census: 610 stdlib + 226 repo files, 0 candidates): a name bound to a tagged
generator word that also holds a container/pointer value is refused with a named diagnostic
naming the container binding (`test_gimple_generator_runner.py::tagged_generator_mixed_type_container_refused`).
