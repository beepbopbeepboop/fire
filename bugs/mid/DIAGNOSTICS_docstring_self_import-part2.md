# DIAGNOSTICS step 9 part 2: Reject self-imports in docstring code blocks

## Goal
Extend the import checker to scan mojo code blocks extracted from docstrings
(for module X) and reject any `import X` (or equivalent self-import) found
there with the diagnostic: `module 'X' cannot import itself`.

## Dependencies
- DIAGNOSTICS_docstring_self_import-part1 (docstring mojo code-block extraction)

## Scope
- Integrate extracted docstring code blocks into import validation.
- Detect self-imports in those blocks using the module's canonical name.
- Emit the exact message `module 'X' cannot import itself` at an appropriate
  location (pointing into the docstring/code block).
- Add `test_docstring_self_import.py` covering the case from the modular test
  `docstring_self_import.mojo`.

## Files likely involved
- Import resolution/checking logic
- Integration with docstring extraction from part 1
- Tests

## Acceptance
- A docstring containing a ```mojo code block with `import X` inside module X
  fails compilation with `module 'X' cannot import itself`.
- `test_docstring_self_import.py` is added and passes.
- No regressions to normal import behavior.

## Status
- **Open.**
