# CODEGEN: integer `%` truncates toward zero for a negative dividend

Found while fixing zero-divisor trapping (test_codegen_int_div_zero.py).

## Repro

```python
def main():
    n = -7
    print(n // 2, n % 2)
```

- Python: `-4 1` (`//` and `%` floor toward the divisor's sign).
- Compiled path (`python3 fire.py --jit`): `-4 -1`.

`//` is correct — it goes through `__mojo_floordiv`, which floors. The plain
`%` lowering in `mojo/backend_gimple/emit_exprs.py` (the arithmetic tail,
`t = lv % rv`) emits C's truncating `%` directly. The runtime's boxed
`mojo_pyobject_arith` `%` path already does the floor fix-up
(`if (r && (r > 0) != (b > 0)) r += b;`), so the box path and the plain path
disagree.

## Not covered by this doc

Integer `/` also differs from Python: Python's `7 / 2` is `3.5`, this
compiler answers `3`. That is a separate question (Mojo's `Int / Int` is a
`Float64`, so the right answer is a typing decision, not a one-line fix) and
is not filed here.

## Next step

Route integer `%` through a floor-correcting helper the same way `//` does,
or emit the fix-up inline in the arithmetic tail, and add the same
`(r != 0) && ((r ^ b) < 0)` correction as `__mojo_floordiv`. Pin with a
`test_codegen_int_div_zero.py`-style compile-and-run case for `-7 % 2 == 1`
and `7 % -2 == -1`. The divisor already goes through `mojo_int_divisor`, so
the zero-check is in place; only the sign correction is missing.
