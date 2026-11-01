# CODEGEN_unary_minus_on_a_received_float_box_is_its_address: `-x` on a received float prints a pointer

## Status (2026-11-01, measured on HEAD before the None-arithmetic fix; not fixed)

`-x` where `x` is a tagged word holding a DOUBLE box (a float yielded by a
kind-mixed generator, bound by a for loop) negates the box's ADDRESS, not the
float. The None-arithmetic fix (`mojo_none_unary_guard`) only raises for a None
box and leaves the float box as it was.

### Repro

```python
def g():
    yield 1
    yield 2.5
    yield 4

def main():
    for x in g():
        print(-x)
main()
```

- CPython: `-1`, `-2.5`, `-4`
- compiled (HEAD): `-1`, `-4341657616` (an address), `-4`

Same wrong value on HEAD with and without the None fix, so it is independent of it.

### Next step

In `_lower_UnaryOp` (`mojo/backend_gimple/emit_exprs.py`), a `-` on a tagged
word that may be a float box should read the box by kind the way
`_tagged_arith_select` does: a double box negated as a double (`mojo_box_from_double`
of `-mojo_box_double(x)`), an int/bool box as its integer. Pin with the repro in
`test_gimple_generator_runner.py`.
