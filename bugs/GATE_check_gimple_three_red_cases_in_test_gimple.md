# GATE: `python3 test_gimple.py` has three red cases outside the mixed-yield fix

Found 2026-11-01 while fixing `generator_mixed_yield_types` (that case now passes).
Full run: `python3 tools/memslot.py --gb 8 --label test_gimple-full -- python3 test_gimple.py`
→ `420 passed, 4 failed`. The fourth failure, `every_ast_mutation_site_invalidates_the_walk_memo`,
is owned by `bugs/GATE_check_gimple_ast_mutation_sites_not_invalidating_walk_memo.md`.

## The three cases

1. `generator_str_key_subscript_honest_refusal` — wrong error text. The refusal DOES fire
   (`Unsupported shape(s): gen: yields ['d'], whose call sites do not all pass the same statically-known type`),
   but the test's expected substring no longer matches it. Decide whether the test's expected
   substring is stale (update it to the current honest message, as the mixed-yield case was) or the message
   regressed. Read the case's comment in `test_gimple.py` first.
2. `ctor_of_a_container_reaches_the_comprehension [single-TU]` — compiled stdout is missing the last
   line `['a', 'b', 'c']`. Real miscompile-by-omission (exit 0, wrong output). Next step: compile the case
   and diff the emitted C for the comprehension over the container constructor (`list()`/`tuple()` ctor
   feeding a comprehension); it is the comprehension-of-ctor lowering in `mojo/backend_gimple/`.
3. `a_string_passthrough_beside_an_int_one_keeps_its_own_elements [single-TU]` — compiled stdout is
   `[1, 2, 3]` only; CPython prints `[1, 2, 3]` then `['a', 'b', 'c']`. The second call's string
   passthrough produces nothing. Same single-TU path as (2); likely the same root (a second
   container-valued call site being dropped).

## Quick test

`python3 test_gimple.py` — each of the three names must print PASS. Run it with
`python3 tools/memslot.py --gb 8 --label <x> -- python3 -I .tmp/one.py` by importing `test_gimple` and
calling the single case helper, as the mixed-yield fix did.
