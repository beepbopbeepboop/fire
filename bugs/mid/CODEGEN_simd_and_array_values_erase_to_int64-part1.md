# Array construction tracks element type and initializes storage (part 1)

Part 1 of `bugs/hard/CODEGEN_simd_and_array_values_erase_to_int64-part1.md`.

## Goal

Lower `Array[T, N]` / `FixedSizeArray[T, N]` construction to a real runtime-backed value whose element C type is tracked, instead of erasing the whole value to `int64_t` and falling back to indirect-call/list-get-int behavior.

## Current state

`_lower_call`'s generic container constructor handling does not give `Array`/`FixedSizeArray` the same treated construction path as tracked list-like containers. As measured in the parent bug, a probe like:

```python
def f():
    var a = Array[Float32, 4](fill={})
    print(a[0])
```

lowers to erased values (`int64_t` temporaries/locals, indirect-call fallback, `mojo_list_get_int`), so downstream element reads and consumers cannot recover the real element type.

## Plan

In `mojo/backend_gimple/emit_calls.py` (generic container constructors / call lowering for container construction):
- add an `Array`/`FixedSizeArray` branch that constructs a real list/array value (`mojo_list_new()` or the runtime form already used for compatible fixed arrays in this backend);
- record `gen._elem_types[t]` for the constructed value from the first bracket type argument (e.g. via `_annotation_container_elem_type(gen, 'Array[%s]' % ann, 'MojoList *')` or equivalent);
- initialize `N` elements for the supported construction forms relevant here (including `fill=`), so indexed reads are well-defined.

Keep the change representation-correct for Array values; byte-identical generated C is not expected.

## Acceptance

- Constructing `Array[Float32, 4]` yields a tracked container value whose element type is known as the float element type (not `int64_t`).
- Element reads from such an Array value no longer go through the erased `mojo_list_get_int` path solely because the Array construction was erased.
- Existing `List` construction behavior remains unchanged.

## Done when

Quick test (file path and command): run the probe in `bugs/hard/CODEGEN_simd_and_array_values_erase_to_int64-part1.md` §"What was measured" via:
`python3 -c "import sys; sys.path.insert(0,'.'); import build_stdlib_dylib as b; src='def f():\n    var a = Array[Float32, 4](fill=0.0)\n    print(a[0])\n'; c=b.compile_module_to_c(src,'arr.mojo','arr',linkable=False); print(c)"`
and confirm the emitted C shows a real constructed/tracked array value for `Array[Float32, 4]` with a typed element access (not the erased `(int64_t)0` constructor + `mojo_list_get_int` path shown in the parent bug).
