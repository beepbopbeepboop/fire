# Compiled (kgen) path accepts a conversion and an operation on an unsupported float8 dtype

Parent: `bugs/hard/GPU_offload_validation_modular.md`, row
`op_with_unsupported_type_error.mojo`, compiled host half. The interpreter
half of the same case is fixed (2026-11-15) and pinned by
`test_regress_gpu_offload_validation_modular_part8.py`; the old
`GPU_offload_validation_modular-part8` doc was deleted with that fix and
named this compiled half as the follow-up if it still accepted the
conversion — it does.

## Symptom

A scalar whose dtype has no conversion or arithmetic rule — the `float8`
family the canonical case uses (`float8_e3m4`) — is accepted and computed on
the COMPILED path, where Modular's kgen refuses it with:

    conversion from 'f8e3m4' to 'f32' is not implemented
    operation with a type 'f8e3m4' is not implemented

## Measured (2026-11-15, this worktree, HEAD `1e8dfb5dd`)

The two probes, compiled rather than interpreted (a bare `fire.py <file>`,
wrapped in `tools/memslot.py --gb 8`):

- `def main(): var a: Float8_e3m4 = 1.0; var b: Float32 = a; print(b)` →
  exit 0, prints `1.0`, no diagnostic: the conversion is silently a float
  copy, the annotation dropped.
- `def main(): var a: Float8_e3m4 = 1.0; var b: Float8_e3m4 = 2.0; print(a + b)`
  → exit 0, prints `3`, no diagnostic.

The same probes through `fire.py run` (interpreter) now refuse both with the
two Modular messages above, exit 1, no traceback — the interpreter half is
done; only the compiled path accepts them.

## Expected

The compiled path refuses both with the same two messages (non-zero exit, no
computed value), matching Modular's `kgen -emit=llvm` host behavior in the
canonical case.

## Next step

Add the same legality guard to the codegen lowering: the float8 dtype
family's conversions and binary ops must be refused where the lowering path
resolves scalar types (`mojo/middle/types.py`/`emit_exprs.py`, the
interpreter half's doc named these as the compiled path's home), worded with
the lowered spellings (`f8e3m4`, `f32`, ...). Pin with a regression test next
to `test_regress_gpu_offload_validation_modular_part8.py` that runs the two
probes above through `fire.py <file>` (compiled) wrapped in
`tools/memslot.py --gb 8`.

## Out of scope

- The NVPTX half of the canonical case (`nvptx64 … sm_89`): target-specific,
  no device toolchain in this tree; the parent triage gates it separately.
