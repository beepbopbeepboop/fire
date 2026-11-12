# DIAGNOSTICS step 3: Inferred-parameter dependency errors

Part of the umbrella `bugs/hard/DIAGNOSTICS_missing_validation_modular.md`;
plan: `docs/diagnostics-missing-validation-plan.md` §3.

## Symptom
An inferred parameter (`_`) whose type depends on a non-inferred parameter must be refused; a non-inferred element-type parameter must be reported.

## Modular tests
autoparam_dependency_errors.mojo

## Files
fire_compiler.py struct-signature elaboration, mojo/backend_gimple/module_gen.py

## Test
`struct RepeatedDep[c: Int, X: Pair[c, c]]` fails with `inferred parameter of type 'Pair[c, c]' cannot depend on non-inferred parameter 'c'`.

## Acceptance
Add `test_inferred_param_dependency_diagnostic.py`.

## Status
- **Open.**
