# SUITE_gimplerunner_21_failing-part3: generator-backed context managers

Split from `bugs/hard/SUITE_gimplerunner_21_failing.md` (group B, subset).

## Goal

Implement or lower generator-backed context manager support so the following `test_gimple_runner.py` cases compile and run instead of being refused for generator functions with `yield`:
- `gimple_with_generator_context_manager_exits`
- `gimple_with_generator_context_manager_exits_on_the_raise_path`

## Acceptance

- `gimple_with_generator_context_manager_exits` compiles and behaves as the test expects on normal exit.
- `gimple_with_generator_context_manager_exits_on_the_raise_path` compiles and behaves as the test expects when the `with` body raises.
- Context-manager enter/exit semantics for generator CMs are preserved on both paths.

## Done when

Run:
`python3 test_gimple_runner.py 2>&1 | tee .tmp/SUITE_gimplerunner_21_failing-part3.log; ! grep -q '^FAIL  gimple_with_generator_context_manager_exits' .tmp/SUITE_gimplerunner_21_failing-part3.log`

The command exits 0 when `gimple_with_generator_context_manager_exits` no longer fails.
