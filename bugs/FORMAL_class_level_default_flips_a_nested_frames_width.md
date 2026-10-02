# FORMAL_class_level_default_flips_a_nested_frames_width: the two passes disagree about `struct_is_framed`

**Found 2026-09-29 while measuring the constructor-assigned field type
(`formal/model.py` `struct_field_assigned_type`). Not fixed here: the
divergence is between `struct_class_constants`' demotion rule and the frame
analysis's value branch, and the right repair is a design decision about
which of the two is authoritative. Status: open, with a four-line reproducer,
the mechanism measured down to the function, and the two candidate next
steps.**

## What I ran

`struct Inner` with **every** field a class-level literal default, held as a
declared typed-nested field of a framed `Outer`:

```
struct Inner:
    var a: Int = 0
    var b: Int = 0
    var c: Int = 0

    fn add(self, v: Int) -> Int:
        return self.a + v

struct Outer:
    var tag: Int
    var pad: Int
    var in1: Inner

    fn go(self, v: Int) -> Int:
        return self.in1.add(v) + self.tag

def main(n: Int) -> Int:
    var o = Outer()
    o.tag = 5
    o.in1.a = 1
    return o.go(2)
```

## What I saw

```
$ python3 fire.py build --formal --no-prove .tmp/scratch/d3.mojo
build: main: 'o.in1.a' is a field of 'o', which the build DOES recognise as a
frame receiver, so a field access on it should be a load from `[base, #8k]`.
It reached the ordinary local path instead, which means the frame analysis
and the emitter disagree about this function's receivers — a compiler bug
rather than a limit of the path, and refused rather than emitted so it cannot
be a silent wrong store
```

`field_access_refusal`'s `holder=True` branch is the one that fires, and it
is the message that means *a bug in this compiler*, not a limit of the
construct. **The build pass does recognise `o` as a frame receiver** — that
part is true. What is false is the conclusion it draws.

The same program with **two** of `Inner`'s three fields defaulted
(`var a: Int = 0 / var b: Int = 0 / var c: Int`) **builds, runs, and returns
8**, which is the source's answer. And a program where only `Outer.tag` is
defaulted also builds and returns 8. So the trigger is specifically *every*
field of the NESTED struct being demoted out of the field set.

## The mechanism, measured

```
Inner: fields=['a']        framed=False one_word=True
        consts=[('b', IntLiteral 0), ('c', IntLiteral 0)]
Outer: fields=['tag','pad','in1']  framed=True  one_word=False
```

`_split_declaration`'s clause 6 demotes a class-level name **with** an
initializer to a constant unless a method writes it or a method *reaches* it.
`Inner.add` reads `self.a`, so `a` survives; `b` and `c` are never touched,
so they are demoted — three declared instance fields become one, and
`struct_is_framed(Inner)` flips to `False`.

That is the demotion rule doing exactly what it says. The failure is
downstream of it, and it is a **three-way** question that only two answers
exist for:

1. `struct_nested_frame_fields(Outer)` requires `struct_is_framed(Inner)`, so
   it places **nothing** in `Outer`'s block for `in1`. The slot holds a
   **one-word `Inner` value** — `struct_is_framed`'s own definition, "a
   one-field struct's receiver is its field".
2. `formal/build.py`'s `_check_frame_escapes` depth-2 branch asks
   `_typed_nested_frame(base, 'in1', …)`, which returns `None` ("agreed, and
   provably not a frame of this unit") and therefore `continue`s — correct,
   there is no nested frame.
3. The emitter's `_member_slot_key` has `o.in1` in `_frame_slots` (step 2 put
   the depth-1 `o.in1` there) and no entry for `o.in1.a`, so the read falls
   to the ordinary local path and is refused.

**So the missing thing is a lowering, and it is a real one:** a frame slot
whose agreed type is a **one-word struct of this module** has no lowering for
`<holder>.<field>.<the struct's only field>`. `_one_word_field_map`
already computes that scalar replacement for a *receiver* (`self`); it is
never consulted for a frame slot. Two loads and a value — or, better, one
load and a value — and `_rewrite_self_fields` has the shape for it.

## The two candidate next steps, and why I did not pick one

* **(A) Teach the depth-2 value branch about a one-word struct type.**
  Small, local to `formal/build.py`, and it makes the two passes agree. The
  risk is that it is the wrong answer: if the demotion is wrong, this
  cements the wrong layout. It also does nothing about
  `struct_nested_frame_fields`, which is still placing nothing.
* **(B) Do not demote a field of a struct that is used as a typed-nested
  field.** `_split_declaration` has no view of who holds the struct; the
  decision would have to be taken where the use is, and the note on
  `struct_field_names` already concedes the direction is chosen without the
  unit that could settle it. This is the semantically honest one and it is
  bigger.

(B) is the right answer and (A) is the cheap one, which is exactly the
trade-off this doc exists to hand over rather than to resolve by picking
silently.

## Verification either way needs

* the reproducer above, **8**, built, run, compared with CPython, on both
  architectures;
* a **guard** for the demotion rule itself, because (B) changes it:
  `struct_class_constants` is what makes `S(x) = 1` a shared value rather
  than storage, and `test_formal_imports.py`'s
  `a dataclass field with a default is in a struct layout` is the case that
  must keep passing;
* the sweep, because this shape is not only in the repo: it is the same
  question `bugs/FORMAL_frame_receiver_handoff.md` §14's dependents are now
  sitting on. Two of them (`mojo/middle/solvers.py`,
  `test_formal_sweep.py`) report a *field of a field* with the same "nothing
  types this field" wording, so a repair here is worth re-measuring on both.

## Not affected

A class-level default on a field of a struct that is **not** a typed-nested
field is fine, and measured: `Outer.tag = 0` with `var pad: Int` undefaulted
builds and returns 8. The width flip only decides anything when the struct
being measured is itself the type of somebody's nested field.
