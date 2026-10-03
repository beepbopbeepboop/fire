# A BARE receiver whose method name two structs of this image declare is refused, even when the receiver's own binding names the owner

**Area:** FORMAL (`formal/build.py`, the method-call dispatch in
`_prepare_functions`). Found 2026-10-03 on `work/formal8-8-r2` while checking
whether `FORMAL_one_word_struct_field_call_receiver_is_collapsed.md` was still
open. It is not — the collapse that doc names is fixed — and this is the
nearest shape that IS still refused.

Split out rather than left as an appendix to that doc, because the fix
direction is the opposite one: that doc's collapse is a rewrite that has to be
undone before the call site, and this is a rewrite that has to be ADDED.

## What is closed, and where

`bugs/FORMAL_one_word_struct_field_call_receiver_is_collapsed.md` (deleted
2026-10-03) named two things and both are fixed in this tree:

* the one-word collapse of a CALL RECEIVER — `_rewrite_one_word_field_method_calls`
  / `_lift_one_word_field_method`, whose docstring quotes that doc's own
  reproducer and explains why the lift has to precede
  `_rewrite_self_fields`. Pinned by `test_formal_run.py`'s
  `both_arch_one_word_struct_method_call_through_its_field`: `o.inner.get()`
  through a one-field `Outer`, 42 on both architectures, and **refused on both**
  when the lift is removed.
* the struct-with-NO-FIELDS family (`std/testing/prop/random.mojo`'s `Rng`
  refusing its own `_next`) — pinned by `test_formal_run.py`'s
  `method_call_in_an_elif_arm_is_lifted`, which is that file's own text.

What that doc left as "the next step, exactly" is the `len(declared) == 1`
gate: "`_owner_from_receiver_type`: a field's declared type names the owner even
when a bare name does not". The field case is what the lift above reads. The
BARE case is this document.

## The measurement

```mojo
struct Inner:
    var a: Int
    var b: Int
    def get(self) -> Int:
        return self.a + self.b

struct Outer2:
    var pad: Int
    var inner: Inner
    def get(self) -> Int:          # the SAME name Inner declares
        return self.inner.get()

def main() -> int:
    var o = Outer2()
    o.inner.a = 20
    o.inner.b = 22
    return o.get()                  # 42 under CPython
```

`fire.py build --formal --no-prove --backend=arm64` (and `--backend=x86_64`,
identically):

> build: `o.get()` is a method call on a value, and this backend lowers only
> append, close, write (on a file descriptor) and the string methods count,
> endswith, find, lstrip, startswith — the receiver is a name on this path, and
> 'get' is not one of those methods of those receivers, so adding it to either
> table would be a guess about what it means on 'int'.

Renaming `Outer2.get` to `Outer2.total` — changing NOTHING else — makes the
identical program build, run, and answer **42** on arm64 and on x86-64. So the
name is the whole of it.

## Why

`_method_owners` is a `{method_name: struct_name}` map and it **pops every
ambiguous name precisely so `_rewrite_method_calls` cannot pick one**
(`formal/build.py`'s own comment, and `_ambiguous_method_owners`'s: it is
"asked of the DECLARATIONS … because that map has already thrown the name
away"). Dispatch on this path is by NAME alone — the receiver's type is not
inferred — so for `recv.m(x)` with `m` declared by two structs, refusing is the
conservative answer and is right for a receiver nothing types.

It is not right here. Every other lowering decision on this path is made the
same way and the rule is already written down in
`formal/model.py`'s field-access refusal: **"a field is lowered three ways and
which one applies is decided by the BINDING of the base, not by a type"**. `o`
is bound by `var o = Outer2()`, and `Outer2` declares `get`. The binding names
the owner; only the spelling does not.

`_constructor_bindings` already computes exactly that fact, and deliberately
keeps a **LIST** per name rather than a struct — because `x = A()` on one path
and `x = B()` on another is one name with two frame layouts, and the emitter
must not pick either. So the rule the fix has to implement is the list's
already-stated rule: lift only when the candidates AGREE.

## The next step

Extend the lift to a bare receiver whose agreed binding is a struct of this unit
that declares the member. Concretely, `_lift_one_word_field_method`'s first arm
currently asks `one_word.get(obj.name)`, and `one_word` holds only ONE-WORD
locals — a two-field holder like `o` is not in it. The narrow form:

1. build the same `{name: [struct, …]}` table for constructor-bound locals of
   this unit (the facts `_constructor_bindings` already computes; it must not
   become a second reading of the bindings), and
2. in `_lift_one_word_field_method`'s first arm, accept a name from that table
   when the list has exactly one distinct struct AND that struct declares the
   member AND `_derived_overrides` declines it — the last clause is
   `_derived_overrides`' own reason and it is not optional, because a
   derived-and-also-declared name lifted to the BASE's method is a silent wrong
   answer.

It must stay AFTER `_rewrite_method_calls` for the reason that function's own
docstring gives: a call that path could lift has already been lifted, so
reaching this one means the name-only path declined it, which is exactly the
ambiguous case.

## What is NOT claimed

* Not measured beyond the two architectures above; every refusal text here is
  arch-free and comes from shared code (`model.py`), so the two could not have
  differed — but that is an argument, not a measurement of the second one.
* The one-word holder of a FRAMED struct, where `o`'s binding is an `Inner`
  frame and `o.get()` names `Outer.get`, is a DIFFERENT refusal and is
  `bugs/FORMAL_one_field_holder_of_a_frame_is_not_a_holder.md`: there the
  receiver really is a frame and the method writes its own struct's layout
  through it. This document is about a receiver whose layout is known and
  unambiguous.
* `Inner` above is a framed two-field struct and `Outer2` a two-field struct.
  The one-field variants of both are doc-6-fixed and doc-4-open respectively;
  neither was used to make the claim here, because the ambiguity gate fires
  before either of those is reached.