# CODEGEN: a STRING (or a call whose freshness cannot be proven) bound to a local is never freed

## Status (2026-09-28 — PARTLY CLOSED; the container half is fixed, the string half is open)

Fixed and pinned by regression tests (`doc/MEMORY.html` §3.B/C, §5): a container bound from a slice,
comprehension, `+`, or a runtime call that always returns a new container is owned by the local;
a user function proven to return a fresh container (`ownership_destruct.analyze_returns_fresh`,
including `return l^`) hands ownership to its caller; a fresh temporary is freed by its one
consumer (`for`, `extend`, `+`, `len`); a struct instance is owned while nothing retains `self`.
Measured flat: `x = f(i)`, `len(mk(i))`, slices, comprehensions, struct locals.

What still leaks (peak-RSS slope, 100k vs 400k iterations, `fire.py build`):

| loop body | B/iter |
|---|---|
| `String("abc").upper()`, a callee returning `String` (not provably fresh) | ~6 |
| `String("a b c").split(" ")` (the list is freed; its three strings are not) | ~48 |

Fixed since this doc was first written (`doc/MEMORY.html` §3.B): a local bound to a provably fresh
STRING (`+`, `String(i)`, slices, f-strings) is owned and freed; `var s = String("n=") + String(i)` and
`"n=" + String(i) + "!"` measure flat.

## Cause

`upper`, `lower`, `strip`, `lstrip`, `rstrip`, `replace`, `join`, `expandtabs` and the padding
functions return their own argument (or a static `""`) in edge cases, so their result cannot be
freed and a method call on a string local may alias it. Only the 10 runtime functions whose every
return path allocates are treated as fresh.

## Fix

Make those functions always return a copy (then add them to `_FRESH_STRING_RETURNS`, and relax the
receiver-result rule for them), and free the element strings when a fresh `split()` list is freed.

## Done when

The rows above are flat between 100k and 400k iterations, output unchanged, `make gate` green.
