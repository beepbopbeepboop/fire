# A float `SIMD`/`Scalar` constructor keeps its C type when the dtype is a scalar type name (part 1)

Part 1 of `bugs/hard/CODEGEN_simd_and_array_values_erase_to_int64.md`.
Class: easy. One lookup change in the constructor arm; no new table.

## Goal

A float `SIMD`/`Scalar` constructor whose dtype is written with the **scalar
type name** produces that scalar's C type, exactly as the other dtype
spellings already do.

Measured 2026-11-15 on this tree (`build_stdlib_dylib.compile_module_to_c`):

    def f32():
        var v = SIMD[Float32, 4](1.5)
        return v

emits `int64_t v;` and `_t1 = (int64_t)1.5;`, while all of these already
emit a `float` value:

    SIMD[DType.float32, 4](1.5)
    SIMD[.float32, 4](1.5)
    SIMD[float32, 4](1.5)

At run time the erasure is observable: `print(SIMD[Float32, 4](1.5))` prints
`1`, where `SIMD[DType.float32, 4](1.5)` prints `1.5`. `Scalar[Float32](0.5)`
erases the same way. This is the "type *spelling*" half of the parent doc's
remaining work.

## Acceptance

- `var v = SIMD[Float32, 4](1.5)` declares `float v;` and stores a `float`;
  no `int64_t v;`, no `indirect call via SubscriptExpr`.
- `var w = SIMD[Float64, 2](2.5)` declares `double w;`.
- `var x = Scalar[Float32](0.5)` declares `float x;`.
- `var i = SIMD[Int32, 4](1)` keeps today's `int64_t i;` lowering: the fix
  widens the float spellings the arm recognizes, it does not turn every SIMD
  value into a float.
- The `DType.float32` / `.float32` / `float32` / `f32` spellings keep their
  current answers, and there is still ONE dtype table: reuse
  `mojo/middle/types.py::_dtype_token_ctype` (the resolver
  `_resolve_type` already uses for signatures).
- An unannotated function that RETURNS a float SIMD value is part 3, not
  this part.

## Done when

File: `test_codegen_erased_container_values.py` (repo root).

Command: `python3 test_codegen_erased_container_values.py ctor_dtype_spelling`

It runs `test_ctor_dtype_spelling_simd_scalar_name_keeps_float_ctype` (red
today: `ctor_dtype_spelling_f32` is `int64_t ctor_dtype_spelling_f32 (void)`
with `int64_t v;`). It must pass, and the integer-spelling arm in the same
test must stay `int64_t`.

## Where to start

`mojo/backend_gimple/emit_calls.py`, `_lower_call`'s `if base in ('SIMD',
'Scalar'):` arm (around line 4271).

The arm currently resolves the bracket dtype in three steps:

1. `_dtype_cast_ctype(_idxs[0])` — knows only `DType.x` and the dot-relative
   `.x` spelling;
2. `_DTYPE_CAST_CTYPES` on the rendered annotation — its keys are the
   lowercase directive names (`float32`), so the scalar type name `Float32`
   misses;
3. `gen._comptime_vals` — a folded `comptime` name, not a bare type name.

`gimple_ctypes._dtype_token_ctype` (`mojo/middle/types.py`) already answers
every spelling including `Float32` / `Float64` / `f32` / `f64`, and is the one
resolver `infra_infer._resolve_type` uses for `SIMD[...]` signatures
(`_SIMD_FLOAT_DTYPE_CTYPE` is its table). Route the float test through that
resolver instead of adding `Float32` keys to `_DTYPE_CAST_CTYPES`; keep the
existing int/uint `_DTYPE_CAST_CTYPES` lowering untouched (a non-float dtype
still resolves to the `int64_t` target). `_float_dtype_arg_ctype` is the
same-table helper already used by the `from_bits=` path in this arm, so the
two branches should agree by construction.

The probe is `test_codegen_erased_container_values.py`, which compiles one
module and asserts on the text of one generated function body. Run it before
and after the change; the three float cases are red today and the `i32` case
is the unchanged pin.
