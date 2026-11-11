# DIAGNOSTICS step 6: @align decorator validation

SPLIT: DIAGNOSTICS_align_decorator-part1, DIAGNOSTICS_align_decorator-part2, DIAGNOSTICS_align_decorator-part3

Part of the umbrella `bugs/hard/DIAGNOSTICS_missing_validation_modular.md`;
plan: `docs/diagnostics-missing-validation-plan.md` §6.

## Symptom
`@align(expr)` on a struct requires a positive power of 2; a non-power-of-2 value must fail with `function instantiation failed` / `struct alignment must be a positive power of 2, got N`.

## Modular tests
align_decorator_parametric_error.mojo

## Files
fire_compiler.py decorator parsing, mojo/backend_gimple struct emission

## Test
`@align(calculate_illegal_alignment(alignment))` with a non-power-of-2 value fails.

## Acceptance
Add `test_align_decorator_diagnostic.py`.

## Status
- **Open.**
