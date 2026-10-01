# CODEGEN: closure environments and boxed mutable locals are never freed

## Status (2026-09-30 — OPEN, re-measured; one leak removed, the rest stands)

A loop that creates a capturing lambda and calls a function containing a
capturing nested `def` leaks about 90 B per iteration (peak RSS 13.9 MB at
100,000 iterations, 41.0 MB at 400,000). The pieces: the environment struct
(`malloc(sizeof env)` per closing lambda/nested def), the bound-method object
that wraps it (`mojo_bound_method_new`: a `malloc` plus an entry in
`_reg_bound_method` that is never removed), and the box for a mutable captured
local (`malloc(8)` in the function prologue, once per call).

### Re-measured 2026-09-30, with `tools/mem_slope.py`

`tools/mem_slope.py` is the instrument `doc/MEMORY.html` §8 asks for (two sizes,
peak-RSS slope, plus the stale-binary and output-drift guards §8 warns about).
Probes live in `build/memprobes/`. One shape, `{mut}` capture + nested `def` +
bound method, called once per iteration:

    +32.17 B/iter   (4.62 MB at 100k, 13.83 MB at 400k)

That is one `malloc(8)` box + the env struct + `mojo_bound_method_new` per
call, all class E, all still unfreed. The number is lower than the ~90 B in the
Status line above because that figure was for a shape with BOTH a capturing
lambda and a capturing nested `def`; this is the nested-`def` half.

### What was removed from this leak (2026-09-30)

`ownership_destruct.analyze_returns_fresh` refused to call ANY function
fresh-returning if it contained a nested `def`/`lambda` anywhere, on the theory
that a closure might keep the returned container. The parser now records an
explicit capture list (`FunctionDef.captures` / `has_capture_list`), so the
refusal is decided against the actual capture set: a nested `def` with a
name-only list cannot capture a returned name outside it, and `{}` captures
nothing. Anything less certain (no list, a bare `{mut}`/`{var}`, any `lambda`)
still refuses, as before.

Measured on `build/memprobes/callee_returns_fresh.mojo` — a callee that defines
a callback and returns a fresh container, whose caller binds the result in a
loop — with everything else held constant (the old behaviour reproduced exactly
by forcing the capture set to "unknown"):

    before   +138.50 B/iter   (14.77 MB at 100k, 54.39 MB at 400k)
    after     +32.17 B/iter   ( 4.62 MB at 100k, 13.83 MB at 400k)

106 B/iter of the old figure was the CALLER failing to own the callee's fresh
container, which had nothing to do with the closure machinery this file is
about. What remains is exactly the closure cost above: the control probe with
the nested `def` deleted is flat.

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

### Note on item 2, after the 2026-09-30 work

Item 2 is still exactly true and `_is_free_eligible_function` is deliberately
UNCHANGED — the two traps above are not addressed, and lifting it would risk a
wrong free, which is the one failure mode this analysis is built to have none
of. The capture-set machinery that would make lifting it tractable now exists
(`ownership_destruct._nested_capture_names`, used by
`analyze_returns_fresh`), so item 2 is closer to doable than it was, but it is
not done. `analyze_returns_fresh` and `_is_free_eligible_function` ask the same
question on opposite sides of a call — the callee may now be proven fresh with a
closure in it, while the caller's own body with a closure in it is still
excluded — which is intentional, not an inconsistency to tidy away.

## Done when

The loop above is flat between 100k and 400k iterations, output unchanged, and
`lambda k: d[k]` with `d` a local container demonstrably keeps `d` alive (add both
as runner tests). `make gate` green.
