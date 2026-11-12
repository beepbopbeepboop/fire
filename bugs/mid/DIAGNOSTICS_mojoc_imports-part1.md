# DIAGNOSTICS mojoc imports, part 1: conformance error on precompiled import

Parent: `bugs/hard/DIAGNOSTICS_mojoc_imports.md` (umbrella split; see also
`docs/diagnostics-missing-validation-plan.md` §10 and
`bugs/hard/DIAGNOSTICS_missing_validation_modular.md`).

## Symptom

Importing a precompiled module (`.mojoc` / precompiled import path) whose
stored signature violates a trait/conformance constraint must report the
conformance error, not succeed silently or crash.

## Modular test

- `import_mojoc_conformance_error.mojo`

## Files / area

- `.mojoc` / precompiled-module loading
- the conformance checker (step 2 of the diagnostics missing-validation plan)

## Test / acceptance

Reproduce the modular file's `error:` line when importing the offending
precompiled module.

**Acceptance:** one regression covering
`import_mojoc_conformance_error.mojo` (its `error:` line is reproduced).

## Status

- **Open.** Part 1 of 3 split from `bugs/hard/DIAGNOSTICS_mojoc_imports.md`.
