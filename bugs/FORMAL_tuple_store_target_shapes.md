# FORMAL_tuple_store_target_shapes: what the tuple-store filing had, and what is left

**Status: the x86-64 half is FIXED and measured before and after on both
architectures. The arm64 half the filing describes was already fixed on this
tree, and the filing's headline reproducer is a different bug.** The filing is
`bugs/FORMAL_tuple_store_to_a_field` on `work/merge2-formal`; this file records
the re-measurement, because three of its four claims do not hold on the current
tree and a reader who trusts them will look for a defect that is not there.

## The filing's four claims, re-measured

| the filing says | this tree, both architectures |
|---|---|
| `self.p, self.q, self.r = 3, 4, 7` in `__init__`, then `Tail()`, **builds on arm64, runs, and returns 0** where the source says 14 | **not the tuple store.** `Tail()` is a ZERO-ARGUMENT construction, so it takes `model.struct_construction_plan`'s `CONSTRUCTION_DEFAULT` branch and never reads the `__init__` body at all: every field comes up at its class-level default, which is 0. That is premise (B2) and it is `bugs/FORMAL_zero_arg_init_not_inlined.md` |
| "arm64 accepts it and leaves the slot as it was" — a `MemberExpr` target is not a shape the arm64 store path emits | **already fixed.** `arm64_codegen.py`'s `_tup_slot` answers a `MemberExpr` element with `_member_slot_key` and `_store_tup_slot` routes it through the same `_store_var` a plain store uses. Measured: `t.x, t.y, t.z = 3, 4, 7` on a three-field struct → **14**, CPython's answer |
| "a tuple store to a plain name works on both architectures and is correct" | still true, and it is the CONTROL for the change below |
| the `TupleExpr` refusal in `formal/x86_64_codegen.py` | **still there, and it was the real remaining gap** |

So the one live item was a two-architecture disagreement on a legitimate
program: x86-64 refused `h.x, h.y = p, q` while arm64 lowered it, which is the
one thing two architectures of one language implementation are not allowed to do
about a program that means something.  And this repository writes the spelling —
`tools/procrun.py` has `self.limit, self._chunks, self._size = limit, [], 0`.

## What landed

`formal/x86_64_codegen.py::_tuple_target_key` — one table for the three target
shapes, answering the same question arm64's `_tup_slot` answers with the same
three answers: a name, a frame-slot key, or a nested list of either.  A
`MemberExpr` whose key the slot tables do not name is refused through the same
`model.field_access_refusal` the single-assignment branch uses, so the two
spellings of "a field of something this path has no model for" read alike.

`_emit_for_unpack` now takes the nested list and RECURSES, so a nested group is
a second unpack against the element at its position.  The blob base lives in R10
across the loop, and the two things that could disturb it are handled rather
than assumed: a nested group is emitted between a `push`/`pop` of R10 because the
recursive call takes R10 for its own base, and a store key cannot disturb it —
every arm of `_store_var` with `src == RAX` writes RAX, R11 or memory and never
R10, which the docstring states because it is the invariant the loop rests on.

## Before and after

| program | before | after | CPython |
|---|---|---|---|
| `t.x, t.y, t.z = 3, 4, 7` on a three-field struct | x86-64 **refused**; arm64 14 | **14 / 14** | 14 |
| `self.x, self.y = p, q` in a method, plus `b.x, b.y = 5, 6` | x86-64 **refused** | `a=17 b=11` both | `a=17 b=11` |
| `a.x, b = 7, 8` — a field and a plain name | x86-64 **refused** | `a=7 b=8` both | `a=7 b=8` |
| `a, (b, c) = 1, (2, 3)` | x86-64 **exited 1 with nothing printed** (the group was flattened, so the outer arity check compared a count of 2 against 3) | `a=1 b=2 c=3` both | `a=1 b=2 c=3` |

The nested row is the one worth reading twice: it was not a refusal, it was a
SILENTLY MISCUNTED EXIT.  Counting a nested group's elements into the outer
arity check is a wrong answer wearing the costume of a correct one, and it was
three lines from the refusal that hid it.

## What the fix deliberately does not reach, and the filing's own list

The filing asked for a mixed target (`self.a, b.c = X(), Y()`) to "still be
refused by name".  It does not need to be: a mixed target is a field store and a
register store, the two have different homes, and both architectures now lower
it correctly (`a.x, b = 7, 8` above).  Refusing it would have been refusing a
program that works.

A **subscript** element target (`a[0], b = 1, 2`) is still refused on x86-64, and
it SIGSEGVs on arm64 — but that is not a tuple defect, and the plain statement
`a[0] = 1` with an integer `a` SIGSEGVs on **both** architectures.  That is
`bugs/FORMAL_subscript_store_on_a_non_container_segfaults.md`, filed from the
same measurements.

## The `_STORE_TUPLE` band-aid in the model, still there

`formal/model.py`'s `struct_field_assigned_type` still has its `_STORE_TUPLE`
arm, which RECOGNISES a tuple store to a field and declines to read a type out
of it, with a comment calling itself a band-aid.  It is still needed and the
reason is unchanged: `init_body_stores` only inlines a constructor whose body is
a straight line of `self.<field> = <expr>`, so `self.p, self.q, self.r = 3, 4, 7`
inside `__init__` is refused by name on **both** architectures
(`constructing Tail with arguments is a call to a user-defined __init__ whose
body this path does not inline: a local assignment (TupleExpr = …)`), which is
correct and which the emitter-side fix does not change.  Lifting it is
`bugs/FORMAL_zero_arg_init_not_inlined.md`'s neighbourhood, not this one.