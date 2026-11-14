SPLIT: parts 1-3; parts 1 (conformance error on a precompiled import) and 2
(implicit default parameter, conformance plus the declared-here note and
synthetic signature) landed with `test_mojoc_import_conformance.py` and
`test_mojoc_implicit_default_conformance.py`, so their docs are deleted.
Remaining: `bugs/mid/DIAGNOSTICS_mojoc_imports-part3.md`.

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
- **Open.**
