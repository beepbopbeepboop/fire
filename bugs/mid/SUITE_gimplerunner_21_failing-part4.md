# SUITE_gimplerunner_21_failing-part4: content-keyed dict keys and lookup correctness

Split from `bugs/hard/SUITE_gimplerunner_21_failing.md` (group A, keying/lookup subset).

## Goal

Fix dict key hashing/equality and lookup behavior for content-keyed/container keys so the following `test_gimple_runner.py` cases produce correct results:
- `gimple_tuple_dict_key_is_content_keyed`
- `gimple_runtime_string_tuple_key_is_content_keyed`
- `gimple_container_keyed_store_reaches_its_own_read`
- `gimple_dict_get_str_hit_empty_string_is_not_a_miss`
- `gimple_tuple_dict_key_lookup_does_not_grow`

## Acceptance

- Tuple and runtime-string tuple keys are content-keyed (equal values retrieve the same entry).
- Container-keyed store/read reaches the same logical entry.
- `dict.get`/lookup treats an empty-string hit as a hit, not a miss/default.
- Repeated lookups of content-equal tuple keys do not grow the dict (lookup remains stable at expected size/count).

## Done when

Run:
`python3 test_gimple_runner.py 2>&1 | tee .tmp/SUITE_gimplerunner_21_failing-part4.log; ! grep -q '^FAIL  gimple_tuple_dict_key_is_content_keyed' .tmp/SUITE_gimplerunner_21_failing-part4.log`

The command exits 0 when `gimple_tuple_dict_key_is_content_keyed` no longer fails.
