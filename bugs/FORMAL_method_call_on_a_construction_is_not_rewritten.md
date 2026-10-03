# A method called on a CONSTRUCTION is not rewritten, and the build dies at the link naming a symbol the source never spells

**Area:** FORMAL (`formal/build.py`, `_rewrite_method_calls` /
`_method_call_target`). Found 2026-10-03 on `work/formal8-8-r2` while closing
`FORMAL_one_field_holder_of_a_frame_is_not_a_holder.md`, whose §"One more gap,
in the same neighbourhood" recorded this and was right to keep it separate: it
fires whether or not the method body is read, so the receiver seeding that
doc's fix needed has nothing to do with it.

## The measurement

```mojo
struct Opt:
    var v: Int
    var has: Int

struct Box:
    var inner: Opt

    def get(self) -> Int:
        return self.inner.v

def main() -> int:
    return Box().get()
```

`fire.py build --formal --no-prove --backend=arm64` (and `--backend=x86_64`,
identically):

> build: ctor_recv.mojo: the image would bind 1 symbol(s) that nothing
> provides, so it could not be loaded: **get**. Nothing on this line provides it:
> `def get` …

The source's callee is `Box.get`; the image asks for a symbol spelled `get`.

## Why

`_method_call_target` — the ONE recogniser for "this call's callee is a method
of a struct this module declares" — requires the receiver to be a bare
`F.IdentExpr`:

```python
if not (isinstance(func, F.MemberExpr) and isinstance(func.obj, F.IdentExpr)):
    return None
```

`Box()` is an `F.CallExpr`, so `Box().get()` is not lifted, and the receiver
carries no frame-receiver type either, so it reaches the emitter's `is a method
call on a value` table… and is not there either, because the method name is in
`owners` and the call arrives with an unresolved callee.

`_receiver_shape_refusal`, which is where a receiver that is not a bare name is
supposed to be caught, deliberately does not fire:

> * "not a bare name" refused 24 working cases in `test_formal_run.py`. A
>   `MemberExpr` receiver is a field or a nested frame …
> * "a subscript or a call result" still pre-empted
>   `frame_opaque_position_refusal`'s own sentence for `mk().take(r)`, which is
>   the SAME fact (a receiver whose type is not established) reached through a
>   path that already says so.

and it only recognises a `SubscriptExpr` receiver anyway. So a CALL result has
no recogniser at all, and what the reader gets is a LINK-time message about a
symbol rather than a compile-time one about the construct — the outcome that
message's own wording calls the failure mode "a better DIAGNOSIS and a worse
INSTRUMENT".

## Why it is not the same fix as the receiver seeding

`Box().get()` is answerable in principle and not trivially: `Box` is a ONE-field
struct, so `Box()` is a word, and the receiver `Box.get` expects is the address
of an `Opt` FRAME. A construction of a one-word holder of a frame has to
materialise that frame — `model.struct_construction_plan` /
`struct_nested_frame_fields` place a nested frame for a struct that is itself a
holder, and whether they place one for a construction of the holder is the
question. Measured answer: no, and the program's first store is the missing
one, so lifting the call alone would move the failure from the link to
`field_access_refusal` and name `Box()` rather than `get`.

## The next step

In order, because each step makes the next one answerable:

1. **Refuse the construct by name**, in `_rewrite_method_calls` /
   `_receiver_shape_refusal`, for a call whose receiver is a CONSTRUCTION of a
   struct this module declares. That is a strict improvement on the link error
   even with nothing else changed: the message names `Box().get()` and the fact
   (a receiver that is not a name) rather than a symbol nothing provides.
   `_receiver_shape_refusal`'s own clause list is where the exclusion has to be
   lifted, and its docstring is where the reason it was there has to be
   revisited — the "a call result already has a better sentence" clause is true
   for `mk().take(r)` and false here, because `Box()`'s type is *established* by
   the declaration while `mk()`'s is not.
2. **Then lift it**, if `struct_construction_plan` can place the nested frame a
   one-word holder of a frame needs at a construction site. That is the same
   placement `b.inner = Opt()` uses, and `b.inner = Opt()` is measured working
   (155) — so the machinery exists and the question is whether the construction
   reaches it.

Step 1 alone is worth landing: a link-time dangling symbol is the one failure
shape in this file that names nothing the reader wrote.

## What is NOT claimed

* Both architectures measured, and the refusal text comes from shared code, so
  the two could not have differed.
* Not measured: whether lifting it answers the program. Step 2 is unstarted.
* The `SubscriptExpr` receiver (`bs[0].get()`) is the shape
  `_receiver_shape_refusal` DOES recognise, and it is refused by name already;
  this document is about the two receiver shapes it does not.