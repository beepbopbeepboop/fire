# DIAGNOSTICS step 9 part 3: Reject self-imports in docstring code blocks at compile time

Class: **mid** (this doc lives in `bugs/mid/`). Touches the compile pipeline
(`gimple_codegen.py`) and must pick the module's canonical name consistently
with how sibling-`.mojo` import resolution names a file; everything else is
already in place (part 1 landed the extraction API, part 2 lands the
detection).

Parent: `bugs/hard/DIAGNOSTICS_docstring_self_import.md`. Plan:
`docs/diagnostics-missing-validation-plan.md` §9.

Dependencies:
- Part 1 (landed, commit e5aa30996): `mojo/middle/docstring_blocks.py` —
  `extract_module_docstring_mojo_blocks(stmts, source=...)`.
- Part 2: `mojo/middle/docstring_self_import.py` —
  `find_docstring_self_imports(blocks, module_name)`.

## Goal

A module whose docstring contains a `mojo` code block that imports the
module itself must fail compilation with
`error: module 'X' cannot import itself` (the exact message modular uses for
`docstring_self_import.mojo`, plan §9), where `X` is the module's canonical
name, reported at the offending import's location.

## Scope

- In `_run_pipeline` (`gimple_codegen.py`) — where the root module's parsed
  `stmts`, its `source` and `filename` are available — after parsing and
  before lowering: extract the module docstring's mojo blocks and call
  `find_docstring_self_imports` with the module's canonical name.
- Canonical name: the stem of `filename` (no directory, no extension) when a
  filename is given — that is the name sibling-`.mojo` import resolution
  uses for a bare `import X`. When no filename is given, skip the check
  (there is nothing stable to compare against). Package-relative dotted
  module names (`pkg.sub.X`) are out of scope for this part.
- On a hit, raise `RuntimeError` in the style of the missing-module
  diagnostic (`_raise_missing_module` in `mojo/backend_gimple/emit_resolve.py`):
  `<file>:<line>: error: module 'X' cannot import itself`, at the import's
  file line/col from part 2.
- Compile-time only. Docstrings are never executed, so `python3 fire.py run`
  gets no new behaviour.
- If imported modules compiled inside an import closure are parsed through
  the same `_run_pipeline`-adjacent code with a known name, apply the same
  check to them; otherwise restrict this part to the root module and say so
  in this doc's Status. Do not build a second canonical-name mechanism just
  for this.

## Acceptance

- `compile_to_gimple(src, do_imports=True, filename='X.mojo')` for a module
  `X` whose docstring carries a `mojo` block with `import X` raises
  `module 'X' cannot import itself`, naming `X`, at the block's import
  location. Same for the `from X import ...` form and for `import X as Y`.
- A docstring `mojo` block importing some other module `Y` still compiles.
- A module with no docstring, or a docstring with no `mojo` block,
  compiles exactly as before.
- The normal import path (`import X` as ordinary code inside `X` itself) is
  unchanged by this part — whatever it does today it still does; the check
  fires only for docstring blocks.

## Done when

File: `test_docstring_self_import.py` (repo root, new). It must carry the
standard `if __name__ == '__main__':` runner block (like
`test_import_missing_module_diagnostic.py`) so running the file executes the
tests. It covers, through `compile_to_gimple` with
`do_imports=True, filename='docstring_self_import.mojo'`: the failing
`import X` case, the `from X import ...` case, the non-self control, and the
clean no-self-import control — i.e. the modular `docstring_self_import.mojo`
case end to end.

Command (this compiles in-process; wrap in the memory reservation):

    python3 tools/memslot.py --gb 8 --label docstring-self-import -- python3 test_docstring_self_import.py

Cheap enough for the gate's fast tier (seconds; same shape as
`test_import_missing_module_diagnostic.py`).

## Not in this part

`tools/suite.py` registration; interpreter-side enforcement; dotted/package
module names; `.mojoc` precompiled imports; narrowing or widening the
self-import rule from part 2 (if §9's modular golden file disagrees with
"root dotted component", change part 2's rule and note it there).

## Status

- **Open.**
