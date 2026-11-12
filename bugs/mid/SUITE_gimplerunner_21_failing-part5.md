# SUITE_gimplerunner_21_failing-part5: mixed-kind dict/list value representation and slot reads

## Status (2026-11-12)

- DONE, all four named cases pass: `gimple_list_slice_mixed` (list slices take their own
  slots' kinds), `gimple_dict_items_pair_var_prints_as_a_pair` (a str-keyed items pair is a
  `MojoList *`, its key a string, and the element repr is not applied to a string slot),
  `gimple_dict_value_repr_uses_the_struct_dunder` and `gimple_dict_value_repr_remaining_two_shapes`
  (a dict's struct value uses its own repr first; a second struct type records its repr on its
  slot as kind 6). One test expectation was wrong and is corrected: `Q(y='b')` is the field dump
  the test rules out; CPython prints `Q<b>` from `Q.__repr__`.
- DONE (2026-11-12): module-scope mixed-list kinds. A global's element kinds are recorded at
  its store and carried onto each read (`_note_global_slot_kinds`, emit_exprs global read), and
  the slice and list-cast paths keep them (emit_calls). `b = a[:]` at module scope now prints 2.5.
- DONE (2026-11-12): bytes-keyed dict with a second struct type renders its own repr
  (`mojo_dict_set_bytes_other_struct_repr`).

## Goal

Fix mixed-kind value boxing/repr and slot reads so the following `test_gimple_runner.py` cases produce correct output:
- `gimple_dict_items_pair_var_prints_as_a_pair`
- `gimple_dict_value_repr_uses_the_struct_dunder`
- `gimple_dict_value_repr_remaining_two_shapes`
- `gimple_list_slice_mixed`

## Acceptance

- Dict items pairs print as pairs (e.g. `('a', 1)`) rather than raw addresses.
- Dict values that are struct instances use the struct dunder repr in dict formatting (e.g. `R<a>` forms as expected).
- Remaining mixed dict-value repr shapes render correctly (no raw addresses leaked).
- Slicing a mixed-kind list preserves per-slot kinds/values (e.g. `2.5` prints as `2.5`, not a raw integer).

## Done when

Run:
`python3 test_gimple_runner.py 2>&1 | tee .tmp/SUITE_gimplerunner_21_failing-part5.log; ! grep -q '^FAIL  gimple_list_slice_mixed' .tmp/SUITE_gimplerunner_21_failing-part5.log`

The command exits 0 when `gimple_list_slice_mixed` no longer fails.
