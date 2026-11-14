# `tools/dangling_doc_refs.py --ratchet` is red on master for the codegen walk-memo citation

**Job:** `doc-refs` (in `check`). Found while merging
`work/fix-merge-fix-proof-fix-replan-diagnostics-mojoc-imports` into master
(commit `ad17707cd`) — the ratchet fails the same on pristine master; the
merge did not introduce the row.

Reproduce (from a master checkout):

    python3 tools/dangling_doc_refs.py --ratchet

Seen, 2026-11-13:

    ratchet: 2 file(s) cite MORE deleted docs than tools/dangling_refs_baseline.py allows:
      bugs/SUITE_self_test_red.md: 1 (baseline 0) — hard/DIAGNOSTICS_mojoc_imports-part2.md
      test_codegen_yield_from_walk_ast_memo.py: 1 (baseline 0) — CODEGEN_walk_ast_memo_cpp_yield_from.md


The `bugs/SUITE_self_test_red.md` row is already tracked there (the claim
`fix-merge-bug-suite-self-test-red-2`, `bug:SUITE_self_test_red`); do not
duplicate it.

The `test_codegen_yield_from_walk_ast_memo.py` row is this doc: master
deleted `bugs/CODEGEN_walk_ast_memo_cpp_yield_from.md` in
`08eeb70b4` ("bugs: remove CODEGEN_walk_ast_memo_cpp_yield_from (fixed by
invalidating walk memo)") but the test landed in `40985caba` ("codegen:
prove the yield-from walk-memo invalidation covers the enclosing call")
and cites the deleted doc at its header (line 2 and line 6,
"the deleted doc, bugs/CODEGEN_walk_ast_memo_cpp_yield_from.md"). The
citation names a bug doc that no longer exists, so it is dangling by
construction.

Expected: the ratchet is green (or this file's row is either fixed or
explicitly allowed by the baseline).

Next step: rewrite the two header mentions in
`test_codegen_yield_from_walk_ast_memo.py` to name the BUG, not the deleted
doc (e.g. "the walk-memo invalidation fix, `08eeb70b4`"), per the ratchet's
own message and CLAUDE.md — or raise the ceiling in
`tools/dangling_refs_baseline.py` for that file deliberately, after reading
the diff. Do not edit the file without the `fix-proof-bug-codegen-walk-ast-memo-cpp-yield-from`
lane's sign-off if their claim is still open; it is that lane's code.
