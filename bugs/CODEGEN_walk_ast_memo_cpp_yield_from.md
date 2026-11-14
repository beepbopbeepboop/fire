# CODEGEN: `test_gimple` walk-memo lint flags `_cpp_yield_from`'s member rewrite

## What I ran

    python3 tools/memslot.py --gb 8 --label gimple -- python3 test_gimple.py

(the `gimple` job in `tools/suite.py`'s `check` bucket).

## What I saw

460 passed, 1 failed:

    FAIL  every_ast_mutation_site_invalidates_the_walk_memo: 1 problem(s):
      mojo/backend_gimple/cpp_core.py::_cpp_yield_from writes an AST node's
      field (12136 `member`, 12134 `member`) and never invalidates the memo -
      either call `_walk_ast_invalidate(<the node it wrote>)` there, or add the
      key to `_WALK_AST_MUTATION_ALLOWLIST` with the reason

The two writes are `call.func.member = _self_method_name` in
`mojo/backend_gimple/cpp_core.py::_cpp_yield_from` (lines 12134 and 12136 in
this tree). `_cpp_yield_from` previously only read `call.func.member`; commit
c27e278c8 ("codegen: delegate yield from to a claimed nested generator",
2026-11-13 19:08) added the rewrite, after `test_gimple.py`'s last change
(8335f7693, 2026-11-13 17:20), and did not invalidate the walk memo for the
node it rewrites.

## Expected

`python3 test_gimple.py` exits 0, and every function that writes a field on an
AST node either calls `_walk_ast_invalidate(<node>)` or is classified in
`_WALK_AST_MUTATION_ALLOWLIST` (`test_gimple.py:68`).

## Not this merge's fault

Identical on current master: `git diff master -- mojo/backend_gimple/cpp_core.py
test_gimple.py` is empty. It was found while merging
work/fix-merge-bug-diagnostics-mojoc-imports-part1 and is filed rather than
edited because `cpp_core.py` belongs to the `yield from` / COMPILE_FAIL_Tools
lanes.

## Exact next step

`cpp_core.py` already imports `_walk_ast_invalidate` (line 46) and calls it for
other rewrites (lines 8560, 9027). After line 12136, call
`_walk_ast_invalidate(call)` once if either rewrite fired (the node written is
`call`), then rerun the command above. Do not add the key to the allowlist: the
memo is observable for this node, so a stale entry is a real wrong answer, not
an unobservable write.
