# DIAGNOSTICS: formatting comparison with modular (category B)

## SPLIT: DIAGNOSTICS_formatting_modular-part1, DIAGNOSTICS_formatting_modular-part2, DIAGNOSTICS_formatting_modular-part3, DIAGNOSTICS_formatting_modular-part4, DIAGNOSTICS_formatting_modular-part5

## Symptom
~10 modular test files check diagnostic output format (error locations, messages). Need to compare our diagnostic formatting to modular's and file individual bugs if ours is worse.

## Affected files
- diagnostics_in_missing_locs.mojo
- diagnostics_in_missing_locs_imports.mojo
- diagnostic_format.mojo
- kgen_lsp_check_parse_error.mojo
- invalid_downcast_error.mojo (diagnostic part)

## Action
Run each file, capture our compiler output, compare to modular's expected CHECK lines. If our formatting is worse, file individual bugs.

## Notes
- This requires manual comparison; not automated yet.
EOF