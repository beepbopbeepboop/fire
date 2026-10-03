# FORMAL_a_dict_field_of_a_module_level_frame_still_has_no_key_kind: the frame gives the field a VALUE; the subscript still needs to know it is a DICT

**Status: OPEN, not fixed — but the reason it was refused is now GONE for
exactly one shape, and this document is the measurement of what that leaves.
Found 2026-10-03 while landing the formal module-frame-slot work
(`work/formal15-module-slot-lifetime`), which is the change that discharged
premise (B2) for a module-level `X = Struct(...)`.**

## The predecessor, and what it said

`bugs/FORMAL_a_dict_subscript_has_no_value_kind.md` §"The field spelling, and
why it stays refused" is explicit about the field case:

> The sweep's three files are `len(self.sections["text"])` where
> `self.sections: dict[str, bytearray]` is a **declared field**. That is
> refused, and correctly: `S()` does not run `__init__` on this path (premise
> B2), so a fresh instance's slot holds the class-level default, and a field
> with no default is a word of zeros — so `len` of that subscript is a count
> read from address 0.

and it names what was missing as *not* the kind:

> The missing thing there is not the kind: it is a dict FIELD with a value at
> all, which is the module-global storage question
> (`bugs/FORMAL_module_state_no_storage.md`).

Both halves of that sentence are now one step further along, and only for the
module-level shape.

## What changed underneath it

`formal/model.py`'s `module_frame_slot_initializer` (with `prepare_module_frame_slots`
and the new `("frame", struct, words)` `GlobalSlot` initializer kind) builds a
module-level `X = Struct(...)` in `__DATA` and gives each slot the word
`__init__` assigns. So for

```mojo
struct Loader:
    var seen: Dict[String, Int]
    var hits: Int

    def __init__(self):
        self.seen = {}
        self.hits = 0
    …

_loader = Loader()
```

`_loader`'s frame slot 0 is a pointer to a laid-out empty pair blob in the image,
not a zero, and it stays that way for every reader in the process. Premise (B2)
— "a struct that declares no `__init__` has no body to run" — is what it rested
on, and it is discharged here. **This is what `ModuleLoader` in
`module_loader.py` needs**: three empty dicts, which is why the two-kinds-of-value
refusal on that file is gone and its next wall is a module-level `os.path` read
instead.

## What is still refused, measured

Two shapes, and the second is the honest limit of this document.

**1. `self.<dict field>[k]` inside a method — still refused, and it is NOT
about premise (B2) any more.** Reproducer (arm64, both backends, this tree):

```mojo
struct Loader:
    var seen: Dict[String, Int]
    var hits: Int

    def __init__(self):
        self.seen = {}
        self.hits = 0

    def put(self, k: String) -> Int:
        self.seen[k] = self.hits + 1
        self.hits = self.hits + 1
        return self.hits

_loader = Loader()

def add(k: String) -> Int:
    return _loader.put(k)
```

    build: `self.seen[k]` cannot be lowered: the INDEX is a string and nothing in
    the source says what `self.seen` holds. On this path a string index is either
    a dict KEY scan — `d["a"]`, the value under the key — or a byte offset into a
    `char *` (`s[0]`), and which one it is comes from the BASE, which here is
    unstated.

**Measured as independent of the module-frame work**: the same refusal fires with
the struct built as a plain local, `var l = Loader(); l.put("a")`, with no module
global anywhere in the file. So this is the frame FIELD's dict-ness, and
`ValueKinds`'s `slot_key`/`_declared_kind` path does not reach it. The
annotation `Dict[String, Int]` is right there in the source and is not read,
which is what the message's "nothing in the source says" is true about and its
"the source says nothing" would not be.

**2. `len(self.<container field>)` — still refused, and this one IS premise
(B2).** `_frame_slot_blob_refusal`'s own words are still correct for every
receiver that is not a module-level frame: `frame_slot_value_refusal` is asked
of the field's DECLARED type with no access to which FRAME `self` is, and a
method can be reached with a local `Loader()` whose slots are zeros whatever the
static one holds. Answering it needs a whole-image fact this pass does not have:
*every* call of *every* method that reads the field hands it the module-level
frame. That is a reachability question with three answers (all callers, some
callers, none) and no partial one, and the middle answer is the SIGSEGV.

So the ladder for a container field on this path is: (a) the field's VALUE,
which this work supplies for a module-level frame; (b) the field's dict-vs-
sequence KIND, which shape 1 above needs and is missing for any frame; (c) the
whole-image fact that discharges premise (B2) for a `len` on it, which is shape 2
and is the largest of the three.

## The next step, exactly

Start at (b), because it is a capability and (c) is a project:

* `formal/arm64_codegen.py`'s `_declared_kind_for` already has the FRAME-SLOT arm
  ("`h.<field>` is a load at `base + 8k` out of a frame whose layout
  `formal/build.py` settled, so the holder's candidate structs are the
  declaration, and the agree-or-refuse in `model.frame_slot_field_kind` is what
  says they agree"), and `formal/types.py::DICT_TYPE_NAMES` is already the shared
  vocabulary. What it does not do is carry the dict-ness half the way it carries
  the KIND half — `global_slot_is_dict` exists for a module global for exactly
  that reason ("a kind cannot say dict", because all four container annotations
  are one word here), so the frame field needs the same separate boolean over
  `struct_field_declared_type(field)`.
* A `LIST`-annotated frame field already works, which is the control and the
  proof that the missing half is only the dict one:
  `self.items[i]` with `var items: List[Int]` assigned `[1, 2, 3]` in `__init__`
  reads `1` and `3` correctly on both architectures from a module-level frame
  (`test_formal_globals.py::frame_global_with_a_container_field`).

Do (b) before (c), and do not widen (c) to a heuristic: "the annotation says
`Dict`" is not enough, because the difference between the two shapes is whether
the key is a string, and that is a question about the subscript's index, which
`FORMAL_a_dict_subscript_has_no_value_kind.md`'s per-key gate already answers for
a literal. Reusing THAT gate — including its refusals — is what keeps a dict
field's subscript from becoming a plausible wrong number where the local's
refuses.