# Gate: stdlib-dylib is red on master

**Job:** `stdlib-dylib`. Created when branch `work/bug-codegen-scalar-integer-dtype-represe-4` (task `bug-codegen-scalar-integer-dtype-represe-4`) turned the gate red.
**Two states:** this doc exists = the job is red and this is the work. Delete it when the job is green on master.

It is red on `work/bug-codegen-scalar-integer-dtype-represe-4`: reproduce it there (`python3 tools/suite.py stdlib-dylib`), then fix the cause. Do not skip or mark the test.

Failing files at the time:
- `std/_gpu/intrinsics.mojo`
- `std/collections/_swisstable.mojo`
- `std/collections/string/_utf8.mojo`
- `std/random/_rng.mojo`
- `std/random/philox.mojo`
- `test/builtin/test_issue_1505.mojo`
- `test/builtin/test_simd.mojo`
- `test/random/test_philox.mojo`
