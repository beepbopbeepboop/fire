# OPEN: a field read straight off a constructor TEMPORARY loses element-type tracking

**State: OPEN, and BOTH of the doc's scope claims are wrong — re-measured
2026-09-30, see "Status (2026-09-30)" at the bottom: the trigger is
narrower than "a `0` element to trip the sentinel" (it takes a
COMPREHENSION) and the blast radius is wider than "through a constructor
TEMPORARY" (reading it through a local fails identically).** Recorded
2026-09-27 while closing out
`bugs/PARTIAL_WORK_HANDOFF.md` §4.2 (the other two container-printing
findings in that section — `print([True, False])` and `print({1, 2})` — are
fixed; this third, related one is not).

## Repro

    class B4:
        def __init__(self, v):
            self.v = v

    print(B4([i for i in range(3)]).v)

CPython: `[0, 1, 2]`. Compiled: `[None, 1, 2]` — the first element (`0`) is
misread as the `None` sentinel. `B4([7, 8, 9]).v` prints `[7, 8, 9]` fine
(no `0` element to trip the sentinel), and reading the SAME field through a
local — `b = B4([i for i in range(3)]); print(b.v)` — is exactly right.

## Root cause

`self.v`'s element type is never a literal inside `B4.__init__` (`self.v =
v` is a bare param passthrough); it can only be known by tracing the
CONSTRUCTOR CALL SITE's argument (`[i for i in range(3)]`, a comprehension
whose element is `int64_t`). `_field_elem_types[struct][field]` (consulted
by `_lower_MemberExpr`'s field-read branch, `mojo/backend_gimple/
emit_exprs.py:1846`-`1858`) is populated reactively, only when codegen
*sees* a `.append(...)` call on a value already known to belong to that
struct field (`emit_methods.py`'s `append` handling, `:3948`-`:3995`,
via `gen._struct_field_owners`) — never from the constructor call site
itself.

Reading through a LOCAL works by a different, unrelated mechanism entirely
(the local's own element type is tracked once bound, and `b.v`'s read
inherits `_elem_types`/`_nested_elem_types` from the LOCAL `b`'s own
tracked container info — not from `_field_elem_types` at all). A
constructor-call-expression RECEIVER (`B4(...).v`, no local in between) has
no such tracked identity to inherit from, so the field-read branch falls
through to the generic `_mojo_repr_list`/`_mojo_generic_elem_repr` pair,
which is where the `0`-as-`None` sentinel heuristic lives.

## Shape of the fix (not attempted)

This needs the SAME kind of call-site-to-field evidence tracing
`CODEGEN_ctor_arg_field_type_scalars_only.md` used for the field's C TYPE
(now fixed — see `mojo/backend_gimple/module_gen.py`'s `_ctxlit_*`
pass, immediately after the literal ctor-arg-type pass), but one level
deeper: instead of "what CONTAINER type does this argument have", the
question is "what ELEMENT type does this argument's container have",
written into `_field_elem_types[struct][field]` the same way `.append`
already does. `_gmi_container_ctype`'s literal classifier only answers the
outer type; a companion element-type classifier would need to handle a
`ListExpr`/`Comprehension` argument's own element inference (reusing
`_infer_list_elem_type`/`_quick_container_elem`, already used elsewhere in
this file for exactly this purpose) and feed it in at the same pipeline
point the container-type pass now runs at.

Not attempted this session — scoped as its own item since it is additive
(a new element-type tracer, not a change to the type tracer just fixed) and
the two together in one change would make either one harder to verify in
isolation.

## Status (2026-09-30) — the doc's scope is wrong in both directions; the trigger is a COMPREHENSION, and the local spelling is broken too

Re-measured at `86d862fc` against CPython on the same text. The
`[None, 1, 2]` sentinel misread reproduces, but the shape is much narrower
and the "reading it through a local works" claim does not hold any more:

    print(B4([i for i in range(3)]).v)   # [None, 1, 2]   CPython: [0, 1, 2]   BROKEN
    b = B4([i for i in range(3)]); print(b.v)
                                        # [None, 1, 2]   CPython: [0, 1, 2]   ALSO BROKEN
    print(B4([i for i in [7, 8, 9]]).v)  # [7, 8, 9]     CPython: [7, 8, 9]   correct
    print(B4([1, 2, 3]).v)              # [1, 2, 3]     correct
    print(B4(["a", "b"]).v)             # ['a', 'b']    correct
    print(B4([str(i) for i in range(3)]).v)
                                        # ['0','1','2']  correct
    print(B4([i for i in [0]]).v)       # [None]        CPython: [0]         BROKEN
    print(B4([i for i in [0, 1]]).v)    # [0, 1]        correct

So: it needs a COMPREHENSION whose element is a bare bound identifier, and
it needs that comprehension's FIRST element to be falsy — the sentinel
heuristic in `_mojo_generic_elem_repr` is what turns the `0` into `None`,
which is why `[i for i in [7, 8, 9]]` is fine and `[i for i in [0]]` is
not. A plain list literal of any element types is fine, temporary receiver
or local, and so is a comprehension over a `str` call. And the doc's
"reading the SAME field through a local is exactly right" is stale: the
local spelling fails identically, so this is not a constructor-TEMPORARY
problem at all — it is the same missing element-type evidence whichever way
the value is reached, which also means the doc's framing (a temporary has
"no tracked identity to inherit from") is not the mechanism.

Two of this session's other fixes are adjacent and did NOT close it, which
is worth recording so nobody re-derives that they might have: a
constructor temporary's field read still does not consult the *argument's*
element type (nothing traces `B4(<arg>)`'s element type into
`_field_elem_types[B4][v]` — the doc's "shape of the fix" is still the
right shape), and the comprehension's own element type is not recorded for
the `range()` iterable case even though the identical comprehension is
printed correctly when it is not stored in a struct field
(`x = [i for i in range(3)]; print(x)` is exactly right). So the
evidence exists at the literal and is lost on the way into the field.

Not attempted: the fix is a call-site element-type tracer feeding
`_field_elem_types`, which is a new inference pass rather than a patch,
and per the gate rules it would owe `mojoc`/bootstrap like everything else
in `mojo/backend_gimple/`. The first thing to measure before writing it is
which of the two losses above is the real one — if the comprehension's
element type were simply recorded for the `range()` case, would the field
read come out right on its own? That is a much smaller change than a
constructor-argument tracer and it would cover the local spelling too.
