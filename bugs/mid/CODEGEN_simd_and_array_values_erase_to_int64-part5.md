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

## Status 2026-11-12 — the gate constraint on landing this part (measured)

Two attempts are archived, not landed, because `stdlib-syntax` went red on
exactly the same eight files both times (`e9fc5462a` and `455405950`, branches
`work/bug-mid-codegen-simd-and-array-values-er-6` / `-5`):

    std/math/math.mojo                         std/math/test_ldexp.mojo
    std/random/_rng.mojo                       std/math/test_math.mojo
    test/builtin/test_simd.mojo                test/utils/test_numerics.mojo
    test/collections/string/test_atof.mojo     test/collections/string/test_string.mojo

Measured by applying only `455405950`'s resolver hunk to master and compiling
each file through `tools/compile_one.py`: all eight fail with

    error: invalid operands to binary & (have 'float' and 'float')
    error: invalid operands to binary & (have 'double' and 'double')

The failing expressions are `val.to_bits() & mask` in
`std/utils/numerics.mojo`'s `isnan`/`isinf` (their comptime-dead float8
branches ARE emitted by this codegen, not pruned) and
`x._to_bits_signed() & mask` in `std/math/math.mojo`'s `frexp` (reached from
`test_ldexp`/`test_math`). Typing the width-1 SIMD receiver as `float` is the
correct half; the other half is that `to_bits()` / `_to_bits_signed()` have an
INTEGER return type in their stdlib signatures, while the generic
scalar-method stub returns the receiver's own type
(`mojo/backend_gimple/emit_methods.py`, "Other scalar methods: pass the
receiver through unchanged").

So landing this part requires, in the same change:

1. the resolver rule above (including the comptime-bound dtype case), and
2. an integer result type for `to_bits` / `_to_bits_signed` on a `float` /
   `double` receiver — or pruning of the comptime-dead arms, which is the
   larger change.

The pinning test for (2) is `test_gimple.py`'s
`gate_stdlib_syntax_float_bit_accessors`; it fails on a resolver-only landing
with the errors above and passes on master. The `stdlib-syntax` red itself was
the held branch's landing gate, not a master regression: master is green on
all eight files.
