# An imported constructor's literal evidence never reaches a field stored under a DIFFERENT name

Found 2026-10-04 while closing
a phantom-struct-field bug in the same table (fixed and deleted on this
branch). Same
table (`_xmod_ctor_field_hints` in `mojo/backend_gimple/module_gen.py`), same
producer, same consumer — but a different question, and the fix for the phantom
field deliberately does NOT answer this one.

## What I ran

Two files, `gimple_codegen.compile_to_gimple(..., do_imports=True)` + `gcc
-fgimple` + `runtime/fire_runtime.c`, against CPython on the same files.
(`_check_agrees_with_cpython` in `test_gimple_runner.py` is the harness.)

`cparam3_def.py`:

```python
class Box:
    def __init__(self, payload):
        self.body = payload
    def show(self):
        return self.body
```

`cparam3_main.py`:

```python
from cparam3_def import Box
print(Box('hello').show())
```

```
CPython   hello
compiled  4309146640          <- the char * payload's own address
```

Exit 0, no diagnostic. `show()` returns `self.body`, which the imported
`Box.__init__` stored correctly; the FIELD's C type is the problem, and it is
`int64_t`, so reading it back hands the caller the pointer's bits.

## Measured scope

| shape | CPython | compiled |
|---|---|---|
| `__init__(self, name): self.name = name` | `hello` | **`hello`** — correct |
| `__init__(self, payload): self.body = payload` | `hello` | an address |
| the same, aliased (`from m import Box as B`) | `hi` | **`hi`** — see below |

The third row is the awkward one and is worth stating precisely, because it is
what makes this look intermittent. `cparam3_main.py` in the aliasing case also
carries a plain `import cparam3_def`, so `cparam3_def.Box(...)` is a
MODULE-QUALIFIED construction resolved through the defining module's own
compiled struct — a different route that types the field correctly. The
`B('hi')` bare-binding construction in the SAME program is the broken one.
Verified by running the two spellings separately: the bare-binding form alone
prints an address, with or without the sibling `import` line present. So it is
not the alias that decides it; it is which of the two construction paths is
taken.

## Mechanism

`_xmod_ctor_field_hints` records what a FOREIGN call site proves about a
constructor argument, keyed `"<home-qualifier>::<struct>::<param>"`. The
producer (`_xf_record`, called from the `_xg_calls` walk) indexes the
constructor's parameter list by argument position, so the key half is
necessarily the PARAMETER's name — that is the whole point of the table, and it
is what the other consumer needs: `_xf_own_ctor_params` feeds
`_ctor_param_evidence`, which types the `self.<f> = <p>` STORE inside
`__init__` by looking up the parameter's name.

The consumer that writes into the struct layout
(`module_gen.py`'s `_xmod_ctor_field_hints` merge, "before struct methods are
emitted, so both the typedef preamble and the `__init__` body's own store
codegen agree") used the same key straight as the field's name. With the
phantom-field guard now in place that merge only refines a field the struct
DECLARES, so:

- `self.name = name` — the parameter name IS a declared field, the hint lands,
  the field is typed. Correct, and pinned by
  `imported_class_ctor_literal_still_types_the_field`.
- `self.body = payload` — `payload` is not a declared field, so the hint is
  dropped and `body` keeps `int64_t`. That is a real regression avoided
  (before the guard it would have created a `payload` field), but it leaves the
  hint with no path to the field it was about.

## Exact next step

1. **Carry the param→field map with the hint**, so the merge can resolve it.
   The map is derivable where the hint is recorded — `_xf_struct_init_params`
   already opens the defining module's source to read the constructor's
   parameter names, so it can equally read the `self.<f> = <p>` assignments and
   return `(field, param)` pairs instead of bare names. Two sub-decisions, both
   real:
   - the table's key stays `<struct>::<param>` (the other consumer needs it), and
     the merge resolves `param -> field` from a NEW companion table, e.g.
     `_xmod_ctor_field_targets: dict[str, str]` keyed `"<qual>::<struct>::<param>"`;
     or
   - the key becomes `<struct>::<field>` and `_xf_own_ctor_params` is fed from a
     differently-keyed sibling. More churn in the consumer that currently works.
   The first is the smaller change and keeps the one table that is correct.
2. **A computed store stays unresolved.** `self.body = payload.strip()` — the
   call site's literal is provably the argument, not the field's value, so the
   honest answer is the `int64_t` default. That is the same rule
   `_xf_stored_fields` was written against when the phantom-field fix was
   drafted, and it should be part of step 1 rather than discovered after it:
   record a mapping only for a DIRECT `self.<f> = <p>`.
3. **Then pin the third row above**, and keep the alias case with the plain
   `import` sibling in place — it is the only thing that distinguishes the two
   construction paths today, and removing it would quietly stop testing the one
   that is broken.

## Related

- The same table's other defect, fixed on the same branch: the key half was
  written into
  `struct_field_types` unconditionally, so every constructor parameter became a
  struct field. Its "Next step" says "derive the fields from `self.<x> = ...`
  ASSIGNMENTS only", which is right about the source of truth and does not say
  where the param→field correspondence has to be carried — that is this doc.
- `CODEGEN_imported_generic_never_elaborated_calls_nothing_defines.md` and
  `CODEGEN_imported_callable_default_answers_zero.md` — the other two
  cross-module-struct symptoms in this batch; neither is this.