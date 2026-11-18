# CODEGEN: narrow-integer arithmetic, comparison and `.cast` for `Scalar[DType.*]` (part 2)

## Goal

With part 1 giving `Scalar[DType.int8/.../uint64]` its real C type, make the
operations on those values obey the dtype width instead of the 64-bit word.

- `mojo/backend_gimple/emit_exprs.py`, `_lower_binary_tail`'s scalar integer
  arm: when both operands have the SAME narrow integer C type (`int8_t` ...
  `uint64_t`), the result takes that type and the emitted C is cast back to it
  after the operation. C integer promotion makes `uint8_t + uint8_t` an `int`,
  so without the cast-back the value widens (measured today:
  `Scalar[DType.uint8](250) + Scalar[DType.uint8](10)` prints `260`; the width
  answer is `4`). Do not change `int64_t`/`int` operations.
- Comparisons (`==`, `!=`, `<`, `<=`, `>`, `>=`) on two same-dtype integer
  `Scalar` operands must compare the real C types directly, with no coercion to
  `int64_t` first, so an unsigned dtype above 2^31 is not compared as a
  negative signed value.
- Subscript load/store through `UnsafePointer[Scalar[DType.X]]`: the loaded
  temp is the element C type (one byte for `uint8`), and a store writes exactly
  one element — no `int64_t` temp that reads/writes neighbouring bytes.
- `.cast[.intN]()` / `.cast[.uintN]()` keeps using `_CAST_SCALAR_CTYPES` and
  must truncate: a value above the target width loses its high bits through a
  real C cast (`.cast[DType.uint8]()` of 256 is 0), and `.cast[DType.uint32]()`
  of a 4000000000 value stays 4000000000. The cast is a conversion, never a
  no-op that echoes the wider receiver.

## Acceptance

A compiled-and-run program prints, in this order:

- `4` for `Scalar[DType.uint8](250) + Scalar[DType.uint8](10)` (`Int(...)` of
  the result).
- `255` for `Scalar[DType.uint8](0) - Scalar[DType.uint8](1)`.
- `250` after storing `Scalar[DType.uint8](250)` through an
  `UnsafePointer[Scalar[DType.uint8]]` and reading it back.
- `True` for `Scalar[DType.uint32](4000000000) > Scalar[DType.uint32](1)`, and
  `4000000000` for `Int(Scalar[DType.uint32](4000000000))`.
- `0` for `Scalar[DType.uint8](Scalar[DType.uint32](256))` /
  `.cast[DType.uint8]()` of 256, and `4000000000` for the `.cast[DType.uint32]()`
  of 4000000000.

The emitted C for the arithmetic and the pointer load names the narrow C type
(e.g. a `uint8_t` temp for `a + b`), not `int64_t`.

## Done when

Add `test_scalar_integer_narrow_arithmetic()` to `test_gimple_runner.py`
(`compile_mojo_to_gimple_exe` in that file already builds and runs a Mojo
program; the function asserts the outputs above and that the emitted C
names the narrow temp type) and call it from that file's `run_tests()` so the
registered `gimplerunner` job runs it too. Run, from the worktree root:

    python3 -c "import test_gimple_runner as t; t.test_scalar_integer_narrow_arithmetic()"

It prints `PASS` and exits 0.
