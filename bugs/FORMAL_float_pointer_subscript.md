# A `Pointer[Float64]` subscript is still refused, while its `.value()` spelling is answered

**Area:** FORMAL (the pointer value model). **Found 2026-10-07** while landing the
`Pointer[Float64]` `.value()` load (the bug doc for that load was deleted with the
fix, as a fully-fixed doc is). **NOT FIXED, and deliberate at this slice** — the
row exists so the gap is on the queue rather than rediscovered.

## What was run

```sh
export PATH=/opt/homebrew/bin:$PATH
cat > .tmp/sub.mojo <<'EOF'
def main(n: Int) -> Int:
    var p: Pointer[Float64] = malloc(8)
    p[0] = 1
    printf("%g", p[0])
    return 0
EOF
python3 tools/memslot.py --gb 8 --label t -- \
  python3 fire.py build --formal --no-prove --backend=arm64 -o .tmp/sub .tmp/sub.mojo
```

Before the `.value()` work this refused (the `Float64` row of
`model.POINTEES_REFUSED` caught every dereference). It still refuses, now with
the subscript-specific sentence:

```
build: `p[i]` reads through a POINTER, and the width of the read is the pointee's —
  the pointee is Float64, and a Float64 pointee is eight bytes of IEEE binary64 and
  the LOAD is bit-exact — one word holding the bit pattern — but there is no KIND
  for the STORE of a subscript to check: `p[i] = 1` would write 0x1, a denormal
  rather than 1.0. Read it through `p.value()`, which carries the declared
  pointee's kind and converts …
```

The `.value()` twin of the same program is answered on both architectures:
`p.value() = 1.5; printf("%g", p.value())` prints `1.5`, and a punned string
`"ABCDEFG@"` read through `p.value()` prints CPython's `46.549 46`.

## Why it is refused, and why that is the safe half

`model.dereference_lowering` answers a declared-double pointee when
`index_scaled` is False — the `.value()` spelling — and deliberately not when it
is True, which is only ever `subscript_base_lowering` (`p[i]` and its store).
The reason is asymmetric and it is about the STORE:

* a `.value()` LOAD's kind flows from the declaration through
  `model.pointer_deref_kind`, so `Int(p.value())` is `FCVTZS` and
  `printf("%d", p.value())` is refused by name rather than printing the bits;
* a `.value() = v` STORE gets the value's kind from `_expr_str_kind` in both
  emitters and refuses an integer;
* a subscript STORE (`p[i] = v`) has neither: `_emit_subscript_store` takes the
  WIDTH from `subscript_base_lowering` and never asks the value's kind, so
  `p[0] = 1` would write `0x1` — measured on both architectures as
  `4.94066e-324`, a denormal, before the refusal above was kept in place.

So the subscript spelling is refused whole rather than half-answered.

## The exact next step

The kind channel has to reach BOTH new places the subscript opens, and the order
is load-first only because the load has no hazard:

1. Extend the kind answer to a pointer subscript — a hook beside
   `model.pointer_deref_kind` for `F.SubscriptExpr` whose base is a declared
   pointer, so `_expr_str_kind(p[i])` is `FLOAT_KIND` the way `p.value()` is.
   Without it `Int(p[0])` reads the exponent field, which is the same defect this
   slice removed for `.value()`.
2. Add the value-kind check to the subscript store — the same three-way evidence
   (`model.printf_arg_float_evidence` / `_expr_str_kind`) at the one place
   `_emit_subscript_store` knows both the pointee and the value, refusing an
   integer into a double pointee and answering a double.
3. Only then flip the `index_scaled` gate in `dereference_lowering` and drop the
   `Float64` row from `POINTEES_REFUSED` — the row's remaining sentence is the
   store's, and it is the store that has to be answered first.

`test_formal_run.py`'s `deref_refuse_a_binary64_subscript_store` is the row that
holds the present line; it should be deleted with this fix, and the two
`a_binary64_pointer_…` rows beside it extended to the subscript spelling.
