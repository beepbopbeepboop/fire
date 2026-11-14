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

## Done when

File: `test_mojoc_import_conformance.py` (repo root; created by this part). It
builds the modular `inputs/precompiled_conformance/pkg` fixture under `.tmp/`,
runs `fire.py precompile` on it, deletes the package sources, and then compiles
the modular consumer. It asserts the modular `error:` line exactly:

    error: 'Container' parameter 'T' has 'Marked' type, but value has type 'AnyStruct[NotMarked]'

in both compile pipelines (`compile_to_gimple` inline and
`driver.compile_program` link mode), plus three controls: the artifact record
carries the trait requirement, a conforming type argument is not refused, and
live sources beside a stale `.mojoc` still win.

Command: `python3 test_mojoc_import_conformance.py`

## Status

- **Fixed (2026-11-13, worker bug-diagnostics-mojoc-imports-part1).** The
  earlier round's blocker was true for that base: no `.mojoc` format and no
  precompile step existed. Master has since landed the signature artifact and
  `fire.py precompile` (`mojo/middle/mojoc_artifact.py`), so the remaining gap
  was narrower and is now closed:

  - the artifact stored traits as a bare name; it now stores each trait's
    required method signatures (`elaborate.extract_trait`, the same extraction
    the source path uses) — `mojoc_artifact._trait_record`;
  - `.mojoc` is a search-path candidate, tried LAST in a directory so a stale
    artifact never shadows live sources (`emit_resolve._module_candidate_paths`);
  - both import pipelines register the artifact's struct/trait records
    (`_compile_imported_module` inline, `_register_link_imports` link mode →
    `gen._mojoc_structs`);
  - an instantiation naming a `.mojoc` struct is checked against its stored
    bracket-parameter bounds at the same place a source-defined generic struct
    is checked (`emit_resolve._ensure_generic_struct`), through the new
    `mojo/middle/mojoc_conformance.py`, which reuses
    `elaborate.check_conformance` rather than adding a second checker.

  Measured before the check: the modular fixture's consumer compiled silently
  in both pipelines (`COMPILED OK` inline; `fire.py build` exited 0 with a
  linked binary). After: both report the exact modular `error:` line and fail.
  Regression: `test_mojoc_import_conformance.py` (fails at
  `test_imported_struct_conformance_error_is_reported` with the hook disabled,
  passes with it). Not in this part: the `note: '<Container>' declared here`
  line and the synthesized-signature rendering (parts 2/3); the
  dual-mount resolution case (part 3).
