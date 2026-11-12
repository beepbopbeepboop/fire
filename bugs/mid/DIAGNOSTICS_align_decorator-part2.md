# DIAGNOSTICS @align decorator — part 2: validate alignment and emit diagnostic

Split from `bugs/hard/DIAGNOSTICS_align_decorator.md` (umbrella step 6 of
`bugs/hard/DIAGNOSTICS_missing_validation_modular.md`; plan:
`docs/diagnostics-missing-validation-plan.md` §6).

## Class
mid

## Depends on
`bugs/mid/DIAGNOSTICS_align_decorator-part1.md` (struct `@align(expr)` is
parsed/stored on the AST).

## Goal
Enforce that a struct's `@align(expr)` resolves to a positive power of 2. A
non-power-of-2 (or otherwise invalid) value must fail compilation with the
expected diagnostic, including parametric cases.

## Scope
- `mojo/backend_gimple/` struct emission/instantiation (and any shared
  comptime-evaluation path needed): resolve/evaluate the stored `@align`
  expression for concrete struct instantiations.
- Emit a compile-time diagnostic consistent with modular's expectation:
  `function instantiation failed` / `struct alignment must be a positive power
  of 2, got N` (match the modular test's CHECK lines as closely as this
  compiler's diagnostic format allows).

## Symptom / test case
`@align(calculate_illegal_alignment(alignment))` (or any expression that yields
a non-power-of-2 value) must fail, e.g. a struct instantiated so alignment is 3.

## Acceptance
- Compiling a struct with a concrete invalid alignment such as `@align(3)` (or
  an equivalent non-power-of-2) fails with a diagnostic stating the alignment
  must be a positive power of 2 and reporting the offending value.
- Compiling a struct with a valid power-of-two alignment such as `@align(8)` is
  accepted.
- A parametric/instantiated case where the computed alignment is non-power-of-2
  fails with the required diagnostic (not silently accepted).

## Notes
Part 3 adds `test_align_decorator_diagnostic.py` as the committed regression.
