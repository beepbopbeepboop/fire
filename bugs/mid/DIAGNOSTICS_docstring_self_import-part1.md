# DIAGNOSTICS step 9 part 1: Extract mojo code blocks from docstrings

## Goal
Add infrastructure to extract ```mojo fenced code blocks from module docstrings (and
potentially other docstrings as needed). This is the "docstring code-block extraction
(new)" piece required for detecting self-imports inside docstring examples.

## Scope
- Identify and parse module-level docstrings.
- Extract fenced code blocks tagged as `mojo` (and possibly untagged blocks if
  the language is inferred as mojo).
- Provide a reusable API for other passes/checkers to access extracted blocks
  with source locations.

## Files likely involved
- Parser/AST (to access docstrings)
- New extraction utility/module (as implied by "docstring code-block extraction (new)")

## Acceptance
- Given a module with a triple-quoted docstring containing ```mojo ... ``` blocks,
  the extractor returns them with correct line/column information.
- Extraction does not affect normal parsing or compilation of non-docstring code.
- Unit-testable in isolation (or verifiable by inspection).

## Status
- **Open.**
