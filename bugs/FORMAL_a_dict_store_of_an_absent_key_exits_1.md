# FORMAL_a_dict_store_of_an_absent_key_exits_1: `d[k] = v` for a key the blob does not hold builds, runs, and exits 1 with nothing printed

**Area:** FORMAL / codegen (shared — both backends behave identically, because
both emitters have one `_emit_dict_lookup_addr` and it is lookup-only). Found
2026-10-03 while landing the dict-KIND half of a frame field's subscript
(`bugs/FORMAL_a_dict_field_of_a_module_level_frame_still_has_no_key_kind.md`,
deleted by that commit), whose own reproducer is a STORE and therefore runs into
this one the moment the field is recognised as a dict.

**Status: OPEN, pre-existing, measured on both architectures, and it is a
build-then-exit-1 rather than a refusal.**

## What I ran

```sh
export PATH=/opt/homebrew/bin:$PATH
cat > .tmp/d.mojo <<'EOF'
def main() -> Int:
    var d = {}
    d["x"] = 3
    printf("v=%d", d["x"])
    return 0
EOF
python3 tools/memslot.py --gb 8 --label t -- \
  python3 fire.py build --formal --no-prove --backend=arm64 -o .tmp/d.arm64 .tmp/d.mojo
.tmp/d.arm64 ; echo "rc=$?"          # nothing printed, rc=1
```

CPython prints `v=3`. Same on `--backend=x86_64`.

The narrowing, measured one program at a time:

| program | arm64 | x86-64 |
|---|---|---|
| `var d = {}; d["x"] = 3` | exit 1, no output | exit 1, no output |
| `var d = {"a": 1, "b": 2}; d["a"] = 5; printf("%d", d["a"])` | `5` | `5` |
| `var d = {"a": 1, "b": 2}; printf("%d", d[0])` | exit 1 | exit 1 |

So it is not "dict stores do not work": a store to a key the blob HOLDS is
correct on both backends, and the third row says the same exit-1 is what an
INTEGER subscript against a dict base already does. The defect is the absent
key alone, and it is the same construct in all three rows — a dict base whose
subscript cannot be answered by a scan that ends in a hit.

## Why it happens

`formal/arm64_codegen.py::_emit_dict_lookup_addr` (and x86-64's copy) scans the
pair blob for the key and, on the miss arm, does
`movz x0, #1; movz x16, #1; svc #0x80` — the Darwin exit(1). That is the right
answer for a READ, because a missing key is CPython's `KeyError` and this path
has no way to raise one; `bugs/FORMAL_a_dict_subscript_has_no_value_kind.md`'s
per-key gate exists so a READ asks about a key the literal actually contains.

A STORE has no such luxury: CPython INSERTS. Inserting here is not "one more
arm", it is three facts the path does not have:

* **capacity.** The blob is `[count:i64][k0][v0]…` reserved at compile time, and
  a literal reserves its own pair count. `d = {}` reserves none, so an insert
  has nowhere to write — and the blob cannot grow, which is the same ceiling
  `_scan_list_caps` bounds for `xs.append(...)` on a list.
* **uniqueness.** The scan compares raw 64-bit words (`_static_key_needle`'s
  element-wise compare is only for a static container key), so a key that is
  present must be FOUND rather than duplicated, and "found" is a fact about the
  run-time contents.
* **what the append path already refuses.** `_emit_list_append`'s bounds check
  exits 1 on a full blob, so an insert is the same guard reached through the
  dict dispatch rather than the list one.

## The exact next step

Decide the direction first, the way
`bugs/FORMAL_a_comprehension_over_a_spliced_literal_exits_1.md` had to, and write
it down:

1. **A reservation.** The cheapest honest answer is for a dict LITERAL to
   reserve room for the STORES in the function that follow it, the way
   `_scan_list_caps` counts `append` sites for a list literal: count the
   subscript-assignment sites on each dict-typed name, add them to the literal's
   own reservation, and let the append path's existing capacity guard stop a
   program that inserts more than it declared. That reuses two mechanisms
   (`_scan_list_caps` and the bounds check) and needs no new blob layout.
2. **Or refuse the store.** `d[k] = v` for a key no compile-time evidence says
   is present is refused by name, with the repair being "give the dict a literal
   entry for the key" — which is what `bugs/FORMAL_a_dict_subscript_has_no_value_
   kind.md`'s per-key gate does for reads and what `formal/hostmods/os/
   __init__.mojo`'s `environ` row works around by calling `putenv` instead of
   subscripting (`test_formal_os_backing.py`'s comment says so). This is the
   smaller change and it is what the tree's conventions point at; the cost is
   that a program which inserts a key computed at run time has no spelling.
3. **Whichever is chosen, it must be BOTH backends in one commit.** The two
   emitters' `_emit_dict_lookup_addr` are separate copies today, and an insert
   landed in one of them is a program that works on one machine and exits 1 on
   the other — which is the failure mode `bugs/FORMAL_x86_64_two_names_bound_to_
   returned_frames_read_one_block.md` is about, on a different construct.

Do NOT widen the reservation unconditionally: an unbounded insert is a write
past the blob, and the capacity guard is the only thing standing between a
program and that.

## Why this was not fixed with the dict-KIND change

The dict-KIND change (`model.frame_slot_field_is_dict`, the seventh
`ValueKinds` hook) makes a frame field declared `Dict[…]` answer a string
subscript, which is a READ capability and is measured: `self.seen[k]` with a
dict literal in `__init__` reads 7 and 9 on both backends, from a module-level
frame and from a local. The same change routes a STORE through the dict
dispatch, where an absent key hits this exit — which is exactly what a LOCAL
dict store already did before it (`var d = {}; d["x"] = 3` exits 1 on this tree
with no field anywhere), so nothing new is reachable: the field spelling simply
stops being a build refusal for a case the local spelling already ran and
stopped on. That trade is recorded here rather than in the commit, because the
refusal it replaces named a FALSE reason (a declaration that was right there on
the struct) and this exit at least stops where the local one does.

## Tests that would pin the fix

* `var d = {}; d["x"] = 3; printf("%d", d["x"])` — `3` on both backends, or a
  refusal naming the missing reservation.
* `var d = {"a": 1}; d["b"] = 2` — the insert case, and the one that says which
  of the two directions above was chosen.
* `var d = {"a": 1}; d["a"] = 5` — the CONTROL, already correct and measured, so
  a fix cannot be "refuse every dict store" (that would refuse a program this
  path computes).
* `d[k] = v` inside a method of a struct whose field is declared `Dict[…]` —
  the spelling this doc was found through, so the field and the local cannot
  drift apart again.