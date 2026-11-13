# DIAGNOSTICS step 9 part 2: Detect self-imports in extracted docstring code blocks

Class: **mid** (this doc lives in `bugs/mid/`). Not a one-liner: docstring
example blocks are often FRAGMENTS that do not parse as a whole module, so the
detector needs a real parse with a line-scan fallback, plus location mapping
back into the source file.

Parent: `bugs/hard/DIAGNOSTICS_docstring_self_import.md`. Plan:
`docs/diagnostics-missing-validation-plan.md` §9.

Landed already: part 1 (the extraction API this part consumes) —
`mojo/middle/docstring_blocks.py` (`extract_module_docstring_mojo_blocks`,
`DocstringCodeBlock` with `.code`, `.line`, `.col`, `.fence_line`,
`.end_fence_line`), commit e5aa30996, regression tests
`test_docstring_mojo_blocks.py`.

Part 3 (this doc's sibling) wires this detection into the compiler and emits
the diagnostic; this part is DETECTION ONLY.

## Goal

Given a module's canonical name and the mojo code blocks extracted from its
docstring, find every import inside those blocks that imports the module
itself, and report it with a 1-based source location pointing into the file
(the block's `.line`/`.col` plus the import statement's offset within the
block's code).

In scope for detection:

- `import X`, `import X.y`, `import X as Y`
- `from X import ...` / `from X.y import ...`
- `lazy import X`, `lazy from X import ...` (PEP 810 spelling, see
  `fire_compiler.py`'s `ImportStmt.lazy` / `FromImportStmt`)
- `from .X import ...`? — NOT a self-import via dotted spelling; skip relative
  imports in this part (part 3 decides if they matter).

Rule: compare the ROOT dotted component of the imported module against the
module's canonical name — and also the full dotted path when the canonical
name itself is dotted. `import X.sub` inside module `X` therefore counts as a
self-import (the root object imported is `X`); if the modular test for §9
disagrees, narrow the rule to exact equality and note it in this doc's
Status.

Docstring example blocks are frequently not complete modules (they may be
an expression, a bare statement, or use `>>>` prompts). The detector must not
silently drop a self-import because a block is not a parseable module:

1. Try the real parser first: `fire_compiler.py_tokenize(block.code)` +
   `fire_compiler.Parser(...).parse_module()`, then walk the top-level
   statements for `ImportStmt` / `FromImportStmt`.
2. If the block fails to tokenize or parse, fall back to a line scan: for
   each line, recognise `import X[...]`, `from X import ...`,
   `lazy import ...`, `lazy from ... import ...` (optionally indented, and
   ignoring trailing comments), and treat it as the import statement.

## Deliverable

New module `mojo/middle/docstring_self_import.py`, pure (no compiler state,
no I/O beyond its inputs), e.g.:

    def find_docstring_self_imports(blocks, module_name) -> list[SelfImport]

`SelfImport` carries at least: the block, the imported module name, and the
1-based `(line, col)` in the FILE of the import statement (from
`block.line`/`block.col` plus the statement's position inside `block.code`;
parser positions inside the block are relative to the block's first code
line, so map them back by adding `block.line - 1`).

## Acceptance

- Each import form above inside a `mojo` block is detected, with the correct
  file line/col.
- `import X` where the module is NOT `X` is not reported; `import Y` where
  the module is `X` is not reported.
- A block that does not parse as a module still yields its self-imports
  (fallback path) — e.g. a bare `import X` line with no enclosing
  statements is fine, fragments with `>>>` prompts are not reported but must
  not crash the scan.
- No module docstring / no blocks / unterminated fence → empty result, no
  exception.

## Done when

File: `test_docstring_self_import_blocks.py` (repo root, new). It must carry
the standard `if __name__ == '__main__':` runner block (like
`test_import_missing_module_diagnostic.py`) so running the file executes the
tests.

Command:

    python3 test_docstring_self_import_blocks.py

(plain unit test; imports `fire_compiler` and `mojo.middle.docstring_blocks` /
`mojo.middle.docstring_self_import` only; runs in seconds.)

The test covers each import form, the non-self control, the fallback path
(block that does not parse), the empty/no-docstring case, and the
line/col mapping back into the file.

## Not in this part

Wiring the check into `compile_to_gimple`, the
`module 'X' cannot import itself` diagnostic, and
`test_docstring_self_import.py` — that is part 3. No `tools/suite.py`
registration. No interpreter change (docstrings are never executed).

## Status

- **Open.** Cutover from the previous part 2 doc (same path, narrowed and
  given a Done when); the compiler-integration half moved to part 3.
