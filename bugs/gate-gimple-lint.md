# Gate: gimple-lint is red on master

**Job:** `gimple-lint`. Created when branch `work/bug-codegen-return-in-try-mixes-int-and` (task `bug-codegen-return-in-try-mixes-int-and`) turned the gate red.
**Two states:** this doc exists = the job is red and this is the work. Delete it when the job is green on master.

It is red on `work/bug-codegen-return-in-try-mixes-int-and`: reproduce it there (`python3 tools/suite.py gimple-lint`), then fix the cause. Do not skip or mark the test.

Failing files at the time:
- `std/math/math.mojo`
- `test/math/test_exp.mojo`
- `test/math/test_ldexp.mojo`
- `test/math/test_math.mojo`
