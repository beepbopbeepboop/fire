# SUITE_gimplerunner_21_failing-part9: reconcile str encode/decode errors case with CPython

Split from `bugs/hard/SUITE_gimplerunner_21_failing.md` (group D).

## Goal

Determine the correct behavior for `gimple_str_encode_errors_and_decode_remaining` by comparing the program to CPython, then either fix codegen or correct the test expectation so the case is consistent and passing.

## Acceptance

- `gimple_str_encode_errors_and_decode_remaining` no longer fails in `test_gimple_runner.py`.
- The resolved behavior matches CPython for the same program, or the test is updated with a clear, justified expectation if CPython's behavior/exit differs from the original assumption.

## Done when

Run:
`python3 test_gimple_runner.py 2>&1 | tee .tmp/SUITE_gimplerunner_21_failing-part9.log; ! grep -q '^FAIL  gimple_str_encode_errors_and_decode_remaining' .tmp/SUITE_gimplerunner_21_failing-part9.log`

The command exits 0 when `gimple_str_encode_errors_and_decode_remaining` no longer fails.
