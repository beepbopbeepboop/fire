# Container element types do not survive a function boundary

## Summary

`gen._elem_types` is a **per-function** map, keyed by lowered C value. A
container that is *shared across functions* — a module-level global, or a
class-level attribute — therefore loses its element type between the
function that populates it and the function that reads it. The list is
still correct at runtime (the values are stored fine); what is lost is the
compile-time knowledge of what is *in* it, so every element reads back as
`int64_t`.

The visible consequence is a **method call on an element that degrades to
a stub**, which returns a pointer-sized garbage number with exit 0.

## Repro

```python
REGISTRY = []


class T:
    def __init__(self, n):
        self.n = n
        REGISTRY.append(self)      # element type `T *` recorded HERE, in __init__

    def numel(self):
        return self.n * 2


def main():
    for i in range(4):
        T(i + 1)
    print(len(REGISTRY), REGISTRY[0].numel())
    #                        ^^^^^^^^^^^^^^^^ read HERE, in main
```

CPython prints `4 2`. The compiled binary prints `4 4311387632` — a heap
address. The generated C for the read is:

```c
_t5 = REGISTRY_...[0].numel ();   /* no: */
_t5 = 4311387632;                 /* int64_t.numel() stubbed */
```

`_lower_struct_method_call` sees an `int64_t` receiver, finds no matching
user method, and emits the generic no-op stub, whose result is whatever
was in the temp.

A **class attribute** behaves the same way:

```python
class T:
    registry = []

    def __init__(self, n):
        T.registry.append(self)
```

`T.registry[0].numel()` is likewise `int64_t.numel() stubbed`.

A **local** list does NOT have this bug:

```python
def main():
    reg = []
    for i in range(4):
        reg.append(T(i + 1))
    print(reg[0].numel())          # correct
```

because populate and read happen in the same function, so the
function-local `_elem_types` entry is still live.

## Why the existing machinery does not cover it

There are two function-independent side-tables for exactly this problem,
and neither applies:

- `_field_elem_types` + `_struct_field_owners` — for an **instance
  field** (`self.blocks = []; self.blocks.append(Block())`). Written by
  `_lower_list_method`'s append branch, keyed on the *owner struct and
  field name*, and read back by `_lower_MemberExpr` when the field is read
  in a different function. This is why `self.blocks[i].w` works.
- `_return_elem_types` — for a container **returned** from a function.

A module global and a class attribute have no equivalent. A partial
`_classattr_owners` map was added (read value -> the
`_classattr_<Cls>__<name>` global) but it does not fire, because the read
does not produce a distinct value to key on: the class-attribute read
emits the global's own name as the value, and the `.append()` receiver is
two coercions downstream of it (`_t2 = _classattr_T__registry;` ->
`_t3 = (int64_t)_t2;` -> `_t5`), so there is no single value linking the
append back to the owner.

## Fix sketch

The missing piece is a **provenance chain from a coerced value back to the
value it was coerced from**. `_coerce_to_type` knows its input; recording
`gen._value_sources[out_value] = in_value` there is a one-line addition and
gives the whole compiler a way to answer "which global/field did this
temporary come from?", which several other sites are currently
special-casing:

- `_struct_field_owners` (a hand-rolled instance-field version of it)
- `_classattr_owners` (the class-attribute version, currently dead for the
  reason above)

With that chain, the append branch can walk it to the owning global or
field and record the element type on the *name* rather than the temp, and
`_lower_MemberExpr`'s global/class-attr read already knows to consult
`_elem_types[global_name]`.

## Real impact

`test_llm/test_llm.py`'s `Model.num_params` is
`sum([p.numel() for p in Tensor.registry])` — exactly this shape. The
compiled binary reports `3350913940624` where CPython reports `993792`,
with no error and exit 0. The tensor registry is also iterated by
`AdamW.step` / `zero_grad` / `grad_norm`, so this is not confined to the
one call site: every one of those reads its parameters as untyped scalars.

Worked around in the LLM by not relying on the registry for the count
(see that file); the underlying bug is untouched and still affects any
module that keeps a registry or index in a global.
