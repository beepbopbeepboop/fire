# CODEGEN: a nested container as a dict-comprehension key, and as a tuple slot, is not described

Found 2026-10-01 while fixing the three docs in the
`bugs-silent-values-b` batch (see their commits). Both shapes below are
**pre-existing and independent** of that batch: verified by reverting every
`mojo/`, `runtime/` and `gimple_codegen.py` hunk of those commits and
re-measuring — identical output on both trees. Filed rather than fixed there
because they are a different mechanism (a nested container read through the
wrong accessor) from any of the three.

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