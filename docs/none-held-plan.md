# Plan: Flow-sensitive None tracking (CODEGEN_a_none_held...)

Source bug: bugs/hard/CODEGEN_a_none_held_in_an_int64_local_is_indistinguishable_from_zero_in_membership.md

## Decomposition

Step 1 — Track None-ness per local at if/while/try join points
  Add a dataflow pass: for each local, record whether it is None on each path.
  Files: mojo/backend_gimple/emit_exprs.py (none_only_locals, _names_bound_by)
  Test: probe `n=None; if cond: n=1; print(n in ["a",None])` prints True.

Step 2 — Consult flow-sensitive info in is_none_needle
  Use the join-point info instead of the global none_only_locals set.
  Files: emit_exprs.py (is_none_needle)

Step 3 — Dict/set None-needle arm
  Extend _lower_in_dispatch dict/set arms to consult the None info.
  Files: emit_exprs.py

Step 4 — Pinned test
  test_gimple_matches_cpython for n=None used as in needle.
