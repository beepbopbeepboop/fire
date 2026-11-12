# DIAGNOSTICS mojoc imports, part 3: dual-mount mojoc import

Parent: `bugs/hard/DIAGNOSTICS_mojoc_imports.md` (umbrella split; see also
`docs/diagnostics-missing-validation-plan.md` §10 and
`bugs/hard/DIAGNOSTICS_missing_validation_modular.md`).

## Symptom

Importing when the same precompiled module (`.mojoc`) is visible via a
dual-mount / multiple mount situation must report the expected diagnostic (or
resolve per the modular test's expectation), not succeed silently in the wrong
way or crash.

## Modular test

- `import_dual_mount_mojoc.mojo`

## Files / area

- `.mojoc` / precompiled-module loading and module resolution/mount handling
- interaction with the conformance/checking path as exercised by this case
  (see `docs/diagnostics-missing-validation-plan.md` §10)

## Test / acceptance

Reproduce the modular file's `error:` line for the dual-mount mojoc import
case.

**Acceptance:** one regression covering `import_dual_mount_mojoc.mojo` (its
`error:` line is reproduced).

## Status

- **Open.** Part 3 of 3 split from `bugs/hard/DIAGNOSTICS_mojoc_imports.md`.
