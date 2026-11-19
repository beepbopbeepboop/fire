# Gate: gimplerunner is red on master

**Job:** `gimplerunner`. Created when branch `work/bug-codegen-scalar-integer-dtype-represe-3` (task `bug-codegen-scalar-integer-dtype-represe-3`) turned the gate red.
**Two states:** this doc exists = the job is red and this is the work. Delete it when the job is green on master.

It is red on `work/bug-codegen-scalar-integer-dtype-represe-3`: reproduce it there (`python3 tools/suite.py gimplerunner`), then fix the cause. Do not skip or mark the test.

Failing files at the time:
- `std/_gpu/intrinsics.mojo`
- `std/collections/_swisstable.mojo`
- `std/collections/span.mojo`
- `std/collections/string/_utf8.mojo`
- `std/collections/string/codepoint.mojo`
- `std/collections/string/string.mojo`
- `std/hashlib/_ahash.mojo`
- `std/memory/pointer.mojo`
- `std/random/_rng.mojo`
- `std/random/philox.mojo`
- `std/sys/_amdgpu.mojo`
- `std/testing/prop/random.mojo`
- `std/testing/prop/strategy/string_strategy.mojo`
- `test/builtin/test_issue_1505.mojo`
- `test/builtin/test_simd.mojo`
- `test/collections/test_optional.mojo`
- `test/random/test_philox.mojo`
