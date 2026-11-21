# CODEGEN: `gimple_id_is_an_integer` is red — `len({id(a), id(b), id(a)})` is 1, not 2

Found 2026-11-20 while running the `gimplerunner` test file to land
`bug:CODEGEN_values_print_as_pointers_inside_containers`; the failure is
present on master (reproduced in a clean `master` worktree at 8c98215cd) and
is not caused by that change. Deterministic: 3 of 3 runs.

## Repro

`test_gimple_runner.py::test_gimple_id_is_an_integer` (the `gimple_id_is_an_integer`
case; the whole program is in the test). The failing line:

```python
ids = {id(a), id(b), id(a)}
print('set', len(ids), int(id(a)) > 0, id(None) == id(None))
```

CPython prints `set 2 True True` (two distinct lists); the compiled program
prints `set 1 True True`. Every earlier line of that test matches, including
`id(a) != id(b)`, so the tokens themselves are distinct outside the literal.

## What I ran

    python3 tools/memslot.py --gb 8 --label gimplerunner -- python3 test_gimple_runner.py
    # Results: 651 passed, 1 failed  (only gimple_id_is_an_integer)
    # the case alone, via test_gimple_matches_cpython, twice: FAIL both
    # times, `set 1` both times

A smaller probe with the same three calls over two fresh lists passes:

```python
print(len([id(a), id(b), id(a)]))      # 2
print(len({id(a), id(b)}))             # 2
print(len({id(a), id(b), id(a)}))      # 2
```

so the collapse depends on the earlier statements in the real test
(`show('list', a)`, `cache[id(a)] = 'A'`, `d = {int(id(a)): 'v'}`), not on the
set literal alone.

## Next step

Reduce the documented program one statement at a time (start by keeping the
`show(...)` calls and the `cache[id(a)] = 'A'` write) until the set length
first drops to 1, then look at how that statement's result interacts with the
`id(a)` call inside `{...}` — a shared temp/slot for repeated calls to the
same expression is the first hypothesis to check (`_lower_set_literal`, the
call-temp allocation, and `gen._elem_types`/boxed-word tracking for `id`).
Add the reducer as a `test_gimple_matches_cpython` case in
`test_gimple_runner.py` and fix it; the existing full program is the oracle.

## Done when

`gimple_id_is_an_integer` passes (CPython and compiled both print `set 2`),
and the reducer is a case beside it.
