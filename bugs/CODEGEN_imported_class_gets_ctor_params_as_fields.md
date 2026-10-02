# An IMPORTED class's `__init__` parameter names become struct FIELDS, so `getattr` answers for an attribute the class does not have

Found 2026-10-02 while verifying
`bugs/CODEGEN_user_class_named_Parser_merged_with_fire_compiler_Parser.md`
(doc deleted with that verification, same commit). NOT the same bug: that one
was a user's `Parser` merged with `fire_compiler.Parser`'s layout, and it no
longer reproduces. This is what is left in the same registration path, and it
has nothing to do with the name `Parser`.

## What I ran

`gimple_codegen.compile_to_gimple(..., do_imports=True)` on two sibling files
+ `gcc -fgimple` + `runtime/fire_runtime.c`, against CPython on the same files.

`pcol_def.py`:

```python
class Parser:
    def __init__(self, tokens):
        self.toks = tokens
```

`pcol_main.py`:

```python
from pcol_def import Parser
p = Parser([9])
try:
    print(getattr(p, 'tokens'))
except AttributeError:
    print('AttributeError')
```

## What I see

| | output |
|---|---|
| CPython | `AttributeError` |
| compiled | `[]` |

exit 0, no diagnostic. `tokens` is a **constructor parameter**, not a field —
the class assigns `self.toks` and never `self.tokens`. The compiled struct
carries both:

```c
typedef struct Parser {
  int64_t __mojo_type_id;
  MojoList * toks;
  MojoList * tokens;      /* the __init__ PARAMETER, never assigned */
} Parser;
```

and the generated reflection answers for it:

```c
static int64_t _mojo_getattr_Parser (Parser *obj, char *attr) {
  if (strcmp(attr, "toks") == 0) return (int64_t)(intptr_t)obj->toks;
  if (strcmp(attr, "tokens") == 0) return (int64_t)(intptr_t)obj->tokens;
  return mojo_obj_getattr((void *)obj, attr);
}
```

So the read returns the never-written slot, which prints as the empty
container it was initialised to — a plausible-looking wrong value rather than
an error. `setattr` mirrors it (`_mojo_setattr_Parser` writes the slot), and
the generated field dump lists the field, so `print(p)` on a class with no
dunder names an attribute that does not exist.

## Scope, measured

* **Cross-module only.** The same class in a single file emits
  `typedef struct Thing { int64_t __mojo_type_id; MojoList * beta; }` with no
  stray parameter field, so the leak is in the IMPORTED class's registration,
  not in the general `__init__`-parameter-as-field path.
* **Every parameter, not just the stored one.** With
  `def __init__(self, tokens, more)`, both names are candidates; with
  `def __init__(self, tokens, more): self.toks = tokens; self.other = more`,
  the measured struct gained a field per parameter.
* **Layout-safe but not behaviour-safe.** The extra field is appended AFTER
  every real one, so no existing offset moves — which is exactly why this
  survives: nothing crashes, and the only symptom is an attribute that should
  not exist.

## Why it is in the same code the deleted doc pointed at

That doc's "Next step, in order" item 1 was: *"`struct_field_types` must not
merge two same-named classes — the class-registration path needs the same
module-scoped discipline the module-globals fix applied to
`_global_var_types`."* The merge is gone; the registration path still has a
struct-shape bug, this one. Nothing here is claimed by another worker.

## Exact next step

Find the IMPORTED-struct registration that builds the field map from the
class's `__init__` signature (`struct_field_types[name]` for a struct that
came in through `_compile_imported_module`), and derive the fields from
`self.<x> = ...` ASSIGNMENTS only — which is what the single-file path
already does, and what `_field_dict_val_types` /
`_ctor_lit_param_types` already assume, since both are keyed by real field
names reached through an assignment.

A regression test must assert the AttributeError, not the struct text alone:
`getattr(p, <a parameter name>)` raising is the only one of the three
symptoms a user can observe, and it is the one that distinguishes "the field
is absent" from "the field exists and happens to be empty".

Already covered by
`user_struct_named_parser_emits_its_own_layout_and_qualifier` in
`test_gimple_runner.py` — DELIBERATELY scoped to the five selfhost field
names, with this defect named in its comment, rather than asserting "only the
user's fields", which would be red for this bug rather than for the one it
pins.