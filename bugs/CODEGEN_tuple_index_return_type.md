# CODEGEN_tuple_index_return_type

## Summary
A function whose `return` is a subscript of a tuple local is declared to
return `int64_t`, whatever the tuple's slot actually holds. A string slot then
comes back as its pointer printed in decimal, at exit 0:

```
def f():
    args = ("a", "b")
    return args[0]

def main():
    print(f())
main()
```

compiled prints e.g. `4341650696`; CPython prints `a`. `print(args[0])` in the
same function prints `a`, so the lowering of the subscript is right — the
function's own C RETURN TYPE is what is wrong.

## Measurements (2026-11-09, this tree)
Compiled with `test_gimple_runner.compile_mojo_to_gimple_exe`:

| source shape | result |
|---|---|
| `args = ("a", "b"); return args[0]` | pointer decimal (WRONG) |
| `args = ("a", "b"); return args[1]` | pointer decimal (WRONG) |
| `args = (1, "a"); return args[1]` | pointer decimal (WRONG) |
| `args = ("a", "b"); print(args[0])` | `a` (right) |
| `args = ("a", "b"); return len(args[0])` | `1` (right; `len` is int) |
| `args = ["a", "b"]; return args[0]` | `a` (right — list literal) |
| `args = (1, 2); return args[0]` | `1` (right by accident: int slot) |
| `def f(args): return args[0]` called with `("a","b")` | pointer decimal (WRONG) |

Not specific to classes or to the class-capture work: the first row has no
class at all. It also reaches a class attribute read
(`class C: args = ("a","b")` / `return self.args[0]`).

## Root cause / next step
`resolve_shared._quick_type`'s `SubscriptExpr` arm (around
`if isinstance(obj, gimple_ctypes.IdentExpr): ... e = gen._elem_types.get(obj.name)`)
has no case for a TUPLE. A tuple literal's per-slot types are recorded at
LOWERING time in `gen._tuple_slot_types[<temp>]` (emit_exprs `_lower_tuple_literal`),
which the return-type pre-pass cannot see (it runs before the body is lowered),
and the cross-call pre-pass in `infra_infer` replays `ListExpr`/`SetExpr`
literals but not `TupleExpr`.

Two consistent fixes, in order of preference:

1. Teach the pre-pass (`infra_infer`'s element/nested pre-pass, the
   `note_list_literal` walk) about `TupleExpr` bindings: record the joined slot
   type (or, for a homogeneous tuple, `_infer_list_elem_type(val.elements)`) so
   `_quick_type`'s existing `_elem_types` lookup answers `char *`.
2. Add a `TupleExpr` arm to `_quick_type`'s `SubscriptExpr` case that joins the
   literal's slot types and returns the indexed one (needed anyway for
   `return ("a", "b")[0]` with no local).

Add the regression beside `gimple_nested_class_method_returns_rebound_str_capture`
in `test_gimple_runner.py`, using the first source shape above.
