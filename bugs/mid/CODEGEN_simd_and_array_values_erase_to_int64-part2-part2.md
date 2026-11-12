# SIMD float values keep non-Int64 typing in call/return lowering (part 2, subpart 2)

Part 2 of `bugs/hard/CODEGEN_simd_and_array_values_erase_to_int64-part2.md`.

Depends on part 2-part1 establishing float SIMD constructor lowering without the
erased placeholder; this part ensures float SIMD values are not represented/typed
as plain `int64_t` when passed through function parameters, locals, and returns.

## Goal

Propagate float SIMD dtype information through lowered locals, arguments, and
results so float SIMD values are not seen as `Int64` solely due to `int64_t`
erasure in call/return contexts.

## Acceptance

- A float SIMD value constructed and passed to/returned from functions in the
  same compiled module is not erased to plain `int64_t` storage/typing in those
  contexts.
- The emitted C reflects float/double typing for the float SIMD values in the
  probe (not only the erased placeholder form).
- Generic call typing/inference over such float SIMD values can observe a
  non-`Int64` floating type rather than the erased fallback.

## Done when

Quick test (file path and command):
`test_codegen_simd_argtype_part2.py` — run
`python3 test_codegen_simd_argtype_part2.py`
and it exits 0.
