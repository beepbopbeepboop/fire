# CODEGEN: comparison on a tagged float generator word reads the box as its integer

Arithmetic on a tagged word beside an integer now selects by the box's kind
(`_tagged_arith_select` in `mojo/backend_gimple/emit_exprs.py`), so
`x * 2` on a float box is `5.0`. The comparison operators were not covered by
that change and still read the box as its integer (`mojo_box_int`).

## What was run and seen (2026-11-01)

```python
def gen():
    yield 2.5
    yield "b"

def main():
    g = gen()
    x = next(g)
    print(x > 2, x == 2.5)
main()
```

Through `test_generator_matches_cpython` (both paths compile and run):

    CPython: 'True True\n'
    compiled: 'False True\n'

`x > 2` is wrong: the box reads as `2`, and `2 > 2` is false. `x == 2.5` is
right, because `==` goes through the word-of-unknown-kind path.

## Expected

`x > 2` prints `True`, matching CPython, on the default path and on
`coro.pinned('cpp')`.

## Where

`mojo/backend_gimple/emit_exprs.py`, `_lower_binary_tail`, the tagged-operand
arm below `_tagged_arith_select`: for `<`, `<=`, `>`, `>=` beside an int it
still takes `mojo_box_int`.

## Next step

Add a comparison counterpart to `_tagged_arith_select`: when a tagged operand
beside an int is a double box, compare as doubles; otherwise compare the
integers. The select has to produce a `_Bool`, not a box, so it cannot reuse
`mojo_float_arith_select` as-is. A small runtime helper is the honest shape
(select between two `_Bool` answers by the box's kind), and it needs its own
header declaration in `runtime/fire_runtime.h`. Pin it with a
`test_gimple_generator_runner.py` case next to `tagged_float_bound_to_name_arithmetic`.
