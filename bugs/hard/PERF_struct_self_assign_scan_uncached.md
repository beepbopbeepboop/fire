# HARD BUG (performance, remainder): struct self-assign scan is uncached; per-level generated-C text joins still grow with the closure

Successor to the closed `_walk_ast` re-scan bug. The AST-node rescan it was
named for is fixed and pinned (see "What is fixed" below). Two costs it
measured are NOT fixed, and this doc carries them so the queue stays honest.

## What is fixed (do not re-open)

`_walk_ast` (`mojo/middle/exprtypes.py`) is memoized on node identity with
per-node invalidation (`_walk_ast_invalidate`, 17 call sites) and cleared per
`_run_pipeline` (`_walk_ast_reset`). Measured 2026-10-16 on the synthetic struct
chain through `compile_to_gimple(do_imports=True)`: `_walk_ast_into` node visits
at n=20/40/80/160 are 31,232 / 62,512 / 125,072 / 250,192, a flat 2.00x per
doubling (was 3.4x-3.8x and rising). Pinned by `test_gimple.py`:
`walk_ast_memo_is_transparent_and_honours_invalidation`,
`walk_ast_memo_never_answers_stale_over_real_compiles`,
`every_ast_mutation_site_invalidates_the_walk_memo`,
`no_walk_ast_caller_mutates_what_it_is_handed`. Re-verified 2026-10-29:
`python3 test_gimple.py` 403 passed / 0 failed.

## Remainder 1 — `_collect_self_assigns` / `_collect_self_reads` are uncached

- Code: `mojo/middle/module_shared.py` `_gmi_collect_self_assigns` (line ~1143),
  `mojo/backend_gimple/module_gen.py` `_gmi_collect_self_reads` (line ~2602).
- Measured (Phase 9 profile, n=160 struct chain): 26,080 calls, 1.75s cumtime
  of a 23.3s profiled run (7.5%). Largest of the remaining per-level costs.
- Why it was not memoized: it mutates struct ASTs directly
  (`s.fields.append(...)`), so a memo must cache the raw syntactic shape and
  re-derive the type from three live pieces of state on every call. The
  invalidation hook now exists (`_walk_ast_invalidate`), so the remaining
  question is the re-derivation, not the invalidation.
- Next step: measure the re-derived-type inputs on the n=160 chain; if the
  three live inputs are a small fixed set, cache the shape keyed on node
  identity with `_walk_ast_invalidate` on each struct mutation, and prove the
  result equal to a fresh walk over the real compiles (copy the shape of
  `walk_ast_memo_never_answers_stale_over_real_compiles`).

## Remainder 2 — wall clock is still superlinear (per-level text join)

- Measured (Phase 10, same benchmark): 0.18 / 0.51 / 1.74 / 6.95 s at
  n=20/40/80/160, ratios 2.8x / 3.4x / 4.0x. Node visits are linear; wall is not.
- Cause as recorded: each level's emitted `parts` contain its whole import
  closure, so `_dedup_variadic_externs` and the module join cost one
  `'\n'.join` of O(cumulative) text per level. The Phase 8 entry (in the
  closed doc's history) removed the per-byte Python re-reading; the join
  remains. Recorded there as inherent to producing the output.
- Status: NOT attempted. Treat as open only if a whole-closure measurement
  shows the join dominates; the 160-module chain does not establish that.

## Not run

Whole-closure memory of the memo (1,279 entries / 23,212 parent edges at n=160;
never measured on a whole-closure self-host compile). Integrator's gate should
record peak RSS for the `stage2` dump when it runs.
