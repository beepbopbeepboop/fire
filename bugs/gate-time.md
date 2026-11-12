# Gate: time is red on master

**Job:** `time`. Created when branch `master` (task `master`) turned the gate red.
**Two states:** this doc exists = the job is red and this is the work. Delete it when the job is green on master.

It is red on `master`: reproduce it there (`python3 tools/suite.py time`), then fix the cause. Do not skip or mark the test.
