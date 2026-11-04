# COMPILE_FAIL sub-task: admit foreign-callable default in _cpp_lambda_ctype (step 3 of 6)

Parent: bugs/hard/COMPILE_FAIL_Tools_c-analyzer_c_common_tables.md
Plan: docs/foreign-callable-table-plan.md

## Scope
In `mojo/middle/types.py` `_cpp_lambda_ctype`, currently returns None for any
default. Admit a default whose value is a known foreign callable (table
lookup): return the table ctype instead.

## Files
- mojo/middle/types.py

## Test
`_cpp_lambda_ctype` returns the table ctype for a lambda default whose value
is a foreign callable name.

## Acceptance
No regression in existing lambda ctype tests.
