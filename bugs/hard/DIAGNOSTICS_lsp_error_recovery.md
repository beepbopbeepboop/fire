SPLIT: bugs/mid/DIAGNOSTICS_lsp_error_recovery-part1, bugs/mid/DIAGNOSTICS_lsp_error_recovery-part2, bugs/mid/DIAGNOSTICS_lsp_error_recovery-part3

# DIAGNOSTICS step 8: LSP error recovery

Part of the umbrella `bugs/hard/DIAGNOSTICS_missing_validation_modular.md`;
plan: `docs/diagnostics-missing-validation-plan.md` §8.

## Symptom
The parser must recover from an unknown declaration and keep parsing, reporting the error and continuing to emit the following declarations.

## Modular tests
error_tolerance.mojo

## Files
the parser's error-recovery path and the LSP front end

## Test
A file with an unknown declaration followed by a valid struct reports `use of unknown declaration` and still emits the struct.

## Acceptance
Add `test_lsp_error_recovery.py`.

## Status
- **Open.**
