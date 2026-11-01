# GATE: `make check` job `gimple` is red: eight AST mutation sites do not invalidate the walk memo

## Status (2026-11-01, OPEN)

`python3 test_gimple.py` (the `gimple` job) fails this case:

```
FAIL  every_ast_mutation_site_invalidates_the_walk_memo: 8 problem(s):
```

The test requires every function that writes an AST node's field to call `_walk_ast_invalidate` on that node, or to list
the key in `_WALK_AST_MUTATION_ALLOWLIST` with a reason. Eight sites do neither:

- `mojo/middle/coro.py`: `_ParamFlow.__init__` (line 1167), `_specialize_mixed_generator_callers` (1528, 1532, 1533),
  `_rewrite_fn` (5632, 5644)
- `mojo/backend_gimple/cpp_core.py`: `drain` (7607), `_cpp_rewrite_yields` (5420), `rewrite` (5712)
- `mojo/backend_gimple/module_gen.py`: `_mark_presence_field` (1474, `.append` on `presence_fields`), `_declare_posthoc_class_attrs` (3850, `.append` on `fields`)

Without the invalidation, a memoised walk can return a stale result after one of these writes.

## Next step

For each of the eight, decide one of two things, and do it in the same commit:

1. If the write changes a node that a memoised walk reads, call `_walk_ast_invalidate(<the node written>)` right after the
   write. This is the default.
2. If the write only touches a node that no memoised walk ever sees (a fresh node built inside the same pass), add the key to
   `_WALK_AST_MUTATION_ALLOWLIST` with that reason written out.

Do not add a blanket allowlist entry. The test exists to make each site a decision.

## Quick test

`python3 test_gimple.py` shows `every_ast_mutation_site_invalidates_the_walk_memo` as PASS. Then this doc is deleted.
