# COMPILE_FAIL sub-task: element access + fix_row typing (step 5 of 6)

Parent: bugs/hard/COMPILE_FAIL_Tools_c-analyzer_c_common_tables.md
Plan: docs/foreign-callable-table-plan.md

## Scope
Per-row accessor for the iterator element type produced by a foreign callable;
type-check `fix_row(row)` body with that element ctype.

## Files
- mojo/backend_gimple/cpp_core.py

## Test
read_table-like shape compiles past the for (may still refuse later).

## Acceptance
No regression in existing cpp_for tests.
