# DIAGNOSTICS step 4: Binding deferral reporting

Part of the umbrella `bugs/hard/DIAGNOSTICS_missing_validation_modular.md`;
plan: `docs/diagnostics-missing-validation-plan.md` §4.

## Symptom
A failed struct binding must report only the error that failed it, not the constraints it deferred before failing.

## Modular tests
failed_binding_deferrals.mojo

## Files
mojo/backend_gimple/emit_resolve.py generic-binding path

## Test
`NeedsCopyablePos[CondCopyable[U], 0]` fails with `violated constraint`; `[..., 1]` compiles.

## Acceptance
Add `test_binding_deferral_diagnostic.py`.

## Status
- **Open.**
