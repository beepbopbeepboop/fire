# A dict's value type is not carried to an unannotated callee parameter

## What was run

```sh
python3 fire.py build /Users/mrs/net/Python-3.14.6/Tools/build/umarshal.py
# then, on a distilled repro:
def f(d):
    a, b = next(iter(d.items()))
    print(b)
f({"x": "1"})
```

## What was seen

Compiled output prints a decimal pointer where CPython prints `1`:

```
4339160016
```

The same program with a dict LITERAL assigned to a local first is correct:

```
d = {"x": "1"}
a, b = next(iter(d.items()))
print(b)     # -> 1
```

And so is the loop form in the same function as the failing one:

```python
def f(d):
    for k, v in d.items():
        print(v)      # -> 1   (local `d`, not a parameter)
f({"x": "1"})          # -> 4339160016  (parameter `d`)
```

## What was expected

`print("1")`. The dict is a literal at the call site, so its value type is a
compile-time fact; the callee's `d` is the same dict.

## Root cause

`_dict_val_types` is keyed by the source-level NAME of a dict value, and it is
seeded where a dict is bound (`_dict_val_of` -> the `.items()` lowering
records `gen._dict_items_val_elems[t] = gen._dict_val_of(ov)`). For a
parameter there is no binding site, so `_dict_val_of('d')` returns the
`int64_t` default — even though the caller passed a literal whose value type
was known.

Confirmed by instrumenting the lookup directly:

```
DICT_VAL_OF d -> int64_t   table has: False
```

versus the local-variable spelling, where the table does have the entry.

So `d.items()`'s value type is `int64_t`, the pair's slot 1 is read with
`mojo_list_get_int`, and the `char *` value comes back as a decimal address.
This is the SAME `int64_t`-means-two-things confusion as
`bugs/CODEGEN_selfhost_actual_types_identifier_field_key.md`, one layer up:
the slot is right, the value in it is not.

## Why it is not fixed here

The fix is the cross-call propagation Pass 1.3d already does for
return/parameter TYPES (`_arg_scalar_type`, `prefer_refined_param`), extended
to dict VALUE types: at a call site, for each argument that is a dict literal
(or a name with a `_dict_val_types` entry), seed the callee's parameter name.
That is a change to how parameters are typed across the whole program, so it
owes the full `make gate` per CLAUDE.md, and it was found while fixing
something else.

It is bounded and specific enough to be worth doing: the propagation point
is `_arg_scalar_type`'s caller in `module_gen.py`, and the consumer to extend
is wherever `gen._param_dict_val_types` would need to exist (the field-level
analogue is `gen._field_dict_val_types`, so the naming and the seeding shape
are already established).

## Next step

Add `gen._param_dict_val_types`, populated at the same Pass-1.3d site that
refines parameter scalar types, and consulted by `_dict_val_of` after its own
`_dict_val_types` lookup. Both the `next(iter(...))` and the `for` spelling
must then agree — the distilled repro asserts exactly that, and it is the
right regression shape for it.