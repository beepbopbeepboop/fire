# DIAGNOSTICS @align decorator — part 1: parse and store struct alignment

Split from `bugs/hard/DIAGNOSTICS_align_decorator.md` (umbrella step 6 of
`bugs/hard/DIAGNOSTICS_missing_validation_modular.md`; plan:
`docs/diagnostics-missing-validation-plan.md` §6).

## Class
mid

## Goal
Recognize `@align(expr)` as a struct decorator in the compiler frontend and
preserve the alignment expression on the struct AST so later stages can read it.

## Scope
- `fire_compiler.py`: parse `@align(...)` on `struct` declarations and attach
  the parsed alignment argument/expression to the `StructDef` (or an equivalent
  dedicated field/representation consistent with existing decorator handling).
- Any minimal plumbing needed so the alignment expression survives through the
  representations used by `mojo/backend_gimple/` struct emission.

Do not implement power-of-two validation in this part (that is part 2), but the
stored form must be sufficient for a backend stage to evaluate/validate the
expression, including parametric/comptime cases.

## Acceptance
- Parsing a struct annotated with `@align(16)` (or an equivalent expression)
  succeeds and the resulting `StructDef` carries the align argument in a form a
  consumer can inspect.
- Existing struct decorator parsing/behavior is unchanged for unrelated cases
  (no regressions in the narrow parser/struct tests you run to verify).

## Notes
Part 2 adds validation/diagnostics; part 3 adds the regression test
`test_align_decorator_diagnostic.py`.
