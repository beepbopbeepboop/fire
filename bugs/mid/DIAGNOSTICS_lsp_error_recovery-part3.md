# DIAGNOSTICS_lsp_error_recovery part 3: regression test_lsp_error_recovery.py

## Parent
`bugs/hard/DIAGNOSTICS_lsp_error_recovery.md` (SPLIT). Plan:
`docs/diagnostics-missing-validation-plan.md` §8. Depends on parts 1-2 for the
implemented behavior.

## Scope
Add `test_lsp_error_recovery.py` that locks in LSP/front-end error recovery for
an unknown declaration followed by a valid struct. The test must construct a
minimal source in the `error_tolerance.mojo` shape (unknown declaration, then a
valid struct such as `Good`) and assert that:
- an error/diagnostic indicating use of an unknown declaration is reported, and
- parsing/compilation continues so the subsequent struct is still
  emitted/recognized.

Keep the test narrow and self-contained (no heavy whole-closure/self-host runs);
follow existing diagnostic regression conventions in this repo.

## Files
- `test_lsp_error_recovery.py` (new)

## Test
`python3 -m pytest -q test_lsp_error_recovery.py` (or the narrowest equivalent
invocation used by sibling diagnostic tests) passes once parts 1-2 land.

## Acceptance
- `test_lsp_error_recovery.py` exists and exercises unknown-declaration recovery
  with a following valid struct.
- The test fails before parts 1-2 and passes after them (serves as the regression
  gate for the split work).
- Satisfies the original doc's acceptance: "Add `test_lsp_error_recovery.py`."
