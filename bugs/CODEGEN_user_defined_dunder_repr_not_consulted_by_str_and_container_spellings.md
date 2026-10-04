# a user-defined `__str__` is never called, and a struct inside a list/tuple/dict reprs as a raw pointer decimal — on both pipelines, exit 0

**State (2026-09-30): rows 1 and 2 of the table below are FIXED; rows 3,
4 and 5 (`repr([p])`, `repr((p,))`, a dict's value) are still open. See
"Status (2026-09-30)" at the bottom for what landed and what did not.**

**Earlier state: OPEN. The residue of the `repr()` fix landed with
cross-module-import series (see the 2026-09-29 section of
`bugs/hard/README.md`; `_repr_value` in
`mojo/backend_gimple/emit_resolve.py` now calls a struct's own `__repr__`
when the receiver's static type proves it); these two spellings were not
covered by it and are unchanged by it.**

## What I ran

Single-TU (`do_imports=True`) and link mode (`link_mode=True`) through
`gimple_codegen._run_pipeline`, then `gcc -fgimple` + `runtime/fire_runtime.c`,
vs CPython on the same text.

```python
class P:
    def __init__(self, x):
        self.x = x
    def __repr__(self):
        return "R<" + self.x + ">"
    def __str__(self):
        return "S<" + self.x + ">"

p = P("a")
print(repr(p)); print(str(p)); print("%r" % p); print("%s" % p)
print(repr([p])); print(repr((p,))); print({"k": p})
```

## What I saw

```
CPython  : R<a>  S<a>  R<a>  S<a>  [R<a>]  (R<a>,)  {'k': R<a>}
single-TU: R<a>  P     R<a>  P     [4303968912]  (4303968912,)  {'k': P(x='a')}
link-mode: R<a>  P     R<a>  P     [4317682320]  (4317682320,)  {'k': P(x='a')}
```

Exit 0 throughout, no stub message, nothing printed to stderr. The two
`repr(...)` and `%r` spellings are CORRECT — that is the part already
fixed. Three shapes remain:

| row | CPython | compiled | what happens |
|---|---|---|---|
| `str(p)` | `S<a>` | `P` | `__str__` is never consulted at all; the struct's own generated repr runs instead, and prints the bare type name |
| `"%s" % p` | `S<a>` | `P` | same path as `str()` |
| `repr([p])` | `[R<a>]` | `[4303968912]` | the container's element repr calls `_mojo_dispatch_repr` on the element; the dispatch finds no type tag for a stack-allocated struct and returns a raw pointer |
| `repr((p,))` | `(R<a>,)` | `(4303962320,)` | same as the list |
| `{"k": p}` (printed via `print`, so `str`) | `{'k': R<a>}` | `{'k': P(x='a')}` | the dict's value repr uses the generated field dump, not `__repr__` |

The list/tuple rows are the worst of these: a **raw pointer decimal**
where CPython prints the object, and the address differs run to run
(ASLR), so no value comparison can pass and no two runs agree.

## What I expected

CPython's, exactly.

## Where

- **`str(p)` / `"%s" % p`.** The `str()` builtin's lowering
  (`mojo/backend_gimple/emit_calls.py`, beside the `repr` arm that
  `_repr_value` now backs) does not go through `_repr_value` and has no
  `__str__` arm at all. `_repr_value` is documented as the choke point for
  `repr()` and `%r`; `str()` and `%s` are a SECOND, separate route with no
  dunder awareness. The one thing that is right about the current output —
  `P`, not a pointer — is the generated repr running with an empty field
  list, which is a second, smaller bug on its own.
- **`repr([p])` / `repr((p,))` / a dict value.** These DO reach
  `_repr_value`, but with `rat == 'MojoList *'`, which returns through
  `_list_repr_call` / `_mojo_repr_pair` / the dict's own value repr —
  branches ABOVE the struct arm the fix added, and they hand each ELEMENT
  to `_mojo_dispatch_repr` by `void *`. That is the same "the element's
  static type is right there and is being thrown away" shape, one level
  down. The element's type is statically known to the container's own
  element-type table (`_field_elem_types` and friends already exist for
  exactly this), so the information to fix it is present.

## Exact next step

Two separable pieces:

1. `str()` / `%s`: route them through the same dunder check `_repr_value`
   now has, with `__str__` preferred over `__repr__` (CPython's rule) and
   `__repr__` as the fallback — which is also what makes `str(p)` stop
   printing the bare type name. Do NOT special-case `__str__`'s absence by
   refusing: CPython falls back to `__repr__` and then to the default
   object repr, and so must this.
2. Containers: make the element/value repr consult the element's static
   type the way the top-level `_repr_value` now does, instead of erasing it
   to `void *` and dispatching on a runtime type tag that a stack-allocated
   struct does not carry.

While in (2), the raw-pointer-decimal fallback is itself the thing to look
at: printing an address is a refusal in disguise. On a struct the runtime
has no metadata for, the honest answer is the generated field dump, which
exists and is correct.

## Not filed under `bugs/hard/`

Silent, but every row is either an obviously-nonsensical value (the
pointer decimals) or a visible field dump rather than a plausible wrong
one, and none of them is a whole feature being wrong — they are the
spellings around one dispatch decision.

## Status (2026-09-30) — `str()` / `%s` FIXED, container element reprs still open

Re-measured at `86d862fc` before acting, against CPython on the same text
(`gimple` compiles, `gcc -fgimple` + `runtime/fire_runtime.c`, exit 0
throughout, ASLR on so the pointer decimals differ run to run — the
measurement is "raw pointer decimal", not a specific number). The claim
reproduced exactly: `str(p)` and `"%s" % p` printed `P`, `repr([p])` and
`repr((p,))` printed a pointer decimal, `{"k": p}` printed
`{'k': P(x='a')}`.

**Fixed — the `str()` / `%s` half (piece 1 of the doc's "Exact next
step", separable as the doc said it was).** `str(x)` lowers to
`_stringify_value` (`mojo/backend_gimple/emit_infra.py`) and `%s` shares
that path, which is a SECOND route from `repr()`'s `_repr_value` and had
no dunder awareness at all: a struct pointer fell to the generic
`mojo_str`, i.e. the generated field dump with an empty field list, hence
the bare type name. `_stringify_value` now consults the receiver's own
dunder, `__str__` first and `__repr__` second, which is CPython's order
for `str` — so a struct that defines only `__repr__` stringifies as its
repr rather than as its type name, exactly as CPython does. The lookup
itself is `user_dunder_repr_call` (`mojo/middle/calls_shared.py`), which
`_repr_value` now calls too, so the two spellings cannot drift apart; it
returns None when there is no dunder, and each caller then keeps its own
pre-existing lowering, which is what keeps this a strict improvement.
Regression test: `gimple_user_defined_dunder_consulted_by_str_and_percent_s`.

`repr()` itself is deliberately UNCHANGED (`('__repr__',)` only). CPython's
fallback there is `__str__`, and taking it would silently change the repr
of every struct in the tree that defines `__str__` without `__repr__` —
`repr()` feeds dict/list printing, error messages and `--dump` output, so
that is a wide behaviour change to be made on its own evidence, not
smuggled in with a `str()` fix. Recorded here as a deliberate omission,
not an oversight.

**Still open — the container half (piece 2).** `repr([p])` /
`repr((p,))` / a dict value still print a raw pointer decimal. They DO
reach `_repr_value`, with `rat == 'MojoList *'`, which returns through
`_list_repr_call` / `_mojo_repr_pair` / the dict's own value repr —
branches ABOVE the struct arm — and each hands its ELEMENT to
`_mojo_dispatch_repr` by `void *`. The element's static type is not thrown
away by the codegen: `_elem_types[<list temp>]` carries it. What is
missing is a way for a RUNTIME walker to reach it, because
`_mojo_dispatch_repr` finds a struct by its runtime type tag and a
struct-allocated local has none. So the two halves of the doc's suggested
fix are not equally hard, and the cheap one is the wrong one: making
codegen pass the element type per read would mean generating a per-element
repr loop in C (build the string, call the dunder, join with ", "), which
is a new emission path rather than a metadata fix.

Two routes, neither taken here, in the order I would try them:

1. **A runtime repr-function table.** The compiler already emits
   `_mojo_repr_<Struct>` per struct and already calls
   `_mojo_classattr_init()` at every entry point; registering each
   struct's own dunder (or its generated field dump) against its
   `__mojo_type_id` there would let `_mojo_dispatch_repr` find it for a
   struct-allocated local too, and would fix the raw-pointer-decimal
   fallback the doc calls "a refusal in disguise" in the same move. It
   also needs the struct-allocated local to CARRY a tag, which is the
   other half of why the dispatch currently misses.
2. **A codegen-built element repr loop** for the list/tuple/dict cases
   only, keyed on `_elem_types` naming a registered struct. Local to this
   codegen, no runtime change, but it is a second repr implementation and
   it only covers the three containers.

Route 1 is the one that makes the doc's last paragraph true rather than
just less wrong ("on a struct the runtime has no metadata for, the honest
answer is the generated field dump, which exists and is correct"). It is
a runtime-table change plus a tag on stack-allocated structs, i.e. a real
project rather than a patch, and per the gate rules it would owe
`mojoc`/bootstrap like everything else in `runtime/`.

## Status (2026-10-01) — the LIST and TUPLE element reprs are FIXED; two narrower residuals are filed separately

Re-measured the doc's table on this tree before acting, through
`gimple_codegen.compile_to_gimple` + `gcc -fgimple` +
`runtime/fire_runtime.c`. Rows 1 and 2 (`repr(p)`, `str(p)`, `%r`, `%s`) were
already fixed by the earlier commit this doc records. Rows 3 and 4 — `repr([p])`
and `repr((p,))` printing a raw pointer decimal — reproduced exactly, and are
now correct wherever the element's static type is visible where the container is
BUILT:

```
CPython  : [R<a>]  (R<a>,)  [R<a>, R<a>]  [[R<a>]]  [R<a>]  [R<a>]  [R<a>, R<a>]
compiled : [R<a>]  (R<a>,)  [R<a>, R<a>]  [[R<a>]]  [R<a>]  [R<a>]  [R<a>, R<a>]
```

for a parameter, a local, a nested list, a slice, a `list()` copy and a `+`
concatenation. Regression test
`gimple_container_element_repr_uses_the_struct_dunder` in
`test_gimple_runner.py`, whose expected text is CPython's own (run there too).

**The mechanism is neither of this doc's two routes, and it is smaller than
either.** Neither the global table (route 1) nor a codegen-built element repr
loop (route 2) is needed, because the information the walker lacks is not a type
tag — it is a FUNCTION, and the codegen can hand it over at the one moment it
still knows the element's type:

* `runtime/fire_runtime.c`'s per-list side table (the one that already carries
  the per-slot `kinds` string) gains a `char *(*repr_fn)(int64_t)` field, with
  `mojo_list_set_elem_repr` / `mojo_list_repr_elem`. Same bargain as `kinds`,
  for the same reason: the type is known where the list is built and
  unrecoverable later, because a struct-allocated value has no runtime type tag
  for `_mojo_dispatch_repr` to find — and a global address->type registry, the
  alternative, goes stale the moment a frame is reused.
* `mojo/backend_gimple/module_gen.py`'s reflection preamble emits one shim per
  reflected struct, `_mojo_elem_repr_<Struct>(int64_t)`, beside that struct's
  `_mojo_repr_<Struct>` and forward-declared with it. A shim rather than a cast
  of the real symbol into `char *(*)(int64_t)`, because calling
  `char *(Foo *)(void)` through that pointer type is undefined behaviour. The
  shim prefers the user's `__repr__` and falls back to the field dump, which is
  CPython's order for a container element (a list reprs its elements with
  `repr`) and is why the element is right rather than merely non-crashing.
* `mojo/backend_gimple/emit_exprs.py` records it: `_lower_list_literal` for the
  literal's joined element type, `_lower_tuple_literal` per slot with the same
  unanimity rule the constructor evidence uses (a tuple that mixes two struct
  types records nothing).
* The runtime carries it across derivations where the kinds string already
  travelled: `mojo_list_inherit_kinds` (so `list(t)` and `t[:]`),
  `mojo_list_concat` (one side recorded, or both recorded and equal), and
  `mojo_list_extend`.

**Two residuals are filed as their own docs** rather than left here, because each
needs a type recorded somewhere this codegen does not record it, which is a
different problem from the container repr:

* `bugs/CODEGEN_module_scope_struct_binding_has_no_type.md` — a container whose
  element is an unannotated MODULE-LEVEL binding read at module level. That
  binding is boxed into an `int64_t` global, `_quick_type` says `int64_t`, the
  slot appends through `mojo_list_append_int`, and there is no type at any point
  for any of this to consult. The doc's own original reproducer is in this
  shape, which is why its `repr([p])` row is fixed only for the shapes listed
  above.
* `bugs/CODEGEN_struct_typed_field_reprs_as_an_integer.md` — a struct-typed
  FIELD inside another struct's generated field dump (`Holder(p=P(...))` prints
  `Holder(p=4381809120, ...)`). `struct_field_types` says `int64_t` for that
  field and `struct_boxed_fields` does not list it, so the dump's
  `_mojo_generic_elem_repr` arm never fires for it either.

**A dict's value repr is unchanged** and is left that way deliberately: a dict's
slots carry a `kind` already (`_DictSlot.kind`), so recording a repr function
per dict is the same one-line extension of the same side table, but nothing in
the codegen currently knows a dict's value type at the store site for the
general case, and the row (`{"k": p}` printing `{'k': P(x='a')}` instead of
`{'k': R<a>}`) needs that first. It is the third row of this doc's table and it
is still open.

**→ FIXED 2026-10-02; see "Status (2026-10-02)" at the bottom.** The store site
does know the value's type (`_dict_val_types[obj_v] = vtype` is written by the
very statement that stores it), so the "needs that first" is what the fix is.

**A dunder-less element is still a divergence, deliberately not frozen in the
test:** CPython prints `<__main__.X object at 0x...>`, this codegen prints the
generated field dump. The shim's fallback is the field dump because this doc's
last paragraph calls it "the honest answer"; that preference is not CPython's,
and asserting either answer in a test would hide the disagreement rather than
record it.

## Status (2026-10-02) — the DICT VALUE row is FIXED; two shapes around it are not

Re-measured the table's last row on this tree before acting, through
`test_gimple_runner.py`'s own `compile_mojo_to_gimple_exe` against CPython on
the same text. Rows 1-4 were already fixed by the two Status sections above;
row 5 reproduced exactly, in both spellings:

```
CPython  : {'k': R<a>}  {'k': R<a>}
compiled : {'k': P(x='a')}  {'k': P(x='a')}
```

and two more shapes of the same family, measured alongside it:

```
CPython  : [R<a>]   dict_items([('k', R<a>)])   dict_values([R<a>])
compiled : [R<a>]   [('k', R<a>)]               [R<a>]
```

**Fixed — the value's repr, everywhere the value appears.** The mechanism is
the list fix's, unchanged in shape, because the information missing was the same
information: a struct-allocated value carries no runtime type tag, so by the
time anything walks the dict there is nothing left to dispatch on.

* `MojoDict` gains `char *(*val_repr)(int64_t)` — LAST in the struct, so every
  existing field keeps its offset, and NULL for every dict that holds no
  struct. `mojo_dict_set_val_repr` records it, `mojo_dict_repr_val` asks it.
  `mojo_dict_init` is the one initialiser both construction paths
  (`mojo_dict_new` and the stack-allocated `MojoDict` of an owned-container
  phase-3 candidate) already go through.
* `mojo_dict_set_struct` stores the value tagged `_DictSlot.kind == 5`, which
  is what makes the answer independent of store order: the tag is per SLOT and
  the function is per DICT, so a second struct type in the same dict is tagged
  `kind == 6` ("a struct this dict's repr does not describe") and falls to the
  generic dispatch instead of being handed the first type's repr — which would
  read a `Q *` through `P`'s repr, a wild read rather than a wrong string.
* `emit_dict_int_value_store` — the ONE dict store, after the 2026-10-02
  consolidation above — is where the shim is looked up
  (`gimple_exprtypes.struct_elem_repr_shim`, moved out of
  `emit_exprs.py` into the middle tier for this: a list and a dict asking the
  same question of the same ctype is exactly how the two copies would have
  drifted) and where `mojo_dict_set_val_repr` is emitted, once per dict.
* The recorded function travels with the values, on the same terms as
  `mojo_list_inherit_kinds`: `mojo_dict_update` (and so `mojo_dict_copy` and
  `|`) carries it, `mojo_dict_values` puts it on the list it builds, and
  `mojo_dict_items` puts it on each PAIR — which is why `_mojo_repr_pair` asks
  its list's recorded element repr for slot 1 and ONLY slot 1. Asking it for
  slot 0 handed the KEY, a `char *`, to the struct's `__repr__` and printed
  `R<>` for the key `'k'`; that was measured, not reasoned about.

**Still open, and deliberately not frozen in the tests:**

1. **`{'p': p, 'q': q}` — the second struct type** prints `'p': R<a>` (the
   recorded function) and `'q': Q(y='b')` (the field dump, via `kind == 6`).
   CPython prints both dunders. One function per dict cannot describe two
   types, and the alternatives are a per-slot function pointer (8 bytes on
   every `_DictSlot`, on the hottest data structure in the runtime) or a
   per-dict TABLE of shims; both are real designs with real costs, and neither
   is this doc's row.
2. **`print(d.values())` / `print(d.items())` print the bare list**, without
   CPython's `dict_values(...)` / `dict_items(...)` view wrapper. The VALUES
   inside are right, which is what this fix is about; the view type is a
   separate display gap.

Regression tests: `gimple_dict_value_repr_uses_the_struct_dunder` (against
CPython — the dict literal, `repr`, `list(d.values())`, `dict(d)`, `|`, and an
int stored beside the struct in BOTH orders) and
`gimple_dict_value_repr_remaining_two_shapes`, which pins the two rows above as
they are, with the reason in the comment, so that changing either is somebody's
decision.
