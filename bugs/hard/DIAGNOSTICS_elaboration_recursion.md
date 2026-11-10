# DIAGNOSTICS step 5: Elaboration recursion detection

Part of the umbrella `bugs/hard/DIAGNOSTICS_missing_validation_modular.md`;
plan: `docs/diagnostics-missing-validation-plan.md` §5.

## Symptom
A self-recursive generic instantiation must be refused with a recursive-loop diagnostic, not compiled or hung.

## Modular tests
elaboration_error_recursion1.mojo

## Files
mojo/backend_gimple/module_gen.py / monomorphize.py instantiation loop

## Test
`self_recursion[i + 1]()` inside `self_recursion` fails with `self recursive call will cause an infinite loop`.

## Acceptance
Add `test_elaboration_recursion_diagnostic.py`.

## Status
- **Open.**
