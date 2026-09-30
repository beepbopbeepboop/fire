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
