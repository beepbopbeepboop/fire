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

**2026-10-30: gate moved before the struct coercion (gate fix).**

The landed gate was red on the stdlib gate (`stdlib-syntax`:
`std/pathlib/path.mojo:558`, a gcc "cannot convert to a pointer type"; and
`std/simd.mojo`). Root cause: `_lower_binary_tail` tested the operand types
AFTER its `P *` -> `int64_t` struct-pointer coercion, so a struct operand
looked like an int and `result /= part` became `mojo_div_double` of a pointer.
The gate is now computed at the top of `_lower_binary_tail`, on the operand
types as they arrive. Verified: `compile_stdlib.transpile_file` passes on
`std/pathlib/path.mojo` and `std/simd.mojo`; `test_codegen_int_div_zero.py` is
green, including the new `test_struct_true_division_builds` (fails on the
previous commit, passes now). The full stdlib gate was NOT run here.

The `path.mojo` line still lowers to integer arithmetic on the pointer, as it
did on master. That is a separate, real gap, filed in
`bugs/CODEGEN_variadic_param_element_type_untyped.md`: the `*parts` element is
`int64_t`, so the struct `/=` never dispatches to `__itruediv__`, and the
repro segfaults at run time.

**Still open (residual):**

- `_Bool` operands now included in the gate (2026-10-30): `t = True; print(t / 2)`
  answers `0.5`; `test_bool_true_division_is_float` pins it.
- `uint*` operands remain excluded (kept from the original gate, which the
  revert did not change): `UInt(7) / UInt(2)` prints `3`. Whether Mojo's
  `UInt` true division is a Float64 has not been checked against real Mojo
  (`tools/mojo`), so this is not asserted either way.
- The `cpp_core.py` mirror is reached via `_cpp_is_int_operand`; no
  coroutine-run-time `/` test exists yet.
- The stdlib gate (`stdlib-syntax`, `stdlib-dylib`) was not run on this
  branch; the struct-operand regression that caused the revert is the thing
  to watch.

## Next step

1. `_Bool` decided (included; `test_bool_true_division_is_float` passes).
   Check Mojo's `UInt` true division against `tools/mojo` before touching the
   `uint` exclusion.
2. Run the full stdlib gate once and compare `std/pathlib/path.mojo` and
   `std/simd.mojo`; if either regresses, bisect the struct-operand shape first.
3. Write a coroutine run-time test for `/` if the `cpp_core.py` lowering is
   reachable; otherwise delete the mirror as dead code.
