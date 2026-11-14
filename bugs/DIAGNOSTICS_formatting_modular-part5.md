# DIAGNOSTICS: formatting comparison with modular (part 5)

## SPLIT: DIAGNOSTICS_formatting_modular-part1, DIAGNOSTICS_formatting_modular-part2, DIAGNOSTICS_formatting_modular-part3, DIAGNOSTICS_formatting_modular-part4, DIAGNOSTICS_formatting_modular-part5

## Symptom
Our diagnostic formatting for modular test cases does not match the expected format from the modular compiler. We need to compare our output with the modular reference and fix any discrepancies.

## Affected file
- `invalid_downcast_error.mojo` (diagnostic part)

## Acceptance
- The diagnostic output for `invalid_downcast_error.mojo` matches the modular reference format exactly.
- The status section of the bug doc reflects the fix.
- No other files are affected by this change.

## Notes
- This is part 5 of 5 parts for the `DIAGNOSTICS_formatting_modular` bug.
- The full list of affected files includes: `diagnostics_in_missing_locs.mojo`, `diagnostics_in_missing_locs_imports.mojo`, `diagnostic_format.mojo`, `kgen_lsp_check_parse_error.mojo`, and `invalid_downcast_error.mojo` (diagnostic part).
- This part focuses on `invalid_downcast_error.mojo` (diagnostic part).
