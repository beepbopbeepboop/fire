# COMPILE_FAIL sub-task: bind foreign-callable default type in _infer_param_types (step 2 of 6)

Parent: bugs/hard/COMPILE_FAIL_Tools_c-analyzer_c_common_tables.md
Plan: docs/foreign-callable-table-plan.md

## Scope
In `mojo/middle/infra_infer.py` `_infer_param_types`, when a parameter has a
default whose value is a name present in `_FOREIGN_CALLABLES`, bind the
parameter's inferred type to that ctype instead of the int64_t fallback.

## Files
- mojo/middle/infra_infer.py

## Test
A `def f(x, _g=csv.reader)` gets a callable-typed param in the declared-param dump.

## Acceptance
Parameter typed as callable, not int64_t.
