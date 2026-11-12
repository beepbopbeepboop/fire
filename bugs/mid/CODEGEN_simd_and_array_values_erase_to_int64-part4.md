# Resolve Scalar/comptime-DType annotations to scalar C types (part 4)

Part 4 of `bugs/hard/CODEGEN_simd_and_array_values_erase_to_int64-part1.md`.

## Goal

Make `_resolve_type` (and related annotation resolution) resolve `Scalar[X]` / `SIMD[X, 1]` to the correct scalar C type of `X`, including when `X` is a comptime/local binding to a `DType` value such as `DType.float32` or `DType.float64`.

## Current state

The parent bug notes: `Scalar[dtype]` is `SIMD[dtype, 1]`, and `_resolve_type` answers `int64_t` for both `Scalar[Float32]` and `DType.float32` (while `Float32` itself answers `float`). Because of this, `Array[Scalar[dtype], N]` cannot recover its element type from the annotation it is written with, contributing to erased element/value typing.

## Plan

In the type-resolution code (e.g. `mojo/backend_gimple/emit_calls.py` / `emit_expr.py` / the module that owns `_resolve_type`, per local structure):
- teach resolution that `Scalar[X]` means `SIMD[X, 1]` and resolves to the scalar C type corresponding to `X`;
- resolve `X` through comptime locals/bindings that refer to `DType.float32`, `DType.float64`, and other supported dtypes, not only direct type spellings like `Float32`;
- keep unknown/unresolved cases conservative (no silent wrong scalar mapping).

## Acceptance

- `_resolve_type` maps `Scalar[Float32]` / `SIMD[Float32, 1]` to the float scalar C type (and analogous float64 cases), not `int64_t`.
- When `dtype` is a comptime local bound to `DType.float32`/`DType.float64`, `Scalar[dtype]` / `SIMD[dtype, 1]` resolve to the corresponding scalar C type.
- `Array[Scalar[dtype], N]` annotations can recover the intended element scalar type in the contexts this resolver feeds.

## Done when

Quick test (inline probe, no test file): run
`python3 -c "import sys; sys.path.insert(0,'.'); import build_stdlib_dylib as b; src='from sys.info import DType\nfn f():\n    comptime dt = DType.float32\n    var a: Array[Scalar[dt], 4]\n'; c=b.compile_module_to_c(src,'sc.mojo','sc',linkable=False); print(c)"`
and confirm the resolved/emitted element/storage type for `Array[Scalar[dt], 4]` is based on `float` (not `int64_t`) once annotation resolution and construction/type tracking are wired for this form. If this exact snippet is not yet a supported compile shape, the implementing worker must replace this probe with one concrete quick command that demonstrates `Scalar[dtype]`/comptime-`DType` resolution to the correct scalar C type.
