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

## Status (2026-11-13)

The test exists (32d00561e) and parts 1-2 have landed, but the test still FAILS,
so this remains open. Measured with
`python3 tools/memslot.py --gb 8 --label lsp-recovery -- python3 test_lsp_error_recovery.py`:

    AssertionError: expected a 'use of unknown declaration' diagnostic,
    got errors=[]

Cause is in the test, not in the parts 1-2 behaviour: its source is a bare
`asdf` at module scope, which the parser accepts as an ordinary expression
statement (`parse_module(recover=True)` yields `[ExprStmt, StructDef]` with
`errors == []`) and which `compile_to_gimple` compiles silently with `struct
Good` present. A real recovered error is made by a malformed declaration (part
1's `def\n`) or an unknown decorator (part 2's `@align(missing)`), and part 2's
test `test_lsp_error_recovery_part2.py` already pins the diagnostic-plus-`Good`
behaviour at such a source.

Next step, for this doc's owner: decide whether `test_lsp_error_recovery.py`
(a) rewrites `UNKNOWN_DECL_SRC` to a real unknown declaration and asserts at
the compilation layer, or (b) is retired as a duplicate of
`test_lsp_error_recovery_part2.py`; then the file can be registered. Until
then it is listed (not registered) in `test_suite.py`'s `UNREGISTERED` as RED
with this doc cited, which is what made the estate check green.
