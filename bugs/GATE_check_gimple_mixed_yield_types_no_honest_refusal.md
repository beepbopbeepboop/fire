# GATE: `make check` job `gimple` is red: a mixed-yield generator is not refused

## Status (2026-11-01, OPEN)

`python3 test_gimple.py` (the `gimple` job, 354 s in the user's `make check`) fails this case:

```
FAIL  generator_mixed_yield_types_honest_fallback: expected an exception containing 'generator function', compile_to_gimple succeeded instead
```

The test expects a generator whose yields have mixed types to be refused with an error that names "generator function" (the
honest fallback). Instead `compile_to_gimple` compiles it. The refusal that was supposed to fire is not reached, so the
compiled path silently emits something for a shape it cannot type.

## Next step

1. `python3 test_gimple.py 2>&1 | grep -n generator_mixed_yield` to confirm the single case.
2. Find the mixed-yield check in `mojo/middle/coro.py` (the generator yield-type inference) and see why it accepts the
   function instead of raising. It is most likely a type join that returns one of the yield types rather than failing.
3. Make it raise the refusal the test names. Do not weaken the test.

## Quick test

`python3 test_gimple.py` shows `generator_mixed_yield_types_honest_fallback` as PASS. Then this doc is deleted with the fix.
