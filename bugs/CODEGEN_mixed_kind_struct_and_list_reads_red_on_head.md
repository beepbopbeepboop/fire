# CODEGEN: one gimple runner case is still red (mixed-kind struct/list reads)

Found 2026-10-29 while verifying `CODEGEN_nested_list_param_two_kinds_segfaults`.
Four `test_gimple_runner.py` cases were red on HEAD.

## Status

**PARTIAL (2026-10-29, branch work/fix-gate-gimplerunner).** Three of the four
cases are fixed and pass alone; the fourth is still red and its root cause is
the open method-receiver bug below.

Landed:

- `gimple_heterogeneous_list_literal_keeps_each_slot`: a heterogeneous scalar
  literal (`[1, 2.5]`) now records its per-slot kinds in
  `gen._struct_slot_kinds` (emit_exprs `_lower_list_literal`), so `print(a)`
  routes through `mojo_repr_list_kinds` instead of the single `double` ctype.
- `gimple_struct_mixed_reads_survive_a_derivation`: a copy of a mixed value
  carries the source's static kinds and element type (emit_calls `list()`
  copy hand-off, which used to pop the element type for every source without a
  nested spec); a derived mixed list with no static table reads its own
  runtime row (emit_infra `_list_repr_fn` / `_list_repr_call`); and
  `mojo_list_inherit_kinds` (runtime/fire_runtime.c) replaces the destination's
  summary-derived element repr with NULL when the source has a kinds row, since
  the element repr otherwise overrides every per-slot kind.
- `gimple_struct_mixed_reads_survive_a_function_boundary`: the same
  `mojo_list_inherit_kinds` / copy path.

Still red:

- `gimple_ctor_param_polymorphic_slot_reads_receiver` (test_gimple_runner.py):
  `L(T(2)).numel()` prints a heap address. Root cause and next step are in
  `bugs/CODEGEN_unresolved_method_receiver_returns_its_own_pointer.md`. That
  doc's area is claimed by another worker, so it was not touched here.

## Next step

Once `CODEGEN_unresolved_method_receiver_returns_its_own_pointer` lands, re-run
`test_gimple_runner.py`; if the remaining case is green, delete this doc in the
same commit.
