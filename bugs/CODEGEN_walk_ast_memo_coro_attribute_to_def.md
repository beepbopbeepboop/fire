# CODEGEN: coro.py `_attribute_to_def` mutates AST line/col without invalidating the walk memo

**Found:** 2026-11-12, `python3 test_gimple.py` on branch work/bug-codegen-genexp-local-single-consumpt (master 4f0c96712).

## Symptom
```
FAIL every_ast_mutation_site_invalidates_the_walk_memo: 1 problem(s):
  mojo/middle/coro.py::_attribute_to_def writes an AST node's field (4635 `line`, 4636 `col`) and never invalidates the memo - either call `_walk_ast_invalidate(<the node it wrote>)` there, or add the key to `_WALK_AST_MUTATION_ALLOWLIST` with the reason
```
The rest of test_gimple.py passes (448 passed, 1 failed).

## Expected
Every AST-mutation site invalidates the `_walk_ast` memo (or is on the allowlist with a reason), so the
test passes.

## Likely cause
`681c07503 codegen: stack-switch generator bodies carry #line directives` added line/col writes in
`mojo/middle/coro.py::_attribute_to_def` (around lines 4635-4636). That function writes `line`/`col` on a
node that the walk memo may have cached, and does not call `_walk_ast_invalidate`.

## Next step
1. Read `_attribute_to_def` (mojo/middle/coro.py ~4620-4640) and decide whether the written node can be
   memoised. If yes, call `_walk_ast_invalidate(<node>)` right after the write. Prefer this over the allowlist.
2. If the write is provably memo-neutral (line/col are not read through the memo), add the key to
   `_WALK_AST_MUTATION_ALLOWLIST` with that reason instead, and say so in the commit.
3. Quick test: `python3 test_gimple.py` and confirm `every_ast_mutation_site_invalidates_the_walk_memo` PASSES.
   It is the test that found this; there is no separate pinning test.
