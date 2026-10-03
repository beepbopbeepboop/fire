# RUNTIME: `mojo_dict_update` discards insertion order, so `dict |` reorders the left operand's keys

Found 2026-10-01 while fixing the `dict |` right-operand coercion in
`Lib/collections/__init__.py` — the key ORDER diverges from CPython while
every key and value is correct, which is easy to mistake for a regression
in whatever change is in flight.

## The repro

```python
class D:
    def __init__(self):
        self.data = {'z': 9}
    def merge(self, other):
        self.data = self.data | other
    def show(self):
        print(self.data)

d = D()
d.merge({'a': 1})
d.show()
d.merge({'b': 2})
d.show()
```

| | output |
|---|---|
| `python3` | `{'z': 9, 'a': 1}` then `{'z': 9, 'a': 1, 'b': 2}` |
| compiled | `{'z': 9, 'a': 1}` then `{'a': 1, 'z': 9, 'b': 2}` |

The first merge is right. The **second** one moves `z` behind `a`. Every
key and every value is correct; only the order is wrong.

## Root cause

`mojo_dict_update` (`runtime/fire_runtime.c`) re-inserts every source slot
with a FRESH insertion-sequence number rather than the source slot's own:

```c
void mojo_dict_update(MojoDict *dst, MojoDict *src) {
    if (!dst || !src) return;
    for (int64_t i = 0; i < src->cap; i++)
        if (src->slots[i].key) {
            if (src->slots[i].keykind == 2)
                _dict_set_ik(dst, src->slots[i].ikey, src->slots[i].val, src->slots[i].kind);
            else
                _dict_set_raw_seq_kind_k(dst, src->slots[i].key, src->slots[i].val,
                                         -1, src->slots[i].kind, src->slots[i].keykind);
        }
}
```

The `-1` is the `seq` argument, and `_dict_set_raw_seq_kind_k`'s own
comment is explicit about what it means:

> `seq >= 0` preserves an already-assigned insertion sequence number (used
> only by `_dict_grow`'s rehash, so a key's original insertion order
> survives moving to a new, bigger slot array); **`seq < 0` assigns a fresh
> one.**

So `update` — and therefore `mojo_dict_copy` (which calls it) and
`mojo_dict_union` (which calls copy then update) — re-numbers every key it
copies, in *slot-array* order rather than insertion order. The first union
happens to come out right because the slot order coincides with the
insertion order for a two-key dict; the second does not.

Two things a fix has to get right, and both are visible here:

- **The slot scan is `i < src->cap`, not `i < src->used`**, so stale slots
  from a previous grow are walked too. They are filtered by `if
  (src->slots[i].key)`, so this is not the cause of the observed reorder,
  but it is the same loop and worth settling at the same time.
- **Preserving order means threading the source slot's sequence number
  through**, which means `_dict_set_raw_seq_kind_k` needs the source's
  `seq` value rather than a hard `-1`. `_dict_grow` already threads it,
  so there is a working precedent inside the same file.

## Not a regression

Verified by reverting the change in flight (the `dict |` right-operand
coercion, `_as_dict_operand` in `mojo/backend_gimple/emit_exprs.py`) and
re-running: the same reorder, same shape, with and without. A test that
asserts key/value content without asserting order therefore PASSES on the
broken tree, which is why this is written down separately rather than
folded into that change's regression test.

## Next step

Pass the source slot's insertion sequence through `mojo_dict_update`'s
`_dict_set_raw_seq_kind_k` call instead of `-1`, and settle whether the
scan bound should be `used` or `cap` while there — both changes are in
one loop and one function, and the `_dict_grow` precedent shows the
mechanism already exists.

Because this is a RUNTIME change, it needs `test_runtime_diff.py` or an
explicit compiled-vs-CPython stdout assertion rather than a
`test_gimple.py` shape check; the repro above is the whole test program.