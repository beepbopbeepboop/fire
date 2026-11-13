# SIMD-typed parameters and returns keep the scalar C type through a call (part 4 replan)

Replan of `bugs/hard/CODEGEN_simd_and_array_values_erase_to_int64-part4.md`,
which sat at a class the pool cannot serve (hard has no slot). Part 4 was one
self-contained piece of work, so it comes back as a single part; see that doc
and its parent `bugs/hard/CODEGEN_simd_and_array_values_erase_to_int64.md`
for the family context (parts 1, 3, 5 are its siblings).

Class: mid. One arm in the annotation-to-C-type resolver, no lowering change —
the same class every sibling part of this family (1, 3, 5) was filed at.

## Goal

The part4 doc's goal was that a float SIMD value passed to
`id_simd(x: SIMD[DType.float32, 2])` and returned keeps its float
representation. The constructor half of that (the `SIMD[...](1.0)` call) is
part 3's; THIS part is the parameter/return/result-local propagation part 4
named.

`def id_simd(x: SIMD[DType.float32, 2]) -> SIMD[DType.float32, 2]: return x`
emits `int64_t simd_sig_id_simd_9f63a2 (int64_t x)` today, and a caller's
local that receives the result (`var r = id_simd(x)`) is declared
`int64_t r;`. After this part, the parameter and the return are the scalar C
type of the bracket's dtype (`float` for `DType.float32`, `double` for
`DType.float64`) and the result local inherits it (`float r;`).

Measured 2026-11-12: `build_stdlib_dylib.compile_module_to_c` on

    def id_simd(x: SIMD[DType.float32, 2]) -> SIMD[DType.float32, 2]:
        return x

    def use_it(x: SIMD[DType.float32, 2]):
        var r = id_simd(x)
        return r

emits `int64_t simd_sig_id_simd_9f63a2 (int64_t x)` and `int64_t r;` in
`use_it`'s body. A runtime patch of `mojo.middle.types._mojo_type` mapping
`SIMD[<float dtype>, N]` to the scalar C type changed all of that to `float`
with no other code change — signature, call-result local, and the argument
coercion all follow the annotation's C type — so the fix is the arm itself.
The result local needs no `emit_calls.py` change: it is typed from the
callee's return C type (`resolve_shared._quick_type` →
`gen._func_return_type_for_call`), populated by the signature pass from the
same resolver.

## Acceptance

- The function above's parameter and return C types are `float` in BOTH the
  forward declaration (`float <name> (float);`) and the definition
  (`float <name> (float x)`), not `int64_t`; `double` for a `DType.float64`
  bracket.
- A caller's local that receives the call result is declared with the
  callee's return C type (`float r;`), not the `int64_t` box, and the call
  site coerces its argument to the parameter's C type.
- Integer SIMD spellings keep their current lowering: `SIMD[DType.int32, 2]`
  still emits `int64_t ... (int64_t x)` (the arm dispatches on a FLOAT
  dtype; anything else falls through exactly as today).
- An unresolvable dtype argument stays conservative: it does not map to a
  wrong scalar type, the `int64_t` fallback stands.
- Downstream, `elaborate.c_to_mojo` already answers `Float32`/`Float64` for
  those C types, so an imported generic with a
  `where T.is_floating_point()` clause accepts the argument (verified
  2026-11-12: `Elaborator().elaborate_generic_call_inferred` instantiates
  such a callee with `Float32` for `['float']` and declines `['int64_t']`).

## Done when

File: `test_codegen_erased_container_values.py` (repo root).

Command: `python3 test_codegen_erased_container_values.py part4_part1`

It runs `test_part4_part1_simd_param_return_keep_ctype` (red today: the
signature is `int64_t ... (int64_t x)` and the result local is
`int64_t r;`) and `test_part4_part1_int_simd_unchanged` (green today, must
stay green). Both must pass. The test source carries NO SIMD constructor, so
the result is independent of part 3 (the constructor, carried by
`bugs/mid/CODEGEN_simd_and_array_values_erase_to_int64-part3.md`); the
original part4 doc's own test
(`test_part4_float_simd_survives_call_and_return`, run under the plain
`part4` prefix) additionally stays red until part 3 lands and is not this
part's gate.

## Where to start

`mojo/middle/types.py::_mojo_type`: `SIMD[<dtype>, N]` splits on the first
`[`, finds base `SIMD` in no branch, and erases to `int64_t` through the
`ann = base` fallthrough. Add a branch there that, for a FLOAT dtype first
argument, maps `SIMD[<dtype>, N]` (any N) to the scalar C type of the dtype,
with a small module-level spelling table (`DType.float32`/`Float32`/
`float32` → `float`; `DType.float64`/`Float64`/`float64` → `double`) so it
is reusable. Scope the arm to base `SIMD`: the `Scalar[...]` spelling is
part 5's.

Sibling coordination:
part 5 landed the same rule for the `Scalar[X]` / `SIMD[X, 1]` spellings in
`mojo/middle/infra_infer.py::_resolve_type` (the former part-5 doc is
DELETED, fixed). Whichever lands first, there must be ONE dtype-spelling
table, not two: if part 5's is already in, the `_mojo_type` arm should
resolve the dtype through it; if this arm lands first, part 5 may delegate
to its table.
