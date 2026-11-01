# GATE: `make check` job `gimple` is red: `yield from` delegation is not emitted on the C++ path

## Status (2026-11-01, OPEN)

`python3 test_gimple.py` (the `gimple` job) fails this case:

```
FAIL  generator_yield_from_delegation_compiles_via_cpp_path: outer's body doesn't call inner's resume/value -- the delegation loop wasn't actually emitted
```

The outer generator compiles, but its body never calls the inner generator's resume or value, so `yield from` delegates
to nothing. The test checks the emitted code for the delegation loop, and that loop is absent.

## Next step

1. `python3 test_gimple.py 2>&1 | grep -n yield_from_delegation` to confirm the case.
2. Find where `yield from` is lowered on the C++ path (`mojo/backend_gimple/cpp_core.py`, the yield rewrite near
   `_cpp_rewrite_yields`). Check whether the delegation statement is dropped before emission or emitted under a condition
   that is never true for this shape.
3. Emit the delegation loop for this shape. The test is the spec; do not weaken it.

## Quick test

`python3 test_gimple.py` shows `generator_yield_from_delegation_compiles_via_cpp_path` as PASS. Then this doc is deleted.
