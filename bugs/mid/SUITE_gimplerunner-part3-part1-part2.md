# SUITE_gimplerunner-part3-part1-part2: Fix wrong return-value gimplerunner cases

Parent: `bugs/hard/SUITE_gimplerunner-part3-part1.md` (split). Depends on the
triage/verdicts in `bugs/mid/SUITE_gimplerunner-part3-part1-part1.md`.

## Goal

Resolve the confirmed wrong-return-value cases identified by part1: for each
case verdict-ed a **compiler bug**, fix the generated GIMPLE/codegen so the
program yields the correct value; for each verdict-ed **wrong expected value**,
correct the test's expectation to match the verified correct behavior. Cases
that are representation-only, compile refusals, or RSS-only remain tracked by
their respective sibling docs/groups.

## Acceptance

- Every case listed as in-scope in the part1 `## Return-value inventory` is
  resolved according to its verdict (codegen fix for compiler bugs, expectation
  corrected for wrong expected values), with no regression to passing
  gimplerunner cases.
- A focused regression test `test_gimple_return_value_regression.py` exists and
  asserts the correct value/result for the resolved return-value cases (or a
  clearly named subset recorded in the part1 inventory) so the fix is pinned.
- The part1 inventory is updated to reflect the resolved status of each case.

## Done when

Run:
`python3 tools/memslot.py --gb 8 --label gimplerunner-return-value -- python3 test_gimple_return_value_regression.py`

The command exits 0 when the focused return-value regression test passes,
proving the resolved cases produce the expected values.
