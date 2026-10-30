# CODEGEN: integer `/` truncates where Python's true division gives a float

Split out of `CODEGEN_int_mod_negative_truncates.md` (its `%` sign defect is
fixed; this part was never in that fix).

## Repro

```python
def main():
    a = 7
    b = 2
    print(a / b)
```

- Python: `3.5`.
- Compiled path (`python3 fire.py --jit`): was `3`, now `3.5`.

## Status (2026-10-29)

**Landed: `Int / Int` with plain signed C integer operands is Float64.**

- `mojo/backend_gimple/emit_exprs.py` (`_lower_binary_tail`): `/` becomes a
  `double` result when BOTH operands are plain signed C integers. The gate is
  on the operands, not on the joined type. The first attempt (fd7ca5941) gated
  on the join and broke `std/pathlib/path.mojo` and `std/simd.mojo`, where a
  struct operand joins with an int; it was reverted in 98043fe81. The operands
  reach the existing `double` path (`mojo_div_double`, which raises on zero).
- `mojo/backend_gimple/cpp_core.py` (`_cpp_expr`): the same gate for the
  coroutine emitter, lowering to `mojo_div_double((double)a, (double)b)`.
- `test_codegen_int_div_zero.py`: `test_int_true_division_is_float` pins
  `7 / 2 == 3.5` and related quotients (fails on the pre-fix tree, printing
  `3 2 1 4`); `test_nonzero_integer_division_unchanged` now expects `8 / b`
  as `4.0`, not the truncated `4`.

**Still open (residual):**

- `_Bool` operands are excluded from the gate: `t = True; print(t / 2)` prints
  `0`; Python gives `0.5`.
- `uint*` operands are excluded (kept from the original gate, which the
  revert did not change): `UInt(7) / UInt(2)` prints `3`. Whether Mojo's
  `UInt` true division is a Float64 has not been checked against real Mojo
  (`tools/mojo`), so this is not asserted either way.
- The `cpp_core.py` mirror is not reached by any program in this sweep
  (`async def` division lowers through GIMPLE, `mojo_div_double (...)`), so it
  is compile-checked only and has no run-time test.
- The stdlib gate (`stdlib-syntax`, `stdlib-dylib`) was not run on this
  branch; the struct-operand regression that caused the revert is the thing
  to watch.

## Next step

1. Decide whether `_Bool` joins the gate (Python: `True / 2 == 0.5`), and
   check Mojo's `UInt` true division against `tools/mojo` before touching the
   `uint` exclusion.
2. Run the full stdlib gate once and compare `std/pathlib/path.mojo` and
   `std/simd.mojo`; if either regresses, bisect the struct-operand shape first.
3. Write a coroutine run-time test for `/` if the `cpp_core.py` lowering is
   reachable; otherwise delete the mirror as dead code.
