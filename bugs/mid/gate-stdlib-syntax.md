# Gate: stdlib-syntax is red on master

**Job:** `stdlib-syntax`. Created when branch `work/fix-proof-bug-mid-codegen-simd-and-array-values-er-4` (task `fix-proof-bug-mid-codegen-simd-and-array-values-er-4`) turned the gate red.
**Two states:** this doc exists = the job is red and this is the work. Delete it when the job is green on master.

It is red on `work/fix-proof-bug-mid-codegen-simd-and-array-values-er-4`: reproduce it there (`python3 tools/suite.py stdlib-syntax`), then fix the cause. Do not skip or mark the test.

Failing files at the time:
- `std/math/math.mojo`
- `std/random/_rng.mojo`
- `test/builtin/test_simd.mojo`
- `test/collections/string/test_atof.mojo`
- `test/collections/string/test_string.mojo`
- `test/math/test_ldexp.mojo`
- `test/math/test_math.mojo`
- `test/utils/test_numerics.mojo`
