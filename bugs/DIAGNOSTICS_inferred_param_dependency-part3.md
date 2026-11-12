# DIAGNOSTICS step 3, part 3: regression test for inferred-parameter dependency diagnostics

Part of the split of `bugs/hard/DIAGNOSTICS_inferred_param_dependency.md`; the
original doc is part of the umbrella `bugs/hard/DIAGNOSTICS_missing_validation_modular.md` and the plan is
`docs/diagnostics-missing-validation-plan.md` §3.

**Prerequisites:** part 1
(`bugs/mid/DIAGNOSTICS_inferred_param_dependency-part1.md`, refuse an inferred
parameter whose type depends on a non-inferred parameter) and part 2
(`bugs/mid/DIAGNOSTICS_inferred_param_dependency-part2.md`, report a non-inferred
element-type parameter).

## Why this part

The original bug doc's acceptance is to add
`test_inferred_param_dependency_diagnostic.py`. This part adds that regression
test beside the existing diagnostic tests (`test_comptime_dtype_diagnostic.py`,
`test_inferred_where_clause_diagnostic.py`).

## Scope

1. **Write the source fixture.** `struct RepeatedDep[c: Int, X: Pair[c, c]]`
   must fail with `inferred parameter of type 'Pair[c, c]' cannot depend on
   non-inferred parameter 'c'`.
2. **Assert the diagnostic.** Compile via
   `gimple_codegen.compile_to_gimple(src, do_imports=True, filename=<real file>)`
   and expect the `RuntimeError`.
3. **Add the positive case.** A satisfied dependency compiles.

## Acceptance

Add `test_inferred_param_dependency_diagnostic.py` and run:

    python3 test_inferred_param_dependency_diagnostic.py

## Status

- **Open.**
