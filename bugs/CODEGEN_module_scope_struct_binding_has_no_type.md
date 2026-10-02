# An unannotated MODULE-LEVEL struct binding is boxed into an `int64_t`, so nothing downstream knows its type

Found 2026-10-01 while fixing the container element repr in
`bugs/CODEGEN_user_defined_dunder_repr_not_consulted_by_str_and_container_spellings.md`
(still open; its list/tuple rows are fixed and this is the residue that keeps
its original reproducer red). It is not a repr bug: the type is gone before any
repr runs.

## What I ran

`gimple_codegen.compile_to_gimple` + `gcc -fgimple` +
`runtime/fire_runtime.c`, against CPython on the same text.

```python
class P:
    def __init__(self, x):
        self.x = x
    def __repr__(self):
        return "R<" + self.x + ">"

p = P("a")            # module level, NOT annotated, read at module level
print(repr([p]))
print(repr(p))
```

```
CPython  : [R<a>]
           R<a>
compiled : [4347419344]
           R<a>
```

The same class, the same literal, and the same `repr` are all correct inside a
function — a parameter, a local, a field, a slice, a copy, a concatenation. The
module-level spelling is the one that fails.

## Where the type is lost

Three measurements, in order:

1. `_infer_list_elem_type([p])` returns `int64_t`, so the literal records no
   element type and (before the fix) recorded no element repr.
2. The element lowers to `int64_t` too: the generated C is
   `mojo_list_append_int(_t1, (int64_t)p)`. So even a per-slot lookup finds
   nothing — this is not only the joined `elem` being conservative.
3. `_quick_type(IdentExpr('p'))` reads `gen.var_types` and, for a name that is
   not a local, returns the `int64_t` default. It never consults
   `gen._global_var_types`, which is where a module-level binding's type lives.

(3) is the root cause and also why the failure is invisible elsewhere: a global
holding a container is stored as an `int64_t` too, and reads back through
`mojo_is_registered_list`, so nothing about that shape is broken. Only a global
holding a STRUCT needs the type and cannot recover it.

## The next step

1. **Teach `_quick_type` about globals.** One arm: an `IdentExpr` that is in
   `gen._global_var_types` answers with that. It is the same lookup
   `var_types` already does one line above, and the reason it is not already
   there is worth checking before adding it — `_quick_type` is called from every
   inference site in the compiler, so an arm that answers for a global where
   the answer used to be `int64_t` will move behaviour everywhere, not only for
   containers. Measure `mojoc --dump-full fire.py` before and after (byte
   comparison) rather than assuming.
2. **Then re-check the doc's original reproducer**, which is the shape that
   failed. If (1) is not enough, the second half is that a module-level struct
   global is boxed (`module_gen.py`'s class-attr emission stores
   `(int64_t)(intptr_t)obj->field`), so the slot is a BOX rather than a bare
   pointer; `struct_boxed_fields` is the table that says so and it is populated
   from observed boxing, not from the declared field type, which is the same gap
   the sibling doc
   `bugs/CODEGEN_struct_typed_field_reprs_as_an_integer.md` records for a
   field.
3. **Do this before that one.** They share the root (a struct's declared type is
   not recorded where the reader looks for it) and fixing the global case first
   is the smaller blast radius, because `_quick_type` is hot and the field-dump
   emitter is not.

No regression test: the container-repr test that motivated this deliberately
does not assert this shape, because the expected answer would be the compiler's
current one rather than CPython's.
