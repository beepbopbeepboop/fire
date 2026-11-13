# A container parameter keeps the element type its annotation declares (part 4)

Part 4 of `bugs/hard/CODEGEN_simd_and_array_values_erase_to_int64.md`.
Class: mid. Two annotation-resolution points (the C type of the parameter and
the element type seeded from its bracket); no lowering change.

Measured 2026-11-13 on this tree:

| parameter annotation | emitted C | `a[0]` inside the callee |
|---|---|---|
| `a: Array[Float32, 4]` | `MojoList * a` | `mojo_list_get_int` |
| `Span(a)` inside that callee | tracked `Span *` | `_mojo_at_char` (one byte) |
| `a: FixedSizeArray[Float32, 4]` | `int64_t a`, then `(MojoList *)` | `mojo_list_get_int` |

`Array` already resolves to `MojoList *`, but `FixedSizeArray` is in neither
the container arm of `mojo/middle/types.py::_mojo_type` nor the parameter
element seed. Neither base is in
`mojo/backend_gimple/emit_funcs.py::_seed_annotated_param_elem_types`, which
seeds `list`/`List`/`set`/`Set`/`frozenset`/`dict`/`Dict`/`Span` only — so
takes the static element type from the container constructor (part 1) but
loses it the moment the value crosses a call.

## Goal

A container parameter's annotation is the static truth about its contents:

    def take(a: Array[Float32, 4]):
        return a[0]                     # mojo_list_get_double

    def span_take(a: Array[Float32, 4]):
        var s = Span(a)
        return s[0]                     # _mojo_at_double

    def take_fixed(a: FixedSizeArray[Float32, 4]):
        return a[0]                     # MojoList * a, mojo_list_get_double

## Acceptance

- `Array[Float32, 4]` and `FixedSizeArray[Float32, 4]` parameters are both
  `(MojoList * a)`, not `int64_t`.
- `a[0]` in both is `mojo_list_get_double`, never `mojo_list_get_int`.
- `Span(a)` over that parameter is tracked, so its element read is
  `_mojo_at_double`, never `_mojo_at_char`.
- An integer element keeps its own read: `Array[Int, 4]` and
  `FixedSizeArray[Int, 4]` parameters stay `(MojoList * a)` and read
  `mojo_list_get_int` (no float-typed read for an `Int` element).
- The element is the **first** bracket argument: `Array[T, N]` and
  `FixedSizeArray[T, N]` carry the count second, exactly like `Span[T,
  origin]` already handles. Do not assume one bracket argument.
- `List`/`Dict`/`Set`/`Span` parameter seeding is unchanged.

## Done when

File: `test_codegen_erased_container_values.py` (repo root).

Command: `python3 test_codegen_erased_container_values.py p4_container_param`

It runs `test_p4_container_param_keeps_element_type` (red today: `Array`
reads `mojo_list_get_int`, `Span(a)` reads `_mojo_at_char`, and
`FixedSizeArray` is `int64_t`). It must pass.

## Where to start

- `mojo/middle/types.py::_mojo_type`, the bracket container arm
  `base in ('List', 'list', 'InlineArray', 'Array')` returns `MojoList *`.
  Add `FixedSizeArray` there; `_TYPE_MAP`'s `List`/`list` entry is what the
  un-bracketed spelling uses. Keep `FixedSizeArray` out of the imported-struct
  path for the same reason `Array` is.
- `mojo/backend_gimple/emit_funcs.py::_seed_annotated_param_elem_types`
  seeds `gen._elem_types` from the annotation. Add `Array` and
  `FixedSizeArray` to the bases it accepts, and take their first bracket
  argument as the element (the existing `Span` branch already does exactly
  that); the generic branch below it requires exactly one bracket argument
  and must not see these two.
- `_annotated_elem_ctype`/`gen._resolve_type` already resolve the element
  spelling to a C type; `FixedSizeArray`'s element type is therefore the same
  lookup, not a new one.
