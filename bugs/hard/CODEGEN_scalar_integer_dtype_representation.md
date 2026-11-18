SPLIT: CODEGEN_scalar_integer_dtype_representation-part1, CODEGEN_scalar_integer_dtype_representation-part2 (part3 fixed and deleted)

# CODEGEN: integer `Scalar[DType.*]` lowers to a 64-bit word

**Status (2026-11-18): replanned for the easy pool. The work is in the
`CODEGEN_scalar_integer_dtype_representation-part1..2` docs; part3 (imported overload choice in a concrete specialised generic) is fixed. This doc keeps the
measured evidence, the rejected fix and the gates.**

## Symptom

Every integer `Scalar[DType.X]` (`uint8`, `int16`, `uint32`, ...) is typed in C
as `int64_t`. Only the float dtypes have a C type of their own. The consequences
measured this round:

1. **Wrong overload, silently.** `stdlib/std/utils/fast_div.mojo` computes
   `mulhi(self._mprime.cast[.uint32](), other.cast[.uint32]())` inside the
   generic struct `FastDiv[dtype]`. `.cast[.uint32]()` lowers to a no-op
   (`_t2 = _t1`), so the call sees two `int64_t` arguments and chooses
   `mulhi(Int64, Int64)`. The `uint32` overload is the one the arithmetic needs.
   For `uint32` operands the `Int64` result is 0 where `uint32` gives the high
   word, so `FastDiv` is wrong. The one remaining undefined `_std_` name in the
   dylib (`_std__gpu_intrinsics_mulhi__1_0_5_Int64_1_1_5_Int64`) is this call.

2. **Erasure stops the typed overload choice.** The import-side overload
   chooser (`emit_calls._imported_overload_call_symbol`) only chooses by exact
   C types in an erasure-free caller (`emit_infra._erasure_free_context`), so
   the generic call stays on the elaborated path.

## Minimal repro (confirmed)

```mojo
def first(ctrl: UnsafePointer[Scalar[DType.uint8]], target: Scalar[DType.uint8]) -> Bool:
    for i in range(4):
        if ctrl[i] == target:
            return True
    return False
```

Emitted today: `_Bool first (int64_t *ctrl, int64_t target)`. Repeated with the
integer mapping temporarily added to `_SIMD_FLOAT_DTYPE_CTYPE`'s lookup (the
experiment, reverted): `_Bool first (int64_t * ctrl, uint8_t target)`. The
pointer element stays `int64_t` while the scalar parameter is `uint8_t`, so the
two spellings of one type disagree.

## Why the naive fix was rejected

Adding `uint8_t`/`uint16_t`/`uint32_t`/... to the dtype table in
`mojo/middle/types.py` (`_SIMD_FLOAT_DTYPE_CTYPE` and the `_dtype_token_ctype`
lookup it serves) was tried and reverted. Measured with the full stdlib dylib
build:

- 53 build errors, all of the form "expected pointer as argument of unary '*'"
  and "invalid conversion in gimple call", in `std/collections/_swisstable.mojo`
  (`ctrl[i]` loops over a `UnsafePointer[Scalar[DType.uint8]]`) and
  `std/random/philox.mojo`.
- 13 exports lost (1203 -> 1190).

The table change reaches the scalar sites but not the pointer-element sites, so
the program now has two disagreeing types for one element.

## Where the mapping lives (measured)

- `mojo/middle/types.py`: `_SIMD_FLOAT_DTYPE_CTYPE` and `_dtype_token_ctype`.
  The float-only table is the single source for the annotation resolver
  (`infra_infer._resolve_type`), the constructor lowerer (`emit_calls`' `SIMD`/
  `Scalar` arm), and `_mojo_type` (per its comment).
- `mojo/backend_gimple/elab_intu.py` ~479-490: the `Scalar[X]` -> `SIMD[X, 1]`
  binding for call-site type inference.
- The pointer element type (`UnsafePointer[Scalar[...]]` -> `int64_t *`) is NOT
  in that table. Its resolver is not yet located; finding it is step 1 below.

## Plan

The site search (step 1) is deliberately deferred: it is the first task of this
bug's next round, and nothing below it should be started before its result is
recorded here.

**Step 1 — locate every mapping site (measurement only). DEFERRED to this
bug's own next round:** the search is not done yet, and this section is its
definition, not a result. For each of: the
annotation resolver; pointer element resolution; parameter ctype; return ctype;
local declarations; subscript load and store through a pointer; the struct field
layout (`_struct_layout_anns`, `_imported_field_ctype`); comparisons and
arithmetic on a `Scalar`; `.cast[T]()`; boxing (`mojo_box_from_*`); the
`_mojo_type` in `gimple_codegen`. Record each site's file and line in this doc
with the repro above as its test. No code change in this step.

**Step 2 — one representation.** Decide the C type of each integer dtype
(`int8_t` ... `uint64_t`) and make every site in step 1 return it, through ONE
function (consolidate, per CLAUDE.md: no second table). Float dtypes already work
and must not change.

**Step 3 — arithmetic and conversion.** Narrow integer arithmetic must wrap at
the dtype width (`uint8` + `uint8` wraps at 256). Check the operators and the
`.cast` lowering. `.cast[.uint32]()` must truncate. A value stored in a
`uint8_t` must not be widened silently by the 64-bit path.

**Step 4 — boxing and the interpreter.** `mojo/middle/float8_dtype.py` and the
float boxing path (`_box_float_mixed_return_arm`) show the pattern for a dtype
with its own C type; mirror it for integers only if the step-1 measurement says
an integer `Scalar` crosses a box.

**Step 5 — the overload choice.** With real argument types, the generic
`FastDiv` call resolves to `mulhi(UInt32, UInt32)`. Remove or narrow
`_erasure_free_context` where the types are now real, and re-measure which
calls still take the elaborated path.

## Tests (must fail before, pass after)

- The repro above: emitted C has `uint8_t` for both the element and the scalar
  parameter.
- `fast_div`: `FastDiv[DType.uint32](d)` divides correctly for a sample set,
  checked against integer division. A `uint32` operand above 2^31 is the case
  where the `Int64` overload differs.
- `test_out_param_local.py`, `test_import_overload_choice.py`,
  `test_gimple.py` (465 today): no change.
- Stdlib gates: `compile_stdlib.py` (610/610, 0 skips today) and the dylib
  (1203/1203, 0 errors, 1 undefined today).

## Gates

Stdlib-syntax and dylib after each step. Full `make gate` is the owner's call.
The swisstable and philox failures above are the early warning: a step that
brings them back is wrong, whatever the other numbers say.

## Out of scope

The generic-struct elaboration itself (per-instantiation emission). Imported
generic instances already specialise (`Fd_5_dtype_17_DType_x002Euint32_f`); the
problem here is the element type, not the instance.
