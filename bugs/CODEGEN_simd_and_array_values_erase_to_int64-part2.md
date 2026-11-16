# A typed container constructor hands its element type across a call boundary (part 2)

Part 2 of `bugs/hard/CODEGEN_simd_and_array_values_erase_to_int64.md`.
Class: easy. One binding shape added to the existing element-type pre-pass.

## Goal

A function that returns a container built by a **typed constructor**
(`List[T]()`, `Array[T, N]()`) gives its caller the element type the bracket
declares, so the caller's `x[i]` uses the typed accessor instead of the
unknown-element default.

This is the parent doc's "a container that crosses a call boundary" half. The
cross-call element contract already exists (`_return_elem_types`, fed by
`_scan_container_elems` -> `_quick_container_elem`); it simply cannot see a
constructor binding. Measured 2026-11-15 on this tree:

    def mk() -> List[Float32]:
        var l = List[Float32]()
        l.append(1.5)
        return l

    def f():
        var a = mk()
        return a[0]

emits `mojo_list_get_int (a, _t2)` in `f`. At run time
`print(mk()[0])` prints `4609434218613702656` (the double's bit pattern)
instead of `1.5`. `List[Int]` and `List[String]` work today because the
unknown-element default happens to be their accessor (`get_int`), which is
exactly why the float case is the observable one.

## Acceptance

- The caller of a function returning `List[Float32]` reads the element with
  `mojo_list_get_double`, never `mojo_list_get_int`; the value printed is
  `1.5`, not its bit pattern.
- The element C type recorded is the list's STORAGE type: a `Float32`
  element is stored as `double` (the same `float` -> `double` mapping the
  `Array` constructor arm already applies), so the accessor is
  `mojo_list_get_double`.
- `List[Int]` still reads `mojo_list_get_int` and `List[String]` still reads
  `mojo_list_get_str` — the fix adds a missing evidence shape, it does not
  change how known kinds are read.
- A locally constructed `List[Float32]` keeps its current codegen (its local
  read is a separate gap; this part is the return/call boundary only).
- The element answer is derived with the existing resolver
  (`gen._resolve_type`) and the existing element-type tables. No second
  dtype/element table.

## Done when

File: `test_codegen_erased_container_values.py` (repo root).

Command: `python3 test_codegen_erased_container_values.py list_elem_across_return`

It runs `test_list_elem_across_return_keeps_element_type` (red today:
`list_elem_return_f32` reads `mojo_list_get_int`). It must pass, and the
`List[Int]` / `List[String]` arms in the same test must stay green.

The observable form of the same probe is a `.mojo` program:

    def mk() -> List[Float32]:
        var l = List[Float32]()
        l.append(1.5)
        return l

    def main():
        print(mk()[0])

`python3 fire.py --jit <that file>` prints `1.5` after the fix; today it
prints `4609434218613702656`.

## Where to start

`mojo/middle/infra_infer.py::_scan_container_elems` (around line 3061). It
builds the per-function element map that `_quick_container_elem` ->
`_collect_return_elems` -> `_return_elem_types` turns into the cross-call
contract.

It replays list literals, `[x] * n`, `append(...)` with a literal or a
known-element identifier, tuple literals and subscript stores — all of them
`AssignStmt` bindings. Two shapes are missing for this probe, and the probe
needs both:

1. Mojo's `var l = ...` parses as a `VarDecl`, not an `AssignStmt` (measured
   with `Parser(N.py_tokenize(src)).parse_module()`), so the pre-pass never
   looks at the binding at all;
2. the right-hand side is a `SubscriptExpr`-callee constructor
   (`List[Float32]()`), which is neither a literal nor a builtin-call shape
   the scan knows.

Add a VarDecl arm (same body as the AssignStmt arm) and a
typed-container-constructor arm: for a `CallExpr` whose `func` is a
`SubscriptExpr` over `List`/`Array`/`FixedSizeArray` (the `Dict`/`Set`
equivalents can follow the same pattern, but they are not needed by this
probe), take the bracket's first type argument through `gen._resolve_type`
and record it as the element type. Apply the same `float` -> `double`
storage mapping the `Array` constructor arm uses
(`emit_calls.py::_lower_call`, the `if _elem_ct == 'float':` line), so the
contract names the type the runtime accessor actually reads.

Do not extend `_elem_types` at the constructor call site instead: the point
is the static pre-pass, which runs before the caller is lowered and is the
only place the cross-call contract can be seeded from.
