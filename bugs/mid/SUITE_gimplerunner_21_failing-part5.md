# SUITE_gimplerunner_21_failing-part5: mixed-kind dict/list value representation and slot reads

## Status (2026-11-12)

- DONE: `gimple_list_slice_mixed`. A bounded slice of a mixed list copied the source's
  whole per-slot kinds (codegen `_struct_slot_kinds`, and the runtime's kinds row), so
  slot 0 of `a[1:]` took slot 0 of `a`'s kind. Now the codegen picks the kinds at the
  slice's slots (`_slice_slot_kinds` in `emit_calls.py`; runtime `_mojo_list_inherit_kinds_slice`
  in `fire_runtime.c`, interned by content so the table stays bounded).
- REMAINING (still failing): `gimple_dict_items_pair_var_prints_as_a_pair`,
  `gimple_dict_value_repr_uses_the_struct_dunder`, `gimple_dict_value_repr_remaining_two_shapes`.
- NEW SIBLING, not in this doc's cases: at MODULE scope the mixed-list kinds are not
  carried to a name. `a = [1, 2.5]` / `b = a[:]` / `print(b[1])` prints the raw double bits
  (`mod2` probe: `print(a[1])` is right, `b[1]` is wrong). The same program inside a
  `def main()` is right. Module-level globals lose the maybe-kinds marker.


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
