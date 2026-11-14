# DIAGNOSTICS mojoc imports: precompiled conformance error (part 1)

## Goal

Ensure importing a precompiled `.mojoc` module whose stored signature violates a trait bound reports the conformance error, matching modular's `import_mojoc_conformance_error.mojo` behavior.

## Acceptance

- Instantiating an imported precompiled struct with a type that does not satisfy its stored trait bound produces the expected conformance diagnostic (not a silent accept).
- A conforming instantiation and the link-mode build path continue to behave correctly.
- A regression test covering this case exists and passes.

## Done when

File: `test_mojoc_import_conformance.py`

Command: `python3 test_mojoc_import_conformance.py`

This test must pass, demonstrating the conformance error is reported for a violating precompiled import.
