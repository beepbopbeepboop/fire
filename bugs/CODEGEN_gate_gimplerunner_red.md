# Gate job `gimplerunner` is red: gimple runner: compiled programs disagree with expected output

## Status 2026-10-30 — six reds, five fixed, one remains

<<<<<<< HEAD
Reproduces alone (not load): `python3 test_gimple_runner.py`. The reds were SIX,
not five, and they were not one bug:

- `gimple_subclass_overrides_a_class_constant` and `gimple_struct_Struct_class_attr`:
  caused by `3accbab0f`, which made an instance read of a class attribute skip
  the class value entirely (it fell through to the instance-field path and read
  nothing). Fixed in `9bcc2c997`: `_cattr_instance_read` (`mojo/backend_gimple/emit_methods.py`)
  probes the instance's dynamic storage first, under the nothrow flag, with the
  class value as the default, which is CPython's lookup order.
- `gimple_heterogeneous_list_literal_keeps_each_slot`,
  `gimple_struct_mixed_reads_survive_a_derivation`,
  `gimple_struct_mixed_reads_survive_a_function_boundary`: `list(<a mixed list>)`
  was a typed walk over the promoted element type. Fixed in `8cda11b64`
  (`_lower_ctor_from_iterable`, `mojo/backend_gimple/emit_calls.py`): a copy of a
  kind-mixed list is `mojo_list_copy`, which copies the raw words and the kinds row.
  Master's `a98f133ed` fixed the same three cases a second way. The merge keeps
  one mechanism for the copy and the parts of `a98f133ed` that the copy does not
  replace: the copy hand-off of the static element/kind tables for sources that
  are not kind-marked, and `mojo_list_inherit_kinds` replacing the destination's
  element repr with NULL when the source has a kinds row (`runtime/fire_runtime.c`).
  Its literal static-kinds table and derived-list routing (`emit_exprs.py`,
  `emit_infra.py`) were removed: with the raw-word copy in place, no case or
  probe changed output without them, and each duplicated what the runtime kinds row
  already does.
- `gimple_ctor_param_polymorphic_slot_reads_receiver`: STILL RED. A method call
  on a polymorphic slot is lowered to a no-op stub. This is a feature gap, not
  a one-line fix. The plan is in
  `bugs/CODEGEN_unresolved_method_receiver_returns_its_own_pointer.md`.

Previously (branch `work/bug-codegen-imported-function-default-ar`, now merged):
`mojoc` was red on master due to the imported-function trailing-default drop
(`bugs/CODEGEN_imported_function_default_argument_dropped_at_call.md`), fixed in
`work/bug-codegen-imported-function-default-ar`; that doc stays removed.

Coverage hole, fixed in `57b2704de`: seven `test_*` functions in
`test_gimple_runner.py` were never invoked. The `if __name__` guard sat above
them and `main()` ends in `sys.exit`, so nothing ran them. `main()` now calls
them, the guard moved to the end of the file, and a refusal's AssertionError is
counted as a FAIL rather than aborting the tally. Master's
`test_nested_class_attr_from_str_param_regression` had been added with no call
in `main()`; it is in that list now.

Measured after the merge: `python3 test_gimple_runner.py` under
`tools/memslot.py --gb 8`: `488 passed, 1 failed`. The one failure is
`gimple_ctor_param_polymorphic_slot_reads_receiver`. The gate job stays red until
that case is fixed or is registered as a known failure with its doc, which is a
`tools/suite.py` decision for the controller and was not made here.

Found while merging, not fixed here, and not a gimplerunner case:
`b = a[:]` of a kind-mixed list reads its int slot as a double.
See `bugs/CODEGEN_list_slice_of_mixed_list_reads_slot_as_bits.md`.
||||||| parent of a98f133ed (CODEGEN: mixed-kind list literals and copies keep each slot's kind (gimplerunner))
OPEN. Found in the full `make gate` run on the `get_sign` String-argument fix (`974d0e538`, landed 2026-10-28 with the gate red). The failure is not confirmed to come from that fix: `mojoc` is red on master as well (see `bugs/CODEGEN_imported_function_default_argument_dropped_at_call.md`), and the other jobs are not compared against master yet.
=======
PARTIAL (2026-10-29, branch work/fix-gate-gimplerunner). Reproduced alone (not load): `python3 test_gimple_runner.py` gives `477 passed, 4 failed` on the pre-fix tree. The four failures are the cases in `bugs/CODEGEN_mixed_kind_struct_and_list_reads_red_on_head.md`. Three are fixed in this round; the fourth (`gimple_ctor_param_polymorphic_slot_reads_receiver`) is the method-receiver bug in `bugs/CODEGEN_unresolved_method_receiver_returns_its_own_pointer.md`, which is owned by another worker. The `gimplerunner` job stays red until that lands.
>>>>>>> a98f133ed (CODEGEN: mixed-kind list literals and copies keep each slot's kind (gimplerunner))

## Gate output (first lines)

```
PASS  user_struct_named_parser_survives_a_re_export_and_a_base
PASS  gimple_id_is_an_integer
PASS  gimple_erase_slot_holding_a_string
PASS  gimple_star_spread_of_string_beside_own_slot
PASS  user_struct_named_parser_emits_its_own_layout_and_qualifier
Results: 467 passed, 5 failed
```

## What to check first

see excerpt; gimplerunner ran 981 s, rerun alone.

## Next step

1. Implement the polymorphic-receiver plan in
   `bugs/CODEGEN_unresolved_method_receiver_returns_its_own_pointer.md`
   (`gimple_ctor_param_polymorphic_slot_reads_receiver` is the test).
2. Then delete this doc in the same commit and run
   `python3 tools/dangling_doc_refs.py --ratchet`.
