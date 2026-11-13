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

- **Open (2026-11-13, worker bug-mid-diagnostics-mojoc-imports-part1-2).** Not
  fixable as a focused change in this tree: there is no `.mojoc` / precompiled
  module format, no `mojo precompile`-style pipeline, and no precompiled-module
  import path in `module_loader.py` or the compiler front end (searched for
  `mojoc`/`precompiled`/serialized module loading; `mojoc` in this repo names the
  compiled compiler binary, not a module file format). The Modular reference test
  (`modular/mojo/test/mojo-tool/run/import_mojoc_conformance_error.mojo` with
  `inputs/precompiled_conformance/`) requires: (1) emitting/loading a `.mojoc`
  package with stored signatures, (2) importing it after sources are removed,
  (3) running trait/conformance checking (step 2 of the diagnostics plan) against
  the stored signature and producing the ordinary diagnostic with a synthesized
  note for a defaulted parameter whose underlying declaration is absent from the
  bytecode. Root-cause fix therefore depends on implementing precompiled module
  serialization/import and then applying conformance validation on load — a
  multi-file feature project, not a single-bug patch. **Next step:** design and
  land `.mojoc` (or equivalent) module serialization + load in `module_loader.py`/
  compiler, persist trait/conformance-relevant signature info, and on import run
  the same conformance checks the source path uses, emitting the Modular-shaped
  diagnostic/note; only then can a regression for
  `import_mojoc_conformance_error.mojo` be made to pass. No code/test added this
  round (no verifiable slice without the precompiled-import infrastructure).
