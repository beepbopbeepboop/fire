SPLIT: SUITE_gimplerunner_21_failing-part1, SUITE_gimplerunner_21_failing-part2, SUITE_gimplerunner_21_failing-part3, SUITE_gimplerunner_21_failing-part4, SUITE_gimplerunner_21_failing-part5, SUITE_gimplerunner_21_failing-part6, SUITE_gimplerunner_21_failing-part7, SUITE_gimplerunner_21_failing-part8, SUITE_gimplerunner_21_failing-part9, SUITE_gimplerunner_21_failing-part10
# SUITE_gimplerunner: 21 failing cases (2026-11-11)

Filed when the `gimplerunner` job was marked `expect=` in `tools/suite.py`. This is the one doc for the
job: the older `SUITE_gimplerunner` tree (from the 2026-11-08 `make check` run) was removed on 2026-11-12, its
done-checks having been unreliable (see Status).

## Status

- Run: `python3 test_gimple_runner.py` on this tree, log at `.tmp/gimplerunner-verify.log`.
  Result: 583 passed, 21 failed, exit 1. No `gcc -fgimple compilation failed` line.
- 2026-11-11: `gimple_nested_class_var_attr_from_str_param` is fixed — the `var`
  spelling of a per-execution class attribute no longer mints a visible struct
  field that shadows the cell (bug:CODEGEN_nested_class_var_attr_untyped_field,
  doc deleted with its fix). Six regressions covering every spelling of a
  per-execution attribute were added beside it; a full re-run on this branch
  reports 592 passed, 20 failed (612 cases).
- Not done: the 20 below are still failing.
- The part-1 triage doc's done-check matches the heading text inside its own Acceptance section,
  so it passes without an inventory. No inventory has been recorded anywhere; this section is it.

## Inventory

Grouped by what the log shows. Each row is the case name from `test_gimple_runner.py`.

### A. Dict value kinds and keys (the mixed-kind dict family, see `doc/DESIGN_dynamic_values.md`)
- `gimple_tuple_dict_key_is_content_keyed`: prints `0 none none`, expected `one none none`.
- `gimple_runtime_string_tuple_key_is_content_keyed`: prints `0 1`, expected `R 1`.
- `gimple_container_keyed_store_reaches_its_own_read`: prints `0 1`, expected `1 1`.
- `gimple_dict_get_str_hit_empty_string_is_not_a_miss`: prints `[dflt]` where `[]` is expected.
- `gimple_tuple_dict_key_lookup_does_not_grow`: prints `0`, expected `299999`; RSS 2.1 MB.
- `gimple_dict_items_pair_var_prints_as_a_pair`: prints raw addresses, expected `('a', 1)`.
- `gimple_dict_value_repr_uses_the_struct_dunder`: prints `{'k': <addr>}`, expected `{'k': R<a>}`.
- `gimple_dict_value_repr_remaining_two_shapes`: prints raw addresses, expected `{'p': R<a>, ...}`.
- `gimple_list_slice_mixed`: prints a raw integer where `2.5` is expected.

### B. Generators refused at compile time (the coroutine-codegen family, see `doc/COROUTINE.html`)
- `gimple_for_over_a_call_through_a_function_value`: refused, 8 C++20 generator symbols.
- `gimple_check_all_idiom`: refused, same cause.
- `gimple_with_generator_context_manager_exits`: refused, generator function with `yield`.
- `gimple_with_generator_context_manager_exits_on_the_raise_path`: refused, same.

### C. Memory limit only (stdout matches, RSS over the 40 MB limit) -- FIXED 2026-11-12

The int-to-string conversion (`String(i)`, `str(i)`) was never freed; `mojo_str_word_fresh` now owns the
result and the codegen registers it as fresh. The three cases pass at ~2.2 MB. Part doc deleted with the fix.
- `gimple_fresh_returning_string_functions_are_owned`: RSS 75.7 MB.
- `gimple_string_locals_owned_when_only_read`: RSS 57.3 MB.
- `gimple_string_method_results_are_owned`: RSS 57.3 MB.

### D. Other wrong output or expectation
- `gimple_str_window_matches_cpython`: output differs from CPython.
- `gimple_math_module_members_lower_to_libm`: prints nothing, expected the libm results.
- `gimple_str_encode_errors_and_decode_remaining`: CPython itself exits 1 on this program. Check
  whether the test's expectation or the program is wrong before any codegen change.
- `gimple_enum_case_without_eq_is_refused`: the program builds where the test expects a refusal
  naming `ENUM CASE`. Either the refusal was lost or the test expects one that was never added.

## Done when

`python3 test_gimple_runner.py` reports 612 passed, 0 failed, and the `gimplerunner` marker in
`tools/suite.py` is removed in the same commit (an `expect=` that passes is reported as a failure).

## Next steps

1. Split along the groups above: A and C are codegen, B is the coroutine project, D needs each
   test's expectation checked against CPython first (`tools/gdbtool` / the python3 reference).
2. C is DONE (2026-11-12, see above). Remaining order: D's math return type (`math.copysign`), then A's dict keys.
