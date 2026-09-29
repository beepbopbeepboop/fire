# CODEGEN: closure environments and boxed mutable locals are never freed

## Status (2026-09-28 — OPEN, measured; deliberately not started)

A loop that creates a capturing lambda and calls a function containing a
capturing nested `def` leaks about 90 B per iteration (peak RSS 13.9 MB at
100,000 iterations, 41.0 MB at 400,000). The pieces: the environment struct
(`malloc(sizeof env)` per closing lambda/nested def), the bound-method object
that wraps it (`mojo_bound_method_new`: a `malloc` plus an entry in
`_reg_bound_method` that is never removed), and the box for a mutable captured
local (`malloc(8)` in the function prologue, once per call).

## Why it is not a small change

1. **The closure's own lifetime.** All three die with the creating scope only if
   the closure never escapes: it is bound to a local that is only ever *called*
   (never returned, stored, passed on, or captured by another closure). That is a
   new escape analysis over callables.
2. **Functions containing a nested `def`/`lambda` are excluded from ownership
   analysis entirely** (`_is_free_eligible_function`), so they also get no
   container freeing. Lifting the exclusion has two traps found while looking:
   - inside a closure the analysis still treats `d[k]`, `d.x`, `d[a:b]` and
     `for x in d` as safe receivers, so `lambda k: d[k]` would NOT disqualify `d`.
     The receiver rules must be switched off when `in_closure`;
   - a nested function is lowered in the middle of its parent, and its
     `begin_function` resets every per-function ownership table
     (`_owned_free_candidates`, `_scope_live`, `_fresh_vals`, ...). The parent's
     state would be lost or, worse, stale. All of it needs saving and restoring
     around a nested lowering.
3. `_reg_bound_method` needs a way to drop an entry when the bound method is freed
   (or bound methods need an in-band tag instead of a registry).

## Done when

The loop above is flat between 100k and 400k iterations, output unchanged, and
`lambda k: d[k]` with `d` a local container demonstrably keeps `d` alive (add both
as runner tests). `make gate` green.
