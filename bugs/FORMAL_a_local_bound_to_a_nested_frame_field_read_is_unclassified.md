# A local bound to a nested frame FIELD READ is not classified as a frame
# address, so `var t = self.inner; t.v` is refused where `self.inner.v` is not

**Area:** FORMAL (the frame-holder seeding; `formal/build.py`'s
`_frame_receivers`). **Status: OPEN, measured on both architectures, not
fixed.** Found 2026-10-04 while landing the `_REASSIGNED` advice fix
(`bugs/FORMAL_builtin_slice_optional_field_is_a_frame_holder.md`, whose Status
section records it as the reason that advice was false).

## What I ran

```console
$ cat .tmp/wf5.mojo
struct Opt:
    var v: Int
    var has: Int

struct Box:
    var pad: Int
    var inner: Opt

    def get(out self) -> Int:
        var t = self.inner
        return t.v * 10 + t.has

def mk(n: Int) -> Opt:
    var o = Opt()
    o.v = n
    o.has = 1
    return o

def main() -> int:
    var b = Box()
    b.inner = mk(4)
    printf("g=%d", b.get())
    return 0

$ for a in arm64 x86_64; do python3 tools/memslot.py --gb 8 --label w -- \
    python3 fire.py build --formal --no-prove --backend=$a -o .tmp/wf5_$a .tmp/wf5.mojo; done
```

## What I saw

**Identical refusal on both backends**, and it is not the one the reader would
predict:

```
build: Box_get: 't.v' is a field access through 't', and this path has no way
to say what 't' holds. A field is lowered three ways and which one applies is
decided by the BINDING of the base, not by a type: a one-field struct's
receiver IS its field, a multi-field struct's receiver is the address of a
frame, and an ordinary word is an integer — and nothing this image can see
about 't''s binding establishes which …
```

**Every other reading of the same program is answerable**, measured on both
architectures against CPython:

| program | verdict |
|---|---|
| `return self.inner.v * 10 + self.inner.has` in `get`, with no method assigning the field | builds, prints `g=41` |
| the same, with `Box(o)` assigning in `__init__` from `__init__`'s parameter (delegating) | builds, prints `g=41` |
| `b.inner.v` read in `main` | builds, prints `g=41` |
| **`var t = self.inner` then `t.v`** | **refused** |

So the field is a frame, the slot holds its address, the chain through it lowers,
and the ONLY thing that fails is naming the same value in a local first. The
binding `var t = self.inner` is a **member read whose declared type is a framed
struct of this module**, and `_frame_receivers` has no arm that turns such a
member read into a holder.

## Why it is worth its own document rather than a line in the refusal's

Two independent reasons, and the second is the one that decides it.

**It is a real gap, not a limit of the design.** `_frame_receivers` already
seeds a holder from a DECLARED type in two other places — a method parameter
(`model.parameter_declared_structs`, the `Slice.__eq__` family) and a
constructor's construction sites. The rule this needs is the same rule those two
use: *a binding whose value is a member read of a field declared as a framed
struct of this module binds a frame address*. What is missing is the arm, and
its absence is why a spelling that is the SAME program is refused.

**It is currently costing a diagnostic.** `_typed_nested_frame`'s `_REASSIGNED`
refusal used to end "Assign the field to a name and read through the name",
which is precisely this program's shape — and following the advice produced this
refusal instead of a working image. That advice is now correct (it names the
delegating constructor instead, which is measured to build), so the diagnostic no
longer misleads, but the gap underneath it is still a gap, and the next
diagnostic in this family will reach for the same rewrite.

## The exact next step

One arm in `_frame_receivers`, beside the parameter seeding:

* over the function's binding statements, find `var NAME = <base>.<field>` /
  `NAME = <base>.<field>` where `NAME` is a fresh local;
* ask `_typed_nested_frame` — or `model.frame_field_type_candidates`, the same
  agree-or-refuse rule the parameter arm uses — for `field`;
* when it agrees on a framed struct AND the field is not `_REASSIGNED`, add
  `NAME` to `fn._frame_holders` with the agreed struct.

**The `_REASSIGNED` exclusion is the load-bearing part**, and it is why this
cannot be a blind copy of the parameter arm: a parameter's declared type settles
the layout at every call site, while a member read's lifetime depends on WHICH
function wrote the slot. So the seeding must ask the same question
`_typed_nested_frame` asks, not a cheaper one — which is why the fix is "route
this binding through the existing decision" rather than "add a rule".

Then: the four programs in the table above must all still build and answer 41 on
both backends, and a case where the field IS `_REASSIGNED` must still be refused
— `test_formal_method_param_field.py` has the machinery for both halves, and a
seeding that skips the `_REASSIGNED` check silently produces exactly the SIGSEGV
`FORMAL_one_field_holder_of_a_frame_is_not_a_holder` records for the analogous
receiver-seeding mistake.

## Reproducing

```console
$ export PATH=/opt/homebrew/bin:$PATH
$ python3 tools/memslot.py --gb 8 --label t -- python3 test_formal_method_param_field.py
# the delegating case passes today; the local-copy case has no case, because it
# is not expressible as one until this lands.
$ python3 tools/memslot.py --gb 8 --label w -- python3 fire.py build --formal \
      --no-prove --backend=arm64 -o .tmp/wf5 .tmp/wf5.mojo
```