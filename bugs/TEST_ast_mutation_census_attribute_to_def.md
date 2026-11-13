# TEST: `every_ast_mutation_site_invalidates_the_walk_memo` is red at `coro.py::_attribute_to_def`

Status: OPEN. Found 2026-11-12 by the `re.sub` named-callback worker on HEAD
bd96d4ba8 while running `test_gimple.py` as the covering file for that fix.
Unrelated to that fix: `mojo/middle/coro.py` is not touched by it, and the
failure reproduces with the fix reverted.

## Symptom

    python3 tools/memslot.py --gb 8 --label test-gimple -- python3 test_gimple.py

ends `Results: 449 passed, 1 failed` with:

    FAIL  every_ast_mutation_site_invalidates_the_walk_memo: 1 problem(s):
      mojo/middle/coro.py::_attribute_to_def writes an AST node's field
      (4635 `line`, 4636 `col`) and never invalidates the memo - either call
      `_walk_ast_invalidate(<the node it wrote>)` there, or add the key to
      `_WALK_AST_MUTATION_ALLOWLIST` with the reason

Expected: the census is green, so any red it reports is a genuine stale-memo
hazard rather than background noise in every `test_gimple.py` run.

## Root cause

`_attribute_to_def(prologue, fn)` (mojo/middle/coro.py, just above
`_async_method_setup`) stamps each synthesized prologue statement with the
generator `def`'s source position:

    for stmt in prologue:
        stmt.line = fn.line
        stmt.col = fn.col

Those statements are AST nodes created by the coroutine lowering, so writing
`.line`/`.col` on them changes what a memoized `walk_ast` of the enclosing
tree can return. The file already calls `_walk_ast_invalidate` at its other
mutation sites (lines 1717-1728, 3848, 6402-6423, ...), and the census in
`test_gimple.py` attributes a write to its innermost function, so this loop is
the one site that has no invalidation. It arrived with the `#line`-directive
commit (`681c07503 codegen: stack-switch generator bodies carry #line
directives`).

## Next step

In `_attribute_to_def`, invalidate each statement whose fields were written —
inside the loop, after the two stores:

    _walk_ast_invalidate(stmt)

(or, if that is measured to be too much work per prologue, add the
`mojo/middle/coro.py::_attribute_to_def` key to
`_WALK_AST_MUTATION_ALLOWLIST` in `test_gimple.py` with the reason that the
nodes are synthesized and not yet reachable from any memoized tree).

The quick test is `python3 test_gimple.py`, whose
`every_ast_mutation_site_invalidates_the_walk_memo` case is the one that
currently reports this; then delete this doc in that commit.
