# Array[T, N](...) lowers to a tracked container, not the erased int64_t (part 1)

Part 1 of `bugs/hard/CODEGEN_simd_and_array_values_erase_to_int64.md`.

Class: mid. The change is one new constructor arm in `_lower_call` mirroring the
existing `List(...)` arm, plus its element-type bookkeeping. It touches one
lowering site and no type-resolution rules, so it does not need the hard pass.

## Goal

`Array[Float32, 4](fill=0.0)` (and `FixedSizeArray[...]`) lowers to a real
runtime-backed value whose element C type is recorded in `gen._elem_types`,
initialized for `N` elements. Today it becomes `_t1 = (int64_t)0;  /* indirect
call via SubscriptExpr */` and the element read goes through
`mojo_list_get_int`.

## Acceptance

- The constructed `Array` is not lowered through the "indirect call via
  SubscriptExpr" placeholder.
- An element read of the Array does not use `mojo_list_get_int`.
- `List[Int]()` construction and its append/get lowering are byte-for-byte what
  they are today (`mojo_list_init`, `mojo_list_append_int`, `mojo_list_get_int`).

## Done when

File: `test_codegen_erased_container_values.py` (repo root, with the other
`test_codegen_*` files).

Command: `python3 test_codegen_erased_container_values.py part1`

It runs `test_part1_array_ctor_is_tracked` (red today) and
`test_part1_list_ctor_unchanged` (green today, must stay green). Both must
pass.

## Where to start

`mojo/backend_gimple/emit_calls.py::_lower_call`, "Generic container
constructors" arm. Model the Array branch on the `List(...)` arm. Element type
comes from `_annotation_container_elem_type(gen, 'Array[%s]' % ann, 'MojoList *')`.
