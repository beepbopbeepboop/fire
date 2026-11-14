# An `alias` of a type survives as a parameter, return, local and element annotation (part 1)

Part 1 of `bugs/hard/CODEGEN_simd_and_array_values_erase_to_int64.md`.
Class: mid. One resolver step plus collecting the module's `alias`
declarations; no lowering change.

Measured 2026-11-13 on this tree: `alias F2 = SIMD[DType.float32, 2]` used as
a parameter and return still emits

    int64_t p1_alias_id_simd_9f63a2 (int64_t x)

and `var r: F2 = x` emits `int64_t r;`, even though the literal spelling
`SIMD[DType.float32, 2]` already resolves to `float` (part4-part1 landed,
9a2d6080c). Likewise `alias F = Float32` in `Array[F, 4](fill=0.0)` emits
`mojo_list_get_int` for `a[0]`, so the element type was recorded as
`int64_t` rather than `float`.

## Goal

A module-local `alias NAME = <type>` behaves exactly like the type it names
wherever that name is used as a **type annotation**:

    alias F2 = SIMD[DType.float32, 2]
    alias F = Float32

    def id_simd(x: F2) -> F2:
        return x

    def use_it(x: F2):
        var r = id_simd(x)
        return r

    def use_local(x: F2):
        var r: F2 = x
        return r

    def arr():
        var a = Array[F, 4](fill=0.0)
        return a[0]

After this part `id_simd` is `float <name> (float x)` (definition and forward
declaration), `use_it` and `use_local` declare `float r;`, and `arr` reads its
element with `mojo_list_get_double`.

## Acceptance

- The definition is `float <name> (float x)` and the forward declaration is
  `float <name> (float);` — neither is `int64_t`.
- `use_it`'s call-result local and `use_local`'s annotated local are both
  `float r;`, with no `int64_t r;` and no `indirect call via SubscriptExpr`
  placeholder.
- `Array[F, 4](fill=0.0)` with `alias F = Float32` records `float` as the
  element type: `a[0]` is `mojo_list_get_double`, never `mojo_list_get_int`.
- An integer alias (`alias I2 = SIMD[DType.int32, 2]`) keeps today's
  `int64_t` lowering: expansion feeds the existing dtype dispatch rather than
  forcing every alias to a float.
- An alias to a non-SIMD, non-container type keeps the type it resolves to
  today (for example a struct alias still resolves to `Foo *`), and an
  unknown name is left untouched so the conservative fallback stands.
- Only module-local aliases are in scope. The stdlib's `Scalar[dt]` spelling
  already landed (part 5); do not build a second dtype-spelling table.
- An alias used as a **constructor callee** (`F2(...)`, `A4(...)`) is part 2,
  not this part.

## Done when

File: `test_codegen_erased_container_values.py` (repo root).

Command: `python3 test_codegen_erased_container_values.py p1_alias`

It runs `test_p1_alias_expands_in_annotations` (red today: the definition is
`int64_t ... (int64_t x)`, the locals are `int64_t r;`, and the array read is
`mojo_list_get_int`). It must pass.

## Where to start

`mojo/middle/infra_infer.py::_resolve_type` is the instance-aware resolver
(every annotation-to-C-type call goes through it; it has `gen`, unlike the
stateless `mojo/middle/types.py::_mojo_type`).

Module-level `alias NAME = T` does not have its own AST node: measured
2026-11-13 with `Parser(N.py_tokenize(src)).parse_module()`, it parses as
`ExprStmt(IdentExpr('alias'))` followed by
`AssignStmt(target=IdentExpr('NAME'), value=<the type expression>)`, so the
declarations can be collected in the same module walk that already prefolds
module-scope `comptime` bindings (`mojo/middle/module_shared.py`). Render the
value with the existing type-text helper used for annotations.

Add `gen._type_aliases: dict[str, str]` populated from those pairs, and in
`_resolve_type` expand a bare annotation that names an alias **before**
delegating to `gimple_ctypes._mojo_type`. Expand recursively (an alias of an
alias) with a seen-set so a cycle cannot hang codegen. Assume nothing about
the alias's target being SIMD: expand and let the existing `SIMD` arm decide,
which is also what keeps the integer and struct cases above unchanged.

The container-element path already asks the resolver: the `Array` constructor
records `gen._elem_types` from the bracket's first type argument through
`gen._resolve_type` (part 1 of the parent doc), so once `F` expands there the
element type follows. Verify that with the `arr` half of the probe rather than
adding a second element-type expansion.
