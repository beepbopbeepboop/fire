# SUITE_gimplerunner_21_failing-part10: reconcile enum case without Eq refusal expectation

Split from `bugs/hard/SUITE_gimplerunner_21_failing.md` (group D).

## Goal

Determine the intended behavior for `gimple_enum_case_without_eq_is_refused`: restore the refusal naming `ENUM CASE` if required, or update the test if the program is legitimately accepted, so the case matches the compiler's specified behavior.

## Acceptance

- `gimple_enum_case_without_eq_is_refused` no longer fails in `test_gimple_runner.py`.
- If refusal is intended, the compiler emits a refusal/diagnostic that names `ENUM CASE` for this case; if acceptance is intended, the test expectation is corrected accordingly.

## Done when

Run:
`python3 test_gimple_runner.py 2>&1 | tee .tmp/SUITE_gimplerunner_21_failing-part10.log; ! grep -q '^FAIL  gimple_enum_case_without_eq_is_refused' .tmp/SUITE_gimplerunner_21_failing-part10.log`

The command exits 0 when `gimple_enum_case_without_eq_is_refused` no longer fails.
