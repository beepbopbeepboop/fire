# FORMAL_subscript_store_on_a_non_container_segfaults: `a[0] = 1` with an integer `a` dies on BOTH architectures

**Status: OPEN, pre-existing, arch-independent, found while fixing the tuple
store (`bugs/FORMAL_tuple_store_to_a_field` on `work/merge2-formal`).** It is a
clean SIGSEGV at run time with a green build, on arm64 and on x86-64 alike, so
nothing is silently wrong because of it — but it is the failure mode this
backend's refusal discipline exists to convert into a message, and it is one
choke point away from a wider family.

## The reproducer

```
def main(n):
    a = 5
    a[0] = 1
    printf("a=%d", a)
    return 0
```

| | result |
|---|---|
| CPython, same text | `TypeError: 'int' object does not support item assignment` |
| `build --formal --no-prove` (arm64) | **Built.** SIGSEGV, exit **139** |
| `build --formal --no-prove --backend x86_64` | **Built.** SIGSEGV, exit **139** |

Five lines, no imports, both architectures.  `a = 5` is a word; `a[0] = 1`
computes `a + 0·8` and stores there, so the store lands at address 5.

## Why it is NOT the tuple-store family, which is why it is here

`a[0], b = 1, 2` is refused by name on x86-64 (a tuple target element must be a
name or a field on this path) and SIGSEGVs on arm64.  That looks like one bug
and is two:

* the tuple path's own defect was the x86-64 **target shape**, now fixed — see
  the commit that added `_tuple_target_key` and made `_emit_for_unpack` recurse;
* what survives on arm64 is this one, and the plain `a[0] = 1` above shows it
  is not about tuples at all.  Fixing the tuple shapes did not touch it and
  could not.

## Why the same refusal does not already exist

The subscript READ path has a whole refusal family — `frame_address_subscript_read`,
`refuse:is a CONTAINER operation on a R FRAME ADDRESS` and its store and slice
and membership and for-in siblings in `test_formal_run.py` — and every one of
them is keyed on the base being a FRAME ADDRESS.  There is no arm of it for
"the base is an ordinary word".  A word is not a frame, so `frame_container_refusal`
does not fire, and what is left is the blob reading: the count word is loaded
from offset 0 of the word itself and the element written at `base + 8 + 8·i`.

Both emitters reach it through the same two functions —
`formal/arm64_codegen.py::_emit_subscript_addr` and
`formal/x86_64_codegen.py`'s subscript address path — and both already have the
kind of the base: `model`'s `ValueKinds` classifies a `char *`, a blob and an
`int`, and `_expr_str_kind` is what the string refusals read.  The missing arm is
a base whose kind is `int` (or unclassified) being asked for an element.

## The next step

One refusal, in the shared model beside `frame_container_refusal`, and one ask
from each backend's subscript address path — the same two-line shape the
`len`-on-a-frame family uses, and for the same reason (the emitters cannot each
decide what a word holds):

1. in `formal/model.py`, a `subscript_operand_refusal(base_kind, spelled)`
   naming the base, its kind, and that a container element is a word inside a
   blob the base does not name — so the write lands at `base + 8·(i+1)` of
   whatever `base` happens to be, which is a wrong answer when the base is
   mapped and a fault when it is not;
2. arm64 and x86-64 ask it from `_emit_subscript_addr` (read) and from the
   store path (write), so a read, a store and an augmented assignment all get
   the same answer — the choke-point argument
   `bugs/FORMAL_string_value_model.md`'s `s[i]` item makes;
3. `test_formal_run.py` gains a `refuse:` case for the store and
   `test_formal_value_model.py` one for the tuple element spelling, so the two
   architectures are pinned to the same message.

**Cost: under an hour, and the current behaviour — a green build and a SIGSEGV
at run time — becomes a build error.**  It is worth doing on its own merits: the
`%s` half of this family is what `formal/model.py`'s `string_operand_is_string`
already refuses, so the gap is that the table has rows for a string base and for
a frame base and no row for "not a container at all".