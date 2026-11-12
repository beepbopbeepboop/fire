# DIAGNOSTICS @align decorator — part 3: regression test

Split from `bugs/hard/DIAGNOSTICS_align_decorator.md` (umbrella step 6 of
`bugs/hard/DIAGNOSTICS_missing_validation_modular.md`; plan:
`docs/diagnostics-missing-validation-plan.md` §6).

## Class
easy

## Depends on
`bugs/mid/DIAGNOSTICS_align_decorator-part1.md` and
`bugs/mid/DIAGNOSTICS_align_decorator-part2.md` (parsing/storage and
power-of-two validation with diagnostics).

## Goal
Add the committed regression test for `@align` decorator validation.

## Scope
- Create `test_align_decorator_diagnostic.py` next to the existing diagnostics
  tests for this area.
- Cover:
  - a valid power-of-two alignment accepted (e.g. `@align(4)` / `@align(8)`),
  - an invalid non-power-of-2 alignment rejected with the expected diagnostic
    (`struct alignment must be a positive power of 2, got N`, and/or the
    surrounding `function instantiation failed` context as produced),
  - the parametric case from the original bug: an `@align(...)` whose computed
    value is non-power-of-2 (e.g. via `calculate_illegal_alignment(alignment)` /
    an equivalent helper) must fail.

Reference modular test name: `align_decorator_parametric_error.mojo` (see
original doc and umbrella). Match its observable expectations where applicable
to this compiler's diagnostic wording.

## Acceptance
- `python3 test_align_decorator_diagnostic.py` is the narrow verification for
  this bug and passes once parts 1-2 are implemented.
- The test does not require whole-closure builds, `--dump-full`, or the quality
  gate; it exercises only the specific compile/diagnostic behavior.

## Original acceptance
Satisfies the original doc's acceptance: "Add
`test_align_decorator_diagnostic.py`." together with the required diagnostic
behavior for the parametric non-power-of-2 case.
