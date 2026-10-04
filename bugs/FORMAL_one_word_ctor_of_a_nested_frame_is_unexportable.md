# FORMAL: a struct whose ONLY field is a nested frame cannot be compiled into a dylib, because its `__init__` is read as returning a frame

**Status, 2026-10-03 (`work/formal13-5`): §"Why step 3 is the wrong answer" is
FIXED and the doc's reproducer turns out to be the half that is RIGHT. The
refusal stays for the shape below and goes for the shape next to it; the two
differ in one line of source, and only one of them is a real escape.**

**Area:** FORMAL (the frame receiver, the receiver writeback, and the dylib
export set). Found 2026-10-03 on `work/formal10-5` while measuring the first
arrow of `bugs/FORMAL_stdlib_optional_needs_a_representation.md`.

## 0. What landed, and what it says about this document's own claim

The write-back `_return_the_receiver` appends is now TAGGED, and both readers of
the tag agree on what a tag means:

| | where | what |
|---|---|---|
| the tag | `formal/build.py::_return_the_receiver` | every `return` it creates or fills in carries `_receiver_writeback`; it is the only place that knows which returns it made, because one-field mutators are the only functions that get an appended `return` at all |
| the rebinding test | `_writeback_rebound_receivers` | the receiver is REBOUND in this body — asked AFTER `_rewrite_self_fields`, which is what makes it the honest question: a store THROUGH the receiver and a rebinding of it are the same assignment by then |
| reader 1 | `_frame_return_status` | a tagged return of an UNREBOUND receiver is not a frame return, so the dylib export refusal does not fire |
| reader 2 | `_check_frame_escapes` | …and it is not an ESCAPE either: the caller already held that block |

Measured, both classifications, on the two constructors that differ in one line:

| constructor | before | after |
|---|---|---|
| `self.inner.a = a` — writes THROUGH the caller's block | refused twice: "returns a frame address, so it cannot be compiled into a dylib", and once that was out of the way "a Inner receiver is returned from a method of Box1, which did not create the frame" | **the dylib builds** |
| `self.inner = Inner(a, b)` — ASSIGNS a frame to its own one word, which the elision makes a rebinding | refused | **still refused**, with the same sentence |

The second sentence of the first row is the one worth keeping: it was the escape
check refusing its own convention, and it named a frame the CALLER created and
still owns.

**So this document's central claim is half wrong, and the measurement is what
says so.** §"Why step 3 is the wrong answer" argues that "the appended
`return self` is a NO-OP for this receiver" for the reproducer at the top of this
file. It is a no-op only when the body WRITES THROUGH. For this document's own
reproducer — `self.inner = Inner(a, b)` — `_rewrite_self_fields` collapses the
store onto `self` BEFORE `_frame_return_status` runs, so the callee really does
bind a frame it built itself and really does hand back its address. **That is an
escape and the refusal is right**, and a fix that took the doc's advice would have
exported a function whose returned word points into a dead frame. The rule that
replaces the doc's advice is the one in the table above: a write-back is not a
frame return unless the receiver was rebound.

**What the doc's §"The related question the fix must not skip" asked for is
therefore already answered, by a refusal that predates all of this.** A
cross-module construction of such a struct is refused BY NAME at the
construction site, on both architectures, for the body this path cannot inline:

```
build: constructing Box1 with arguments is a call to a user-defined `__init__`
whose body this path does not inline: `Inner(…)`, a construction of a struct
whose receiver is a frame … OR `a local assignment (`self.inner.a = …`)` …
so what it needs from the body is that it IS a sequence of those
```

So there is no window in which an importer gets a wrong answer: the export
exists, and the only construct that would consume it is refused before it is
lowered. Whether that refusal should become a *by-name* cross-module refusal
rather than a construction-inlining one is a decision, and it is recorded below
rather than taken.

**`std/builtin/builtin_slice.mojo` is still refused, and now for the right
reason.** `StridedSlice.__init__` is `self._inner = Slice(start, end, stride)` —
the ASSIGNING shape — so it is a real returned frame and this change does not
unblock it. The 20+ `CODEGEN/DEPENDENCY` rows in `bugs/sweeps/sweep-x86-6.txt`
that carry its text keep carrying it. Unblocking it needs the by-reference
construction convention (`bugs/FORMAL_wide_receiver_by_reference.md`), not a
classification change.

## 1. What was here before this update

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
   `FORMAL_one_word_struct_field_call_receiver_is_collapsed` measures
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

> **Answered 2026-10-03, and the pair already holds.** The cross-module
> construction is refused by name today, on both architectures, with a sentence
> that names the body it cannot inline (`constructing Box1 with arguments is a
> call to a user-defined `__init__` whose body this path does not inline: a local
> assignment (`self.inner.a = …`)`). §0's change therefore exports a symbol with
> no consumer that can reach it, rather than exporting a wrong answer. The
> decision left open is whether the refusal should be re-spelled as a
> cross-module refusal, which would be a message change and not a behaviour one.

## Status 2026-10-03: the mechanism this doc's chain runs through is GONE, and the reported refusal with it — measured on `work/formal15-mutator-return-abi` (`11558f0d`)

**Steps 2, 3 and 4 above cannot happen any more, and the reproducer's DYLLIB
builds.** `formal/build.py`'s `_return_the_receiver` — the thing that appended
`return self` — and `_apply_receiver_writeback` are both DELETED, replaced by a
receiver handed over BY REFERENCE: a one-field struct's mutating method receives
the ADDRESS of its caller's one-word cell and writes the receiver back through it
on every exit (`formal/model.py`'s `receiver_writeback_name`, unchanged in name
and changed in mechanism). There is no appended return to read as a frame return,
so `_frame_return_status` has nothing to misread and
`returned_frame_library_refusal` never fires for this shape:

```
$ python3 fire.py dylib --formal --no-prove -o .tmp/box/box5.dylib .tmp/box/box5.mojo
Built: .tmp/box/box5.dylib            # at 17ddeaec: "Box1___init__ returns a
                                      # frame address, so it cannot be compiled
                                      # into a dylib: …"
```

**The doc is NOT deleted, because its blast radius is measured still standing and
it now stops somewhere else.** `std/builtin/builtin_slice.mojo` still does not
build, on both architectures, on a DIFFERENT refusal:

```
build: builtin_slice.mojo imports 'std.format._utils', which cannot be built
either: builtin_slice.mojo: self is assigned other in StridedSlice___init__(),
and self is this method's receiver, so it is the address the CALLER passed
rather than a name either side can re-declare …
```

which is `bugs/FORMAL_one_field_receiver_rebound_propagates.md` — the RECEIVER
REBIND, not the write-back. So of this doc's two subjects, the dylib export half
is closed by the convention change and the rebind half is somebody else's open
doc.

**The "related question" above is answered, and by measurement rather than by
policy.** A cross-module CONSTRUCTION of such a struct is refused BY NAME at the
construction site on both architectures — `constructing Box1 with arguments is a
call to a user-defined __init__ whose body this path does not inline …` — so
exporting the symbol opens no window in which an importer gets a wrong answer.
That is the pair this doc asked for (export nothing a caller cannot use; refuse
the cross-module construction at the import site), and it now holds without
anyone deciding the question on paper.

**Read this before merging `work/formal13-5` onto that branch.** Its commits
`84c6f663` / `25653c86` are entirely about the appended `return self` — tagging
it `_receiver_writeback`, teaching `_check_frame_escapes` and the export gate not
to read it as a frame return or escape, and `_writeback_rebound_receivers`
asking whether the body rebound the receiver. The first two have no producer left
to classify and should be dropped rather than reconciled; the third still has a
subject, because the rebind refusal above is live and is a DIFFERENT fact from
the write-back.

## Blast radius, measured where it is cheap

* `std/builtin/builtin_slice.mojo` is refused, and with it every importer of
  `std.format._utils` / `std.builtin.rebind` — `bugs/sweeps/sweep-x86-6.txt`
  carries the text on 20+ `CODEGEN/DEPENDENCY` rows. **Unchanged by §0**: its
  constructor is the ASSIGNING shape, so it is a real returned frame.
* The WRITE-THROUGH shape now builds as a dylib, and the cost of that is one
  new case in `test_formal_dylib.py` (`a receiver write-back is not a returned
  frame`), which asserts both directions: that the write-through library is
  written and that the assigning one is still refused with its own sentence.
  **Re-measured 2026-10-04: that case is RED on `master` (`86d60026`), and only
  its second assertion.** `python3 test_formal_dylib.py` → `PASS=22 FAIL=1`, and
  the failure is verbatim "a constructor that ASSIGNS a frame to its own one word
  was built as a dylib: the frame it hands back is one the CALLEE built, and an
  importer has no way to learn the width of the block it must reserve". So the
  first assertion (the write-through library IS written, and exports `mk`) holds
  and the refusal the paragraph above says is right does not fire — which is the
  remaining half of this doc's subject and nothing to do with the export-gate
  work in `formal/imports.py` measured on the same day. The classification to
  look at is `_frame_return_status` / `returns_frame` in `formal/build.py`
  (`_return_the_receiver` is gone, so the one-word receiver now travels BY
  REFERENCE and the rebind has to be recognised from the constructor's own body
  rather than from an appended `return self`). Not measured on x86-64: this test
  file skips off arm64.
* This session's own chain: `variant.mojo` and `builtin_slice.mojo` both stop
  here on arm64 AND x86-64, which is worth stating because the refusal is raised
  by the BUILD PASS (arch-free classification) even though `fire.py dylib
  --formal` only builds an arm64 dylib — so the classification that causes it is
  the same on both architectures and the export table is simply not built for
  x86-64.

## What is still open here

1. **`std/builtin/builtin_slice.mojo`**, which is the whole of the blast radius
   above. Its `__init__` assigns a frame to its own one word, so the only fix
   left for it is the by-reference CONSTRUCTION convention — the callee builds
   the frame in the block the CALLER reserved instead of in its own — and that
   is `bugs/FORMAL_wide_receiver_by_reference.md`, another lane's design
   question.
2. **A related crash in the same family, filed separately** because it is not a
   dylib question at all:
   `FORMAL_one_word_struct_of_a_frame_field_is_constructed_as_a_null_word`
   — `Box1()` gives the one word ZERO, so the first field access through it is a
   load from address 0 (SIGSEGV on both architectures), and the same tree holds a
   two-backend disagreement about a one-field mutator whose receiver is a frame
   address.

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
