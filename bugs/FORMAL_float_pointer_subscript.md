# A `Pointer[Float64]` subscript is still refused, and so is its `.value()` store — while the load is answered

**Area:** FORMAL (the pointer value model). **Found 2026-10-07** on
`work/formal150-docs` while landing the `Pointer[Float64]` `.value()` load (the
bug doc for that load was deleted with the fix, as a fully-fixed doc is).
**NOT FIXED, and deliberate at this slice** — the rows exist so the gap is on
the queue rather than rediscovered. **Update 2026-10-12 (`work/merge-qwen1`
merge):** the branch's own slice answered the `.value()` STORE as well (a
`value_kind` parameter on `model.pointer_store_lowering`, asked from
`_expr_str_kind` in both emitters); the merge kept master's implementation,
which is canonical and refuses the store (below), so on the merged tree the
answered spelling is the LOAD alone and the two refusals are the store and the
subscript.

## What was run

On the merged tree, both backends, `python3 tools/memslot.py --gb 8 --label t --
python3 fire.py build --formal --no-prove --backend=$A`:

```console
$ cat > .tmp/sub.mojo <<'EOF'
def main(n: Int) -> Int:
    var p: Pointer[Float64] = malloc(8)
    p[0] = 1
    printf("%g", p[0])
    return 0
EOF
# subscript store + load:
build: `p[i]` reads an element of a FLOAT pointee, and this path carries a
  dereference's kind but not a SUBSCRIPT's: the eight bytes would be loaded
  right and the element would then be read as an integer, ...
$ cat > .tmp/sub2.mojo <<'EOF'
def main(n: Int) -> Int:
    var p: Pointer[Float64] = malloc(8)
    p.value() = 1.5
    printf("%g", p.value())
    return 0
EOF
# .value() store:
build: p.value() on the left of an assignment is a STORE to the address the
  receiver holds, and the store's width is the pointee's — the pointee is
  Float64, and the LOAD of one lowers (the word's kind is carried by
  `pointer_deref_kind`), but a STORE through it is refused: a store needs the
  kind of the value on the right, so `p.value() = 5` would write an integer's
  word where the source means `5.0`, and nothing on this path reads that kind
  yet. Store the element through an integer-typed view, or build the value
  where it lives
```

and the `.value()` LOAD is answered on both architectures: a punned string
`"ABCDEFG@"` read through `p.value()` prints CPython's `46.549 46` (measured
2026-10-12, the row `a_binary64_pointer_load_reaches_int_and_the_format`).

On the BRANCH tree (before the merge) the subscript was refused by a different,
subscript-specific sentence — the `Float64` row of `model.POINTEES_REFUSED`'s
*"there is no KIND for the STORE of a subscript to check: `p[i] = 1` would
write 0x1, a denormal rather than 1.0"* — which the merge did not take; the
merged tree's sentence above is `subscript_base_lowering`'s, reached from BOTH
the load and the store because the store's base goes through the same reader.
The branch's pre-refusal measurement is kept: with the check out of the way,
`p[0] = 1` came back `4.94066e-324` on both architectures — a denormal.

## Why the store and the subscript are refused, and why that is the safe half

The asymmetry is about the VALUE's kind, and on the merged tree it lands in two
places:

* a `.value()` LOAD's kind flows from the declaration through
  `model.pointer_deref_kind`, so `Int(p.value())` is `FCVTZS` and
  `printf("%d", p.value())` is refused by name rather than printing the bits;
* a `.value() = v` STORE has no such channel on this tree: `model.
  pointer_store_lowering` refuses every store through a float pointee, because
  `p.value() = 1` would store `0x1`, a denormal, and nothing downstream
  converts it — the slot has no kind at run time. The refusal names the
  alternative: store the element through an integer-typed view (this tree's
  load row does exactly that, filling 1.0's pattern through a `Pointer[Int64]`
  view), or build the value where it lives. `work/formal150-docs` implemented
  the channel this refusal is missing — a `value_kind` parameter asked from
  `_expr_str_kind` at the one place each emitter knows both the pointee and
  the value, answering `p.value() = 3.9` (exact) and refusing an unestablished
  value — and the 2026-10-12 merge kept the master-side refusal rather than
  that implementation; the branch's code is the starting point for the next
  step below, not a lost one;
* a subscript STORE (`p[i] = v`) has neither: the store's base goes through
  `subscript_base_lowering`, which answers the WIDTH of the element (eight
  bytes) and nothing more, so `p[0] = 1` would write `0x1` — the denormal
  above. The same reader answers the subscript LOAD with a `"float"` shape it
  then refuses, so `p[i]` on a `Pointer[Float64]` is refused whole rather than
  half-answered, in both spellings.

## The exact next step

The kind channel has to reach the store first, because the store is the half
with the hazard, and the order is load-first only because the load has none:

1. **Give the `.value()` store the value's kind** — the `work/formal150-docs`
   implementation: a `value_kind` on `model.pointer_store_lowering`, asked from
   `_expr_str_kind` in both emitters, answering a double and refusing an
   integer into a double pointee. Until this lands the store stays refused by
   the sentence above.
2. **Extend the kind answer to a pointer subscript** — a hook beside
   `model.pointer_deref_kind` for `F.SubscriptExpr` whose base is a declared
   pointer, so `_expr_str_kind(p[i])` is `FLOAT_KIND` the way `p.value()` is.
   Without it `Int(p[0])` reads the exponent field, which is the same defect
   the load's enablement removed for `.value()`.
3. **Then the subscript store, and only then flip the gate**: add the same
   value-kind check where the subscript store knows both the pointee and the
   value, and replace the `"float"`-shape refusal in `subscript_base_lowering`
   with the answered subscript.

`test_formal_run.py` holds the present line on the merged tree:
`deref_refuse_a_binary64_subscript_store` (the store spelling, needle the
merged tree's message), `deref_refuse_a_float_pointee_subscript` (the load
spelling), and the `.value()` store refusal is the message's own words in
`model.pointer_store_lowering`. Delete them with the fix, and extend the
`a_binary64_pointer_…` rows to the store and subscript spellings.
