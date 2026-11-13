# Gate: stdlib-syntax is red on master

**Job:** `stdlib-syntax`. Created when branch `work/bug-mid-codegen-simd-and-array-values-er-5` (task `bug-mid-codegen-simd-and-array-values-er-5`) turned the gate red.
**Two states:** this doc exists = the job is red and this is the work. Delete it when the job is green on master.

It is red on `work/bug-mid-codegen-simd-and-array-values-er-5`: reproduce it there (`python3 tools/suite.py stdlib-syntax`), then fix the cause. Do not skip or mark the test.

Failing files at the time:
- `std/math/math.mojo`
- `std/random/_rng.mojo`
- `test/builtin/test_simd.mojo`
- `test/collections/string/test_atof.mojo`
- `test/collections/string/test_string.mojo`
- `test/math/test_ldexp.mojo`
- `test/math/test_math.mojo`
- `test/utils/test_numerics.mojo`

## Status 2026-11-12 — green on master; the red was the branch's resolver

The branch was held by the landing gate and its work retired; it never reached
master. The job is green on master: each of the eight files above compiles
cleanly today through the job's own pipeline

    python3 tools/memslot.py --gb 8 --label verify -- python3 tools/compile_one.py <file>

(RC 0 for all eight).

The branch's commit was `455405950` ("codegen: resolve Scalar/SIMD width-1
annotations to scalar C types", the part-5 fix). Applying only its
`mojo/middle/infra_infer.py` resolver hunk to master reproduces all eight
failures, at the bits accessors (`std/utils/numerics.mojo`'s `isnan`/`isinf`,
and `std/math/math.mojo`'s `frexp`, which `test_ldexp`/`test_math` reach):
`val.to_bits() & mask` becomes `float & float`, which gcc rejects with
"invalid operands to binary &". The resolver types the width-1 SIMD value
correctly, but the generic scalar-method stub hands a float receiver's type
back from `to_bits()`/`_to_bits_signed()`, whose stdlib signatures return an
integer. The comptime-dead float8 arms that carry the expression are emitted,
not pruned, so they are still compiled.

That is a constraint on landing part 5, not a master regression; it is
recorded in `bugs/mid/CODEGEN_simd_and_array_values_erase_to_int64-part5.md`.

## Done when

`python3 test_gimple.py` reports `PASS gate_stdlib_syntax_float_bit_accessors`:
both bit-accessor spellings on a `SIMD[Float32, 1]` / `SIMD[Float64, 1]`
receiver compile. The case fails on a resolver-only landing with gcc's
"invalid operands to binary &" (measured; that is the eight-file red's minimal
shape) and passes on this tree.
