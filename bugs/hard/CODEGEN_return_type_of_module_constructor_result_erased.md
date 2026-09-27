# HARD BUG: a function returning a module-level constructor's result is declared `int64_t`, so every consumer of that value is type-erased

**State: OPEN.** Found 2026-09-26 while fixing
`CODEGEN_struct_format_shadowed_by_format_attribute.md` (since deleted — that
bug is fixed) and confirming there was no residue of it. This is **not** that
bug's residue: it is a distinct mechanism, in a distinct pass
(`mojo/middle/infra_infer.py`'s return-type inference), and it breaks the
attribute **read** as well as the call — the deleted doc always held that the
read was correct, and for this shape it is not.

It is the **return-value twin** of
`CODEGEN_method_call_on_struct_param_mistyped.md` (which is the *parameter*
case, in `_infer_param_types`): both are "a value whose real type this codegen
knows at its construction site loses that type at a function boundary".

## Symptom

`/tmp/b1r/r.py`:

```python
import struct

def make():
    return struct.Struct("<HH")

def main():
    var s = make()
    print("size read:", s.size)

main()
```

| | CPython | reference interpreter | compiled |
|---|---|---|---|
| output | `size read: 4` | `size read: 4` | `Unhandled exception: AttributeError: size`, exit 1 |

Loud, not silent — the `struct.Struct` attribute read that
`mojo/backend_gimple/emit_exprs.py` routes to `mojo_struct_size` never gets
there, because by the time the call site sees the value it is an untyped
`int64_t` and the read degrades to `_mojo_dispatch_getattr`, which has no
registration for it and raises.

The generated C makes the erasure explicit (`/tmp/b1r/gen.c`, whole-program
`do_imports=True`):

```c
int64_t make (void)          /* <-- declared int64_t, not MojoStructFmt * */
{
  int64_t _t1;  char * _t2;  MojoStructFmt * _t3;  int64_t _t4;
  void * _t5;  int64_t _t6;
  _t1 = _root_globals._struct;
  _t2 = _slit_10000;
  _t3 = mojo_struct_new (_t2);   /* the body knows the real type exactly */
  _t5 = (void *)_t3;
  _t6 = (int64_t)_t5;            /* ...and boxes it anyway */
  _t4 = _t6;
  return _t4;
}
```

The box is not a lowering accident: the *declared* return type of `make` is
already `int64_t`, so the function body is obliged to convert. Fixing this means
fixing the declaration, not the conversion.

## Root cause

`mojo/middle/infra_infer.py`, `_infer_return_type` (`:1293`) →
`_collect_return_types` (`:1269`):

```python
acc.append('void' if node.value is None else gen._quick_type(node.value))
```

`_quick_type` is the cheap static guess used for pre-pass bookkeeping, and for
a `CallExpr` whose callee is a module-level runtime constructor it answers
`int64_t`. The *authoritative* lowering for that same call —
`_lower_struct_module_call` in `mojo/backend_gimple/emit_methods.py:682` — does
know the answer, returning `'MojoStructFmt *'` for `struct.Struct(...)` (and
`'MojoBytes *'` / `'MojoList *'` / `'void'` / `'int64_t'` for the rest of that
module's surface). The two disagree, and the pre-pass wins, because it is what
writes the C prototype.

## Scope, measured — narrower than it looks

Not "every returned value loses its type". Both of these are **correct** today
(verified by building and running against CPython):

- a function returning a locally-constructed user struct (`return Box("hi")`)
  → `b.v` prints `hi` ✓
- a function returning a list literal (`return [1, 2, 3]`) → `len(x)` = 3,
  `x[1]` = 2 ✓

So the inference handles user-struct constructions and container constructors.
What it does not handle is a value whose type is contributed by a
**module-level runtime-constructor call** — `struct.Struct(...)` and its
siblings. That is a narrow, enumerable list, and `struct.Struct` is the only
one of them whose result this codebase models as a **named, non-container
handle** type with attribute reads of its own (`format`, `size`, and the five
pack/unpack methods), which is why the erasure is *visible* here and not for,
say, a returned `MojoBytes *`.

## What a fix needs

`_quick_type`'s `CallExpr` arm needs to consult the same module-constructor
return-type table `_lower_struct_module_call` uses, rather than answering
`int64_t` for any callee it does not recognise. The two must not be allowed to
disagree, or every fix here re-opens as a mis-boxed value somewhere else.

**Risk: moderate-to-high, and this doc's own reason for not attempting it.**
A function's declared return type is about as load-bearing a thing as this
codegen has: it drives the C prototype, the forward declaration, every call
site's argument conversion, and the callee's own return-value lowering. Widening
it changes generated C for every module containing such a function — so unlike
the deleted `struct.format` bug, "byte-identical generated C on a large
succeeding case" is **not** available as the bar here. It needs the full gate
plus a deliberate read of the C diff on the 664-file corpus, and a decision on
whether a widened return type is accepted everywhere it newly applies or has to
be gated per-type the way the deleted bug's fix was scoped.

Sequencing note: this is the *smaller* half of the value-identity problem. The
larger half is
`CODEGEN_same_bare_name_struct_collision_across_modules.md` — the same bare-name
model, on the other side of the function boundary.
