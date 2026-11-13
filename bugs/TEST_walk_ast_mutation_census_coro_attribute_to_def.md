# TEST: the walk-memo mutation census is red on `coro.py::_attribute_to_def`

**Found:** 2026-11-12, while running `python3 test_gimple.py` as the quick test
for the tuple-slot mixed-container refusal. Pre-existing on the worktree's base
commit (`0fc26bf13`); no change of this lane's was applied when it failed.

## Symptom

`python3 test_gimple.py` ends `447 passed, 1 failed`, and the failure is not
the tuple-slot case:

    FAIL  every_ast_mutation_site_invalidates_the_walk_memo: 1 problem(s):
      mojo/middle/coro.py::_attribute_to_def writes an AST node's field
      (4635 `line`, 4636 `col`) and never invalidates the memo - either call
      `_walk_ast_invalidate(<the node it wrote>)` there, or add the key to
      `_WALK_AST_MUTATION_ALLOWLIST` with the reason

## Where it came from

`681c07503` ("codegen: stack-switch generator bodies carry #line directives",
2026-11-12 15:44) added `_attribute_to_def` (coro.py, around line 4625), which
sets `stmt.line` / `stmt.col` on each synthesized prologue statement. The
commit deleted its own bug doc and added
`test_line_directives_per_generated_line.py`, but did not teach
`test_gimple.py`'s mutation census about the new write: the function is not in
`_WALK_AST_MUTATION_ALLOWLIST` and does not call `_walk_ast_invalidate`.

## Expected

`python3 test_gimple.py` green (the census has no unclassified site).

## Next step

Decide with evidence which of the two the census asks for:

1. The writes are on freshly built prologue statements that no walk has seen,
   so the allowlist entry is the honest one — add
   `"mojo/middle/coro.py::_attribute_to_def": "<the fresh-node reason>"` next
   to the other `coro.py` entries.
2. If any of those statements can be a node an earlier walk memoized, call
   `_walk_ast_invalidate(stmt)` after the writes instead.

Then run `python3 test_gimple.py` and
`python3 test_line_directives_per_generated_line.py`; the `#line` behaviour the
commit added must stay green.
