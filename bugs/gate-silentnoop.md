# Gate: silentnoop is red on master

**Job:** `silentnoop`. Created when branch `master` (task `master`) turned the gate red.
**Two states:** this doc exists = the job is red and this is the work. Delete it when the job is green on master.

It is red on `master`: reproduce it there (`python3 tools/suite.py silentnoop`), then fix the cause. Do not skip or mark the test.

## Done when

`test_client_stdlib_dylib_is_reused_until_an_input_changes` in
`test_runtime_dylib.py` passes, and a case's `fire.py build` in a fresh tree
(a `git archive` with no `build/`) no longer pays for the whole stdlib dylib
inside its own 300 s budget.
