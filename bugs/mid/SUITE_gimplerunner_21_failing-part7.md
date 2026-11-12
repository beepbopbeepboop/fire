# SUITE_gimplerunner_21_failing-part7: math module members lower to libm

Split from `bugs/hard/SUITE_gimplerunner_21_failing.md` (group D).

## Goal

Fix lowering of `math` module members so `gimple_math_module_members_lower_to_libm` in `test_gimple_runner.py` prints the expected libm results instead of nothing.

## Acceptance

- `gimple_math_module_members_lower_to_libm` compiles and runs.
- Output matches the test's expected stdout (the libm results).

## Done when

Run:
`python3 test_gimple_runner.py 2>&1 | tee .tmp/SUITE_gimplerunner_21_failing-part7.log; ! grep -q '^FAIL  gimple_math_module_members_lower_to_libm' .tmp/SUITE_gimplerunner_21_failing-part7.log`

The command exits 0 when `gimple_math_module_members_lower_to_libm` no longer fails.
