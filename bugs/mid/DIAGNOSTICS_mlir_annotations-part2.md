# DIAGNOSTICS step 7: MLIR type/attribute annotations

Part of the umbrella `bugs/hard/DIAGNOSTICS_missing_validation_modular.md`;
plan: `docs/diagnostics-missing-validation-plan.md` §7.

## Part 2 of 2 (filed at mid)

The replan of `bugs/hard/DIAGNOSTICS_mlir_annotations.md` split its two
self-contained halves:

* **Part 1** (filed at easy, fixed and deleted 2026-11-12) was the annotation
  **parsing** half — make `fire_compiler.py` accept `__mlir_type.<attr>` /
  `__mlir_attr.<attr>` so a module using them parses — and it tracked the
  `error: invalid call to 'foo'` refusal of a literal or a primitive-typed
  value at a `__mlir_type.*` argument (literals landed first, then the
  variable/parameter half via the per-scope static-type table).
* **This part** is the call-**checker** half — reject a call that supplies a
  value the annotation forbids, with `error: invalid call to 'foo'` at the
  argument's location.

The original doc stays at `hard`; this part carries the diagnostic work.

## Symptom
`__mlir_type.index` / `__mlir_attr.` annotations must parse and a bad call must report `error: invalid call to 'foo'` at the right location.

## Modular tests
identifier_source_range.mojo

## Files
fire_compiler.py annotation parsing, the call checker.

## Test
`def foo(x: __mlir_type.index)` called with a non-index value fails with `invalid call to 'foo'`.

## Acceptance
Add `test_mlir_annotation_diagnostic.py`; the modular file's CHECK line is reproduced.

## Status
- **Open.**
- **2026-11-12:** the call-checker refusal this part tracks has landed in
  `fire_compiler.py` (`_check_mlir_type_argument_calls`): a literal, a
  primitive-typed `var` (declared type or literal initialiser), or a
  primitive-typed parameter passed to a `__mlir_type.*` parameter is refused
  with `error: invalid call to 'foo'` at the argument — each half measured
  against the real compiler, regression `test_mlir_annotation_diagnostic.py`
  (23 cases). What remains for this part: the modular file's CHECK-line
  acceptance (identifier_source_range.mojo is not in this tree) and any
  further value shapes the real compiler refuses that the front end's
  static-type table cannot see.
