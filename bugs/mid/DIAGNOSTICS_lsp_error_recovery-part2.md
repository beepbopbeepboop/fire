# DIAGNOSTICS_lsp_error_recovery part 2: report diagnostic and emit following declarations

## Parent
`bugs/hard/DIAGNOSTICS_lsp_error_recovery.md` (SPLIT). Plan:
`docs/diagnostics-missing-validation-plan.md` §8. Depends on part 1 for parser
continuation.

## Scope
Ensure the front-end/LSP-facing compilation path reports the recovered
`use of unknown declaration` diagnostic while still emitting/retaining the
declarations that follow the recovered error. For a file with an unknown
declaration followed by a valid struct, compilation/reporting must include the
error and must still produce the struct declaration in the module output (e.g.
the emitted decl/listing used by downstream checks, such as `lit.struct.decl
@Good` in the modular `error_tolerance.mojo` expectation).

## Files
The front end's diagnostic reporting and declaration emission/LSP-facing output
path that consumes recovered parse results (parser front end / module emission
as applicable).

## Test
Processing a file with an unknown declaration followed by a valid struct
reports `use of unknown declaration` and still emits the struct (observable via
the compiler's module/decl output or the API the regression test inspects).

## Acceptance
- The diagnostic for the unknown declaration is reported.
- The following valid struct is still emitted/present after recovery.
- Behavior matches the modular `error_tolerance.mojo` shape described in the
  plan: error followed by `lit.struct.decl @Good` (or this compiler's equivalent
  observable).
- Covered by `test_lsp_error_recovery.py` (part 3).
