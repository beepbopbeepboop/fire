SPLIT: parts 1 and 2 landed (`test_mojoc_import_conformance.py` and
`test_mojoc_implicit_default_conformance.py`); their docs are deleted.
Remaining case (dual-mount mojoc import) is tracked by
`bugs/DIAGNOSTICS_mojoc_imports-part2.md`.

# DIAGNOSTICS step 10: mojoc / precompiled import errors

Part of the umbrella `bugs/hard/DIAGNOSTICS_missing_validation_modular.md`;
plan: `docs/diagnostics-missing-validation-plan.md` §10.

## Symptom
Importing a precompiled module whose stored signature violates a constraint must report the conformance error.

## Modular tests
import_mojoc_conformance_error.mojo, import_mojoc_implicit_default_param.mojo, import_dual_mount_mojoc.mojo

## Files
.mojoc loading and the conformance checker from step 2

## Test
Each modular file's `error:` line is reproduced.

## Acceptance
One regression per file.

## Status
- **Open.** `import_mojoc_conformance_error.mojo` and
  `import_mojoc_implicit_default_param.mojo` are covered by landed
  regressions (`test_mojoc_import_conformance.py`,
  `test_mojoc_implicit_default_conformance.py`) and their docs are deleted.
  The remaining case (`import_dual_mount_mojoc.mojo`, the dual-mount /
  multiple-mount import) is tracked by the replanned easy part
  `bugs/DIAGNOSTICS_mojoc_imports-part2.md`.
