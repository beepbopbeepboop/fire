# An unannotated function that returns a float SIMD value keeps its scalar C type (part 3)

Part 3 of `bugs/hard/CODEGEN_simd_and_array_values_erase_to_int64.md`.
Class: easy. One binding shape in return-type inference; no lowering change.

## Goal

A function with no return annotation whose body returns a local bound to a
float `SIMD` constructor infers that float's scalar C type, so the value
survives the call boundary instead of being truncated to `int64_t`.

Measured 2026-11-15 on this tree:

    def mk32():
        var v = SIMD[DType.float32, 4](1.5)
        return v

    def use():
        var a = mk32()
        return a

emits `int64_t mk32 (void)` with `_t3 = (int64_t)v;`, and `use` declares
`int64_t a;`. At run time `print(mk32())` prints `1`, and
`print(use())` prints `1`, not `1.5`.

The body's local is already `float v;` — the constructor's own dtype
resolution landed in an earlier round — so this is return-type inference only. A SIMD value is scalar-erased in this codegen (`mlir.py`'s model; every
`SIMD[dtype, N]` value has the dtype's scalar C type), which is why the
answer for a float dtype is exactly `float`/`double`.

## Acceptance

- `mk32`'s generated definition starts `float simd_value_return_mk32 (void)`
  and returns the value without an `(int64_t)` cast; a caller's
  `var a = mk32()` declares `float a;`.
- A `Float64` SIMD local returns `double`, and its caller's local is
  `double a;`.
- A function returning an integer SIMD local (`SIMD[DType.int32, 4](1)`)
  keeps the `int64_t` word. The fix dispatches on a float dtype; it does not
  make every SIMD return a float.
- The existing `DType.float32` constructor lowering is unchanged (the local
  is `float` before and after this part).
- The return annotation path is untouched: `def f() -> SIMD[DType.float32,
  4]` already resolves through `_resolve_type` and must keep its answer.
- A name rebound to a float SIMD value and to a different kind in the same
  body keeps whatever the existing conflict rule says; do not introduce a
  second, wider rule for scalars.

## Done when

File: `test_codegen_erased_container_values.py` (repo root).

Command: `python3 test_codegen_erased_container_values.py simd_value_across_return`

It runs `test_simd_value_across_return_keeps_float_ctype` (red today:
`simd_value_return_mk32` is `int64_t ... (void)`). It must pass, and the
integer-SIMD arm in the same test must stay `int64_t`.

The observable form is `python3 fire.py --jit` on a file containing the
`mk32`/`use` pair above: today it prints `1`; after the fix it prints `1.5`.

## Where to start

`mojo/middle/infra_infer.py::_infer_return_type_with_locals` overlays the
body's pointer-shaped locals onto `gen.var_types` before the return scan
(`_prebound_local_ctypes`), and `_collect_return_types` then asks
`gen._quick_type` about each returned expression. A bare `IdentExpr` that is
not in that overlay falls to the `int64_t` default, which is exactly what
`return v` does here.

`_prebound_local_ctypes` (same file, above `_infer_return_type_with_locals`)
replays `AssignStmt` bindings only — Mojo's `var v = ...` is a `VarDecl`
(measured with the parser) — and its candidate table
(`_CONTAINER_LITERAL_CTYPES` and the arms that follow it) deliberately
excludes scalars. Both facts hide this binding.

Record one more candidate: a `VarDecl`/`AssignStmt` whose value is a
`SIMD`/`Scalar` constructor with a FLOAT dtype bracket, as that scalar's C
type. Read the dtype with the one resolver
`gimple_ctypes._dtype_token_ctype` (or `_simd_float_dtype_ctype` on the
rendered bracket text, which reads the same
`_SIMD_FLOAT_DTYPE_CTYPE` table); a non-float dtype answers None, which
keeps the `int64_t` word. `_type_expr_to_ann`-style rendering of the bracket
is enough to feed it, since `DType.float32`, `Float32`, `float32` and `f32`
are all keys the resolver already knows.

Keep the existing conflict rule (`conflicting` in that function): a name bound
to two disagreeing kinds must not gain a positive claim. This part adds one
narrow, float-only shape; do not relax the rule for every scalar.
