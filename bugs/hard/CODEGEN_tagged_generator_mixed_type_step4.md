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
Floats and strs are done (steps 2 parts 2-3). The container case (CODEGEN_tagged_generator_mixed_type_container)
was closed as option 2: no corpus need found, and a name bound to a tagged generator word
that also holds a container/pointer value is refused with a diagnostic naming that container
binding (`test_gimple_generator_runner.py::tagged_generator_mixed_type_container_refused`).
