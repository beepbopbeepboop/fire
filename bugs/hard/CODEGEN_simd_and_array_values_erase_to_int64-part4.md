SPLIT: CODEGEN_simd_and_array_values_erase_to_int64-part4-part2, CODEGEN_simd_and_array_values_erase_to_int64-part4-part3

# A float SIMD value survives a call and a return (part 4)

Split: the parameter/return/result-local propagation piece landed separately
(part4-part1, 2026-11-13). This doc remains for the full call-and-return
probe (`test_part4_float_simd_survives_call_and_return`), which also depends
on part 3's float SIMD constructor.

Part 4 of `bugs/hard/CODEGEN_simd_and_array_values_erase_to_int64.md`.

Depends on part 3: a float SIMD value must first be constructed with its dtype
(part 3) before argument and return typing can carry it. Class: mid. This part
is the propagation of part 3's type through locals, arguments and results.

## Goal

A float SIMD value passed to `id_simd(x: SIMD[DType.float32, 2])` and returned
keeps its float representation. Today the local `r` is `int64_t` and so is the
argument, so generic call typing sees `Int64`.

## Acceptance

- In the probe, the local that receives the call result is not declared
  `int64_t` (`int64_t r;` is absent from the function body).
- The function body carries no "indirect call via SubscriptExpr" placeholder.
- The callee's parameter and return C types are float-typed, not `int64_t`.

## Done when

File: `test_codegen_erased_container_values_pins.py` (repo root).

Command: `python3 test_codegen_erased_container_values_pins.py part4`

It runs `test_part4_float_simd_survives_call_and_return` (green: part 3 has
landed and this pin moved to the pins file). It must pass.

## Where to start

`mojo/backend_gimple/emit_calls.py` for call-result typing, and the
parameter/return `_mojo_type` mapping. Thread the dtype from part 3's
constructed value into the local's declared C type.
