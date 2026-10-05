# A set is a LIST here: insertion order, no hashing, and `for x in s` disagrees with CPython

**Status: NOT A BUG — this is the value model, and it is the document
`tools/formal_fuzz.py`'s `KNOWN_DIVERGENCES['set_order']` row names.** The row
was added by the fuzz-5 sweep in the same session that added `--mix sets`,
because a corpus that could not produce a set could not notice the day this
changed — which is the only moment the row is for, and the same argument
`bugs/FORMAL_string_value_model.md` makes for `s[i]`.

## What the model is, in the one line that states it

`formal/model.py`'s blob-layout comment, immediately above `BLOB_HEADER_BYTES`:

    # A list/tuple is a blob:  [count:i64][elem0][elem1]…   (8-byte slots)
    # A set lowers as a list. A dict is a PAIR blob:

That is the whole of it. A set literal is a list literal with distinct words:
no hash, no bucket array, no probe sequence, no load factor, and no resize. So:

| operation | CPython | this path | why |
|---|---|---|---|
| `len(s)` | the element count | the element count | the count word |
| `x in s` | a hash probe | a linear scan | same answer, different cost |
| `s.add(x)` for a member | no change | no change | a list walk finds it |
| `for x in s` | HASH order | **INSERTION order** | the one disagreement |
| `print(s)` | `{3, 1, 2}` | refused or a blob | `print` will not guess a set's spelling |

## The measurement

    def main() -> Int32:
        s = {3, 1, 2}
        for x in s:
            print(x)
        return 0

| | answer | exit |
|---|---|---|
| CPython | `1` `2` `3` | 0 |
| arm64 | `3` `1` `2` | 0 |
| x86-64 | `3` `1` `2` | 0 |

The order is insertion order on both backends, which is the blob's order. It is
deterministic, so it is not a miscompile — it is a different value model, and
the corpus's job is to keep it visible rather than to be surprised by it.

**Note what does NOT disagree**, because a set whose model is wrong in three
places would be a much bigger statement than one that is wrong in one:
`len({3, 1, 2})` is `3` on all three, and `1 in s` / `9 in s` are `True` /
`False` on all three. The `set_len` and `set_in` families in `--mix sets` are
there to keep measuring those two, and the `set_iter` family is there to keep
measuring the third.

## What CPython's order actually is, so the row's claim is checkable

CPython iterates a set in the order its table's slots come out, which for a
`set` of small non-negative integers is `hash(v) % table_size` — so it is
ASCENDING for `{1..8}` (table size 8) and scrambled above that. The corpus
draws its elements from `range(1, 30)` and inserts them in the sampled order,
so most generated tables disagree and the `set_order` row fires. A table whose
CPython order happens to equal its insertion order agrees by accident, which is
why a sweep of `sets` reports a mix of `KNOWN:set_order` and `match` rather
than a clean column of one or the other.

## Why the neutraliser rewrites the LITERAL and not the walk

`NEUTRALISERS['set_order']` turns `S = {3, 1, 2}` into `S = [3, 1, 2]` and
leaves `for x in S:` alone. A walk over a list is insertion-ordered on both
engines, so the rewritten program agrees with CPython and the disagreement is
attributed to the set-ness rather than to anything else in the program. Deleting
the walk instead would take the program's control flow with it, and
`tools/formal_fuzz.py`'s docstring is explicit that a neutraliser which changes
the shape teaches nothing.

The regex distinguishes a set literal from a dict literal by the absence of a
`:`, because both are `= {…}` textually and a neutraliser that rewrote a dict
literal into a list would take every dict subscript in the program down with it.

## If this ever stops being true

Delete the `set_order` row in the same commit that changes the model, and say
here what the new order is. A row naming a construct that is now RIGHT forgives
the next disagreement that happens to contain it — that is the whole reason
`KNOWN_DIVERGENCES` is a different table from `MIX_MUST_GENERATE`, and the same
reason `str_subscript`'s row is a claim rather than a suppression.
