# A one-word struct whose only field holds a frame is constructed as a NULL word, and both backends then fault

**Area:** FORMAL (`formal/model.py`'s `struct_default_word`, and
`formal/{arm64,x86_64}_codegen.py`'s `_emit_fresh_one_word`). **Status: OPEN,
not fixed — it needs a prologue reservation this branch is not making.** Found
2026-10-03 on `work/formal13-5` while measuring
`bugs/FORMAL_one_word_ctor_of_a_nested_frame_is_unexportable.md`, whose §"Two
shapes of the same trigger" calls the variant below "builds" and is right only
about the exit status.

## 1. It builds, and it dies of SIGSEGV on both architectures

```mojo
struct Inner:
    var a: Int
    var b: Int

struct Box1:
    var inner: Inner
    def setboth(out self, a: Int, b: Int):     # the only reason `inner` is a
        self.inner.a = a                        # frame at all: without a method
        self.inner.b = b                        # that writes it, nothing here
                                                # nests
def main() -> Int32:
    var bx = Box1()
    bx.inner.a = 1
    bx.inner.b = 2
    bx.setboth(7, 8)
    printf("a=%d b=%d", bx.inner.a, bx.inner.b)
    return 0
```

```
$ python3 fire.py build --formal --no-prove --backend=arm64  -o bx.a  bx.mojo
Built: bx.a  [arm64/macho]        $ ./bx.a
Segmentation fault: 11            exit 139
$ python3 fire.py build --formal --no-prove --backend=x86_64 -o bx.x  bx.mojo
Built: bx.x  [x86_64/macho]       $ ./bx.x
Segmentation fault: 11            exit 139
```

CPython prints `a=7 b=8`. So this is a program that compiles to an image which
dies at the first field access, with no diagnostic anywhere — the failure mode
`bugs/FORMAL_known_limits.md` opens the queue for.

## 2. Why: the one word is a frame ADDRESS and the construction gives it zero

* `Box1` is a ONE-FIELD struct, so its receiver IS its sole field's storage and
  that storage is an address (`model.one_word_sole_field_frame` — measured on
  this tree: `one_word_sole_field_frame(Box1, decls)` is `Inner`).
* `bx.inner.a` therefore lowers to a load at `[word + 8·slot]`, which is right.
* `Box1()` is a fresh one-word construction, and `struct_default_word(Box1)`
  answers `("none", None)` — "no class-level initializer, so a fresh word of
  zeros is right". Measured:

      >>> M.struct_default_word(Box1)
      ('none', None)
      >>> M.one_word_sole_field_frame(Box1, decls)
      StructDef(name='Inner', …)

  **Both are true answers to different questions and together they are a null
  pointer**: the word is a frame address, and the thing put in it is 0.
  `_emit_fresh_one_word` then emits `mov X0, #0` and every field access through
  it is a load from address 0.

The same `("none", None)` is correct for every other one-field struct — the rule
itself says "a fresh word of zeros is right" for a field with no value, and for
`x: Int` it is. It is the frame-valued field the rule has no answer for.

## 3. It is NOT the receiver-rebind or field-access refusals, and the two shapes that DO get refused

| variant | arm64 | x86-64 |
|---|---|---|
| no method writes `inner`, then `bx.inner.a = 1` | refused: `'bx.a' is a field access through 'bx'` | same |
| `bx.inner = i` (a frame built by the caller) before any read | `a=5 b=6` | `a=5 b=6` |
| `bx = Box1()` then a mutator writes `self.inner.a` | **SIGSEGV** | **SIGSEGV** |
| a two-field struct (`var inner: Inner` + `var tag: Int`), same body | `a=3 b=4` | `a=3 b=4` |
| `Box1()` then a mutator that also got a frame assigned first | `a=9 b=6` | **SIGSEGV** |

Read the second row against the first: **the shape that works is the one that
never reads through the null word**, and the row below it differs only in that a
mutator is called. So a `Box1()` that is written into before it is read is fine
and one that is read is a segfault — which is exactly the "answer depends on
what comes next in the function" property no refusal can have and no correct
lowering can have either. **That is the argument for fixing the construction
rather than the access: the access is a correct lowering of a word the
construction filled with zero.**

The last row is a second defect and a worse one, because it is a two-backend
disagreement about a program that has a representation (§4).

## 4. `bx.touch(9)`: arm64 right, x86-64 SIGSEGV

```mojo
struct Inner:  var a: Int;  var b: Int
struct Box1:
    var inner: Inner
    def touch(out self, x: Int):
        self.inner.a = x
# main: bx = Box1(); i = Inner(); i.a = 5; i.b = 6; bx.inner = i; bx.touch(9)
#       printf("a=%d b=%d", bx.inner.a, bx.inner.b)          CPython: a=9 b=6
```

```
arm64    a=9 b=6   exit 0        # right
x86-64   Segmentation fault: 11   exit 139
```

**One program, two architectures of one language implementation, two different
verdicts** — which is the failure this project treats as worse than either
answer alone. The shape is a one-field mutator whose receiver is a FRAME
ADDRESS, i.e. `receiver_writeback_name` is not None, the method stores through
the address, and the caller stores the returned word back over its own binding.
`bugs/FORMAL_x86_64_a_field_of_a_returned_frame_in_an_argument_position_
segfaults.md` (claimed by another lane) is about a field of a returned frame in
an ARGUMENT position; this one is the write-back path and is not that doc, so
whoever owns the x86-64 receiver should check this reproducer against it before
filing a second.

## 5. Why the fix is not a refusal, and what it is

**Not a refusal at the construction**: §3's second row works today, and it is
the same `Box1()`. Refusing there narrows a working program for a defect the
program does not have.

**Not a refusal at the field access**: the lowering is right and the word is
wrong, so the refusal would be about an expression the source wrote correctly
(`bx.inner.a`) for a fault in an earlier statement — the same mistake
`bugs/FORMAL_a_one_word_frame_holder_constructor_is_answered_by_the_receiver_
rule.md` §"Why the receiver message is the wrong one" documents for the
receiver rule.

**The fix: bring the frame up, which is what `_emit_frame_constructor` already
does for a struct of two or more fields.** The frame has to exist before the
body runs, so this is a layout decision and it belongs in the shared model next
to the one that already makes them:

| where | what |
|---|---|
| `formal/model.py::struct_default_word` | answer a new kind for "the sole field holds a nested frame of this module", read through `one_word_sole_field_frame` so there is one reader of the question, not two |
| `formal/model.py::struct_constructor_sites` | reserve the NESTED frame's bytes for a construction site of such a struct. It reserves a block per call site for every `framed_struct_names` entry, and a one-word struct is not one; its object's own 8 bytes are not needed either, since the VALUE is the nested address |
| `formal/{arm64,x86_64}_codegen.py::_emit_fresh_one_word` | on the new kind, emit the nested frame's base (from the site's `nested` list) after bringing it up, rather than `mov X0, #0` |

`_emit_frame_nested` / `_emit_frame_nested_addresses` and the nested block's
zeroing are already there for the framed case, which is why this is a layout
change and not a new lowering. **The reason it is not done here** is the shape
of the change: a prologue reservation in the shared model, read by both
backends' frame layout and by every consumer of `_frame_sites` that assumes the
struct there is framed (`_check_frame_escapes`, the returned-frame copy, the
dylib frame-export refusal). That wants a `make gate`, and this branch is a
light worker that does not run one.

**Cost in the corpus: 0 rows of the stdlib sweep move**, and that is a
measurement rather than a guess — the shape needs a one-field struct whose sole
field is a struct of two or more fields, and `std/builtin/builtin_slice.mojo`'s
`StridedSlice`/`Slice` is the one the sweep reaches, and it is refused upstream
of this (`bugs/FORMAL_builtin_slice_optional_field_is_a_frame_holder.md`).

## 6. Reproducing every number here

```console
$ python3 tools/memslot.py --gb 8 --label b5 -- \
      python3 fire.py build --formal --no-prove --backend=arm64  -o bx.a bx.mojo && ./bx.a
$ python3 tools/memslot.py --gb 8 --label b5 -- \
      python3 fire.py build --formal --no-prove --backend=x86_64 -o bx.x bx.mojo && ./bx.x
$ python3 -c "
import sys; sys.path.insert(0,'.')
import fire_compiler as F, formal.build as B, formal.model as M
src = open('bx.mojo').read()
decls = {s.name: s for s in B.parse_module(src, 'bx') if isinstance(s, F.StructDef)}
print(M.struct_default_word(decls['Box1']), M.one_word_sole_field_frame(decls['Box1'], decls).name)"
('none', None) Inner
```