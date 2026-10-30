# x86-64 decoder refuses SIB-indexed memory operands

## What was seen

`python3 test_formal_sweep_truth.py` on 2026-10-29: every end-to-end test on
an example failed with `ValueError: body does not decode`, from
`formal/x86_64_endtoend_test.py::_plan`. `D.decode_all` raised
`DecodeError: SIB with index 1 is not emitted` at the float-repr helper's
`mov byte [r11+rcx], r9b` (bytes `45 88 0c 0b`), reached because `_body` swept
linearly past the end of the entry function into the helper.

## Cause

Commit `a2135f390` added the x86-64 float-repr helper, emitted unconditionally
after every function body. It uses SIB-indexed memory forms
(`encode_mov_rm8_r8_idx`, `encode_movzx_r64_rm8_idx`). `formal/x86_64_decode.py`
decodes a SIB byte only when its index field is 4 (no index) and refuses
everything else (`_modrm_fields`, line ~133).

## What landed

The sweep no longer walks into the helper: the backend publishes
`info["float_repr_addr"]`, and `x86_64_decode.body_end(info)` bounds a body at
the first string or the helper. Both `_body` (end-to-end) and
`x86_64_proof_gen._decode_function_body` use it. The bound is correct because
nothing in a body falls through into the helper (it is reached only by `call`).

## What remains

The decoder still does not read SIB-indexed operands, so any future body that
contains one (a helper emitted before the entry, or a body the bound does not
cut) is refused rather than decoded. The model also has no step lemma for these
forms, so decoding alone would not be enough: the form needs both a decode arm
and a `x86_step` lemma in `formal/x86_64.py`/`lib/X86.lean`.

## Next step

Add the SIB-index form to `_modrm_fields` (base + index*scale, scale from SIB
bits 7:6), a `form` for `mov r/m8, r8` and `movzx r64, r/m8` with an indexed
operand, and a step lemma in the model. Test: `test_formal_sweep_truth.py`
`TestX86EndToEndEmitter` on a program whose entry body contains an indexed
store, and the float-repr helper's own bytes decoded in full.
