# A float SIMD constructor keeps its scalar dtype (part 3)

Part 3 of `bugs/hard/CODEGEN_simd_and_array_values_erase_to_int64.md`.

Independent of parts 1 and 2. Class: mid. One constructor shape, one lowering
arm, no type-resolution change.

## Goal

`SIMD[DType.float32, 2](1.0)` lowers to a value that is not the erased
`int64_t` placeholder. Today it becomes `_t1 = (int64_t)0;  /* indirect call
via SubscriptExpr */` and `v` is `int64_t`, so `c_to_mojo` answers `Int64` for
it.

## Acceptance

- A float SIMD constructor is not lowered through the "indirect call via
  SubscriptExpr" placeholder.
- The constructed local is not declared `int64_t`.
- Integer SIMD constructors (for example `SIMD[DType.int32, 2](1)`) keep their
  current integer lowering. Pin their current output in a test before changing
  the arm, since the placeholder path is shared.

## Done when

File: `test_codegen_erased_container_values.py` (repo root).

Command: `python3 test_codegen_erased_container_values.py part3`

It runs `test_part3_float_simd_ctor_keeps_dtype` (red today). It must pass.

## Where to start

`mojo/backend_gimple/emit_calls.py`, where `SIMD[...]` calls fall through to
the plain call path. The placeholder comes from there. Dispatch on the bracket's
dtype argument, the same way the Array arm of part 1 does on its element type.
