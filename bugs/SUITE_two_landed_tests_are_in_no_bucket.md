# SUITE: two landed test files are in no bucket, so `suite-self-test` is red

Found 2026-11-13 while running `python3 test_suite.py` for an unrelated change
(the formal doc index's directory walk). The estate check reports:

    Results: 372 passed, 1 failed
      - the estate: every test file is run by something, or says why not: not
        run by any registered spec, not in UNREGISTERED, and in no declared
        family: test_contains_method_diagnostic.py, test_lsp_error_recovery.py

## Measured

Both files are TRACKED and came in with their fixes:

- `test_contains_method_diagnostic.py` — commit 03d4302ba ("Reject membership
  on provably scalar containers without `__contains__`"); its document
  `bugs/DIAGNOSTICS_contains_check_rejects_selfhost_source.md` says at §"test_
  contains_method_diagnostic.py must keep passing" that the file pins the fix.
- `test_lsp_error_recovery.py` — its document is
  `bugs/mid/DIAGNOSTICS_lsp_error_recovery-part3.md`, whose acceptance is "Add
  `test_lsp_error_recovery.py`".

`git show master:tools/suite.py | grep` finds neither file, and
`git show master:test_suite.py` has neither name either, so the red is on
master rather than on the branch that ran it. Nothing runs either file: a test
file in no bucket and in no `UNREGISTERED` entry is exactly the coverage hole
the estate check exists to report, and the job it takes down (`suite-self-test`)
is in `check`.

## Expected

`python3 test_suite.py` is green, and each file is either registered in
`tools/suite.py` — the right answer, since both are cheap regression tests for
fixes on this tree — or listed in `UNREGISTERED` with a reason. Neither is.

## Next step

Register each in `tools/suite.py` beside its area's existing job
(`reg-lsp-error-recovery-part2` is already there for the part-2 test), carrying
the `deps`/`mem` of its siblings, then run `python3 test_suite.py` and
`python3 tools/suite.py <bucket> --dry-run` to confirm both names land in a
bucket. This is the write set of whoever owns
`DIAGNOSTICS_contains_check_rejects_selfhost_source` and `DIAGNOSTICS_lsp_error_
recovery-part3`, not the doc-index lane's.
