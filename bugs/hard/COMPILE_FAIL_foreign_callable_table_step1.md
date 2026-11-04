# COMPILE_FAIL sub-task: foreign-callable table (step 1 of 6)

Parent: bugs/hard/COMPILE_FAIL_Tools_c-analyzer_c_common_tables.md
Plan: docs/foreign-callable-table-plan.md

## Scope
Create a module-level dict `_FOREIGN_CALLABLES` in `mojo/middle/types.py` mapping
a callable's qualified name to its declared ctype (from the `_CPP_CALLABLE_CTYPE`
family). Seed with one entry: `'csv.reader' -> _CPP_CALLABLE_CTYPE`.

## Files
- mojo/middle/types.py (add the dict near `_CPP_CALLABLE_CTYPE` definitions)

## Test
A unit test asserting `_FOREIGN_CALLABLES.get('csv.reader') is not None`.

## Acceptance
Import succeeds; dict present; entry matches.
