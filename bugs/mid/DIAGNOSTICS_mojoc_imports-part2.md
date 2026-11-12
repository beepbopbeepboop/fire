# DIAGNOSTICS mojoc imports, part 2: implicit default param on precompiled import

Parent: `bugs/hard/DIAGNOSTICS_mojoc_imports.md` (umbrella split; see also
`docs/diagnostics-missing-validation-plan.md` §10 and
`bugs/hard/DIAGNOSTICS_missing_validation_modular.md`).

## Symptom

Importing a precompiled module (`.mojoc` / precompiled import path) whose
stored signature involves an implicit default parameter in a way that violates
constraints must report the expected diagnostic, not succeed silently or crash.

## Modular test

- `import_mojoc_implicit_default_param.mojo`

## Files / area

- `.mojoc` / precompiled-module loading
- the conformance/checking path for implicit/defaulted parameters on imported
  signatures (step 2 of the diagnostics missing-validation plan)

## Test / acceptance

Reproduce the modular file's `error:` line when importing the offending
precompiled module.

**Acceptance:** one regression covering
`import_mojoc_implicit_default_param.mojo` (its `error:` line is reproduced).

## Status

- **Open.** Part 2 of 3 split from `bugs/hard/DIAGNOSTICS_mojoc_imports.md`.
