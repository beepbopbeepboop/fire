# SUITE: the residue budgets are out of date after the estate registration

Found 2026-11-10 when the 42 unregistered test files were registered in the `check` bucket (see the estate audit).
`suite-self-test` is red on master because of two budget checks in `test_suite.py`'s `budgets` group.

## What the checks say

    FAIL  budgets: the residue census is the residue: the census and the walk disagree. Converted a file? drop its row. Added a literal? add the file with its count and read its call sites. Difference: test_bootstrap_hotspots.py: census 0 vs walk 1; test_dict_slot_read_regression.py: census 0 vs walk 1; test_formal_admitted_two_args.py: census 0 vs walk 1; test_formal_fstring_printf_regress.py: census 0 vs walk 1; test_imported_decorator_regression.py: census 0 vs walk 2; test_python315_frozendict.py: census 0 vs walk 1; test_python315_sentinel.py: census 0 vs walk 1; test_regress_timespec_type.py: census 0 vs walk 1; test_regression_profiling_package.py: census 0 vs walk 1; test_typeddict_extra_items_regression.py: census 0 vs walk 1; test_unpacking_in_comprehensions.py: census 0 vs walk 1 | census-only: 
    FAIL  budgets: the residue is not allowed to GROW: 23 files carry a literal against a census of 12
    budgets: 40 literal(s) in 23 unconverted file(s), 17 in 4 where the budget is the subject

## What to do

Each file in the list is either a new registration whose literal count the census does not yet carry, or a file
whose literal moved. For each one: read its call sites, then either convert the literal or add the file to the
census with its count and a reason. Do not raise the growth ceiling without a justification in the commit message.
Delete this doc in the commit that brings `suite-self-test` green.
