SPLIT: DIAGNOSTICS_align_decorator-part3
# DIAGNOSTICS step 6: @align decorator validation

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
`@align(calculate_illegal_alignment(alignment))` at a non-power-of-2 result fails
with the diagnostic above, covered by `test_align_decorator_parametric_diagnostic.py`.

## Status
- **Open — replanned 2026-11-12, SPLIT to `bugs/mid/DIAGNOSTICS_align_decorator-part3.md`.**
  Landed on master: part 1 (`b32905e78`, `f17d40d29`/`c76551ebb` literal validator,
  test `test_align_decorator_literal_diagnostic.py`); part 2 (`d3bfa60ce`, test
  `test_align_decorator_parametric_diagnostic.py`; its doc was deleted with the fix).
  Remaining on master: the comptime call shape, `DIAGNOSTICS_align_decorator-part3`.
  **Overlap:** branch `work/bug-mid-diagnostics-align-decorator-part-3` has commit
  `b3f363cf9` implementing that call shape (new `test_align_decorator_diagnostic.py`,
  `elaborate.py`) and deleting the part3 doc. It is not yet integrated. If it lands,
  that deletion is correct and this SPLIT line becomes dangling; reconcile then.
