# `std/builtin/builtin_slice.mojo` needs a REPRESENTATION for `Optional`, not a lowering — and that is what the 13-file row is really waiting on

**Area:** FORMAL (the value model; shared by both backends and the Lean proof).
Found 2026-10-01 on `work/formal2-re-and-slice`. **NOT FIXED — it is a
value-model decision, and it is the last thing between the `builtin_slice` row
and 13 files.**

This doc exists to say what `bugs/FORMAL_builtin_slice_optional_field_is_a_frame_holder.md`
left open, with the measurement that settles the question of which wall it is.

## What the frame-holder doc measured, and what was behind it

That doc's own text is accurate and its two messages are both real: the 13-file
row is refused for `a Optional receiver is stored in the field 'self.start'`, and
disabling that refusal does not produce a build. Measured here, by patching the
branch out and re-running the terminal file:

```
$ for a in arm64 x86_64; do python3 fire.py build --formal --no-prove --backend=$a \
      -o .tmp/sl ../new-modular/Mojo/stdlib/std/builtin/builtin_slice.mojo; done
build: builtin_slice.mojo imports 'std.format._utils', which cannot be built
either: builtin_slice.mojo: self.step.or_else() is an Optional unwrap …
```

So the frame-holder refusal was real but was not the row's terminal cause. The
row's terminal cause is `UNWRAP_METHODS` (`formal/model.py:5879`), and it is a
**representation** problem, which the refusal's own text states:

> it answers by knowing which of two words was the empty one, and on this path
> there is no way to know. None and a value are both one 64-bit word in one frame
> slot, and None is emitted as the integer 0, so treating 0 as empty would be
> wrong about `Some(0)` — a silent wrong answer on a program that computes a
> different number. There is no niche, no discriminant and no tag word here.

## Why the answer is not "pick a tag word" and what actually has to change

`Optional` is not a two-word struct on this path and never was. `formal/model.py`
measured it at 2 fields **because of a defect** — `Optional`'s second "field" was
its private method `_write_to`, counted by the derived-field walk because
`self._write_to[is_repr=False](writer)` is a call through brackets. Fixed on
`work/formal2-re-and-slice` (`bd757a63`), which is the real content of that
commit; after it, `Optional` measures **1** field and
`struct_is_one_field(Optional)` is true, i.e. the receiver IS the field.

**That is the whole shape of the problem, and it is why a tag word is not enough.**
`Optional`'s single field is `var _value: Self._type` where
`comptime _type = Variant[_NoneType, Self.T]` (`optional.mojo:182-183`). So:

* `Optional[Int]` is ONE word — a `Variant`'s — and `None` and `Some(v)` are two
  values of that one word;
* there is no spare bit to niche into, because the word is fully occupied by the
  payload;
* the discriminator is a RUNTIME property of `Variant`, and `Variant` is one
  field on this path too — measured: `Variant` has exactly one field
  (`_storage`), and that storage is one of `_DefaultVariantStorage` (1 field),
  `_NichedOptionalStorage` (3) or `_CustomNicheStorage` (2). So the tag lives a
  SECOND frame away from `Optional`, and `Optional._value` is a word naming it.

So `or_else` needs to read a tag that lives in a DIFFERENT struct's frame, and
`formal/model.py` currently refuses precisely that: a method on a value read out
of another function's frame. **This is not a new construct. It is the frame
design meeting the fact that `Optional`'s tag is not in `Optional`.**

## The wall behind THAT, measured — and it is MLIR, not a representation choice

`Variant`'s discriminator EXISTS and is readable:

* `std/utils/variant.mojo:370` — `def isa[T](self) -> Bool`, which compares
  `self.get_discriminant()` against a comptime type index;
* `std/utils/variant.mojo:361` — `def get_discriminant(ref self) -> ref[self]
  UInt8`.

So the information is there. What is missing is a PATH to it, and that path is
refused before any `Optional` question is reached:

```
$ python3 fire.py build --formal --no-prove --backend=arm64 \
      -o .tmp/var ../new-modular/Mojo/stdlib/std/utils/variant.mojo
build: a _CustomNicheStorage receiver is passed to __get_mvalue_as_litref() …
       It is a compile-time REFLECTION INTRINSIC of the compiler … There is no
       MLIR on this path … In the standard library it is the operand of an
       `__mlir_op.…` build (48 of its 50 spellings), and that construct is what
       this path refuses; this name is its operand rather than a call of its own
```

`get_discriminant` is written with `__mlir_op.\`pop.variant.discr_gep\``
(`variant.mojo:362`) and `unsafe_bitcast`, so the discriminator is reached through
MLIR dialect intrinsics, and `std/utils/variant.mojo` is refused on THAT before
any `Optional` question is asked.

**Which means the representation option below is necessary and NOT sufficient**,
and saying so is the most useful thing in this doc. The honest dependency order,
each arrow measured:

    MLIR intrinsic (__mlir_op / __get_mvalue_as_litref)
      ->  Variant.get_discriminant / isa
        ->  Optional.or_else
          ->  builtin_slice.mojo builds
            ->  the 13 files reach their own next refusal

The first arrow is `construct:mlir-and-gpu-globals` (merged, and it did not take
this on). So `tile.mojo`'s row and `Optional`'s row meet at the same place, one
layer below either of them.

## What the 13 files actually need, measured

Re-swept the 13-file row's files on both trees (`tools/formal_sweep.py -j 3 -t
200`, arm64):

| | before `bd757a63` | after |
|---|---|---|
| `builtin_slice.mojo` alone | `CODEGEN` — `a Optional receiver is stored in the field 'self.start'` | `CODEGEN/DEPENDENCY` — `self.step.or_else() is an Optional unwrap` |
| the 13 dependents | all `CODEGEN/DEPENDENCY`, all `or_else()` | **all `or_else()`, unchanged** |

**So the honest accounting is: 0 files gained a PASS, and 13 files did not move.**
`builtin_slice.mojo` moved to the refusal its 13 dependents already had, which is
progress on the FILE and nothing on the ROW. Reporting that as "13 files
unblocked" would be false, and `formal_sweep_causes.py`'s own warning is the
reason to be careful: "FILES BLOCKED IS AN UPPER BOUND".

Two other measurements from the same sweep, which are the real yield of
`bd757a63` and are recorded here so they are not lost:

* 31 structs across the stdlib and this repository have a NARROWER field set
  after it (`Optional`, `List`, `Dict`, `Set`, `Array`, `Deque`, `Span`,
  `Tuple`, `Counter`, `LinkedList`, `Pointer`, `Variant`, `StringSpan`,
  `_DLHandle`, `OwnedDLHandle`, `UnsafeUnion`, `SIMD`, `Logger`, `BitSet`,
  `Coroutine`, `VariadicPack` and six more), 30 of them because a bracketed
  method call had been inventing a field slot.
* 4 files moved to a different refusal and 0 lost anything.

## The next step

A decision about `Optional`'s representation, and there are exactly two that do
not lie:

1. **Make `None` a reserved word rather than the integer 0.** `Optional[T]`'s
   payload is a full word, so a reserved sentinel is only sound for a `T` whose
   domain provably excludes it — which is `Int` only if the compiler can prove
   it, and it cannot in general. So this is sound for the stdlib's
   `Optional[Int]` under a stated exclusion and **wrong** for a `T` that can hold
   every word. Do not take it without the exclusion.
2. **Give the unwrap a tag the backend can read.** `Variant` already HAS one —
   that is what `isa` (`variant.mojo:370`) and `get_discriminant` (`:361`) are.
   The change is then not a new representation but an existing one the unwrap
   path is refusing to read: `self.step.or_else(d)` becomes
   `_value.isa(_NoneType) ? d : _value.payload`. **On its own this is still not
   enough**, because `isa` reaches its tag through `__mlir_op` (measured above),
   so option 2 is really two changes: the unwrap, and a way to read a `Variant`'s
   discriminant without the MLIR intrinsic. The second is the same
   `__mlir_op` problem `std/utils/variant.mojo` is refused on today, and it is
   the one that has to be solved first — it is `construct:mlir-and-gpu-globals`'s
   and it is already merged without it.

**Option 2 is the one to take**, and it is smaller than it looks — but the
measurements above are what make it small. Everything it needs already exists:
`Variant`'s field list, its discriminator methods, and a frame layout for a
2-field struct. Two things are missing: the unwrapping itself (what stands in
its way is `UNWRAP_METHODS` refusing on the NAME, before any of this is
consulted), and a path to `get_discriminant` that does not go through
`__mlir_op`. The second is not part of this option; it is the arrow above it.

Two consequences worth stating before it is started, because both are
value-model level and neither is local:

* **`lib/ProofLib.lean` grows with it.** The frame layer (step 1 of
  `bugs/FORMAL_wide_receiver_by_reference.md`) already proves
  `frameRead_frameWrite_same` / `_ne`, which is what a tag read needs; nothing in
  the current proof story covers "a value read out of a frame slot is
  discriminated by a second read of the same slot". `Frame.frameRead_in_range`
  is the lemma that constrains it.
* **x86-64 must move at the same time.** `UNWRAP_METHODS` is arch-free and asked
  by both backends precisely so they cannot disagree (`specialization_call_refusal`
  says the same about its own table). A fix that lands on one machine and not the
  other is the two-machines-one-language failure this backend exists to prevent.

## Re-measured 2026-10-01 (`work/formal3-7`): the dependency chain's FIRST
## arrow has MOVED, and it moved to something this doc does not cover

`builtin_slice.mojo` still lands where this doc says it does, which is the
whole of what this doc is about:

```
$ python3 tools/memslot.py --gb 8 --label bsl -- python3 fire.py build \
      --formal --no-prove -o .tmp/esc/bsl \
      ../new-modular/Mojo/stdlib/std/builtin/builtin_slice.mojo
build: builtin_slice.mojo imports 'std.format._utils', which cannot be built
either: builtin_slice.mojo: self.step.or_else() is an Optional unwrap […]
```

**But `std/utils/variant.mojo` no longer refuses on `__mlir_op`.** This doc's
§"The wall behind THAT" puts the first arrow of the chain at
`get_discriminant`'s `__mlir_op.\`pop.variant.discr_gep\`` and measured that
refusal as the thing standing between `Optional.or_else` and a build. That
refusal has moved EARLIER in the file and now says something else:

```
$ python3 tools/memslot.py --gb 8 --label var -- python3 fire.py build \
      --formal --no-prove -o .tmp/esc/var \
      ../new-modular/Mojo/stdlib/std/utils/variant.mojo
build: Self._Storage reads a `comptime` class attribute of Variant, whose
value is `_VariantStorageFor[…]` — and a formal value is one 64-bit word with
nowhere to keep a non-literal one […]
```

The `__mlir_op` code is still in the source — `variant.mojo:362` still reads
`__mlir_op.\`pop.variant.discr_gep\`` and `:154`/`:310` still call
`__get_mvalue_as_litref` — so this doc's claim that reaching the tag needs the
MLIR intrinsic is unchanged as a statement about the SOURCE. What changed is
the ORDER: a `comptime` class attribute holding a computed value is now
refused earlier than the intrinsic is reached, so `construct:mlir-and-gpu-globals`
is no longer the first thing in the way.

**So the chain in §"The wall behind THAT" now reads:**

    comptime class attribute whose value is a computation (`_VariantStorageFor[…]`)
      ->  Variant.get_discriminant's `__mlir_op` (unchanged, now second)
        ->  Optional.or_else
          ->  builtin_slice.mojo builds
            ->  the 13 files reach their own next refusal

and the first arrow is a *value-model* question about a `comptime` class
attribute holding a non-literal — closer to this doc's own subject than the
MLIR one was, and NOT covered by anything this doc records. Anyone picking up
option 2 should measure that arrow first rather than reaching for
`__mlir_op`, which is what this doc's own text tells them to do.

What did NOT move: `Optional`'s own refusal, `builtin_slice.mojo`'s terminal
cause, and therefore the honest accounting — still 0 of the 13 files gained a
PASS. Verified on arm64 only; the x86-64 half of this doc's measurements is
from its author and I did not repeat it.

## What was measured, and what was not

* Both refusals, on arm64 and x86-64, identical text.
* The 13-file row swept before and after, per-file detail text diffed.
* That disabling the frame-holder branch yields `or_else()`, which is what
  establishes the terminal cause.
* `Optional`'s measured field list before and after, and that its one field is a
  `Variant` (`optional.mojo:182-183`).
* **NOT measured:** a full-corpus sweep delta (the integrator's), the x86-64
  answer for any file this unblocks, and whether `Variant`'s discriminator
  survives this path's own value model — that is the first thing to check when
  option 2 is picked up, and it is checkable on one file.
* **Re-measured on arm64 only** by the 2026-10-01 session above, which did not
  repeat the x86-64 half.