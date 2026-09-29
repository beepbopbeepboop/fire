# CODEGEN: a container (or string) bound from a CALL RESULT is never freed

## Status (2026-09-28 — OPEN, measured, not started)

Loop-body containers built from a constructor (`[]`, `{}`, `set()`, literals)
are now freed per iteration (`ownership_destruct.analyze_scoped_locals`,
`doc/MEMORY.html` §7.1). What is left is the same shape with a different
right-hand side. Peak RSS at 100k vs 400k iterations, `fire.py build`:

| loop body | B/iter |
|---|---|
| `String("a b c").split(" ")` (runtime call returning a fresh list) | ~280 |
| `x = f(i)` where `f` builds and returns a `List` | ~232 |
| `var p = Pt(i, 2)` (struct: `_alloc_<S>` `calloc`) | ~28 |
| `var s = String("n=") + String(i)` | ~28 |
| one string bound to a local (`+`, `String(i)`, `.upper()`, slice) | ~7 |

## Cause

`ownership_destruct` rule 1 credits a name only when EVERY assignment to it is a
container constructor, because a bare-name RHS is an alias. A call result is
neither: the analysis cannot tell a fresh, unshared value (a runtime helper that
always allocates) from one the callee also keeps.

## Fix

Give the analysis an "owned result" fact for calls: a runtime function known to
return fresh heap memory (the ~105 in `doc/MEMORY.html` §2.1), and a user
function whose every `return` yields a fresh local it built (the ownership doc's
Phase 4 calling convention, `owned` = move). A name bound from such a call then
follows the same escape rules and the same block-scoped free. Strings need the
borrowed/owned split first (list-of-`str` elements, dict values and literals are
borrowed; see §3.D). Structs additionally need their `__del__`/field ownership.

## Done when

The rows above are flat between 100k and 400k iterations, output unchanged,
`make gate` green.
