# CODEGEN: `coro._attribute_to_def` writes AST line/col without invalidating the walk memo

Status: OPEN. Filed 2026-11-12 from the regex-scan worker's `test_gimple.py` run (HEAD 9dc338893). Not caused by that change; `mojo/middle/coro.py` is untouched by it.

## Symptom

`python3 test_gimple.py` reports one failure outside the regex work:

    FAIL  every_ast_mutation_site_invalidates_the_walk_memo: 1 problem(s):
      mojo/middle/coro.py::_attribute_to_def writes an AST node's field (4635 `line`, 4636 `col`) and never invalidates the memo - either call `_walk_ast_invalidate(<the node it wrote>)` there, or add the key to `_WALK_AST_MUTATION_ALLOWLIST` with the reason

The test is `test_gimple.py` around line 11700. It enforces that every site writing an AST node's fields also calls `_walk_ast_invalidate` (defined in `mojo/middle/exprtypes.py:86`) so a memoised walk is not served stale.

## Code

`mojo/middle/coro.py`, `_attribute_to_def` (~line 4625):

    for stmt in prologue:
        stmt.line = fn.line
        stmt.col = fn.col
    return prologue

## Expected

Either call `_walk_ast_invalidate(stmt)` after the two assignments, or, if the writes cannot change any walk result, add the key to `_WALK_AST_MUTATION_ALLOWLIST` with a reason. The invalidate call is the default, since `line`/`col` feed `#line` emission and a stale memo there is exactly the failure the test guards.

## Next step

1. `python3 test_gimple.py` and confirm the single FAIL above.
2. Read both call sites before choosing the form: `_async_method_setup` (around
   `coro.py:4668`) and the async-generator lowering (around `coro.py:8556`) both
   run in `lower()`, before `gen_module` walks the tree, and both hand
   `_attribute_to_def` a `prologue` of freshly synthesized `VarDecl` nodes built
   immediately above the call. If no `gen_module` path can reach an already-walked
   prologue, the reasoned `_WALK_AST_MUTATION_ALLOWLIST` entry is correct (the
   writes cannot change any walk result). If one can, invalidate instead.
3. If invalidating: add `_walk_ast_invalidate(stmt)` inside the loop in
   `_attribute_to_def` (import it from `mojo.middle.exprtypes` the same way the
   neighbouring call sites do).
4. Re-run `test_gimple.py`; the FAIL must clear and the count of failures must be 0.
