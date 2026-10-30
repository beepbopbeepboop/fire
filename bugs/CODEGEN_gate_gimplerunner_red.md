# Gate job `gimplerunner` is red: gimple runner: compiled programs disagree with expected output

## Status 2026-10-29 — root causes found; six reds, five fixed, one remains

Run alone on this branch (`python3 tools/suite.py gimplerunner`, and
`test_gimple_runner.py` directly): it reproduces, and it is not load. The
reds were SIX, not five, and they were not one bug:

- `gimple_subclass_overrides_a_class_constant` and `gimple_struct_Struct_class_attr`:
  caused by `3accbab0f`, which made an instance read of a class attribute skip
  the class value entirely (it fell through to the instance-field path and read
  nothing). Fixed: `_cattr_instance_read` (`mojo/backend_gimple/emit_methods.py`)
  probes the instance's dynamic storage first, under the nothrow flag, with the
  class value as the default, which is CPython's lookup order.
- `gimple_heterogeneous_list_literal_keeps_each_slot`,
  `gimple_struct_mixed_reads_survive_a_derivation`,
  `gimple_struct_mixed_reads_survive_a_function_boundary`: `list(<a mixed list>)`
  was a typed walk over the promoted element type. Fixed in
  `_lower_ctor_from_iterable` (`mojo/backend_gimple/emit_calls.py`): a copy of a
  kind-mixed list is `mojo_list_copy`. See `bugs/CODEGEN_mixed_kind_struct_and_list_reads_red_on_head.md`.
- `gimple_ctor_param_polymorphic_slot_reads_receiver`: STILL RED. A method call
  on a polymorphic slot is lowered to a no-op stub. This is a feature gap, not
  a one-line fix. The plan is in
  `bugs/CODEGEN_unresolved_method_receiver_returns_its_own_pointer.md`.

Also fixed in the same change, a coverage hole: seven `test_*` functions in
`test_gimple_runner.py` were never invoked. The `if __name__` guard sat above
them and `main()` ends in `sys.exit`, so nothing ran them. `main()` now calls
them, the guard moved to the end of the file, and a refusal's AssertionError is
counted as a FAIL rather than aborting the tally. That run is what found the
polymorphic case alongside the others.

Measured after the fixes: `test_gimple_runner.py` 485 passed, 1 failed (the
polymorphic case). The gate job stays red until that case is fixed or is
registered as a known failure with its doc, which is a `tools/suite.py` decision
for the controller and was not made here.

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
