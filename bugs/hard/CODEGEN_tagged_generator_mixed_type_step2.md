# CODEGEN_tagged_generator_mixed_type_step2

SPLIT: CODEGEN_tagged_generator_mixed_type_step2-part3 (part1 landed in b6c72c837, part2 in this commit)

## Parent plan
docs/tagged_generator_mixed_type-plan.md

## Scope
Step 2 of the plan. See plan for details.

## Files
See plan.

## Test
See plan.

## Acceptance
Step 2 complete per plan.

## Status
- part 1 (landed, b6c72c837): the box kind contract, pinned in `test_ptr_registry.py`.
- part 2 (landed 2026-11-11): a double stored into a mixed tagged name is boxed with
  `mojo_box_from_double` (`emit_stmts.py`, the simple-name arm; a float is widened first).
  Also `_mixed` in the declaration arm (`emit_stmts.py`) now includes `tagged_mixed_name`,
  so a `double` pre-pass hint no longer declares such a name a double. The two float fixtures in
  `test_gimple_generator_runner.py` are CPython-oracle cases. Runner: 434 passed, 22 failed,
  the same 22 as the baseline; all nine `tagged_for_target_*` cases pass.
- part 3 (str): not started.
