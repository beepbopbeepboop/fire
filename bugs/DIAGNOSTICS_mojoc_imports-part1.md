# DIAGNOSTICS mojoc imports, part 1: implicit default param conformance on precompiled import

Replanned from `bugs/hard/DIAGNOSTICS_mojoc_imports.md` (umbrella step 10 of
`docs/diagnostics-missing-validation-plan.md`). The original conformance-error
case landed separately; this part covers `import_mojoc_implicit_default_param.mojo`.

## Goal

When instantiating an imported (precompiled `.mojoc`) struct whose stored
signature includes an implicit/defaulted parameter, a type argument that
violates the parameter's trait constraint must produce the same conformance
diagnostics as the source path, including the note pointing at the declaration
and the synthetic signature detail line.

## Acceptance

For the modular fixture corresponding to `import_mojoc_implicit_default_param.mojo`
(`Container[T: Marked, W: Wrapper = Wrapper(4)]` instantiated as
`Container[NotMarked]()` with the source removed and `Container` imported from a
precompiled module), compilation reports a non-zero exit and emits:
- `error: 'Container' parameter 'T' has 'Marked' type, but value has type 'AnyStruct[NotMarked]'`
- `note: 'Container' declared here`
- the rendered synthetic signature line for `Container` (matching the modular
  `CHECK-SAME` / `# note - synthetic signature` expectation).

## Done when

File: `test_mojoc_implicit_default_conformance.py` (repo root)
Command: `python3 test_mojoc_implicit_default_conformance.py`

This quick in-process test (parse/elaborate against the precompiled signature
record; no native build) must pass and assert the error, note, and synthetic
signature lines above.
