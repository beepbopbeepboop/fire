# DIAGNOSTICS mojoc imports: implicit-default bracket parameter diagnostic (part 2)

## Goal

Ensure a `.mojoc` struct with an implicit-default bracket parameter reports the full three-line conformance diagnostic when instantiated with a non-conforming type, matching modular's `import_mojoc_implicit_default_param.mojo` behavior.

## Acceptance

- The diagnostic includes the parameter/type mismatch line, the declaration note, and the synthetic signature line spelling the stored implicit conversion default without resolving it.
- A regression test covering this case exists and passes.

## Done when

File: `test_mojoc_implicit_default_conformance.py`

Command: `python3 test_mojoc_implicit_default_conformance.py`

This test must pass, demonstrating the full diagnostic is produced for an implicit-default precompiled import.
