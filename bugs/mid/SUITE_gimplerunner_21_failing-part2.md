# SUITE_gimplerunner_21_failing-part2: generator codegen for for-over-call and check-all idiom

Split from `bugs/hard/SUITE_gimplerunner_21_failing.md` (group B, subset).

## Goal

Implement or lower the generator/coroutine codegen needed so the following `test_gimple_runner.py` cases compile and run instead of being refused with C++20 generator symbols:
- `gimple_for_over_a_call_through_a_function_value`
- `gimple_check_all_idiom`

## Acceptance

- `gimple_for_over_a_call_through_a_function_value` compiles and its stdout matches the test's expected output.
- `gimple_check_all_idiom` compiles and its stdout/result matches the test's expected behavior.
- No `gcc -fgimple compilation failed` refusal caused by missing generator lowering for these shapes.

## Done when

Run:
`python3 test_gimple_runner.py 2>&1 | tee .tmp/SUITE_gimplerunner_21_failing-part2.log; ! grep -q '^FAIL  gimple_for_over_a_call_through_a_function_value' .tmp/SUITE_gimplerunner_21_failing-part2.log`

The command exits 0 when `gimple_for_over_a_call_through_a_function_value` no longer fails.
