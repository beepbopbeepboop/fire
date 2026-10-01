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

## The next step (as originally written)

Answer that question in `FORMAL_wide_receiver_by_reference.md` — the field
representation, frame-address or inline-copies — and both shapes fall out of it,
because both refusals are the analysis declining to guess. Until it is
answered, the honest summary for the sweep is the row itself: **13 files, 0 of
which name anything `builtin_slice.mojo` declares, blocked on a two-field
`Optional` in a stdlib struct's field list.** `std/utils/_nicheable.mojo` is one
of the 13, which is worth noting for whoever takes it: the module that would
express "an absent value in one word" is itself behind the same wall.