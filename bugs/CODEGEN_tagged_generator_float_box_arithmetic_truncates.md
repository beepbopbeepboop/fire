# CODEGEN: arithmetic on a tagged float generator word truncates (`x * 2` prints `4`)

A generator whose yields mix kinds is a TAGGED word: each yield is a box of
its own kind. `x = next(g)` keeps the box (commit `b09622930`), so `print(x)`
renders the kind. Arithmetic on the bound name does not yet select by the box
kind at run time: a tagged operand beside an int is read as its integer
(`mojo_box_int`), so a float box truncates.

## What was run and seen (2026-11-01)

```python
def gen():
    yield 2.5
    yield "b"

def main():
    g = gen()
    x = next(g)
    print(x)
    print(x * 2)
main()
```

Through `test_generator_matches_cpython` (both paths compile and run):

    CPython: '2.5\n5.0\n'
    compiled: '2.5\n4\n'

`print(x)` is correct. `print(x * 2)` is wrong twice over: the value is
truncated (`4`, not `5.0`), and the result is an int, not a float.

## Expected

`print(x * 2)` prints `5.0`, matching CPython, on the default path and on
`coro.pinned('cpp')`.

## Where

`mojo/backend_gimple/emit_exprs.py`, `_lower_binary_tail`, the tagged-operand
arm: a tagged word beside a non-double operand takes `mojo_box_int`, and a
float box is only read as a double when the other operand is a double. The
arm's own comment records this as a stopgap (`_unbox_float_param_operand`).

## Next step

Make the tagged operand select int or double by the box's kind at run time,
instead of deciding it from the other operand's static type. The existing
`_FLOAT_ARITH_OPS` run-time select, already used for may-hold-float
parameters, is the mechanism to reuse; do not add a new helper. Pin it with
a `test_gimple_generator_runner.py` case next to
`tagged_int_bound_to_name_arithmetic` (the probe above, both paths).
