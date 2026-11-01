# CODEGEN_cpp_path_plain_float_call_in_generator_yields_as_int: a float-returning plain call in a generator is truncated on the cpp path

## Status (2026-11-01)

Found while checking `CODEGEN_cpp_path_reads_stale_generator_registry`. Not caused
by that bug: reproduced in a fresh process with NO other module compiled first.

## Repro (silent wrong output, exit 0)

```python
def h():
    return 2.5

def g():
    y = h()
    yield y

def main():
    for v in g():
        print(v)
main()
```

- CPython: `2.5`
- `coro.pinned('cpp')` compile + run: `2`
- `coro.pinned('stackswitch')` compile + run: `2.5` (PASS)

Test harness: `test_gimple_generator_runner.py::test_generator_matches_cpython`
(`.tmp/d4_cpp_only.py` in the round that found it).

## Expected

The cpp path must type `y` (and therefore the yield slot) as a double, the same as
the stack-switch path does. Equivalently it must refuse the module, never truncate.

## Next step

Find where the cpp path types `y = h()` for a same-module plain function `h` with
a float `return`. The candidate reader is the cpp-path kind inference reached from
`cpp_async.py` via `_generator_value_kind` (coro.py), which goes through
`_static_env` and `_callee_return_kind`. Compare with what `_static_env` gives on
the stack-switch path for the same source. Add a regression test beside
`cpp_path_ignores_previous_module_state` in `test_gimple_generator_runner.py`.
