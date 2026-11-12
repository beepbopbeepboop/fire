# DIAGNOSTICS step 7: MLIR type/attribute annotations

Part of the umbrella `bugs/hard/DIAGNOSTICS_missing_validation_modular.md`; plan: `docs/diagnostics-missing-validation-plan.md` §7.

## Symptom
`__mlir_type.index` / `__mlir_attr.` annotations must parse and a bad call must report `error: invalid call to 'foo'` at the right location.

## Modular tests
identifier_source_range.mojo

## Files
fire_compiler.py annotation parsing, the call checker.

## Test
`def foo(x: __mlir_type.index)` called with a non-index value fails with `invalid call to 'foo'`.

## Acceptance
Add `test_mlir_annotation_diagnostic.py`.