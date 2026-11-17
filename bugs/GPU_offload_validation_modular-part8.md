# GPU offload validation modular - part 8: refuse a conversion or an operation on an unsupported float8 dtype

Parent: `bugs/hard/GPU_offload_validation_modular.md`. This part owns the host
half of the `op_with_unsupported_type_error.mojo` row.

## Goal

A scalar whose dtype has no implementation here — the `float8` family the
canonical case uses (`float8_e3m4`) — must be refused at the point it is used,
with the two messages Modular prints:

    conversion from 'f8e3m4' to 'f32' is not implemented
    operation with a type 'f8e3m4' is not implemented

Today the type is accepted silently (the interpreter answers `1.0` at exit 0),
so a program gets a value from a dtype that has no conversion or arithmetic
rule behind it.

## Current state (measured 2026-11-15, HEAD `fa105c747`)

The family does not exist at all in the interpreter: `DType` is a
`SimpleNamespace` built at `myinterpreter.py:6540-6560` with
`int8..64`, `uint8..64`, `float16/32/64`, `bfloat16`, `bool`, and nothing else.
`print(DType.float8_e3m4)` fails with
`AttributeError: 'SimpleNamespace' object has no attribute 'float8_e3m4'`,
while a program that spells the type directly is accepted and run:

    def main():
        var a: Float8_e3m4 = 1.0
        var b: Float32 = a
        print(b)

`python3 tools/memslot.py --gb 8 --label probe-fp8 -- python3 fire.py run .tmp/probe/fp8.mojo`
prints `1.0`, exit 0: the unknown annotation is dropped and the assignment is a
plain float copy. On the compiled path the same program is also accepted (the
triage row measured `fire` exit 0, no output).

## Work

1. Add the float8 scalar family to the interpreter's type table
   (`myinterpreter.py:6540`): `Float8_e3m4`, `Float8_e4m3fn`,
   `Float8_e4m3fnuz`, `Float8_e5m2`, `Float8_e5m2fnuz`, `Float8_e8m0fnu` as
   `_MojoScalarType(..., 1, is_float=True)`, and expose them on `DType` so
   `DType.float8_e3m4` and `size_of[DType.float8_e3m4]()` (which is 1) work.
2. Give them the lowered spellings the canonical case quotes (`f8e3m4`,
   `f8e4m3fn`, ... ; `f32`, `f16`, `bf16` for the implemented ones) so the
   diagnostic can be worded as Modular words it. The spelling table belongs
   next to the types, and `mojo/middle/types.py` / `formal/model/types.py`
   already carry the same family for the other paths — do not invent a second
   list of dtypes if one of those can be imported or mirrored once.
3. Refuse a coercion to/from an unimplemented float8 in
   `Interpreter._coerce_to_declared_type` (the same place the other scalar
   coercions live): `conversion from 'f8e3m4' to 'f32' is not implemented`.
4. Refuse a binary operation with an unimplemented float8 operand in
   `Interpreter._apply_binary_op` (`myinterpreter.py:9318`):
   `operation with a type 'f8e3m4' is not implemented`.
5. Add `test_regress_gpu_offload_validation_modular_part8.py`.

## Acceptance

- `print(size_of[DType.float8_e3m4]())` prints `1` at exit 0, and
  `DType.float8_e3m4` resolves (it currently raises `AttributeError`).
- `var a: Float8_e3m4 = 1.0; var b: Float32 = a` exits non-zero with
  `conversion from 'f8e3m4' to 'f32' is not implemented`, no traceback.
- `var a: Float8_e3m4 = 1.0; var b: Float8_e3m4 = 2.0; print(a + b)` exits
  non-zero with `operation with a type 'f8e3m4' is not implemented`.
- An implemented dtype still works on both paths (`Float32`/`Float16`/`BFloat16`
  conversion and arithmetic unchanged).

## Done when

`python3 test_regress_gpu_offload_validation_modular_part8.py` exits 0. It runs the three probes
above through `tools/memslot.py --gb 8` + `python3 fire.py run` (three
interpreter runs, ~3 s, < 0.1 GB peak) and asserts `size_of` on the family, the
conversion refusal and the operation refusal.

## Out of scope

- The NVPTX half of the canonical case (`--target-accelerator nvidia`,
  `-emit=llvm` on `nvptx64`): target-specific, no device toolchain in this
  tree; the triage row records it as the follow-up that needs one.
- The compiled path's lowering of these dtypes
  (`mojo/middle/types.py`/`emit_exprs.py`): the triage row's "verify host path
  first" is this part; the compiled path gets its own doc if it still accepts
  the conversion afterwards.
- The rest of the float8 arithmetic surface (no conversion TO float8 either):
  the refusal is the deliverable, not an implementation.
