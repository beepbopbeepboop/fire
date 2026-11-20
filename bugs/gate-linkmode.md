# Gate: linkmode is red on master

**Job:** `linkmode`. Created when branch `master` (task `master`) turned the gate red.
**Two states:** this doc exists = the job is red and this is the work. Delete it when the job is green on master.

It is red on `master`: reproduce it there (`python3 tools/suite.py linkmode`), then fix the cause. Do not skip or mark the test.

## Done when

`python3 test_suite.py` passes its `timeout:` pins for `linkmode`, and a cold
`python3 tools/suite.py linkmode` (no cached PASS) reports the job PASS inside
its timeout instead of `[TIMEOUT]`. The 56 cases in `test_link_mode.py` stay
unchanged.
