# SUITE: four landed test files are in no bucket, so `suite-self-test` is red

Found 2026-11-13 while running `python3 test_suite.py` for an unrelated change
(the formal doc index's directory walk). The estate check reports:

    Results: 371 passed, 2 failed
      - the estate: every test file is run by something, or says why not: not
        run by any registered spec, not in UNREGISTERED, and in no declared
        family: test_contains_method_diagnostic.py,
        test_elaboration_recursion_diagnostic.py, test_lsp_error_recovery.py,
        test_where_alias_diagnostic.py

The first measurement named two files; merging master added the other two, each
landed with its fix and registered nowhere. This doc is edited in place to carry
all four rather than a second doc being filed for the same bug.

## Measured

All four files are TRACKED and came in with their fixes:

- `test_contains_method_diagnostic.py` — commit 03d4302ba ("Reject membership
  on provably scalar containers without `__contains__`"); the bug doc that
  landed with it said at §"test_contains_method_diagnostic.py must keep
  passing" that the file pins the fix.
- `test_lsp_error_recovery.py` — commit 32d00561e ("tests: add LSP error
  recovery regression (`DIAGNOSTICS_lsp_error_recovery-part3`)"); that doc's
  acceptance is "Add `test_lsp_error_recovery.py`".
- `test_elaboration_recursion_diagnostic.py` — commit b3e501b60 ("Refuse
  mutually recursive and unbounded generic instantiation").
- `test_where_alias_diagnostic.py` — commit 491ae6d5b ("elaborate: reject where
  clauses that name module alias constants").

`git show master:tools/suite.py | grep` finds none of the four, and
`git show master:test_suite.py` has none of the names either, so the red is on
master rather than on the branch that ran it. Nothing runs any of them: a test
file in no bucket and in no `UNREGISTERED` entry is exactly the coverage hole
the estate check exists to report, and the job it takes down (`suite-self-test`)
is in `check`.

## Expected

`python3 test_suite.py` is green, and each file is either registered in
`tools/suite.py` — the right answer, since all four are cheap regression tests
for fixes on this tree — or listed in `UNREGISTERED` with a reason. None is.

## Next step

Register each in `tools/suite.py` beside its area's existing job
(`reg-lsp-error-recovery-part2` is already there for the part-2 test), carrying
the `deps`/`mem` of its siblings, then run `python3 test_suite.py` and
`python3 tools/suite.py <bucket> --dry-run` to confirm all four names land in a
bucket. This is the write set of whoever owns
`DIAGNOSTICS_contains_check_rejects_selfhost_source`,
`DIAGNOSTICS_lsp_error_recovery-part3`, and the two elaboration diagnostics
above, not a merge-fix lane's.
