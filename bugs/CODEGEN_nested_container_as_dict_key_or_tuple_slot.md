# CODEGEN: a nested container as a dict-comprehension key, and as a tuple slot, is not described

Found 2026-10-01 while fixing the three docs in the
`bugs-silent-values-b` batch (see their commits). Both shapes below are
**pre-existing and independent** of that batch: verified by reverting every
`mojo/`, `runtime/` and `gimple_codegen.py` hunk of those commits and
re-measuring — identical output on both trees. Filed rather than fixed there
because they are a different mechanism (a nested container read through the
wrong accessor) from any of the three.

## Status — PARTIALLY FIXED (2026-10-02): the comprehension's key and the
## lookup now agree; the CONTENT KEY's repr does not, and the tuple-slot
## repr is still the generic walker's

Two of the four measurements below are closed and two are not, and the split
is worth stating first because the remaining two are NOT the same defect as
the fixed ones.

### Landed: the dict-comprehension key is content-keyed, and `d[(1, 1)]` HITS

`mojo/backend_gimple/emit_resolve.py`'s dict arm of `_gen_compr_append` did two
things no other dict-key site does:

1. `_char_to_cstr(kt, kv)` with NEITHER `transient` nor `word_ok`, so a
   `MojoList *` key fell past `_char_to_cstr`'s container arm entirely and out
   to the raw `(char *)value` cast — which reads the list HEADER's bytes as a
   C string. Every other dict-key site (subscript get/set, `in`, `d.get`,
   `emit_methods`' own key arm) passes `(True, True)`.
2. `gen._emit(f"  mojo_dict_set_int ({res}, {kv}, {vv64});")` instead of
   `gen._emit_call`. That matters independently: `_emit_call` is where
   `_apply_kw_keys` runs, and that is what resolves `_char_to_cstr`'s
   placeholder into the `_kw` twin carrying the raw word. A raw `_emit`
   bypassed it, so even with the right flags the placeholder would have reached
   the store as the bare cast it stands in for.

With both, the comprehension's key goes through the same
`mojo_dict_key_for` content key the subscript path uses. Measured on the two
programs below, before and after, and byte-identical to a pristine
`git archive HEAD` checkout for every case that did not change:

```
{(i, 1): i + 1 for i in range(2)}   key repr:  garbage bytes   ->  'T1100…' (content)
d[(1, 1)]                            0        ->  2
d[(0, 1)]                            0        ->  1
```

The lookups are the half that matters most: a comprehension-built dict could be
printed and had the right LENGTH, but no equal tuple ever found its own entry.

### Not landed: the content key's REPR

`{'T1100032100030100031': 1}` where CPython says `{(0, 1): 1}`. The stored key
is `mojo_dict_key_for`'s length-delimited HEX encoding (a marker byte, then
each element's byte count and hex bytes — see its own comment on why a repr
with separators is not injective), and `_mojo_repr_dict` prints the stored
string verbatim.

**This is not specific to the comprehension.** A plain store has always shown
it, on this tree and on a pristine HEAD:

```python
e = {}
e[(2, 3)] = 7
print(e)        # {'T1100032100032100033': 7}   baseline AND after
```

so the comprehension fix made the comprehension's keys agree with the OTHER
dict-key path rather than introducing a new spelling. The keykind IS recorded
per slot (`_DictSlot.keykind`, `MOJO_KEY_TUPLE` = 3), so a repr can tell a
content key from a str key; what is missing is the inverse of
`mojo_dict_key_for`'s encoding. Fixing it changes every container-keyed dict's
printed form, so it belongs with whoever owns the content-key spelling
(`bugs/CODEGEN_dict_content_key_aliases_a_string_key.md`, §1, which asserts
the content key IS the repr text — that assertion is stale on this tree, and
the literal-vs-subscript mismatch below is the same staleness).

### Not landed: the literal and the subscript still use DIFFERENT key
### spellings

```python
d = {(1, 1): 5}
print(d[(1, 1)])     # CPython 5; compiled 0 -- and the printed key is
                     # '{'(1, 1)': 5}', i.e. the repr-based spelling
e = {}
e[(2, 3)] = 7
print(e[(2, 3)])     # 7 -- the length-delimited spelling
```

`_lower_dict_literal`'s `_emit_dict_pair_store` renders a container key through
`_repr_value`, while every subscript routes through `mojo_dict_key_for`. The
two do not produce the same string, so a literal tuple key is unreachable by
the lookup that should find it. Same doc, same subject, as above — filed as the
stale part of `CODEGEN_dict_content_key_aliases_a_string_key.md`, which claims
the two were made to agree.

### Already fixed on this tree, before this work: `[([1, 2], 3)]`

The segfault (item 3 below) no longer reproduces — exit 0 and the correct
`[([1, 2], 3)]`, identically on a pristine HEAD — and `([1, 2], "z")` is
correct too. `mojo_repr_list_slotkinds`' `mojo_list_repr_elem` probe now
describes the inner list before the `mojo_is_registered_list` arm can fault.

### Not landed: a nested container as a tuple slot, read on its own

`print(([1, 2], 3))` still gives `([1, 2], <object at 0x3>)` for CPython's
`([1, 2], 3)`. `_list_repr_fn` picks `mojo_repr_list_intlists` — reached by

```python
if gen._elem_types.get(rav) == 'MojoList *' and nested == 'int64_t':
    return 'mojo_repr_list_intlists'
```

and that branch means "a list whose every element is a list of ints". For the
TUPLE `([1,2], 3)` the same tables hold: `_nested_elem_types[rav]` is
`'int64_t'` because SLOT 0 is a list of ints, and `mojo_repr_list_intlists`
then reads slot 1 (the int `3`) through the inner-list reader, which has no
list to describe and falls to `mojo_repr_obj`.

The record that would decide it does not exist and is the whole next step:
there is no codegen-side "this value is a TUPLE" flag, so a tuple read
directly is indistinguishable from a list of tuples in exactly the tables
`_list_repr_fn` reads (`_elem_types[rav] == 'MojoList *'` plus
`_tuple_slot_types[rav]`). `_lower_tuple_literal` already calls
`mojo_mark_as_tuple` on the value it builds; recording that fact the way
`_tuple_slot_types` is recorded — a `_tuple_vals` set, propagated across
assignment/return beside the other three maps — is what lets `_list_repr_fn`
route a tuple through `mojo_repr_list_kinds` (which already handles a `'l'`
slot by recursing with NULL kinds, so slot 0 would describe as `[1, 2]` and
slot 1 as `3`) instead of through the list-of-lists helpers.

## Original report (2026-10-01; unchanged)

## Status — OPEN, reproduced on current master, compiled path only


The interpreter (`python3 fire.py run`) is correct for every case below.

## 1. A TUPLE key in a dict comprehension is not described

```mojo
def main():
    print({(i, 1): i + 1 for i in range(2)})


main()
```

CPython / the interpreter:

```
{(0, 1): 1, (1, 1): 2}
```

Compiled: the key is the tuple's own ADDRESS rendered as text, and the value
is wrong too:

```
{'(l\xef\x04\x01': 1, 'ht\xef\x04\x01': 2}
```

`_gen_compr_append`'s dict arm coerces the key with `_char_to_cstr`, which for
a `MojoList *` key reads the list HEADER's bytes as a C string — the header is
`{MojoList *data; int64_t len, cap; ...}`, so what lands in the key is a
pointer and two small integers, not `(0, 1)`. That is why the printed key is
binary garbage rather than a tuple repr.

Consequence beyond the repr, and the worse half: `d[(1, 1)]` then MISSES,
because the lookup key is built the same way from a different address:

```mojo
def main():
    var d = {(i, 1): i + 1 for i in range(2)}
    print(d[(1, 1)])      # interpreter 2, compiled 0
    print(len(d))         # 2 on both — only the lookup is wrong


main()
```

This is the same root defect as `CODEGEN_tuple_dict_key_hashed_by_address.md`
(that doc covers `d[k] = v` / `k in d` at the runtime's key layer; this is the
COMPREHENSION's key coercion, in codegen, and it mangles rather than hashes),
so fix them together or not at all: one content-keyed stringification of a
registered tuple, reached from both.

`{(1, 1): 1}` — the same key shape spelled as a dict LITERAL — prints
`{'(1, 1)': 1}` where CPython says `{(1, 1): 1}`, so the literal path coerces
through a different (repr-based, at least stable) route. The comprehension
path is the one that produces garbage bytes.

## 2. A nested container as a tuple slot is not described either

```mojo
def main():
    print(([1, 2], 3))


main()
```

```
interpreter: ([1, 2], 3)
compiled:    ([1, 2], <object at 0x3>)
```

and with a `char *` in slot 1 instead of an int, both slots come back as
pointer decimals:

```mojo
def main():
    print(([1, 2], "z"))


main()
```

```
interpreter: ([1, 2], 'z')
compiled:    (4380236176, 4364040448)
```

The nested list is appended as a boxed handle and its slot type IS recorded
(`_tuple_slot_types` has `'MojoList *'` for that slot), but nothing reads that
record on the repr path: `_list_repr_fn` consults `_nested_elem_types` (a
list-wide "what the elements hold", which is meaningless for a 2-slot mixed
tuple) and `_struct_slot_kinds`, never `_tuple_slot_types`. The generic walker
therefore reads slot 0 as an int.

Note this is the SAME gap the third commit of the batch closed one level out
(`mojo_repr_list_slotkinds`, for a list OF tuples): the per-slot record exists
on the tuple side and the list-of-tuples side now consults it, but a tuple read
directly — printed on its own, or as a dict value — still does not. So the fix
is `_list_repr_fn` consulting `_tuple_slot_types` for a value that IS a tuple,
reusing the kind-string mapping that commit added
(`_TUPLE_SLOT_KIND_BYTE`), rather than a new mechanism.

The `mojo_repr_list_slotkinds` helper does handle this shape when the tuple is
inside a LIST (`[([1, 2], 3)]`), and crashes there instead — see below.

## 3. `[([1, 2], 3)]` SEGSEGVs

```mojo
def main():
    print([([1, 2], 3)])


main()
```

Exit 139, no output, on BOTH trees (verified by the revert described above).
Generated C is `mojo_repr_list_slotkinds (_t1, _slit_10000)` with
`_slit_10000 = "lI"`-style kinds, so the helper added by the batch's third
commit is reached and faults inside it: `mojo_repr_list_kinds` is asked to
describe the inner list with `kinds` describing the OUTER tuple's slots, and
the inner list's own slot 0 (an int) is then read through the 'l' arm as a
`MojoList *`. That is a defect in the NEW helper, so unlike (1) and (2) it did
not exist before this batch — but it is a defect in a shape (`a list of tuples
whose slots include a nested container`) that no test covered, and it is a
crash, so it belongs here rather than being left implicit.

## Next step

1. `_char_to_cstr` on a `MojoList *` key: produce the tuple's CONTENT as a
   string (the repr `mojo_repr_list_kinds` already builds is the right
   text), and share that one helper with `CODEGEN_tuple_dict_key_hashed_by_address.md`'s
   runtime-side fix.
2. `_list_repr_fn`: consult `_tuple_slot_types[rav]` for a value whose own
   per-slot record exists, reusing `_tuple_slot_kind_bytes` from the batch's
   third commit. Fixes (2) and, with (3), keeps the list-of-tuples case honest.
3. `mojo_repr_list_slotkinds`: it passes the CALLER's kinds string straight to
   `mojo_repr_list_kinds` for the inner list. That is right only while every
   inner slot is a scalar the same kinds string describes; a 'l' (nested
   container) or 'p' slot of the inner tuple makes the two levels'
   descriptions collide. Guard it — recurse with the INNER list's own recorded
   kinds (`mojo_repr_list_kinds(_in, NULL)`) whenever the static string says
   'l', which is what the 'l' arm of `mojo_repr_list_kinds` already does for
   its own nesting.

No gate was run for this doc (it is a report, not a change).