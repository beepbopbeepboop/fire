# SUITE_gimplerunner_21_failing-part8: nested class var attribute from str parameter

Split from `bugs/hard/SUITE_gimplerunner_21_failing.md` (group D).

## Goal

Fix codegen/runtime handling so `gimple_nested_class_var_attr_from_str_param` in `test_gimple_runner.py` prints the expected values instead of `0 0`.

## Acceptance

- `gimple_nested_class_var_attr_from_str_param` runs and prints `x y` (as expected by the test).
- Nested class variable attribute access involving a string parameter is correctly lowered/read.

## Done when

Run:
`python3 test_gimple_runner.py 2>&1 | tee .tmp/SUITE_gimplerunner_21_failing-part8.log; ! grep -q '^FAIL  gimple_nested_class_var_attr_from_str_param' .tmp/SUITE_gimplerunner_21_failing-part8.log`

The command exits 0 when `gimple_nested_class_var_attr_from_str_param` no longer fails.
