# An `alias` of a type works as a constructor callee (part 2)

Part 2 of `bugs/hard/CODEGEN_simd_and_array_values_erase_to_int64.md`.
Class: mid. One expansion at call lowering, reusing part 1's alias table; no
second table and no second constructor implementation.

Depends on part 1
(`bugs/mid/CODEGEN_simd_and_array_values_erase_to_int64-part1.md`), which adds
`gen._type_aliases`. If this part lands first, add that same harvest here and
part 1 reuses it — one map, whichever order the two land.

Measured 2026-11-13 on this tree:

    alias F2 = SIMD[DType.float32, 2]
    def mk_simd():
        var v = F2(1.0)
        return v

emits `int64_t _t1; int64_t v;` and `_t1 = (int64_t)1.0;` — the alias named
as a callee is not recognised as the `SIMD` constructor at all, so the call
takes the generic fallback. Likewise `alias A4 = Array[Float32, 4]` with
`var a = A4(fill=0.0)` emits an `int64_t a;`, casts it to `MojoList *` for
the read, and reads the element with `mojo_list_get_int`, so both the
constructor and the element type are lost.

## Goal

A module-local `alias NAME = <type>` used as the callee of a constructor call
behaves exactly like writing the aliased type's own constructor:

    alias F2 = SIMD[DType.float32, 2]
    alias A4 = Array[Float32, 4]

    def mk_simd():
        var v = F2(1.0)      # -> float v;, like SIMD[DType.float32, 2](1.0)
        return v

    def mk_arr():
        var a = A4(fill=0.0) # -> a tracked MojoList * of float
        return a[0]

## Acceptance

- `mk_simd` declares `float v;` (no `int64_t v;`) and emits no
  `indirect call via SubscriptExpr` placeholder; the argument is converted to
  the aliased dtype's scalar type, not to `int64_t`.
- `mk_arr` produces a tracked `MojoList *`: `mojo_list_append_double` for the
  fill and `mojo_list_get_double` for `a[0]`, never `mojo_list_get_int`, and
  no `(MojoList *)` cast of an `int64_t` local.
- An integer alias (`alias I2 = SIMD[DType.int32, 2]`, `I2(1)`) keeps today's
  `int64_t` lowering: expansion feeds the existing ctor dtype dispatch.
- An alias whose target is not a constructible type keeps today's behaviour;
  an unknown name is left untouched.
- No duplicated constructor lowering: expand the callee, then let the existing
  `SIMD`/`Scalar` and `Array`/`FixedSizeArray` arms in `_lower_call` do the
  work. No second alias map (reuse `gen._type_aliases`).

## Done when

File: `test_codegen_erased_container_values.py` (repo root).

Command: `python3 test_codegen_erased_container_values.py p2_alias_ctor`

It runs `test_p2_alias_ctor_expands_callee` (red today: `mk_simd` is
`int64_t v;` and `mk_arr` reads `mojo_list_get_int`). It must pass.

## Where to start

Measured 2026-11-13 with `Parser(N.py_tokenize(src)).parse_module()`: the
alias declaration is `ExprStmt(IdentExpr('alias'))` +
`AssignStmt(target=IdentExpr('NAME'), value=SubscriptExpr(...))`, and a call
through the alias is `CallExpr(func=IdentExpr(name='F2'))` — the callee
carries **no** `index`, so the bracket that would say which dtype/count is
missing by the time the constructor arms look at it.

`mojo/backend_gimple/emit_calls.py` computes the callee name as
`base = node.func.obj.name` and then dispatches `base in ('SIMD', 'Scalar')`
and `base in ('Array', 'FixedSizeArray')`. Expand a `base` that names an
alias to the target type's text before those tests, split that text into the
base name plus its bracket arguments, and dispatch on the expanded spelling.
The alias table records the target's annotation text (part 1), so the split
can reuse the existing top-level-comma/type-text helpers rather than parsing
Mojo again.

Scope the expansion to the callee position; a call whose name merely shares a
local variable's name must not be rewritten. `F2(...)` with a target that is
not one of the constructor arms falls through exactly as it does today.
