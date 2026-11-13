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
- **Fixed (2026-11-12, parts 1-2).** A failed binding reports its own violated
  `where` clause (`invalid instantiation of '...': violated constraint`, naming
  the clause) and reports only the error that failed the binding, with no
  deferred-constraint noise (pinned by
  `test_binding_deferral_diagnostic.py`).
