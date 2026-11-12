# Span(<tracked container>) inherits the element type (part 2)

Part 2 of `bugs/hard/CODEGEN_simd_and_array_values_erase_to_int64.md`.

Depends on part 1: until `Array[...]` is a tracked container, there is no
element type for `Span` to inherit. Class: mid. The inheritance is the existing
`_span_list` arm, extended to Array-backed sources.

## Goal

`Span(a)` over a tracked `Array` records the source element type, so
`_lower_subscript` reads elements with a typed getter. Today the source has no
`_elem_types` entry, the untracked-Span arm treats `_data` as `char *`, and
`s[0]` reads ONE BYTE through `_mojo_at_char`. That byte is what
`tanh(x[0])` then sees as `Int`.

## Acceptance

- `Span` over an `Array[Float32, 4]` value does not read elements through
  `_mojo_at_char` (the one-byte path).
- The element read carries the source element type, so the `tanh(x[i])`
  where-clause no longer sees `char`/`Int`.
- `Span` over an already-tracked list source is unchanged.

## Done when

File: `test_codegen_erased_container_values.py` (repo root).

Command: `python3 test_codegen_erased_container_values.py part2`

It runs `test_part2_span_over_array_inherits_element_type` (red today; it is
also red until part 1 lands, because the source is still erased). It must pass.

## Where to start

`mojo/backend_gimple/emit_calls.py`, the `Span(...)` constructor arm and the
`_span_list` path that already inherits element type from a tracked
`MojoList *`. Extend that to a source that part 1 has recorded in
`gen._elem_types`.
