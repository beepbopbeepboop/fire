# A struct-typed FIELD inside another struct's generated field dump reprs as an integer

Found 2026-10-01 while fixing the container element repr in
`bugs/CODEGEN_user_defined_dunder_repr_not_consulted_by_str_and_container_spellings.md`.
Found as a side effect of writing that fix's test: the element case is fixed, and
a struct element whose own repr contains a struct FIELD still prints an address.

## What I ran

`gimple_codegen.compile_to_gimple` + `gcc -fgimple` +
`runtime/fire_runtime.c`, against CPython on the same text.

```python
class P:
    def __init__(self, x):
        self.x = x
    def __repr__(self):
        return "R<" + self.x + ">"

class Holder:
    def __init__(self, p):
        self.p = p

def main():
    var h = Holder(P("a"))
    print(repr([h]))
```

```
CPython  : [Holder(p=R<a>)]
compiled : [Holder(p=4381809120)]
```

`h` on its own reprs correctly (`repr(h)` → `Holder(p=4347419344)` is wrong too
for the same reason), and `h.p` prints `R<a>` — so the value is stored properly
and only the DUMP formats the slot wrongly. Exit 0, ASLR-varying answer.

## The generated C is the whole story

```c
static char * _mojo_repr_Holder (Holder *obj) {
  if (!obj) return "None";
  return mojo_str_cat(... "p=", mojo_repr_int((int64_t)obj->p) ...);
}
```

`mojo_repr_int` on a `char *`-valued slot, i.e. the address.

## Mechanism

`module_gen.py`'s reflection preamble picks a `val_expr` per field, and it has
exactly the right arm for this —

```python
            elif fname in boxed and ftype in ('int', 'int64_t', ...):
                val_expr = f'_mojo_generic_elem_repr((int64_t){fref})'
```

— which dispatches on the slot's runtime type TAG and would render the field
through `_mojo_dispatch_repr`. Neither half of its condition holds for a
class-typed field:

* `ftype` is `int64_t`, not a pointer: `struct_field_types['Holder']['p']` is
  `int64_t` for a field whose declared type is a class instance, because a
  struct-allocated field is stored in a machine word.
* `fname in boxed` is False: `struct_boxed_fields` is populated from fields
  OBSERVED being boxed at runtime (a `mojo_box_*` allocation), not from fields
  whose declared type is a struct. This one is not boxed — it is a plain pointer
  in an `int64_t` field.

So the arm that was written for "an `int64_t` slot that is really a value" is
skipped, and the integer arm runs instead. The sibling fix in this commit added
a third arm (a field whose declared type is a reflected struct renders through
that struct's `_mojo_elem_repr_<Struct>` shim) and it does not fire either, for
the same reason: the declared type is not in the table this emitter reads.

## The next step

1. **Record the field's semantic type where the emitter looks.** The emitter
   iterates `self.struct_field_types[sn]`, so the fix is a table that says
   "field `p` of `Holder` holds a `P`" — `struct_field_semantic_types`, or an
   entry in the existing boxed/nullable-container side tables generalised. It
   can be filled from the same place that types the field for a READ
   (`self.p = p` in `__init__`, where `pm`/`_gmi_collect_self_assigns` already
   knows), so this is inference the compiler already does and throws away.
2. **Then both arms become reachable**: the existing `_mojo_generic_elem_repr`
   arm for a boxed field, and the new `_mojo_elem_repr_<Struct>` arm for a
   plain one. Both are already written; neither can fire without (1).
3. Also covers a struct field inside a LIST's element repr
   (`[[Holder(p=...)]]`), which is the same slot read by the same emitter.

No regression test: the test that found this
(`gimple_container_element_repr_uses_the_struct_dunder`) asserts only the
shapes that are now correct, so this shape stays unasserted rather than frozen
at the wrong answer.
