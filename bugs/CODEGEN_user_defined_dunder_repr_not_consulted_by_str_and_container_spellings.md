# a user-defined `__str__` is never called, and a struct inside a list/tuple/dict reprs as a raw pointer decimal — on both pipelines, exit 0

**State: OPEN. The residue of the `repr()` fix landed with
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
