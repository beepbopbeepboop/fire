# SIMD values keep scalar dtype through lowering (part 3)

Part 3 of `bugs/hard/CODEGEN_simd_and_array_values_erase_to_int64-part1.md`.

## Goal

Preserve enough scalar dtype information for SIMD values (including `SIMD[.float32, N](...)`, `SIMD[...]` results, and related SIMD/FMA forms) so codegen does not erase them to plain `int64_t` in a way that makes `c_to_mojo`/generic call inference see `Int64`.

## Current state

The parent bug shows SIMD constructors/calls lowered through the plain call path and stored/typed as `int64_t` (e.g. `std/random/philox.mojo` `log(u)`, `test/math/test_erf.mojo` `erf(SIMD[.float32, 2](2))`, `test/math/test_ldexp.mojo`, `test/math/test_math.mojo` `log1p(val)`). `c_to_mojo` then maps them to `Int64`, breaking floating-point generic constraints and compiled-mode behavior.

## Plan

In the SIMD call/lowering path (`mojo/backend_gimple/emit_calls.py` and any supporting expr/type helpers):
- recognize SIMD construction/calls and lower them with a representation that retains the scalar element C type/dtype (not a generic `int64_t` result for float SIMD values);
- ensure values produced/propagated from these forms carry type info sufficient for downstream elaboration/c_to_mojo to answer the correct floating scalar type where applicable.

This is a representation/typing change for SIMD values; byte-identical generated C is not expected.

## Acceptance

- `SIMD[.float32, N](...)` and float-typed SIMD values are not erased to plain `int64_t` such that they read back as `Int64`.
- Generic floating-point callees receiving such SIMD/scalar-SIMD arguments no longer see `Int64` solely because of SIMD erasure in the covered cases.
- Integer SIMD cases that intentionally map to integer C types remain correct.

## Done when

Quick test (file path and command): `python3 compile_stdlib.py test/math/test_erf.mojo`
and/or `python3 compile_stdlib.py test/math/test_ldexp.mojo`
run without the SIMD-erasure where-clause/inference failure described in the parent bug (at least the `erf(SIMD[.float32, 2](2))` case compiles past the erased-`Int64` argument typing).
