# An unannotated MODULE-LEVEL struct binding is boxed into an `int64_t`, so nothing downstream knows its type

**State: FIXED 2026-10-02 (`work/bugs4-3-c`, commit with `_quick_type`'s own
overlay arm).** Both of this doc's next steps turned out to be one change: step
(1) was the whole fix and step (2) was not needed once it landed, because the
element type is recovered at the LIST LITERAL rather than at the field. The
original reproducer agrees with CPython now, and the measurement that decided
the fix's SCOPE is recorded below because it is the part that is easy to get
wrong.

**State before that: OPEN, found 2026-10-01 while fixing the container element
repr in `bugs/CODEGEN_user_defined_dunder_repr_not_consulted_by_str_and_container_spellings.md`
(still open; its list/tuple rows are fixed and this was the residue that kept
its original reproducer red). It is not a repr bug: the type is gone before any
repr runs.**

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
before:  CPython  : [R<a>]
                 R<a>
         compiled : [4345469360]        <- the heap address, exit 0
                 R<a>

after:   both     : [R<a>]
                 R<a>
```

The same class, the same literal, and the same `repr` are all correct inside a
function — a parameter, a local, a field, a slice, a copy, a concatenation. The
module-level spelling is the one that failed, and the test that pins the fix
asserts both the module-level row and that inside-a-function control.

## Where the type was lost

Three measurements, in order:

1. `_infer_list_elem_type([p])` returns `int64_t`, so the literal records no
   element type and (before the fix) recorded no element repr.
2. The element lowers to `int64_t` too: the generated C is
   `mojo_list_append_int(_t1, (int64_t)p)`. So even a per-slot lookup finds
   nothing — this is not only the joined `elem` being conservative.
3. `_quick_type(IdentExpr('p'))` reads `gen.var_types` and, for a name that is
   not a local, returns the `int64_t` default. It never consulted
   `gen._global_var_types`, which is where a module-level binding's type lives.

(3) was the root cause and also why the failure is invisible elsewhere: a global
holding a container is stored as an `int64_t` too, and reads back through
`mojo_is_registered_list`, so nothing about that shape is broken. Only a global
holding a STRUCT needs the type and cannot recover it — which is exactly what
`repr([p])` shows and what `module_level_list_global` in the same test does NOT
show.

## What landed

`resolve_shared._quick_type`'s `IdentExpr` arm gained one: a name that is not a
local and not a closure answers with `_own_global_var_types[name]` when it is
there. The element type is then recovered at the list literal, which is where
`_struct_elem_repr_shim` looks for it — so step (2) below was never needed, and
the doc's own step-3 ordering advice (do the global case before the field-dump
one) held.

## The measurement that decided the SCOPE — `_own_`, not the shared table

The obvious spelling of the arm answers from the shared
`gen._global_var_types`, and it is **wrong**, measured: the self-host closure's
`.ci` goes from 13 distinct gcc errors to **15**, adding

    mojo/middle/resolve_shared.py: assignment to 'char *' from 'int64_t' makes
        pointer from integer without a cast
    gimple_codegen.py: invalid conversion in gimple call

`_global_var_types` is a whole-transitive-tree superset — it has to be, for
cross-module `mod.attr` — so answering from it makes `_quick_type` describe a
SIBLING's global, and the answer is a *semantic* pointer type while the value on
the C level is a boxed `int64_t`. The own overlay is the same "is this bare
name MINE" answer `_lower_IdentExpr` asks before it picks a field to load, so
the two now agree by construction. (This is also why
`_lower_IdentExpr`'s bare-read gate consults `_own_global_var_types` at all; see
its own comment for the `filename` mis-resolution that gate exists to refuse.)

## Reproduce

`test_gimple.py`'s `module_level_struct_global_keeps_its_type_in_a_container`
(on both the single-TU and link-mode pipelines, against CPython's stdout).
test_gimple.py is 372/0 with it.

## What is NOT this bug

The sibling `bugs/CODEGEN_struct_typed_field_reprs_as_an_integer.md` (a struct
held in a FIELD, whose `struct_boxed_fields` table is populated from observed
boxing rather than from the declared field type) is a different table and is
untouched here — the global case no longer reaches it.

**Why this file is still here rather than deleted with its fix.** It is cited,
by name, as one of "two residuals" from
`bugs/CODEGEN_user_defined_dunder_repr_not_consulted_by_str_and_container_spellings.md`,
which is another worker's doc. Deleting this one would leave that citation
dangling in a file this branch may not edit — and the two residuals do still
share a root ("a struct's declared type is not recorded where the reader looks
for it"), so the pointer still carries information. The module-level half is
closed; the field half is that sibling's, and this doc's own step 3 is what
ordered the two.

## Suite-bucket note

`gimple` (`test_gimple.py`), and the compile is exercised by `selfhost`.