# SIMD constructor lowering preserves float scalar dtype (part 2, subpart 1)

Part 1 of `bugs/hard/CODEGEN_simd_and_array_values_erase_to_int64-part2.md`.

## Goal

Lower float-typed `SIMD[...]` constructor calls so the constructed value keeps
its scalar dtype/representation instead of being erased to the plain `int64_t`
placeholder path (`(int64_t)0` with "indirect call via SubscriptExpr") in the
generated C.

## Acceptance

- A float SIMD constructor such as `SIMD[DType.float32, 2](1.0)` is no longer
  lowered through the erased `int64_t` placeholder/indirect-subscript fallback.
- The emitted C carries float/double-typed representation information for the
  constructed float SIMD value sufficient for downstream typing to distinguish
  it from `Int64`.
- Integer SIMD constructors that intentionally map to integer representations
  remain correct.

## Done when

Quick test (file path and command):
`test_codegen_simd_ctor_dtype_part2.py` — run
`python3 test_codegen_simd_ctor_dtype_part2.py`
and it exits 0.
