# A struct-typed FIELD cannot be initialised from an argument, and a struct PARAMETER cannot be stored in one

**Area:** FORMAL (the wide-receiver family; struct-typed fields). Found
2026-10-01 on `work/formal-re-refusal` while working the `other refusal` row of
the x86-64 sweep. **NOT FIXED, and not a one-construct change** — but the
boundary is now measured rather than described, which is what the next person
needs.

## What was run, and what it says

**The 13-file row.** `tools/formal_sweep_causes.py --min 4 .tmp/sweep-x86-4.txt`
puts 13 files behind `builtin_slice.mojo`, and

    uses: 0 of 13 blocked by builtin_slice.mojo name anything it declares
           [the refusal is about the import CLOSURE, not about these files]

`builtin_slice.mojo` itself is refused identically on both architectures:

    $ for a in arm64 x86_64; do python3 fire.py build --formal --no-prove \
        --backend=$a -o .tmp/sl ../new-modular/Mojo/stdlib/std/builtin/builtin_slice.mojo; done
    build: a Optional receiver is stored in the field 'self.start', so it
    outlives the frame it names by however long that object lives: the slot
    belongs to the function that created THAT frame, and nothing here can say
    the two lifetimes agree on this path: the receiver of a multi-field struct
    is the ADDRESS of a frame of 8-byte slots that belongs to the function
    which created it, so it can only be read, written, copied, or passed as a
    method's receiver. bugs/FORMAL_wide_receiver_by_reference.md records the
    design and what is still open about it

Raised by `formal/build.py:4290-4299` (`_refuse_holder_use`, the
`AssignStmt(MemberExpr, IdentExpr)` arm). `struct Slice`
(`builtin_slice.mojo:40-45`) is three `Optional[Int]` fields and its second
`__init__` (`:64-81`) stores the caller's `start` into `self.start`.
`Optional[Int]` is two fields, so on this value model it is a FRAME, and
`start` is that frame's address — the caller's scratch.

**The wall behind it, in twelve lines, with no stdlib involved.** The refusal
above is about the ctor body; the thing that makes the row unfixable is one
step earlier, and it has its own message:

    struct Opt:            # two fields, so a frame here
        var v: Int
        var has: Int

    struct Box:
        var inner: Opt
        def __init__(out self, o: Opt):
            self.inner = o

    def main() -> int:
        var o = Opt()
        var b = Box(o)          # <-- HERE
        printf("v=%d", b.inner.v)
        return 0

    $ python3 fire.py build --formal --no-prove --backend=arm64 widefield2.mojo
    build: constructing Box with argument 'o' as field 'inner' is refused on
    this path: 'inner' is declared as a Opt, a struct of this module whose
    receiver is a frame of 8-byte slots, so the constructor PLACED a Opt frame
    in that slot and in the object's own block — a word stored over it would
    leave a value where every read of `self.inner.…` computes a frame base from
    it. Assign the field after `Box(…)`, which is the same program and is the
    form the placement's own write-once rule already anticipates

**And the workaround the message names actually works.** Same module, the field
assigned after construction instead of through the argument:

    struct Box:
        var inner: Opt
        def __init__(out self):
            self.inner = Opt()

    def mk(v: Int) -> Opt:          # returns a frame: a legal return here
        var o = Opt()
        o.v = v
        o.has = 1
        return o

    def main() -> int:
        var b = Box()
        b.inner = mk(41)
        printf("v=%d h=%d", b.inner.v, b.inner.has)
        return 0

    $ python3 fire.py build --formal --no-prove --backend=arm64 widefield4.mojo
    Built: .tmp/wf4  [arm64/macho]
    $ .tmp/wf4
    v=41 h=1

So a struct-typed field is not unimplementable on this value model: a frame
returned by a callee, stored into a field of another frame, and read back
field-by-field, all work and give the right answer. What is missing is exactly
two shapes:

  1. **initialising** such a field from a constructor ARGUMENT (the message
     above, which names its own workaround); and
  2. **storing a struct PARAMETER** into a field inside a method — the shape
     `Slice.__init__` has, and the 13-file refusal. Isolating that one needs a
     method whose parameter it can be reached with, and doing so runs into the
     NEXT gap in the chain: passing a frame-returning call (`b.set(mk(41))`) to
     a parameter declared as a struct is itself refused —
     `Box_set() declares 'o' as Opt, so it is compiled with 'o' as the ADDRESS
     of a frame … every call site in this image hands it something else:
     Box_set(b, mk(41)) passes a call to 'mk'`.

## Why it is not closed here

`bugs/FORMAL_wide_receiver_by_reference.md` drove the 153 findings that named
its own diagnostic to zero and lists three `model.frame_return_*` messages as
still refused. Neither of the two shapes above is in that list, so this is
additional open ground in that design rather than a restatement of it — and the
design decision it needs is the one the doc has not made: **what a
struct-typed field is.** Two answers, and they are not equivalent:

  * **the frame address** (what the workaround above stores, and what
    `b.inner = o` does today). Cheap, already works, and needs the write-once /
    lifetime discipline the message refers to to be complete: the field holds a
    pointer into whatever frame produced the value, and nothing at the store
    says whether that frame outlives the object. Assigning from a LOCAL is
    analysable; assigning from a PARAMETER is not, which is the 13-file
    refusal.
  * **a copy of the words, in the object's own block** (what the constructor
    message says it tried and why a later word store would corrupt it). This is
    the representation that makes an argument-initialised field sound, and it is
    a layout change: the field stops being one slot and becomes N.

## Status, 2026-10-01 (`work/formal2-re-and-slice`): the DERIVATION is fixed; the row's terminal cause is not this

The frame-holder refusal itself was real, and it was a SYMPTOM. Measured on
`bd757a63`:

* `Optional` measured **2** fields because its second "field" was its private
  method `_write_to` — counted by `formal/model.py`'s derived-field walk, which
  exempts `self.m()` but not `self.m[T]()`. `Optional` is a ONE-word value
  (`struct_is_one_field`), so every `Optional` receiver was being treated as a
  frame address. **That is fixed**: 31 structs across the stdlib and this
  repository have a narrower field set, 30 of them for exactly this reason, and
  the 13-file census drops from 33 structs-in-29-files to 3 (the three being the
  sibling VALUE-position shape, deliberately untouched).
* **But the row did not move.** `builtin_slice.mojo` now refuses with
  `self.step.or_else() is an Optional unwrap`, which is what its 13 dependents
  already reported, and re-sweeping all 13 before and after shows them
  unchanged: **0 gained a PASS.** So this doc's headline was measuring one step
  removed from the terminal cause, which is what its own text hints at when it
  says the row is "blocked on a two-field `Optional` in a stdlib struct's field
  list" — the two fields were not the blocker, the unwrap is.

The refusal's own next step (answer "what a struct-typed field is") turns out not
to be the question either: the field representation this doc asks about is
**frame address vs inline copies**, and for `Slice.start: Optional[Int]` neither
is needed, because `Optional` is one word. The real question is a
representation for `Optional` ITSELF, which is
`bugs/FORMAL_stdlib_optional_needs_a_representation.md`, and that doc measures
one layer further down again — the unwrap's tag lives in `Variant`, which reaches
it through `__mlir_op`, which this path refuses. **Keep this doc for the
measurement that made the derivation question visible; the next step is the
other one.**

## Status, 2026-10-01 (`formal3-2-r2`): shape 2's own next-step blocker is GONE

The "Why it is not closed here" section names, as the thing standing between
this doc and shape 2, a gap one step further in: passing a frame-returning call
(`b.set(mk(41))`) to a parameter declared as a struct was itself refused.
**That gap was a dead recognition** — `_check_holder_agreements` was handed the
identity-keyed `returns_frame` and passed it to `model.frame_returning_predicate`,
whose contract is `(callee_name, bound_name)`, so every lookup missed and
`_frame_valued_calls`' frame-returning half never fired. One argument, and the
shape works:

    struct Opt:                       # two fields, so a frame
        var v: Int
        var has: Int

    def peek(o: Opt) -> Int:          # declares a frame parameter
        return o.v * 10 + o.has

    def mk(v: Int) -> Opt:            # RETURNS a frame
        var o = Opt();  o.v = v;  o.has = 1;  return o

    def main(n):  return peek(mk(4))  # → 41, CPython's answer

Pinned as four cases in `test_formal_run.py`
(`declared_frame_parameter_given_a_frame_returning_call` and three others,
including the guard that a WORD beside the returned-frame call still refuses).
`test_formal_method_param_field.py` went 16 PASS / 2 FAIL → 18 / 0 on it.

**Shape 2 itself is still refused, and the refusal has moved one layer along —
onto the answer this doc says is the open design question.** With `Box.set` now
reachable, `b.inner.v` reads through `b.inner`, whose agreed declared type is a
framed `Opt`, but `Box.set` ASSIGNS that field — so it is `_REASSIGNED` ("the
word in the slot is a frame belonging to whichever function ran the
assignment"), which is the lifetime half of the same "what is a struct-typed
field" question and not a recogniser gap. It takes the answer "the frame
address, with the write-once discipline the message already names" and is a real
program; it takes "a copy of the words in the object's own block" and is a
layout change. Neither is decided here, which is what this doc has consistently
said.

Shape 1 (initialising the field from a constructor ARGUMENT) is unchanged and
still says "a word stored over it would leave a value where every read of
`self.inner.…` computes a frame base from it" — the same question, asked at the
construction rather than at the store.

So the row's terminal cause is unchanged from the section above it:
`FORMAL_stdlib_optional_needs_a_representation` (formal3-7's claim), one layer
below this one. What this session removed is the step between here and the
question.

## Status, 2026-10-02 (`formal3-2-r2-r2`): the `_REASSIGNED` reading above is
WRONG, and the wall is one layer UP, in a receiver this doc never named

The paragraph above says shape 2 is refused as `_REASSIGNED` and that the
question is therefore "what a struct-typed field is". Re-measured on this tree,
neither half is true, and both are worth recording because the row's terminal
cause is now named rather than described.

**Shape 2's own method does not even reach the store.** `struct Box` with the
single field `var inner: Opt` is a ONE-FIELD struct, so `Box`'s receiver IS its
field and `self` is a word holding the ADDRESS of an `Opt` frame — there is no
`Box` storage to speak of and no representation decision to make. The store
`self.inner = o` rewrites to `self = o`, but the refusal comes earlier, on the
READ in the other method:

    build: Box_get: 'self.v' is a field access through 'self', and this path
    has no way to say what 'self' holds. …

`'self.v'` is not in the source (`self.inner.v` is), and "this path has no way
to say" is false: `_frame_receivers` has no case for seeding a method receiver
whose owner is a one-field struct, which is the only shape in which a receiver
is a frame and its owner is not.

**The boundary is the holder's OWN field count, measured.** The same `Opt`/`Box`
body builds and runs correctly — 155 on both architectures, and 155 is `41*10+1`
— with `var pad: Int; var inner: Opt` (two fields, so `self` is a `Box` frame
whose slot 1 is the `Opt` address), and is refused with `var inner: Opt`
(one field). The LOCAL half already works: `b.inner.v` in `main`, with `Box()`
one field, builds and returns 41 on both.

**So the two halves of this doc are not the same wall.** Shape 1 (the
construction) is still the question this doc has always said it is. Shape 2 (the
store) is behind a RECEIVER SEEDING, one layer up, and the fix for that layer
is not safe to land alone — measured, it turns the store case from a refusal
into a SIGSEGV. The measurement, the reproducer, and the order the two checks
have to land in are in
`FORMAL_one_field_holder_of_a_frame_is_not_a_holder`; read that one for
shape 2 and this one for shape 1.

## Status, 2026-10-03 (`formal10-2`): the recorded terminal cause was ONE layer
## too deep, and shape 1's boundary now has a test

Two measurements, neither of which re-verifies anything the sections above say.
The first corrects a pointer that is sending the next reader the wrong way; the
second turns a promise the refusal message makes into something that is checked.

**The row no longer stops where this document's last section says it does.** It
says the terminal cause is `FORMAL_stdlib_optional_needs_a_representation` — the
`self.step.or_else()` unwrap, whose tag lives in `Variant`. Measured on this
tree, `builtin_slice.mojo` is refused **earlier**, identically on both backends:

```console
$ for a in arm64 x86_64; do python3 fire.py build --formal --no-prove \
      --backend=$a -o .tmp/sl ../new-modular/Mojo/stdlib/std/builtin/builtin_slice.mojo; done
build: builtin_slice.mojo imports 'std.format._utils', which cannot be built
either: builtin_slice.mojo: StridedSlice___init__ returns a frame address, so
it cannot be compiled into a dylib: the returned-frame convention needs the
CALLER to reserve the block the object is built in, and an importer of this
library is a compilation this build does not perform
```

That is `model.dylib_frame_return_refusal`, and it is
`bugs/FORMAL_wide_receiver_by_reference.md`'s ("a frame-returning function
offered at a module boundary: the hidden word is a property of ONE image's
calling convention"). So the chain is now `dylib_frame_return_refusal` →
`StridedSlice___init__` returns a frame → and only then, one layer below that
and two layers below where this document pointed, the `Optional` unwrap. Both of
those are other claims. **Nothing here is a `formal/` change on the struct-field
path any more**, and a reader who starts at the `Optional` document is starting
two layers from the refusal they will actually meet.

Note what the message says about the fix direction, because it is the same
shape as the answer to this document's own question: the returned-frame
convention hands the caller a block to reserve, and a module boundary has no way
to say which exports take one. `FORMAL_wide_receiver_by_reference.md` owns that.

**Shape 1 is unchanged, and what the refusal is actually about is sharper than
"what is a struct-typed field".** Measured on both backends: `Box(o)` with
`self.inner = o` is refused with the message quoted in §"What was run"; the
workaround the message names, `b.inner = mk(41)`, builds and prints `v=41 h=1`
on arm64 and x86-64. The pair differs in ONE thing — **where the frame comes
from.** `Box(o)` stores the CALLER's frame through the object, and a frame
parameter outlives whatever the constructor does with it, so nothing at the
store can say the two lifetimes agree; the working form stores a frame the
CALLEE created, which the caller owns for the whole expression. So the
obstacle in shape 1 is the assignment-from-a-parameter half of this document's
own two-way question, and the two candidate answers it lists do not change it:
the frame address needs the lifetime discipline the message names, and inline
copies are a layout change.

**And the classifier is not over-refusing.** `struct Word: var only: Int` — a
ONE-field struct, so a WORD and not a frame — initialised from a constructor
argument builds and prints `42` on both backends. Without that measurement the
refusal reads as "a struct field from an argument is refused", which is false,
and the next reader files the false version.

All three are now cases in `test_formal_method_param_field.py` — the refusal
with its exact wording, the workaround with a CPython oracle, and the one-field
boundary — because the refusal message's advice is a PROMISE to the reader and a
promise nobody checks is how a refusal sends readers after a non-bug. That is
the failure mode this family documents itself as existing to prevent, and the
message here names a specific alternative spelling, so the alternative has to
keep working for the message to keep being true.

## The next step (as originally written)

Answer that question in `FORMAL_wide_receiver_by_reference.md` — the field
representation, frame-address or inline-copies — and both shapes fall out of it,
because both refusals are the analysis declining to guess. Until it is
answered, the honest summary for the sweep is the row itself: **13 files, 0 of
which name anything `builtin_slice.mojo` declares, blocked on a two-field
`Optional` in a stdlib struct's field list.** `std/utils/_nicheable.mojo` is one
of the 13, which is worth noting for whoever takes it: the module that would
express "an absent value in one word" is itself behind the same wall.