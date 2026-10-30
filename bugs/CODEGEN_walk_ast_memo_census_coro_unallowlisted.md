# test_gimple: `every_ast_mutation_site_invalidates_the_walk_memo` fails on two `mojo/middle/coro.py` sites

Found 2026-10-29 while running `test_gimple.py` for the decorator-application
fix. Not caused by that change: `mojo/middle/coro.py` is untouched on the
branch and was last changed in `4c6cac624`, which is already on master.

## What was run

    python3 tools/memslot.py --gb 8 --label gimple-decorator -- python3 test_gimple.py

Result: `413 passed, 1 failed`. The one failure:

    FAIL  every_ast_mutation_site_invalidates_the_walk_memo: 2 problem(s):
      mojo/middle/coro.py::_capture_self_into_generator writes an AST node's field
        (5468 `params`, 5473 `body`, 5479 `.append` on `args`) and never invalidates
        the memo ...
      mojo/middle/coro.py::_finish_sync_hoist writes an AST node's field
        (5548 `body`, 5556 `name`) and never invalidates the memo ...

## Expected

Each function either calls `_walk_ast_invalidate(<node it wrote>)` after its
writes, or has a reasoned entry in `_WALK_AST_MUTATION_ALLOWLIST` in
`test_gimple.py`. Per CLAUDE.md, the answer must be decided by reading the
writes, not by adding an allowlist entry to silence the census.

## Next step

1. Read `_capture_self_into_generator` (`mojo/middle/coro.py:5454`) and
   `_finish_sync_hoist` (~`:5540`). Decide whether each write targets a node
   that was already walked (then `_walk_ast_invalidate` on the mutated parent
   is required, and the missing call is the bug) or a fresh node built in the
   same function (then an allowlist entry with that reason is correct).
2. If the first: add the invalidation call after the writes and keep the
   test's expectation. Add a regression only if the stale-walk is observable.
3. Run `python3 tools/memslot.py --gb 8 --label x -- python3 test_gimple.py`
   and confirm 0 failed.
