# SUITE_gimplerunner_21_failing-part5: mixed-kind dict/list value representation and slot reads

Split from `bugs/hard/SUITE_gimplerunner_21_failing.md` (group A, repr/slot subset).

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
