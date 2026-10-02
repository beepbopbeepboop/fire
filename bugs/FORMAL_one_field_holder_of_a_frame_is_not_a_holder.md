# A method of a ONE-FIELD struct whose sole field is a FRAMED struct: `self` is a frame address and nothing says so

**Area:** FORMAL (the wide-receiver family; the holder walk). Found 2026-10-02
on `work/formal3-2-r2-r2` while re-measuring shape 2 of
`bugs/FORMAL_builtin_slice_optional_field_is_a_frame_holder.md`, whose last
Status section was written from a different refusal than the one the shape
actually reaches. **NOT FIXED, and the reason is measured rather than
described: the fix is two lines and it alone turns a refusal into a SIGSEGV.**

This is not a duplicate of
`bugs/FORMAL_builtin_slice_optional_field_is_a_frame_holder.md` (that doc's
shapes 1 and 2 are the CONSTRUCTION and the STORE) nor of
`bugs/FORMAL_wide_receiver_by_reference.md` (which is the by-reference
receiver switch, landed). It is the RECEIVER SEEDING, which neither of them
names, and it is the wall behind that doc's shape 2.

## The gap, in one program and one line of difference

```mojo
struct Opt:                    # TWO fields, so a frame
    var v: Int
    var has: Int

struct Box:                    # ONE field  ->  the difference
    var inner: Opt

    def get(self) -> Int:
        return self.inner.v * 10 + self.inner.has

def main() -> int:
    var b = Box()
    b.inner = Opt()
    b.inner.v = 41
    b.inner.has = 1
    return b.get()
```

`fire.py build --formal --no-prove --backend=arm64` (and `--backend=x86_64`,
identically):

> build: `Box_get: 'self.v' is a field access through 'self', and this path has
> no way to say what 'self' holds. … 'self' is bound here as a parameter, so
> none of the three is established … Bind the base from a constructor this
> module declares (`x = S()`)`

The message is false in three separate ways, and each one is a fact the rest of
the tree already has:

1. **`'self.v'` is not in the source.** `_one_word_field_map` rewrote
   `self.inner` to `self` (correctly: `Box` is one field, so its receiver IS
   its field), leaving `self.v`. That flattening is the right access — `self` is
   an `Opt` frame address, so `self.v` is one load at `self + 8*slot(v)`.
2. **"'self' is bound here as a parameter … none of the three is established"**
   is a claim about a name the analysis could have settled. It was settled for
   the LOCAL half of the same program (below).
3. **"Bind the base from a constructor this module declares"** is advice about
   `self`, which is not bound from anything.

## The boundary is exactly the holder's OWN field count

Three programs, the same `Opt`/`Box`, the same body. The only variable is how
many fields `Box` itself declares.

| `Box` | program | result on arm64 and x86-64 |
|---|---|---|
| `var pad: Int; var inner: Opt` | method reads `self.inner.v` | **Built, 155** (= 411 & 255), and 155 is `41*10 + 1` |
| `var inner: Opt` (one field) | same body | **refused** — the message above |
| `var inner: Opt` (one field) | no method; `b.inner.v` in `main` | **Built, 41** — the local half already works |

So a two-field holder's frame-typed field reads through a method, and a
one-field holder's identical read does not. Nothing about `Opt` is different;
the only difference is that a one-field struct has no storage of its own, so
`self` and `self.inner` are ONE word, and the holder walk has no case for a
word that is a frame.

The local half working is the load-bearing half of this measurement: the
analysis already knows how to place `b` as an `Opt` frame when the binding is
`b = Opt()` (the `b.inner = Opt()` store rewrites to `b = Opt()` before the walk
runs, and `_constructor_bindings` settles it). What is missing is only the
method's own `self`.

## The fix, and why it cannot land alone

`formal/build.py::_frame_receivers` seeds a method's receiver from the owner's
own layout:

```python
owner = owners.get(fn.name)
if owner is not None and owner.name in framed:
    for recv in M.struct_receivers(owner):
        holders[...].add(recv); hstruct[...][recv] = [owner]
```

`Box` is not framed, so the branch does not fire and `self` is not a holder.
Seeding it with the FIELD's struct instead — `model.one_word_sole_field_struct`
is the helper that answers "a word holding this one-field struct addresses which
frame", and both this and `formal/build.py::_check_method_receiver_types` must
read it from one place — makes the READ half work, and the read half was
measured working with that patch applied:

| case | before | with the seeding alone |
|---|---|---|
| `b.get()` where the body only reads the field | refused by `_check_method_receiver_types` ("`b.get()` is dispatched to `Box.get()` … and the receiver is a `Opt` frame") | **Built, 155** on both architectures |
| `b.set(mk(41))` where the body only STORES the field | refused by `field_access_refusal` | **Built, and dies with SIGSEGV (exit 139) on both architectures** |

**The second row is the whole reason this is a document and not a commit.**
`self.inner = o` rewrites to `self = o`, so the store overwrites the method's
own receiver word with a frame address belonging to the caller. Every later
`self.v` in that method then reads the caller's object, and the caller's `b`
still points at the original frame. That is a wrong answer, not a failure, and
it is the outcome every refusal in this family exists to prevent.

It is not caught today because `_collect_holder_rebinds` **excludes a method's
own receiver by name**, and the docstring says why in as many words:

> `self = <a word>` is a different thing again (the caller's slot still points
> at the old frame, so the method's effect does not reach its caller) and it is
> not this check's to decide; **the escape checks are where a receiver that
> stops being the caller's object belongs.**

So the exclusion is deliberate and correct, and the check it defers to does not
exist. That is the pair that has to land together:

1. seed a method of a one-field struct as a holder of its sole field's frame
   (`_frame_receivers`), and let `_check_method_receiver_types` agree with it;
2. refuse a method receiver ASSIGNED a frame address that is not a construction
   of the receiver's own layout, in the escape checks.

(2) is the write-once half of "what is a struct-typed field", the question
`bugs/FORMAL_builtin_slice_optional_field_is_a_frame_holder.md` has been
pointing at, and it is also `bugs/FORMAL_a_frame_holder_rebound_from_a_word.md`
/ `bugs/FORMAL_holder_rebound_from_a_word.md`'s subject. This document does not
attempt it: the analysis has no path sensitivity, `self` is excluded from the
one check that exists, and getting it wrong is a segfault on both machines.

## One more gap, in the same neighbourhood

A method called on a CONSTRUCTION — `Box().get()` — is not rewritten at all, and
the build dies at the link with a dangling symbol rather than a diagnostic:

> build: the image would bind 1 symbol(s) that nothing provides, so it could
> not be loaded: **get**.

`formal/build.py::_rewrite_method_calls` only rewrites a receiver that is a
plain `IdentExpr`, so `Box()` reaches the emitter as a call to a symbol spelled
`get`. Identical on both architectures. It is independent of the receiver
seeding above (it fires with the method body present but unread), and it is a
one-line-shaped gap in the same rewrite — worth taking with the above rather
than separately, because both are "a receiver that is not a name".

## How to reproduce, and the exact next step

Every program is in this document; `.tmp/` copies are not committed, and the
reproducers are five lines each:

    python3 fire.py build --formal --no-prove --backend=arm64 -o /tmp/w .tmp/shapes/s2a.mojo
    python3 fire.py build --formal --no-prove --backend=arm64 -o /tmp/w .tmp/shapes/s2b.mojo
    python3 fire.py build --formal --no-prove --backend=arm64 -o /tmp/w .tmp/shapes/s2d.mojo

`grep -n "one_field_struct\|one_word" bugs/*.md` shows no doc for this shape, so
this is the one to work from. Next step, in order: the escape check (2), then
the seeding (1), then `Box().get()`. In that order because (1) alone is a
measured segfault and (2) alone refuses nothing new.
