# SUITE: two landed test files are run by nothing, so `test_suite.py` is red

**Status (2026-11-13):** open, on master, not caused by the `stdlib-syntax` merge
that found it. `test_suite.py`'s "the estate" check fails; nothing else does.

## What I ran

    python3 tools/memslot.py --gb 8 --label suite-self -- python3 test_suite.py

Observed (tail):

    Results: 372 passed, 1 failed
      - the estate: every test file is run by something, or says why not: not run by
        any registered spec, not in UNREGISTERED, and in no declared family:
        test_conditional_conformance_declaration_diagnostic.py,
        tools/test_control_norm_claim.py

## Why it is master's, not the merge's

Both files were landed by master commits this branch did not touch:

- `test_conditional_conformance_declaration_diagnostic.py` — `b3b2233b0`
  ("fix stdlib-dylib: two regressions from today's diagnostics commits").
- `tools/test_control_norm_claim.py` — `6e35ff35e` ("control: norm_claim treats
  a `bugs/<class>/` path as its document's claim").

Neither name appears in master's `test_suite.py` (`UNREGISTERED`) or
`tools/suite.py` (a registered spec), which is exactly what the estate check
reports.

## Expected

`python3 test_suite.py` green: every test file is either registered in a bucket
or listed in `UNREGISTERED` with a reason (the mechanism that `43c148b42` used
for the previous four landed-but-unregistered diagnostics tests; that commit
deleted `bugs/SUITE_landed_tests_are_in_no_bucket.md`, so this is the same
class of hole reappearing with two new files).

## Exact next step

Decide each file's fate and make the registry say it:

1. If the test is cheap and belongs in the regression set (both measured cheap
   here: the conditional-conformance test builds one program, the control test
   is pure Python), register it in `tools/suite.py` beside its area's pins —
   e.g. `reg-conditional-conformance-declaration-diagnostic` in `regressions`,
   and a `tools/test_control_norm_claim.py` spec next to the other control
   tests — then run `python3 test_suite.py` to confirm 373 passed.
2. If it stays standalone for now, add it to `test_suite.py`'s `UNREGISTERED`
   with `_STANDALONE_TEST_REASON` and the same one-line justification.

Do not delete either test: both pin fixes landed on master.
