# COMPILE_FAIL sub-task: flip refusal test to stdlib-output comparison (step 6 of 6)

Parent: bugs/hard/COMPILE_FAIL_Tools_c-analyzer_c_common_tables.md
Plan: docs/foreign-callable-table-plan.md

## Scope
Update `_regression_read_table_callable_reader` in test_gimple_generator_runner.py
from a refusal assertion to a stdlib-output comparison (CPython ground truth).

## Files
- test_gimple_generator_runner.py

## Test
The regression compares compiled output to CPython output for read_table.

## Acceptance
Test passes.
