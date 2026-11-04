# COMPILE_FAIL sub-task: _cpp_for_stmt branch for callable-local call (step 4 of 6)

Parent: bugs/hard/COMPILE_FAIL_Tools_c-analyzer_c_common_tables.md
Plan: docs/foreign-callable-table-plan.md

## Scope
In `mojo/backend_gimple/cpp_core.py` `_cpp_for_stmt`, add a new branch after
the generator-handle branch: `for <target> in <call through callable local>`
whose callee's table entry gives an iterator element ctype. Refuse by name if
the entry is absent (keep current refusal for unknown callees).

## Files
- mojo/backend_gimple/cpp_core.py

## Test
Extend `cpp_for_over_callable_param_names_the_callee` regression.

## Acceptance
Refusal message names the callable-local case precisely.
