# Gate: silentnoop is red on master

**Job:** `silentnoop`. Created when branch `master` (task `master`) turned the gate red.
**Two states:** this doc exists = the job is red and this is the work. Delete it when the job is green on master.

It is red on `master`: reproduce it there (`python3 tools/suite.py silentnoop`), then fix the cause. Do not skip or mark the test.

## Done when

`test_silentnoop_builds_without_the_shared_stdlib_dylib` and
`test_client_stdlib_dylib_is_reused_until_an_input_changes` in
`test_runtime_dylib.py` pass: a case builds without link mode (so a fresh tree
does not pay for the stdout dylib inside a 300 s budget), and a warm client
build is answered by the currency stamp instead of re-deriving 664 modules.
