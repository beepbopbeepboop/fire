# SUITE_gimplerunner_21_failing-part1: bounded-memory string ownership (RSS cases)

Split from `bugs/hard/SUITE_gimplerunner_21_failing.md` (group C).

## Goal

Fix the ownership/resource handling so the three `test_gimple_bounded_memory` string cases in `test_gimple_runner.py` no longer exceed their RSS limits while preserving their expected stdout.

## Acceptance

- `gimple_fresh_returning_string_functions_are_owned` passes within its 40 MB limit.
- `gimple_string_locals_owned_when_only_read` passes within its limit.
- `gimple_string_method_results_are_owned` passes within its limit.
- Stdout for each remains identical to the current expected output in the test.

## Done when

Run:
`python3 test_gimple_runner.py 2>&1 | tee .tmp/SUITE_gimplerunner_21_failing-part1.log; ! grep -q '^FAIL  gimple_fresh_returning_string_functions_are_owned' .tmp/SUITE_gimplerunner_21_failing-part1.log`

The command exits 0 when `gimple_fresh_returning_string_functions_are_owned` no longer fails.
