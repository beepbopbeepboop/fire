# SUITE_gimplerunner_21_failing-part6: str window behavior matches CPython

Split from `bugs/hard/SUITE_gimplerunner_21_failing.md` (group D).

## Goal

Make `gimple_str_window_matches_cpython` in `test_gimple_runner.py` produce the same observable behavior as CPython for the program under test (or correct the test expectation if it is wrong, after comparison with CPython).

## Acceptance

- The `gimple_str_window_matches_cpython` case passes: compiled gimple-runner output matches CPython's stdout/behavior for that program.
- Any change is grounded in a direct comparison with `python3` on the same source.

## Done when

Run:
`python3 test_gimple_runner.py 2>&1 | tee .tmp/SUITE_gimplerunner_21_failing-part6.log; ! grep -q '^FAIL  gimple_str_window_matches_cpython' .tmp/SUITE_gimplerunner_21_failing-part6.log`

The command exits 0 when `gimple_str_window_matches_cpython` no longer fails.
