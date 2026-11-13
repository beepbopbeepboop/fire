# A `comptime`-bound float DType survives in every type position (part 3)

Part 3 of `bugs/hard/CODEGEN_simd_and_array_values_erase_to_int64.md`.
Class: mid. Resolve a `comptime` name bound to a dtype before the annotation
and constructor dtype lookups; no lowering change.

Measured 2026-11-13 on this tree: with `comptime dt = DType.float32`,

- `def id_simd(x: SIMD[dt, 2]) -> SIMD[dt, 2]` emits
  `int64_t <name> (int64_t x)` and `int64_t r;` at its call site;
- `var v = SIMD[dt, 2](1.0)` emits `int64_t v;`;
- a function-scope `comptime d2 = DType.float32` followed by
  `var r: SIMD[d2, 2] = ...` emits `int64_t r;`.

Only width 1 is handled today: `_resolve_type`'s `Scalar[...]` /
`SIMD[..., 1]` arm consults `gen._comptime_vals` (part 5), while the
any-width `SIMD[<float dtype>, N]` arm lives in the stateless
`mojo/middle/types.py::_mojo_type` and its `_simd_float_dtype_ctype` table
knows literal spellings only.

## Goal

A float SIMD value whose dtype comes from a `comptime` binding keeps its
scalar C type through a parameter, a return, an explicitly annotated local,
and a SIMD constructor:

    comptime dt = DType.float32

    def id_simd(x: SIMD[dt, 2]) -> SIMD[dt, 2]:
        return x

    def use_it(x: SIMD[dt, 2]):
        var r = id_simd(x)
        return r

    def mk():
        var v = SIMD[dt, 2](1.0)
        return v

    def use_local(x: SIMD[DType.float32, 2]):
        comptime d2 = DType.float32
        var r: SIMD[d2, 2] = id_simd(x)
        return r

After this part `id_simd` is `float <name> (float x)`, and `use_it`, `mk` and
`use_local` declare `float r;` / `float v;`.

## Acceptance

- The module-scope source produces a `float ... (float x)` definition and a
  `float ... (float);` forward declaration, `float r;` in `use_it`, and no
  `int64_t r;` / `indirect call via SubscriptExpr`.
- `var v = SIMD[dt, 2](1.0)` emits `float v;`.
- The function-scope `comptime d2` source emits `float r;`.
- `comptime dt64 = DType.float64` resolves to `double` (definition and
  forward declaration).
- An unresolved or non-dtype binding stays conservative: it does not map to a
  scalar type, the `int64_t` fallback stands.
- One dtype-spelling table only: reuse
  `mojo/middle/types.py::_SIMD_FLOAT_DTYPE_CTYPE`; do not add a second
  mapping.

## Done when

File: `test_codegen_erased_container_values.py` (repo root).

Command: `python3 test_codegen_erased_container_values.py p3_comptime`

It runs `test_p3_comptime_dtype_resolves_in_all_type_positions` (red today at
the module-scope signature: `int64_t ... (int64_t x)` and `int64_t r;`). It
must pass.

## Where to start

`mojo/middle/infra_infer.py::_resolve_type` has `gen`, so it can consult
`gen._comptime_vals` before delegating to the stateless
`mojo/middle/types.py::_mojo_type`. Measured 2026-11-13 with
`GimpleGen.gen_module` on `comptime dt = DType.float32`:
`gen._comptime_vals['dt']` is the string `"('DType', 'float32')"` — a
tuple-repr, not a DType object — so the resolver must recognise that shape
(and the bare `'float32'` / `'Float32'` spellings) and map it through
`_SIMD_FLOAT_DTYPE_CTYPE`.

For the constructor, `mojo/backend_gimple/emit_calls.py`'s `SIMD`/`Scalar` arm
resolves the bracket's first element with `_dtype_cast_ctype`, then with
`_type_expr_to_ann` + `_DTYPE_CAST_CTYPES`; a bare `dt` is in neither. Add
the same folded-value lookup there (reusing the resolver helper) rather than
a second dtype table.

Two orderings have to be checked while landing this:

- the module-scope binding must be prefolded before the signature pass that
  resolves parameters and returns (see
  `mojo/middle/module_shared.py::_gmi_prefold_toplevel_comptime`); if it is
  not, prefold it first rather than special-casing signatures;
- the function-scope binding is recorded when the `comptime` statement is
  walked, which is before a later `var r: SIMD[dt, 2]` is emitted — verify
  that with the function-local half of the test.

Scope the lookup to a bracketed dtype argument; do not rewrite arbitrary
annotations that merely share the name.
