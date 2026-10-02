# A dict's CONTENT key aliases a plain string key, and a content key is not Python's `==`

Found 2026-10-01 while fixing
`bugs/CODEGEN_tuple_dict_key_hashed_by_address.md` (deleted with that fix).
**NOT the address bug** — a container key is now keyed by its VALUE, which is
the fix; these are the four properties of that value-keying that remain, all of
them reachable from ordinary code and none of them a crash.

## 1. A tuple key and a string key can be the same entry

A content key is TEXT — the container's own `repr` — in a dict whose every
other key is also text, so nothing separates the two domains.

```python
d = {}
d[("a", 1)] = 1
print(d.get("('a', 1)", "none"), len(d))
```

```
CPython  : none 1
compiled : 1 2            # the string key found the tuple's entry, and
                         # reading it INSERTED a second entry
```

Measured through `gimple_codegen.compile_to_gimple` + `gcc -fgimple` +
`runtime/fire_runtime.c`. The insertion is the worse half: `d.get` on a missing
key grows the dict, so this is a lookup that adds an entry.

This is **pre-existing in kind**, not introduced by the address-key fix: a
dict LITERAL key already rendered through `_repr_value`
(`mojo/backend_gimple/emit_exprs.py`'s `_emit_dict_pair_store`, "a value-based
string distinct tuple/list contents won't collide on"), so
`{(1, 2): "v"}` and `d["(1, 2)"]` were already one entry. What the fix did is
make the SUBSCRIPT spelling agree with the literal one, which is what it had to
do; this doc records what agreeing costs.

## 2. `1` and `1.0` in the same tuple position are different keys

```python
d = {}
d[("a", 1)] = "int"
print(d.get(("a", 1.0), "none"))
```

CPython prints `int` (`hash(1) == hash(1.0)`, `1 == 1.0`). The compiled
program prints `none`: a list records its per-slot ELEMENT KINDS only when
something sets them (`mojo_list_set_kinds` — a `struct.unpack` of a mixed
format, a heterogeneous list literal), and a tuple literal is built slot by
slot through `mojo_list_append_int`/`_double`, so it carries no kinds row. With
no row, `mojo_cstr_or_int_str`'s content key reads every slot as an integer and
a float slot becomes its IEEE-754 bit pattern (`4607182418800017408` for
`1.0`) — deterministic, so repeated lookups agree with each other, but not with
CPython's equality.

## 3. A struct instance in a tuple keys by its ADDRESS

```python
class P:
    def __init__(self, x):
        self.x = x
d = {}
d[(P("a"), 1)] = 1
print(d.get((P("a"), 1), "none"))
```

`none`. `_key_slot_str` has no answer for a struct: the field table that would
describe it is emitted per translation unit into the generated C (that is what
`_mojo_dispatch_repr` reads), and this code runs in the runtime on an untyped
word. It renders `<object at 0x...>`, which is stable per instance and
different per equal instance.

## 4. `keys()` / `items()` return the key TEXT, not the key

```python
d = {(1, 2): "v"}
for k in d.keys():
    print(k)
```

```
CPython  : (1, 2)
compiled : ('one', 2) style text — the dict's storage key
```

A consequence of the same string-keyed model as 1: the tuple is gone once it
has been rendered. `items()` likewise pairs the text with the value.

## The next step, in order

1. **Give a content key its own key DOMAIN.** `_DictSlot` already has
   `keykind` (1 = text, 2 = bytes, 3 = integer word — see `_ikey_lazy` and the
   `keykind` comments in `runtime/fire_runtime.c`), so the mechanism is there
   and this is a fourth value of it plus entry points that carry it: the codegen
   knows at the subscript store that the key was a container, so
   `mojo_dict_set_int`/`get_int`/`contains` need `_tup`-keyed twins (or one
   `..._ckey(MojoDict *, char *, ...)` family) rather than reusing the text
   ones. That closes 1 and, with the same kind, lets a struct's generated repr
   be the key (3) because the DOMAIN is chosen by the codegen rather than
   inferred by the runtime.
2. **Record element kinds on a tuple/list literal.** The codegen knows each
   element's static type while lowering `_lower_tuple_literal`, so it can emit
   the `mojo_list_set_kinds(t, "pdi")` string it already builds for a
   `struct.unpack` slot (`emit_methods.py`'s `_struct_slot_kinds`). That closes
   2, and it also makes the compiled `repr` of a mixed tuple right, which is
   the same walker's other job. Note the first attempt at this fix had it the
   other way round — the kinds walker with a NULL kinds row — and a float slot
   then segfaulted the whole program (the bit pattern read as a `char *`); the
   runtime-side guard is `mojo_boxed_is_str`, which is why (1) is not reachable
   through a float either.
3. **`keys()`/`items()` (4)** is the largest of the four and the one with the
   widest blast radius: it means the dict has to store the original key value,
   not only its text. Worth its own project.

The regression tests for the fixed halves are
`gimple_tuple_dict_key_is_content_keyed` and
`gimple_dict_container_keys` (the runtime group in `test_ptr_registry.py`).
