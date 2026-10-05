# CODEGEN: a `*str` spread BESIDE a literal slot of its own prints that slot's zero as `None`

**Found 2026-10-04** while fixing
`bugs/CODEGEN_star_spread_in_a_list_or_tuple_display_segfaults.md`, which
fixed the SIGSEGV and left this. Filed, not fixed: the repair needs a runtime
length for a per-slot kinds string, which is a change to
`runtime/fire_runtime.c`'s private kinds table.

## What I ran

```python
def tup_str(a: str) -> tuple:
    return (0, *a)

def list_str(a: str) -> list:
    return [0, *a]

print(tup_str('ab'))
print(list_str('ab'))
print([*'ab'])
```

| expression | CPython | compiled |
|---|---|---|
| `print([*'ab'])` | `['a', 'b']` | `['a', 'b']` |
| `print(tup_str('ab'))` | `(0, 'a', 'b')` | **`(None, 'a', 'b')`** |
| `print(list_str('ab'))` | `[0, 'a', 'b']` | `[None, 'a', 'b']` |

Before the spread fix all three SIGSEGVed, so this is a large improvement and
still not the right answer. The plain string spread alone is right; only the
mixed spelling is wrong.

## What I see

The literal is genuinely heterogeneous — one int slot and N string slots — and
the one mechanism this runtime has for "these slots are not all one kind" is
the per-slot kinds string, which is
**one byte per slot** (`runtime/fire_runtime.c`'s `_KindRow.kinds`: "one byte
per slot, or NULL"). Its length is a compile-time constant here and the list's
length is not: the spread contributes `strlen(s)` slots.

So `mojo/backend_gimple/emit_exprs.py`'s `_literal_slot_kinds` stops at the
first spread (that is what removed the segfault, and the same rule makes
`[0, *a, 9]` print `[0, 1, 2, 9]`), which leaves:

* kinds `"i"` — covering slot 0 only, and never recorded at all because it is
  homogeneous and carries no `None` (`_lower_tuple_literal`'s
  `len(set(_tkinds)) > 1` gate);
* `_elem_types[t] == 'char *'`, so `_list_repr_fn` falls through every uniform
  branch to the generic `_mojo_repr_list`;
* and the generic walker's "a slot holding the raw value 0 is a boxed None"
  heuristic, which is right for a genuinely dynamic list and wrong for a slot
  this compile knows is an `int`. Hence `None`.

A plain `[0, 'a']` gets all three of these right, because both of its slot
indices are static — that is the shape the kinds string was built for, and the
spread is the first shape it cannot express.

## Why it is not fixed here

The kinds string has to become a runtime-length string, and it is currently
NOT copied: `mojo_list_set_kinds` stores the codegen's interned string-pool
constant by pointer, and its own comment says so ("both callers hand over a
pointer that outlives every list it reaches"). Appending bytes to it therefore
needs an ownership flag on `_KindRow` and a copy-on-write in
`_kinds_row_for_write`. `_KindRow` and `_reg_kinds` are both `static` inside
`fire_runtime.c`, so this is NOT an ABI change and no Lean model or header
census moves — but it is a runtime change, and it is the kind this session's
change set should not smuggle in behind a codegen fix.

There is precedent for the shape in the same file: `mojo_list_repeat`
(fire_runtime.c:1947) already builds a fresh runtime-length kinds string with
`malloc` for exactly this reason ("the source kinds, repeated n times to cover
the result (a fresh string, since the source's is shared)").

## The exact next step

1. Add `char owned;` to `_KindRow`, cleared by `mojo_list_set_kinds` and set by
   whatever builds a string. A helper `_kinds_append(_KindRow *r, const char
   *bytes, int64_t n)`: no-op when the row has no kinds at all (a list that
   never recorded any must not start recording on an append), otherwise
   copy-on-write then grow with `realloc`, which is safe because `owned` is
   true exactly when the buffer is private.
2. `mojo_list_extend` calls it with `src`'s kinds bytes. That alone fixes every
   `list.extend` / `[x, *y]` where the source already described its slots — the
   inheritance the function already does for `repr_fn` a few lines above, and
   for the same reason.
3. For a STRING spread, `mojo_str_chars` records `"pppp…"` of its own length on
   the list it builds (the string is the one case where the element type is
   provable, which is why step 2 alone is not enough for `(0, *s)`), and
   `_lower_tuple_literal`/`_lower_list_literal` record their statically-known
   PREFIX whenever the literal contains a spread at all — today the
   `len(set(_kinds)) > 1` gate drops a homogeneous prefix that a runtime
   extension is about to continue.
4. Then `print(tup_str('ab'))` is `(0, 'a', 'b')` and
   `print(list_str('ab'))` is `[0, 'a', 'b']`, asserted against CPython on
   both pipeline modes. Also re-measure the printed-container memory case: a
   growable kinds string is a new allocation per extended list, and
   `test_gimple_runner.py`'s `gimple_printed_container_repr_does_not_grow`
   (seven shapes, 60 000 iterations, a 40 MB ceiling) is the instrument for
   it. That case's own argument is the reason to re-measure rather than
   assume: a ceiling loose enough that a real slope fits under it measures
   nothing, and the repr-walker's release protocol is what that case was
   written to protect — commit `b1b26609`, "Every repr walker releases its
   cat buffers: 87.2 MB -> 12.8 MB on a printing loop".

## Related

- `bugs/CODEGEN_star_spread_in_a_list_or_tuple_display_segfaults.md` — the fix
  this is the residue of, and whose Status records it.
- The same repr-walker's remaining ownership gap, on the `print` side: a
  printed container's repr buffer was never freed (16.4 B per print), and
  neither were the four other consumers of the same walkers — `str(xs)`,
  `repr(xs)`, `f"{xs}"` and `'%s' % xs`, all 12.8 B per call, plus the
  dict-keyed `'%(k)s' % d` primitive at 122 B. All fixed 2026-10-04 by putting
  `_OWNED_REPR_FNS` into `_FRESH_STRING_RETURNS` and teaching the ownership
  analysis that an f-string is not a constant; pinned by the eight
  `gimple_*_repr_is_released` rows in `test_gimple_runner.py`.