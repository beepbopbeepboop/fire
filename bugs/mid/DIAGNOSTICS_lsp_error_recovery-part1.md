# DIAGNOSTICS_lsp_error_recovery part 1: parser recovers from unknown declaration

## Parent
`bugs/hard/DIAGNOSTICS_lsp_error_recovery.md` (SPLIT). Plan:
`docs/diagnostics-missing-validation-plan.md` §8.

## Scope
Implement parser-level error recovery for an unknown declaration so parsing
does not abort at the bad declaration. After reporting/recovering from
`error: use of unknown declaration '<name>'` (or the compiler's equivalent
diagnostic for an unknown declaration form), the parser must synchronize and
continue parsing the remainder of the file, producing AST/module entries for
valid declarations that follow.

## Files
Parser / error-recovery path in the front end (e.g. `fire_compiler.py` and any
shared parse helpers it uses) where top-level declarations are recognized and
unknown declarations are currently handled.

## Test
A source file containing an unknown declaration followed by a valid `struct`
declaration parses to completion: the unknown declaration yields a diagnostic,
and the subsequent struct is still present in the parsed/emitted module
structure (not dropped due to parse abort).

## Acceptance
- Parsing continues past the unknown declaration; the later struct is retained.
- No hang or crash on the recovered error.
- Covered by the regression added in part 3 (`test_lsp_error_recovery.py`) or
  an equivalent narrow test named in that part.
