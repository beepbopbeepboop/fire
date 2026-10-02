# FORMAL_method_param_field_access: a method parameter's field, with no call site to establish it

**Status: NOT FIXED, and not this lane's. Found while landing the declared
`__init__` inline (`bugs/FORMAL_struct_construction_shapes.md`); it is where all
twenty of that family's dependents land now, so it is worth more than the finding
it replaced. The construct is claimed by `formal-receiver-handoff`
(`construct:receiver-handoff-method`).**

## The refusal

```
build: builtin_slice.mojo: Slice___eq__: 'other.start' is a field access
through 'other', and this path has no way to say what 'other' holds. A field is
lowered three ways and which one applies is decided by the BINDING of the base,
not by a type: a one-field struct's receiver IS its field, a multi-field struct's
receiver is the address of a frame, and an ordinary word is an integer. 'other'
is bound here as a parameter, so none of the three is established, and a store
to the field with no home lands in a register the next function reads as its
first parameter.
```

`formal/model.py`'s `field_access_refusal`, printed for the first of
`Slice.__eq__`'s three `other.<field>` reads.

## The root cause, and it is one line of fact

**A method parameter is a frame address only when some call site in the image
says so.** `formal/build.py`'s `_frame_receivers` fixpoint has two edges that
make a name a holder: a binding from a framed struct's constructor
(`_constructor_bindings`), and an argument reaching a visible callee at a known
position (`_frame_argument_slots`, which wave 5 extended to every position and
not only the first). A method's own receiver is seeded directly — `for recv in
M.struct_receivers(owner)` — but its OTHER parameters are not. So
`other: Self` inside `__eq__` is established exactly when some `x.__eq__(y)`
exists, and is an ordinary word when nothing in the image calls it.

`Slice.__eq__` is never called in `builtin_slice.mojo`. Nothing in that file
compares two `Slice`s, so `other` has no call site, and reading `other.start`
is refused. That is the whole of it, and the fix is not a new analysis: it is
the DECLARED TYPE, which the message itself names ("`other` is bound here as a
parameter") and which the message's own advice reaches for ("or declare the
field's type so the base is not typeless") — advice this path does not act on.

## The smallest reproducer, and the one-line A/B that identifies it

```mojo
struct SE:
    var a: Int
    var b: Int
    def __eq__(self, other: Self) -> Bool:
        return self.a == other.a

def main(n: Int) -> Int:
    var x = SE()
    var y = SE()
    x.a = 1
    y.a = 1
    if x.__eq__(y):          # <-- change THIS ONE THING
        return 1
    return 0
```

* with `x.__eq__(y)`: **builds** on both backends. The call rewrites to
  `SE___eq__(x, y)`, `y` reaches parameter 1, and `other` becomes a holder.
* with `x == y`, or with **no call at all**: **refused**, with the message above.

Nothing else differs, the `==` operator is not involved (removing every `==` on a
struct from the file does not help, because a `CompareChain` on a struct is
lowered as an integer compare of the two frame addresses rather than dispatched
to `__eq__` — a separate question, see the end of this file), and the decorator
is not involved. One call site, or none. Both reproducers are pre-existing: they
refuse identically on the commit before the `__init__` inline landed, verified by
building the same two sources in an export of `HEAD~1`.

A ONE-FIELD struct's method has the same refusal for a second, independent
reason — its receiver is not a frame at all (`struct_is_framed`: "a one-field
struct's receiver IS its field"), so there is no frame to be a holder of and the
constructor-binding edge does not apply either:

```mojo
struct S9:
    var a: Int
    def eq2(self, other: S9) -> Bool:
        return self.a == other.a
```

## Why it is twenty files

`std/builtin/builtin_slice.mojo` is a first-class dependency of a large part of
the stdlib, so anything that stops it building stops everything downstream.
Measured on the 294-file stdlib sweep (`python3 tools/formal_sweep.py -j 8 -t
300 <stdlib>/std`, arm64), before and after the `__init__` inline:

| | before | after |
|---|---|---|
| `codegen/dependency by family: builtin_slice.mojo: …` | `construction with arguments needs __init__ x20` | `other refusal x20` |
| pass / codegen / codegen / dependency / not-answerable | 24 / 88 / 181 / 1 | 24 / 88 / 181 / 1 |

**Twenty files, one terminal fact, and no verdict changes class in either
direction.** The twenty: `base64/__init__`, `benchmark/{__init__,benchmark}`,
`builtin/{builtin_slice,globals,int,reversed}`, `gpu/host/dim`,
`hashlib/{_fnv1a,hasher}`, `math/uutils`, `memory/{__init__,_poison,alloc,
unsafe_maybe_uninit}`, `python/numpy`, `reflection/location`,
`runtime/tracing`, `utils/{__init__,_nicheable}`.

## The next step, precisely

`formal/build.py`'s `_frame_receivers`, seeding a method's parameters the way
`model.struct_nested_frame_fields` already seeds a typed-nested FIELD:

1. **which structs.** `frame_field_type_candidates([owner], pname, decls)` is the
   existing predicate for "a declared type that names a struct of this module",
   and `struct_nested_frame_fields` uses it to decide a field holds a placed
   frame. Asked about a parameter instead of a field it is the same question.
2. **which parameters.** Every parameter of a method whose declared type says
   "struct of this module with a frame receiver" — position does not matter for
   the FIRST step, because this is a declaration and not a call site, and
   declaring a type is not the same evidence as a call passing a word. The
   position-sensitive argument (a frame address in a NON-first position, wave 5's
   `bugs/FORMAL_frame_receiver_handoff.md` §11) does not apply to it: a declared
   type names the LAYOUT, and the lifetime argument in §8 is about the value, not
   the position.
3. **the agreement check is the test.** `_check_holder_agreements` already
   distinguishes "the build does recognise this as a frame receiver and the
   emitter did not treat it as one" (a compiler bug) from "nothing recognised it"
   (a limit), and `field_access_refusal`'s `holder=True` arm is the first. **The
   fix is verified by that arm staying unreachable** — which is also how to tell
   a correct fix from a lucky one.
4. **one-field structs are a separate half.** A one-field struct's receiver is
   its FIELD, so there is no frame to be a holder of and the question is a
   different one: the parameter's declared type says the word IS the field, and
   `self.<field>` is already rewritten to `self` (`_rewrite_self_fields`). The
   same declared-type read answers it, and it is worth doing in the same change
   because the message is the same one and a reader who fixes the framed half
   and still sees the refusal on a one-field struct will think the first half was
   wrong.

**What the fix must NOT be.** Turning the refusal off without the declared type
is the same class of change the whole `bugs/FORMAL_frame_receiver_handoff.md` is
about: arm64's `_store_var` used to fall through to `mov x19, src` and x86-64's
`_load_var` read an immediate 0, both silent and both wrong, and a case that
checked only a return value never noticed. The test for it has to be a program
that reads `other.<field>` through such a parameter **and writes through it as
well, on both backends** — a read alone and a store alone are two branches and a
fix to one is not a fix to the other.

## A second, unrelated question this reproducer turned up

`x == y` on a struct is lowered as an **integer comparison of the two frame
addresses** (`_emit_compare_chain`'s `cmp_conds` has no struct case and no
`__eq__` dispatch), so two distinct objects with identical contents compare
unequal. That is a wrong answer, not a refusal, and it is NOT this file's
subject — but it is in the same reproducer and the same stdlib neighbourhood
(`Slice` is `Equatable`), and a reader who fixes the parameter question and then
writes `Slice(1,2,3) == Slice(1,2,3)` will get a false answer. **Not measured on
this tree** — no test here dispatches a struct comparison — so it is recorded as
an open question, not as a finding.
