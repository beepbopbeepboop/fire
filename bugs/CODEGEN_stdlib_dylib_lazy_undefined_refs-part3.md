# A same-arity dunder overload group is referenced as one concrete overload, never bare (part 3)

Part 3 of `bugs/hard/CODEGEN_stdlib_dylib_lazy_undefined_refs.md`.
Class: easy. One overload-selection clause in the struct-dunder dispatch; no
lowering change.

Measured 2026-11-13 on this tree. A struct with two same-arity
`__getitem__` overloads

    struct Pair:
        var a: Int
        var b: Int
        def __getitem__(self, i: Int) -> Int:
            return i + 100
        def __getitem__(self, s: String) -> Int:
            return s.length + 100
    def f(p: Pair) -> Int:
        return p[0]

compiles to two suffixed definitions plus a BARE, suffix-less reference:

    int64_t pair_Pair___getitem___8176d0 (Pair *, int64_t);
    int64_t pair_Pair___getitem___12ca46 (Pair *, char *);
    int64_t pair_Pair___getitem__ (...);
    __GIMPLE int64_t pair_Pair___getitem___8176d0 (Pair * self, int64_t i)
    __GIMPLE int64_t pair_Pair___getitem___12ca46 (Pair * self, char * s)
      _t1 = pair_Pair___getitem__ (p, _t3);

`_lower_struct_subscript_dunder` (`mojo/backend_gimple/emit_methods.py`)
picks an overload only when the arity match is UNIQUE; two same-arity
overloads leave `overload_id == ''`, which is what emits the suffix-less
`extern (...)` and the unresolved call. Per the parent doc, the same shape
produced `_std_memory_pointer_Pointer___{eq,getitem}__`,
`StringSpan___{eq,gt,le,lt}__`, `CStringSpan___eq__` and
`_std_python__cpython_CPython_as_imm` on the production dylib.

## Goal

When a struct dunder (`__getitem__`/`__setitem__` and their comparison twins)
resolves to more than one same-arity candidate, the reference names ONE
concrete overload, chosen from the lowered argument types — never the
suffix-less catch-all. With a unique candidate the choice is bit-identical
to today.

## Acceptance

- The synthetic `Pair` probe: no `pair_Pair___getitem__ (` appears anywhere
  in the emitted C (not the extern, not the call); the `p[0]` call names a
  definition that exists; and it is the Int-parameter overload (`int64_t`
  parameter), not the `char *` one.
- The other bare-dunder names in the parent doc clear the same way IF they
  route through this dispatch (or its comparison twin): verify each call
  site routes through `_lower_struct_subscript_dunder` and fix it there; a
  name that routes through a different path is NOT this part — leave it in
  the parent doc.
- The Array/Deque/List `__getitem__` entries named in the parent doc are
  NOT in scope: they overlap the in-flight
  `CODEGEN_simd_and_array_values_erase_to_int64` lane — re-measure after
  that lane lands before touching them.
- No behavior change when exactly one candidate matches (today's unique-hit
  case is bit-identical), and no silent guess when none matches (today's
  fallback/diagnostic path stays).

## Done when

File: `test_stdlib_dylib_lazy_undefined_refs_probes.py` (repo root).

Command: `python3 test_stdlib_dylib_lazy_undefined_refs_probes.py p3_same_arity`

It runs `test_p3_same_arity_dunder_names_one_overload` (red today: the call
site emits `pair_Pair___getitem__ (p, _t3);` and the extern is
`int64_t pair_Pair___getitem__ (...);`). It must pass.

## Where to start

`mojo/backend_gimple/emit_methods.py::_lower_struct_subscript_dunder` — the
`cands` / `matching` arity filter near the end of the function. The
`arg_pairs` it receives carry ALREADY-LOWERED `(ctype, value)` pairs (e.g.
`int64_t` vs `char *`), so same-arity candidates can be discriminated by
matching each candidate's declared parameter CTYPES against the provided
argument ctypes before falling back. Keep the fallback shape (no match →
today's behavior); do not widen `min_arity <= n <= max_arity` beyond
disambiguating a genuine tie.
