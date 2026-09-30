# FORMAL_string_constructor_collision: `String()` is a `char *` to the emitter and a three-slot frame to the analysis

**Status:** found while landing the returned-frame convention, NOT fixed, and
not in this lane. It is a crash (SIGBUS, exit 138) on **both** machines, in the
pre-change tree as well as this one, so nothing is silently wrong because of it —
but it is the reason the returned-frame convention cannot be exercised on a
struct that declares the name `String`, which is the shape the stdlib's own
`String` is.

## The reproducer

```python
# .tmp/sr/t9b.mojo — 14 lines, no imports
struct String:
    var _ptr_or_data: Pointer[UInt8]
    var _len_or_data: Int
    var _capacity_or_data: Int
    def size(self) -> Int:
        return self._len_or_data

def main(n: Int) -> Int:
    var a = String()
    a._len_or_data = 5
    return a.size()
```

```
$ python3 fire.py build --formal --no-prove -o t9b t9b.mojo
Built: t9b  [arm64/macho]
$ ./t9b
Bus error: 10          (exit 138; the source says 5)
$ python3 fire.py build --formal --no-prove --backend=x86_64 -o t9bx t9b.mojo && ./t9bx
Bus error: 10          (exit 138)
```

Measured on `.tmp/base` (this tree at `HEAD` before the returned-frame
convention) as well, so it is pre-existing and not something that change
introduced. Also measured: the same struct with the field names shortened, with
the struct renamed to `S3`, and with `size` renamed to `get`, **all build and
return 5**. It is the NAME that does it.

## The cause, and it is a two-answer disagreement

`String` is in `STRING_TYPE_CTORS` and in `IDENTITY_TYPE_CTORS`, so
`type_constructor_kind("String")` answers `("string", …)` and
`formal/arm64_codegen.py`'s `_emit_call` routes `String()` there **before** it
reaches `_emit_struct_constructor` — because `type_constructor_prefers_local_struct`
(`formal/model.py`) only fires for a name in `UNREPRESENTABLE_TYPE_CTORS`, and
that is a DELIBERATE exclusion, quoted from its own docstring:

> only `UNREPRESENTABLE_TYPE_CTORS` is overridden, never the identity or the
> integer tables.  `Pointer` is a struct some files in this repository declare
> AND an identity conversion … Preferring the local declaration there would turn
> a working identity conversion into a construction, which is a change of
> MEANING rather than a change of verdict

So the emitter produces **the address of the interned empty string** — one
word, a `char *` — and hands back 0 in the zero-operand form
(`String()` with no operand is `String("")`, another spelling, and it is
materialized as the empty string's address).

`formal/build.py`'s `_constructor_bindings` does not consult any of that: it
sees a call to a name in `framed_struct_names`, which is a purely local
question, and makes `a` a **holder of a three-slot frame**. So
`_frame_slots["a._len_or_data"] = 1` is emitted and the store is
`STR X0, [X?, #8]` where `X?` is whatever `a` holds — the address of a string
literal in `__TEXT,__text`, plus 8 — which is not a writable page. SIGBUS.

Two answers to "what does `String()` mean in this file", and the file says both
of them: it declares a three-field struct AND it calls a name the model has
already decided is a string conversion. `model.struct_field_count` derives
three fields from the declaration; the emitter never asks it.

## The stdlib says the same thing about `String`, in a comment

`std/collections/string/string.mojo:220-224` declares three fields and then says
why there are two readings of them:

```
# Fields: String has two forms - the declared form here, and the "inline"
# form when '_capacity_or_data.is_inline()' is true. The inline form
# clobbers these fields (except the top byte of the capacity field) with
# the string data.
var _ptr_or_data: UnsafePointer[UInt8, MutUntrackedOrigin]
var _len_or_data: Int
var _capacity_or_data: Int
```

That is worth reading carefully next to the SIGBUS, because it says something
the two candidate fixes do not agree about: **the two forms live in the SAME
three slots.** The inline form is a `char *` written over the declared form's
first bytes, chosen at run time by a flag in the top of the capacity field.

So a returned-frame COPY is faithful for both forms — copying the three slots
copies whichever form is in them, and the flag moves with the bytes. The
returned-frame convention is not what is wrong about `String`, and the doc's
"the next step is D2's" stands: the disagreement is about which form a given
CONSTRUCTION produces, and about which of the two a local is.

Which is also why the fix is (1) and not (2) as a first move. `String()` in the
stdlib is called all over the place and its result is concatenated, appended to
and compared — all of which on this path are `char *` operations, so those
locals are inline-form words. Making the emitter prefer the local struct for a
wide declaration would turn all of them into three-slot frames, and the string
methods are lowered under the `char *` reading
(`bugs/FORMAL_string_value_model.md`'s decision), so the two would then disagree
in the other direction. The honest first move is to make the ANALYSIS stop
claiming a frame for a construction the emitter does not lower as one, and to
say so by name; the wider question — which form a `String` local is, per
binding, with a flag read at run time — is a larger piece of work than either
fix and is not a change to a constructor.

## Why it is not this lane's, and what the next step is

The returned-frame convention is about where a frame LIVES. This is about
whether a `String` local is a frame at all, which is
`bugs/FORMAL_string_value_model.md`'s D2 item ("the frame/field derivation")
and the exact collision that document names: *"a `String` local must be either a
three-slot frame or a `char *`, and today the two representations are in force
simultaneously."* Fixing it means making the two agree, and there are two ways
with different blast radii:

1. **Make `_constructor_bindings` ask the emitter's question.** One guard, in
   `formal/build.py`: a call whose name the emitter will NOT lower as a framed
   construction is not a constructor binding, so the name is a plain word and
   `a._len_or_data = 5` becomes `model.field_access_refusal` ("this path has no
   way to say what `a` holds") instead of a store through a string address.
   Narrow, honest, and it refuses a construct the stdlib's `String` genuinely
   is on this path — which is the point, and also why it will move verdicts in
   the sweep for every file that declares its own `String`.
2. **Make `type_constructor_prefers_local_struct` prefer the local struct when
   it is a multi-field one.** That unifies the two readings and makes
   `String` frames work, and it is the change `bugs/FORMAL_string_value_model.md`
   argues for. It is also the direction that "turns a working identity
   conversion into a construction", so the exclusion would have to become
   "prefer the local struct when the local declaration is WIDE" — which is the
   discrimination the docstring already says it declined to make.

**The measurement to take first** is (1) on `formal_sweep.py --no-stdlib` and
on the stdlib scope, and it is the same denominator warning wave 3 wrote down:
files that stop being `codegen` because a crash became a refusal have not become
answerable, and the coverage percentage must not be read as a gain.

## What is testable right now, and is

`test_formal_returned_frame.py` uses the `class`/`def __init__` spelling for
every case that can use it, and the one case that needs a `struct` declaration
is `returned_frame_carries_its_nested_frame` — which is about a NESTED frame
and has nothing to do with this name. A `String`-shaped **returned** frame is
therefore not covered by a case, and cannot be until this is settled; the
returned-frame convention itself is name-independent (it is keyed on
`struct_is_framed`, not on any table of names), which is why the rest of the
suite stands.
