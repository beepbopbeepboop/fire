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
| one string bound to a local (`+`, `String(i)`, `.upper()`, slice, callee returning `String`) | ~6 |
| `var s = String("n=") + String(i)` | ~28 |
| `String("a b c").split(" ")` (the list is freed; its three strings are not) | ~48 |
| a call whose result the analysis cannot prove fresh, bound to a local | (not freed; by design) |

## Cause

A string local needs an owner, and strings have a shorter safe-pattern list than containers:
`+`, comparisons and f-strings all take bare identifiers as operands, which the escape analysis
treats as an escape. There is also a borrowed/owned split to respect (list-of-`str` elements, dict
values and literals are borrowed and must never be freed).

## Fix

Give strings the same declaration gate as containers (own a local only when the lowered value
is a provably fresh `mojo_str_cat`/`mojo_str_from_int`/... result), add `+`/comparison/f-string
reads to the safe patterns for names known to be strings, and free the strings a fresh
`split()` list holds when that list is freed.

## Done when

The rows above are flat between 100k and 400k iterations, output unchanged, `make gate` green.
