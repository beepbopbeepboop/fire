# CODEGEN_tagged_int_times_int_prints_as_float_in_mixed_for_loop: `x * 2` on an int yield prints `2.0`

## Status (2026-11-01, measured on HEAD before the None-arithmetic fix; not fixed)

In a for loop over a kind-mixed generator (ints and a float), `x * 2` where
`x` is an INT yield prints as a float (`2.0`), though CPython prints `2`.
`x + 1.5` on the same loop is correct, and `x - 1`, `x // 1`, `x % 3`, `x / 2`
are correct for int yields. Only `*` by an int reads wrong.

### Repro

```python
def g():
    yield 1
    yield 2.5
    yield 4

def main():
    for x in g():
        print(x * 2)
main()
```

- CPython: `2`, `5.0`, `8`
- compiled (HEAD): `2.0`, `5.0`, `8.0`

### Next step

Trace the `*` lowering for a tagged int operand beside an int literal: the
select in `_tagged_arith_select` (`mojo/backend_gimple/emit_exprs.py`) and
`mojo_float_arith_select` (`runtime/fire_runtime.c`) return an int-or-double box
by the OTHER box's kind. Find why the result box for `1 * 2` is a double box
(likely the `_FLOAT_PARAM_OPS` `*` path marking the result of an int-by-int
product as a double when the loop also yields a float). Pin with the repro in
`test_gimple_generator_runner.py`.
