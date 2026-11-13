SPLIT: DIAGNOSTICS_docstring_self_import-part1, DIAGNOSTICS_docstring_self_import-part2
# DIAGNOSTICS step 9: Docstring code-block self-import

Part of the umbrella `bugs/hard/DIAGNOSTICS_missing_validation_modular.md`;
plan: `docs/diagnostics-missing-validation-plan.md` §9.

## Symptom
A docstring code block that imports its own module must be rejected: `module 'X' cannot import itself`.

## Modular tests
docstring_self_import.mojo

## Files
docstring code-block extraction (new) and the import checker

## Test
A docstring containing a `mojo` code block with `import X` inside module X fails.

## Acceptance
Add `test_docstring_self_import.py`.

## Status
- **Open.**
