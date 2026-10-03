# FORMAL: a struct whose ONLY field is a nested frame cannot be compiled into a dylib, because its `__init__` is read as returning a frame

**Area:** FORMAL (the frame receiver, the receiver writeback, and the dylib
export set). Found 2026-10-03 on `work/formal10-5` while measuring the first
arrow of `bugs/FORMAL_stdlib_optional_needs_a_representation.md`. **NOT FIXED —
it belongs to whoever owns the frame/export boundary, and it is not this
session's claim.**

The whole stdlib is downstream of it: `std/builtin/builtin_slice.mojo` is
refused for exactly this, which is why `std/utils/variant.mojo` and every
`std.format` / `std.builtin.rebind` importer now stop there instead of at the
construct their own docs are about. 20+ files in
`bugs/sweeps/sweep-x86-6.txt` carry it as their `CODEGEN/DEPENDENCY` text.

## The 15-line reproducer, both shapes measured

```mojo
struct Inner:
    var a: Int
    var b: Int

struct Box1:
    var inner: Inner
    def __init__(out self, a: Int, b: Int):
        self.inner = Inner(a, b)

def mk(x: Int) -> Int:
    return x + 1
```

```
$ python3 fire.py build --formal --no-prove -o .tmp/box5 .tmp/box5.mojo
Built: .tmp/box5  [arm64/macho]                    # exit 11, prints nothing

$ python3 fire.py dylib --formal --no-prove -o .tmp/box5.dylib .tmp/box5.mojo
formal dylib: Box1___init__ returns a frame address, so it cannot be compiled
into a dylib: the returned-frame convention needs the CALLER to reserve the
block the object is built in, and an importer of this library is a compilation
this build does not perform …
```

**What was expected:** the program and the library are the same module, and the
module is ordinary Mojo. `Box1` has one field holding a two-field struct, and
its only writer is its own constructor — nothing here constructs a frame across
a boundary.

**Two shapes of the same trigger, both measured, and the difference is the
informer:**

| variant | program | dylib |
|---|---|---|
| one field written by a method that is NOT `__init__` (`self.inner = v`, `def setboth(self, v: Int)`) | builds | **builds** |
| one field written ONLY by `__init__` (`box5.mojo` above) | builds | **refused** |

The difference is `model.struct_nested_frame_fields`, which excludes every field
some method *outside* `__init__` writes (`struct_field_written_outside_init`).
In the first variant the nested frame is not PLACED, so `self` is an ordinary
word and nothing is classified; in the second it is placed, so `self` IS the
`Inner` block's address.

## The chain, all four steps verified on this tree

1. **`Box1` is a ONE-WORD struct** (one field), and its one slot holds a placed
   nested frame, so `self` and `self.inner` are the same word — the elision
   `bugs/FORMAL_one_word_struct_field_call_receiver_is_collapsed.md` measures
   and calls correct.
2. **`_apply_receiver_writeback` appends `return self`.**
   `formal/build.py:6948`: a method that mutates its receiver and returns
   nothing gets `return <receiver>` so an early exit hands the receiver back
   too, and so no path returns nothing. Correct for a one-word VALUE struct,
   where the word has genuinely changed.
3. **`_frame_return_status` reads that as a frame return.**
   `formal/build.py:5744` treats "a bare name that holds a frame address" as
   frame-valued, `self` is a holder of `Inner` from step 1, and the appended
   `return self` lands in `frames`. Measured with a scratch probe that wraps
   `_frame_return_status` and calls the same entry point
   `fire.py dylib --formal` calls:
   `Box1___init__: frame struct=Inner holder=self`. The stdlib instance reads
   `StridedSlice___init__: frame struct=Slice holder=self` — the same shape,
   with `Slice`'s three `Optional[Int]` fields.
4. **`returned_frame_library_refusal` refuses the module.**
   `formal/build.py:12313`, from `_frame_return_status` being `_RETURN_FRAME`
   on a name that is in the export set.

## Why step 3 is the wrong answer, and where the fix goes

**The appended `return self` is a NO-OP for this receiver.** The function was
handed the block's address in `self` and hands the same address back; nothing
about the returned-frame convention applies, because that convention is about a
callee that must BUILD a block in a block the CALLER reserved. Here the caller
already has the block — it is the object.

So the question the export refusal should be asking is not "does this function
return a frame address" but "does this function produce a frame the caller had
to reserve space for", and for a receiver writeback the answer is no by
construction. The place that knows is `_apply_receiver_writeback` (which is the
thing that appends the `return`) and `_frame_return_status` (which is the thing
that reads it), and the fix is one of:

* **do not append the writeback when the receiver is a frame address** — the
  value cannot have changed identity, so there is nothing to hand back; or
* **mark the appended `return self` as a writeback rather than a return**, and
  have `_frame_return_status` skip a writeback return when the name is the
  receiver.

The first is smaller and needs no new state; the second says more. Either way
the check belongs next to the code that appends the return, NOT in
`returned_frame_library_refusal`, because the export set is where the symptom
shows up and not where the classification is made — that placement is what makes
this look like a dylib problem when it is a frame-identity one.

**The related question the fix must not skip.** If a one-word struct's word is a
frame address, then a cross-module construction of it (`Box1(a, b)` from
another module) is a construction this path cannot answer either — the importer
would need the `__init__`'s body to inline, and a dylib gives it a symbol. So
dropping the export refusal for these `__init__`s without checking that would
move the failure from "this module cannot be built" to "this module builds and
the importer gets a wrong answer". The honest pair is: export nothing a caller
cannot use, and refuse the cross-module CONSTRUCTION by name at the import site.
Whether that second refusal is wanted is a decision, not a measurement.

## Blast radius, measured where it is cheap

* `std/builtin/builtin_slice.mojo` is refused, and with it every importer of
  `std.format._utils` / `std.builtin.rebind` — `bugs/sweeps/sweep-x86-6.txt`
  carries the text on 20+ `CODEGEN/DEPENDENCY` rows.
* This session's own chain: `variant.mojo` and `builtin_slice.mojo` both stop
  here on arm64 AND x86-64, which is worth stating because the refusal is raised
  by the BUILD PASS (arch-free classification) even though `fire.py dylib
  --formal` only builds an arm64 dylib — so the classification that causes it is
  the same on both architectures and the export table is simply not built for
  x86-64.

## Reproducing

```
python3 tools/memslot.py --gb 8 --label b5 -- \
    python3 fire.py build --formal --no-prove -o .tmp/box5 .tmp/box5.mojo
python3 tools/memslot.py --gb 8 --label b5 -- \
    python3 fire.py dylib --formal --no-prove -o .tmp/box5.dylib .tmp/box5.mojo
```

`--no-prove` matters: `fire.py dylib --formal` runs the Lean check by default,
and the proof of a library this size takes 2.7 GB and does not finish inside the
session (measured here: killed after printing an unsolved-goal dump, which is a
different bug and not this one).
