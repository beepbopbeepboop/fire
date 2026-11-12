# Span inherits element type from tracked Array/container sources (part 2)

Part 2 of `bugs/hard/CODEGEN_simd_and_array_values_erase_to_int64-part1.md`.

Depends on part 1 making `Array[...]` values tracked; this part makes `Span(<tracked value>)` preserve element type so subscript lowering does not fall back to byte reads.

## Goal

When `Span(...)` is constructed from a tracked container/list-like value (including Arrays fixed by part 1), propagate the source element type so `Span` element accesses use the correct typed getter/lowering instead of the untracked byte path.

## Current state

The parent bug measures `Span(a)` over an erased `Array` yielding no `_elem_types` entry, so `_lower_subscript`'s untracked-`Span` arm treats `_data` as `char *` and reads one byte. The call `tanh(x[0])` then sees `char`/`Int` instead of a floating type. The `_span_list` / tracked-`MojoList *` path already inherits element type when the source is tracked, but Array sources are not reaching that state.

## Plan

In `mojo/backend_gimple/emit_calls.py` and/or the Span construction/subscript helpers:
- ensure `Span(source)` records/inherits element type from `source` when `source` has tracked element type (`gen._elem_types` / equivalent span tracking), covering Array-backed tracked values;
- avoid the untracked-span byte fallback for these cases so element reads and `c_to_mojo` see the real element C/Mojo type.

## Acceptance

- `Span` over a tracked `Array[Float32, 4]` value yields element accesses typed as the float element (not one-byte `char` reads).
- `tanh(x[i])` / similar generic math calls over such a span no longer fail where-clause inference due to the element lowering as `char`/`Int` (once element types are preserved end-to-end for the case covered here).
- Existing Span behavior over already-tracked list sources remains unchanged.

## Done when

Quick test (file path and command): `python3 compile_stdlib.py test/math/test_tanh.mojo`
(or the narrowest single-file compile command this tree uses for that test) completes without the erased-element `char`/`Int` where-clause failure described in the parent bug for `tanh(x[i])` over a Span of array elements.
