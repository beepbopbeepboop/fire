# CODEGEN: in a module with a bool-yielding generator and a float-yielding generator, the float one prints `True`

**State: OPEN, reproduced 2026-10-29. Pure literals, no lambdas. Cause NOT
yet located. Found while pinning
`bugs/hard/CODEGEN_generator_lambda_expr_unsupported.md`'s yield residue.**

## Repro

```python
def gen_bool(n):
    yield n > 2

def gen_float():
    r = 1.5
    yield r

def main():
    for v in gen_bool(5):
        print(v)
    for v in gen_float():
        print(v)
main()
```

CPython: `True` then `1.5`. Compiled (A3 path, exit 0): `True` then `True`.

Reproduced with the 2026-10-29 `coro.py` change reverted, so it is not caused
by that work.

Each generator on its own is right: `gen_float` alone prints `1.5`, and
`gen_bool` alone prints `True`. The defect needs both in one module.

## Where to look

- `_generator_value_kind` gives each generator its own kind (`'b'` for
  `gen_bool`, `'d'` for `gen_float`), so the per-generator choice looks right.
- The consumer side is the likely culprit: the `for v in gen_float():` loop in
  `main` reads `value_ctype` through the `_api` registry
  (`mojo/backend_gimple/module_gen.py`'s `_register_free_generator` and the
  `_api['value_ctype']` readers in `emit_calls.py`). Check whether the
  registry is keyed by something two generators share, or whether a `bool`
  accessor from the first generator is reused for the second's `next` call.
- The float generator's own C should be inspected first: does its value slot
  and `__mgco_*` accessor come out `double`?

## Next step

1. Build the repro with `compile_to_gimple_with_cpp` and dump the C for both
   generators and the `main` consumer. Find which accessor `main` calls for
   `gen_float`'s values.
2. Once the wrong accessor is identified, find where it is chosen and key it
   per generator. Add a regression test beside the generator consumer tests
   in `test_gimple_generator_runner.py`, CPython-compared.
