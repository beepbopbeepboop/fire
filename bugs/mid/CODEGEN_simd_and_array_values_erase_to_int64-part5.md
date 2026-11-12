# Scalar[X] / SIMD[X, 1] annotations resolve to the scalar C type (part 5)

Part 5 of `bugs/hard/CODEGEN_simd_and_array_values_erase_to_int64.md`.

Independent of parts 1–4 as code, but it is what lets `Array[Scalar[dt], N]`
annotations recover their element type, so it helps part 1's consumers.
Class: mid. A resolver rule in `_resolve_type`; no lowering change.

## Goal

`_resolve_type` maps `Scalar[X]` (= `SIMD[X, 1]`) to the scalar C type of `X`.
Today every `Scalar[...]` / `SIMD[..., 1]` spelling resolves to `int64_t`,
while `Float32` alone resolves to `float`.

Measured 2026-11-12 with `gimple_codegen.GimpleGen()._resolve_type`:

| annotation | today | wanted |
|---|---|---|
| `Float32` | `float` | `float` (unchanged) |
| `Float64` | `double` | `double` (unchanged) |
| `Scalar[Float32]` | `int64_t` | `float` |
| `SIMD[Float32, 1]` | `int64_t` | `float` |
| `Scalar[DType.float32]` | `int64_t` | `float` |
| `Scalar[Float64]` / `Scalar[DType.float64]` | `int64_t` | `double` |

## Acceptance

- Every row of the table above.
- `Scalar[dt]` / `SIMD[dt, 1]`, where `dt` is a `comptime` local bound to
  `DType.float32` or `DType.float64`, resolves to the corresponding scalar C
  type. The test below does not yet cover this case; the implementer adds it
  to `test_part5_scalar_annotation_resolves_to_scalar_ctype`, using the
  comptime-binding API the generator already has.
- An unknown or unresolvable dtype stays conservative: it does not silently
  map to a wrong scalar type.

## Done when

File: `test_codegen_erased_container_values.py` (repo root).

Command: `python3 test_codegen_erased_container_values.py part5`

It runs `test_part5_scalar_annotation_resolves_to_scalar_ctype` (red today; it
must pass, with the comptime case added as described above).

## Where to start

`mojo/middle/infra_infer.py::_resolve_type` (the function
`gimple_codegen.GimpleGen._resolve_type` delegates to). Unwrap `Scalar[X]` and
`SIMD[X, 1]` to `X`, then resolve `X` through the existing dtype spellings.
