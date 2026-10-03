# FORMAL_a_one_field_struct_whose_only_field_is_a_nested_frame: `Outer { n: In }` is refused on both backends, and the message names a field the source never writes

**Area:** FORMAL, both backends (the shape is decided by the shared one-word-receiver rule and the shared nested-frame layout). **Status: OPEN, measured on this tree, and the diagnostic is the
defect: the answer is a refusal on both machines and the reason it gives names
`o.a`, which the source does not contain.** Found 2026-10-03 while closing the
"method call on a nested receiver" item of
`FORMAL_wide_receiver_by_reference.md`, whose measurement turned up this shape
next door.

## What I ran

The only difference from the case that WORKS is that `Outer` has one field
instead of two:

```python
# builds, answers 77 on both backends, matches CPython
struct Inner:
    var a: Int
    var b: Int
    def put(out self, v: Int) -> Int: self.a = v; return self.a
    def get(self) -> Int: return self.a
struct Outer:
    var pad: Int          # ← the only difference
    var n: Inner
def main(k: Int) -> Int:
    var o = Outer()
    o.n.put(7)
    printf("%d %d", o.n.a, o.n.b)
    return o.n.get() * 10 + o.n.a
```

```python
# refused on BOTH backends
struct Outer:
    var n: Inner          # ← the sole field is the nested frame
```

| | arm64 | x86-64 |
|---|---|---|
| `Outer { pad, n }`, `o.n.put(7)` | `a=7 b=0`, exit 77 | `a=7 b=0`, exit 77 |
| `Outer { n }`, same body | `build: main: 'o.a' is a field access through 'o', and this path has no way to say what 'o' holds …` | identical words |

## Why the message names `o.a`, and why that is the bug

`o` is bound from `Outer()`, and `Outer` has exactly ONE field. So the
one-word-receiver rule applies (`model.one_word_receiver_kind`'s docstring:
"the receiver of a struct with exactly one field IS that field — `self.<f>` is
`self`"), and the rewrite collapses `o.n` into `o` before anything asks what
`o.n.a` means. What is left is `o.a`: a ONE-HOP field access through `o`, whose
only slot holds — per `model.struct_nested_frame_fields` — the ADDRESS of the
nested frame, not a copy of it.

So the walk is right about the shape and wrong about the story. It sees a
one-hop field read and asks which field; the answer it reports is `a`, a name
that exists in `Inner` and in neither `Outer` nor the source line the reader is
looking at. The two facts it needed were both available and neither was asked:

* **`Outer`'s one field IS a placed nested frame**, so `o.a` is `o` → slot 0 →
  the nested frame's slot 0 — a TWO-hop read that `_frame_nested_slots` already
  represents as a tuple of slots for exactly this (the Round-4 read-side fix:
  "the value is the TUPLE of slots"). The rewrite throws the first hop away, so
  the tuple is never built.
* **a hop with no slot to load has its own message** — `model.nested_frame_hop_unplaced`
  exists and says "the field is agreed to be a nested FRAME and the LAYOUT has
  no index for it". Nothing here is unplaced; the layout has both indices.

This is the diagnostic defect C5 already fixed once and in the same words —
"the field-of-a-field refusal printed the METHOD's own name where the FIELD's
belonged, so `interpreter.scope.define()` read as 'the word in the slot
`interpreter.define`' — a field the source never mentions", fixed by
`model._member_chain` — recurring one level in, through a rewrite rather than
through a message.

## What is NOT the cause

* **Not the depth bound.** `MAX_NESTED_FRAME_DEPTH = 4` and this is level 1; the
  two-level chain with `pad` in `Outer` runs at every level the file already
  tests.
* **Not `struct_frame_representable` / the block reservation.** `Outer { n }`
  reserves a block for its own slot 0 plus the nested frame's, and the
  construction site succeeds — the refusal comes later, from the field walk.
* **Not a two-backend divergence.** Both refuse, in the same words, which is the
  good half and is why this is a diagnostic defect rather than a wrong answer.
* **Not the mutator convention.** `put` is `out self` in both rows; only
  `Outer`'s field count differs.

## The exact next step

1. **Decide what a one-hop field access through a ONE-FIELD struct whose field is
   a nested frame means, and write it down before coding it.** Two answers, and
   they are not the same code:
   * the two-hop read (`o.a` ≡ `o.n.a`), which is what the source says and what
     the passing two-field row computes; or
   * a refusal that says so — "`Outer` has one field, `n`, and it is a nested
     frame, so `o.a` is two hops and this path reads one" — which is also TRUE,
     and is the cheaper and more honest answer if the two-hop read turns out to
     need a layout change.
2. Whichever is chosen, it belongs where the collapse happens: the one-word
   receiver rewrite must not discard a hop before the nested-slot walk has seen
   it, or the walk must be able to ask for the chain rather than for the field.
   `model._frame_nested_slots` and `model.struct_block_children` are the two
   tables that already carry what it needs.
3. Whatever the decision, the refusal must name the SOURCE's chain (`o.n.a`), by
   `model._member_chain`, for the reason in the "Why" section above.
4. Test: this shape as a `refuse:` row in `test_formal_x86_64_parity.py`'s
   `REFUSALS` (both machines, same words) if the answer is a refusal, and as a
   positive row beside `nested_frame_chain_three_levels` if it is the two-hop
   read — with the CPython oracle the parity file already uses, not a constant.
   The two-field row that passes today is the guard for "the fix did not break
   the shape that worked".