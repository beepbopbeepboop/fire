# A `comptime`-bound float DType survives a call and a return (part 4 replan, part 3)

Part 3 of the replan of
`bugs/hard/CODEGEN_simd_and_array_values_erase_to_int64-part4.md`; see also
the family parent `bugs/hard/CODEGEN_simd_and_array_values_erase_to_int64.md`.

Class: mid. Resolve a `comptime` name bound to a dtype before the annotation
reaches the stateless resolver; no lowering change.

Measured 2026-11-13: the original part 4 probe
(`test_part4_float_simd_survives_call_and_return`) is GREEN on this tree,
because part 3's float SIMD constructor (c0dc53479) and part4-part1's
resolver arm (9a2d6080c) both landed. What still erases is a dtype that is
not spelled literally in the bracket: `SIMD[dt, 2]`, where `dt` is a
`comptime` name bound to `DType.float32`, falls through to `int64_t`.

## Goal

A float SIMD value whose dtype comes from a `comptime` binding keeps its
scalar C type through a parameter, a return, and the local that receives the
call result. Both spellings matter:

- module scope, a signature:

      comptime dt = DType.float32
      def id_simd(x: SIMD[dt, 2]) -> SIMD[dt, 2]:
          return x
      def use_it(x: SIMD[dt, 2]):
          var r = id_simd(x)
          return r

- function scope, an explicitly annotated local:

      def use_it(x: SIMD[DType.float32, 2]):
          comptime dt = DType.float32
          var r: SIMD[dt, 2] = id_simd(x)
          return r

Today the first emits `int64_t p4_ct_top_id_simd_9f63a2 (int64_t x)` and
`int64_t r;`; the second emits `int64_t r;` with an `(int64_t)` cast around
the call result, even though `id_simd` itself returns `float`.

## Acceptance

- Both sources above produce `float r;` (no `int64_t r;`), and the
  module-scope one also produces a `float ... (float x)` definition and a
  `float ... (float);` forward declaration.
- `comptime dt = DType.float64` resolves to `double`.
- An unresolved or non-dtype binding stays conservative: it does not map to
  a scalar type, the `int64_t` fallback stands.
- One dtype-spelling table only: reuse
  `mojo/middle/types.py::_SIMD_FLOAT_DTYPE_CTYPE` (added by part4-part1)
  rather than adding a second mapping. The `Scalar[...]` spelling remains
  part 5's (a separate sub-part).

## Done when

File: `test_codegen_erased_container_values.py` (repo root).

Command: `python3 test_codegen_erased_container_values.py p4_comptime`

It runs `test_p4_comptime_dtype_keeps_ctype` (red today at the module-scope
signature: `int64_t ... (int64_t x)` and `int64_t r;`). It must pass. The
`p4_comptime` prefix is deliberate: the original part 4 probe's command runs
every `test_part4_*`, and that probe is green today, so an open sub-part must
not redden it.

## Where to start

`mojo/middle/infra_infer.py::_resolve_type` has `gen`, so it can consult the
already-populated compile-time binding table `gen._comptime_vals` before
delegating to the stateless `mojo/middle/types.py::_mojo_type`. Measured
2026-11-13 with `GimpleGen.gen_module` on `comptime dt = DType.float32`:
`gen._comptime_vals['dt']` is the string `"('DType', 'float32')"` — a
tuple-repr, not a DType object — so the resolver must recognize that shape
(and the bare `'float32'`/`'Float32'` spellings) and map it through
`_SIMD_FLOAT_DTYPE_CTYPE`.

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
