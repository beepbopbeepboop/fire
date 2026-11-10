# DIAGNOSTICS step 1: Generic `where`-clause enforcement at call sites

Part of the umbrella `bugs/hard/DIAGNOSTICS_missing_validation_modular.md`;
plan: `docs/diagnostics-missing-validation-plan.md` §1.

## Symptom
When a call instantiates a generic whose `where` clause is provably false for the supplied type arguments, compilation must fail with `error: invalid call to '<fn>': violated constraint`.

## Modular tests
tuple_contains_type_mismatch_error.mojo, tuple_first_of_error.mojo

## Files
mojo/backend_gimple/emit_resolve.py, emit_calls.py, mojo/middle/comptime.py

## Test
`f[T: Equatable](x: T) -> Bool where T == Int` called as `f[Float64](1.0)` must fail; a satisfied `where` clause must still compile.

## Acceptance
Add `test_where_clause_call_site_diagnostic.py`.

## Status
- **Open.**
