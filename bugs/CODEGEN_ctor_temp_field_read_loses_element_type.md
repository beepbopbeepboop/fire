# OPEN: a field read straight off a constructor TEMPORARY loses element-type tracking

**State: OPEN.** Recorded 2026-09-27 while closing out
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
