# CODEGEN: integer `/` truncates where Python's true division gives a float

Split out of commit cc01733ce (its `%` sign defect is
fixed; this part was never in that fix).

## Repro

```python
def main():
    a = 7
    b = 2
    print(a / b)
```

- Python: `3.5`.
- Compiled path (`python3 fire.py --jit`): `3`.

## Why it is not a one-line fix

Mojo's `Int / Int` is a `Float64`, so the correct answer is a float result,
which is a typing decision (the result type of `/` on two integers in the
lowering), not a sign correction. The plain `/` in
`mojo/backend_gimple/emit_exprs.py` (`_lower_binary_tail`'s arithmetic tail)
emits C's integer division on two `int64_t` operands, and the `int`/`double`
join there never sees a float result type.

## Next step

Decide the result type for `/` on two integer operands (Float64, per Mojo),
then lower it in `_lower_binary_tail` the way the float path already does
(convert both operands to `double` before dividing, with the zero check via
`mojo_div_double`). Mirror it in `mojo/backend_gimple/cpp_core.py`'s `/`
lowering, which has the same integer shape. Pin with a compile-and-run case
in `test_codegen_int_div_zero.py` for `7 / 2 == 3.5`.
