# An `alias` of a float SIMD type survives a call and a return (part 4 replan, part 2)

Part 2 of the replan of
`bugs/hard/CODEGEN_simd_and_array_values_erase_to_int64-part4.md`; see also
the family parent `bugs/hard/CODEGEN_simd_and_array_values_erase_to_int64.md`.
Part 1 of this replan (the `SIMD[<float dtype>, N]` resolver arm) landed
2026-11-13 and its doc was deleted with the fix.

Class: mid. One annotation-resolution step plus collecting the module's
`alias` declarations; no lowering change — the same class part4-part1 was
filed at.

Measured 2026-11-13: the original part 4 probe
(`test_part4_float_simd_survives_call_and_return`) is GREEN on this tree,
because part 3's float SIMD constructor (c0dc53479) and part4-part1's
resolver arm (9a2d6080c) both landed. What still erases is the same value
spelled through a user `alias`: `alias F2 = SIMD[DType.float32, 2]` is not
expanded, so a parameter/return/local annotated `F2` falls through to the
universal `int64_t` scalar.

## Goal

`alias F2 = SIMD[DType.float32, 2]` used as a parameter and return annotation
keeps the scalar C type of the aliased SIMD dtype. Today

    alias F2 = SIMD[DType.float32, 2]
    def id_simd(x: F2) -> F2:
        return x
    def use_it(x: F2):
        var r = id_simd(x)
        return r

emits `int64_t p4_alias_id_simd_9f63a2 (int64_t x)` and `int64_t r;` in
`use_it`. After this part both are `float`, and the call result needs no cast
to `int64_t`.

## Acceptance

- The definition is `float <name> (float x)` and the forward declaration is
  `float <name> (float);` — neither is `int64_t`.
- `use_it`'s local that receives the call result is `float r;`, not
  `int64_t r;`, and its body carries no `indirect call via SubscriptExpr`
  placeholder.
- An integer alias (`alias I2 = SIMD[DType.int32, 2]`) keeps today's
  `int64_t` lowering: the expansion feeds the existing resolver, which is
  what dispatches on a FLOAT dtype.
- An alias to a non-SIMD type keeps the type it resolves to today (for
  example a struct alias still resolves to `Foo *`); an unknown name is left
  untouched, so the conservative fallback stands.
- Only module-local aliases are in scope. The stdlib's `Scalar[dt]` spelling
  is part 5's rule and landed with it (`_resolve_type` resolves `Scalar` and a
  width-1 `SIMD` through `mojo/middle/types.py::_SIMD_FLOAT_DTYPE_CTYPE`; part
  5's doc was DELETED with that fix). Do not build a second dtype-spelling
  table: the resolver and `emit_calls._float_dtype_arg_ctype` both read the
  one table.

## Done when

File: `test_codegen_erased_container_values.py` (repo root).

Command: `python3 test_codegen_erased_container_values.py p4_alias`

It runs `test_p4_alias_simd_param_return_keep_ctype` (red today: the
definition is `int64_t ... (int64_t x)` and the result local is
`int64_t r;`). It must pass. The `p4_alias` prefix is deliberate: the
original part 4 probe's command runs every `test_part4_*`, and that probe is
green today, so an open sub-part must not redden it.

## Where to start

`mojo/middle/infra_infer.py::_resolve_type` is the instance-aware resolver
(every annotation-to-C-type call goes through it; it has `gen`, unlike the
stateless `mojo/middle/types.py::_mojo_type`). Module-level `alias NAME = T`
does not have its own AST node: measured 2026-11-13 with
`Parser(py_tokenize(src)).parse_module()`, it parses as
`ExprStmt(IdentExpr('alias'))` followed by
`AssignStmt(target=IdentExpr('NAME'), value=<the type expression>)`, so the
declarations can be collected in the same pass that walks the module body.

Add a `gen._type_aliases: dict[str, str]` populated from those pairs (render
the value with the existing type-text helper used for annotations), and in
`_resolve_type` expand a bare annotation that names an alias before
delegating to `gimple_ctypes._mojo_type`. Expand recursively (an alias of an
alias) with a seen-set so a cycle cannot hang codegen. Assume nothing about
the alias's target being SIMD: expand and let the existing `SIMD` arm decide,
which is also what keeps the integer and struct cases above unchanged.
