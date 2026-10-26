# A dict's CONTENT key aliases a plain string key, and a content key is not Python's `==`

**See the Status section at the end (2026-10-02) first: item 1 is now known to
be the same change that fixes a float key and a bool key, which were measured
while working on `CODEGEN_dict_comprehension_repr_is_separately_broken.md`,
and one more repr defect was located here — it is item 2's runtime half.**

**Then read the LAST Status section (2026-10-19, `work/mimo-cgen3b-1`):
item 1 is measured FIXED** — a content key and a plain str key of the same
characters are two entries, matching CPython and this repo's own interpreter —
**and what is left on this path is that `print(d)` shows a container key as its
`T<len><hex>` STORAGE encoding rather than as a tuple.** That is a different
defect from the one this doc opened with, and closing it needs element kinds to
reach the key walker, i.e. this doc's item 2. Also measured there: the
2026-10-02 note about `'(None, None)'` is stale.

Found 2026-10-01 while fixing
`CODEGEN_tuple_dict_key_hashed_by_address` (deleted with that fix).
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

## Status (2026-10-02, `work/bugs4-2`) — the `keykind` value is now the whole of items 1 and 2, and one more key kind needs it

None of the four is fixed. What this session established is that the fix is
**smaller and more uniform than the doc's four items suggest**, and that one of
them is already half-built.

### Item 1 is ONE new `keykind` value, and a float/bool key needs it too

`_DictSlot.keykind` is already `0 = a str key, 1 = a bytes key, 2 = an
INTEGER key`. Every problem in this doc — (1) a content key aliasing a string
key, (3) a struct instance in a tuple keying by address, and two more
measured here — is the same shape: **the dict cannot tell what KIND of Python
object the key was, so it falls back on "it is text"**, and then either quotes
it or compares it by whatever text it can render.

A fourth value is all the mechanism needs, and the `_kw` dispatch table
already has the three-arm shape to extend (`_kw_kind`: `mojo_boxed_is_str` ->
str, `_kw_is_container_key` -> container, else int). Measured 2026-02-02 on
this tree, from the two other dict-repr bugs' repro programs:

```
print({1.5: "x"})      CPython {1.5: 'x'}    compiled {'1.5': 'x'}
print({True: 1})       CPython {True: 1}     compiled {'True': 1}
print({k: 1 for k in [(0, 0), (0, 1)]})
                       CPython {(0, 0): 1, (0, 1): 1}
                       compiled {'(None, None)': 1, '(None, 1)': 1}
```

The float and bool cases are NOT in any existing doc and are the same defect:
`_canon_int` cannot read `"1.5"` or `"True"`, so both become `keykind == 0`
(str) slots and the repr quotes them. A `keykind == 3` for "a float key" and a
`keykind == 4` for "a bool key" — or, better, ONE rule that a key whose text
is not the repr of a str is stored under its own kind — is what makes
`_mojo_repr_dict`'s single `if (keykind == 2)` into the general form.

The third line is this doc's item 1/3 seen from the repr side: the key IS a
container's content text (that part is fixed — it used to be the tuple's heap
ADDRESS, ASLR-varied, which is worse than a stable wrong answer), and it is
still quoted and still renders a `0` slot as `None`.

### Item 2's runtime half is `_key_slot_str`, and it is the `0 -> None` too

`mojo_dict_key_for` renders a container key with `_container_key_str`, which
walks the inner list slot by slot through `_key_slot_str`. That function reads
**every slot as an integer** — which is exactly this doc's item 2 (`1` and
`1.0` in the same position are different keys, because a float slot becomes its
IEEE-754 bits) — AND it applies the `0 -> None` heuristic, which is why the
comprehension case above prints `'(None, None)'` for the tuple `(0, 0)`.

So item 2 has TWO halves in the same function, and only the first was named:
the missing element kinds (`mojo_list_set_kinds`, which
`_lower_tuple_literal` already emits for a heterogeneous literal) and the
sentinel. A tuple of ints is a `keykind`-uniform list, so `mojo_list_get_kinds`
answers NULL for it and the walker still has nothing to read slots by; that is
the gap `mojo_repr_list_slotkinds`'s `kinds` ARGUMENT already solves for the
repr (the codegen knows the pattern statically there, from
`gen._tuple_slot_types`), and the same `kinds` string handed to
`_container_key_str` would solve it for the key.

### Ordering

1. **`_mojo_repr_dict`'s key `if`** — already extended once for `keykind == 2`
   (see `CODEGEN_dict_comprehension_repr_is_separately_broken.md`'s Status). It
   is the one line that has to learn about every new kind, so it is the last
   thing to change, not the first.
2. **`_kw_kind` + the `_kw` twins' fourth arm**, and
   `mojo_dict_set_*_ckey` / `_get_*` / `_contains_*` / `_pop_*` / `_setdefault_*`
   for it. That is what closes this doc's (1) and (3).
3. **`_key_slot_str` taking the inner list's `kinds`**, which closes this doc's
   (2) and the comprehension repr's remaining `None`s together.
4. (4) `keys()`/`items()` returning the key VALUE is still the largest and is
   unchanged: it means the dict has to STORE the original key, not only its
   text, which is a different data model from everything above.

## Status (2026-10-19, `work/mimo-cgen3b-1`) — item 1 is FIXED; a container key's REPLICA is the defect that is left, and it was not in any doc

Measured on this tree, one program, three engines (`fire.py --jit`,
`fire.py run`, CPython):

    d = {(1, 2): "v"}
    d["(1, 2)"] = "s"
    print(d); print(len(d))
    print({k: 1 for k in [(0, 0), (0, 1)]})

| | CPython | interpreter | compiled |
|---|---|---|---|
| `d` | `{(1, 2): 'v', '(1, 2)': 's'}` | same | `{'T1100032100031100032': 'v', '(1, 2)': 's'}` |
| `len(d)` | 2 | 2 | 2 |
| comprehension | `{(0, 0): 1, (0, 1): 1}` | same | `{'T1100032100030100030': 1, 'T1100032100030100031': 1}` |

### Item 1 is closed

The content key and the plain str key are TWO entries in the compiled path, in
both directions, matching CPython and this repo's own interpreter — which is
what `MOJO_KEY_TUPLE 3` and the length-delimited hex encoding were built to do.
This doc's item 1 can be struck.

### And the `0 -> None` half of item 2 is gone from this path too

The 2026-10-02 Status measured the comprehension printing `'(None, None)'` and
`'(None, 1)'` — `_key_slot_str` reading every inner slot as an integer and
applying the `0 -> None` heuristic. It does not print that now. What it prints
is the encoding itself.

### The defect that is left, and which no doc states: a container key is REPR'd as its STORAGE FORM

`_mojo_repr_dict` renders a slot's key with `mojo_repr_str(mojo_dict_slot_key
(d, _i))` and that is right for keykind 0 (str) and keykind 2 (an integer
slot, whose `_slot_key` answers the DECIMAL). For `keykind == 3`
(`MOJO_KEY_TUPLE`) the slot's key IS the `T<elem-count><len><hex>...`
encoding, so printing it verbatim gives `'T1100032100031100032'` where every
engine prints `(1, 2)`. The dict is CORRECT — it holds one entry per distinct
key and answers lookups right — it is only what `print(d)` shows.

This is the same missing arm in `_mojo_repr_dict` that its own comment
declines, seen from the container side instead of the integer side, and the
sibling doc's last section records the integer side's design in full (built,
measured, reverted; the revert's reasons are there).

**It is NOT a one-line decode.** The encoding is injective but not
self-describing: it records each element's BYTE LENGTH and its hex bytes, not
its KIND, so a decoder cannot tell `('1', '2')` from `(1, 2)` (or a `None`
from a `0`) — the very ambiguity that `_key_slot_str`'s integer-read was
papering over, and that `mojo_repr_slot_kind` solves for the PAIR walkers by
taking a `kinds` argument the codegen supplies. Closing this therefore needs
the element `kinds` string to reach the key walker as it already reaches
`mojo_repr_list_slotkinds`, which is item 2's runtime half from the 2026-10-02
Status — so this doc's items 1 and 2 have swapped which one is the live work.

### Items 2, 3 and 4 are unchanged and were not exercised here

`1` vs `1.0` in a tuple position, a struct instance in a tuple keying by
address, and `keys()`/`items()` returning the key TEXT rather than the key,
were not measured in this session and are still open as written.
