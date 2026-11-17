# Gate: stdlib-syntax is red on master

**Job:** `stdlib-syntax`. Created when branch `work/bug-land-codegen-stdlib-dylib-lazy-undef-8` (task `bug-land-codegen-stdlib-dylib-lazy-undef-8`) turned the gate red.
**Two states:** this doc exists = the job is red and this is the work. Delete it when the job is green on master.

It is red on `work/bug-land-codegen-stdlib-dylib-lazy-undef-8`: reproduce it there (`python3 tools/suite.py stdlib-syntax`), then fix the cause. Do not skip or mark the test.

Failing files at the time:
- `test/benchmark/test_quick_bench.mojo`
- `test/math/test_math.mojo`
