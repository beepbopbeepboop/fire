# Gate: stdlib-syntax is red on master

**Job:** `stdlib-syntax`. Created when branch `work/bug-codegen-nested-bracket-generic-call` (task `bug-codegen-nested-bracket-generic-call`) turned the gate red.
**Two states:** this doc exists = the job is red and this is the work. Delete it when the job is green on master.

It is red on `work/bug-codegen-nested-bracket-generic-call`: reproduce it there (`python3 tools/suite.py stdlib-syntax`), then fix the cause. Do not skip or mark the test.

Failing files at the time:
- `std/simd.mojo`
- `test/builtin/test_simd.mojo`
- `test/builtin/test_sort_issue_1018.mojo`
- `test/hashlib/test_ahash.mojo`
- `test/hashlib/test_fnv1a.mojo`
- `test/math/test_exp.mojo`
- `test/math/test_math.mojo`
