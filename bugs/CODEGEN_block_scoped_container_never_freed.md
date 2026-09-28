# CODEGEN: a container declared inside a loop body is never freed (and never stack-homed)

## Status (2026-09-28 — OPEN, measured, not started)

Found while auditing the compiled path's memory (see `doc/MEMORY.html`).
`for i in range(n): var l: List[Int] = []; l.append(i); total += len(l)`
built with `fire.py build`, peak RSS at 100k vs 400k iterations:

| loop-body local | B/iter |
|---|---|
| `var l: List[Int] = []` + 2 appends | ~232 |
| `var l = [1, 2, 3, i]` | ~232 |
| `var s = {1, 2, i}` | ~456 |
| `var d: Dict[String, Int] = {}` + 1 set | ~540 |
| callee returns a `List`, caller binds it | ~232 |
| `String("a b c").split(" ")` | ~280 |

The emitted C for the list case is `l = mojo_list_new ();` in the loop body and
no `mojo_list_free`/`_destroy` anywhere in the function.

## Cause

`ownership_destruct.py` only credits a name that is assigned once AND is
definitely assigned at every *function* exit (`_definitely_assigned`). A loop
body may run zero times, so a name assigned only inside one is never definitely
assigned at exit; its own module docstring records this as an intentional v0
limitation ("loop-body-scoped container ... intentionally NOT a candidate").
`bugs/CODEGEN_container_no_deallocation_unbounded_growth.md` reports this
shape as fixed and flat at ~9 MB; that does not match the measurement above
(annotated `var x: T = ...` declared in a loop in `main`).

## Fix

Make the exit point the end of the *declaring block*, not the function: a
candidate is freed (or `_destroy`'d, if stack-homed) at the end of its block on
fall-through and before every `break`/`continue`/`return` that leaves it. Escape
rules unchanged. Stack-homed storage is re-`_init`'d each iteration, so `_init`
must follow `_destroy` on the same storage. The analysis module is self-hosted
and has a long history of compiled-path divergences: the full `make gate`
including bootstrap byte-identity is required, not optional.

## Done when

This doc's table rows above are flat between 100k and 400k iterations
(`doc/MEMORY.html` §8 recipe), program output unchanged, `make gate` green.
