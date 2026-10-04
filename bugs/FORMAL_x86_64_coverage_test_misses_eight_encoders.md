# The x86-64 coverage test's sample list misses eight emittable encoders

**Status**: open. One of the eight (`mov r/m32, r32` with an `r8`-`r15`
register) is fixed here; the other seven cannot be added until
`formal/x86_64_decode.py` stops refusing them, which is the real half of this.

`formal/x86_64_model_coverage_test.py` states the property it checks as "every
byte sequence this backend can emit is one `x86_step` can step", and every
sample it runs is first put through `formal/x86_64_decode.py` so that a failure
is unambiguous. That design is what makes the gap below possible: the list is
hand-written, and a form nobody thought to write down is neither sampled nor
missed. It is not a coverage test that discovers encoders; it is a coverage test
that checks the ones somebody remembered.

`formal/x86_64_model_fuzz.py --census` enumerates the encoders instead, and in
one run found **nine** emittable forms `x86_step` could not step at all, plus
one form it decoded to the wrong successor. Eight of the encoders involved were
absent from this list.

## What was missed, and what each one cost

Fixed in this commit (the model is fixed too):

| encoder | what `x86_step` did |
|---|---|
| `encode_mov_r32_r32` / `encode_mov_rm32_r32` with an `r8`-`r15` register | resumed one byte early — the length of a REX-prefixed `89`/`8B` was computed as if there were no REX byte |

Not yet sampled, because `formal/x86_64_decode.py` rejects each of them (fixed
in `lib/X86.lean` in this commit; the decoder is the blocker):

| encoder | decoder's complaint | what `x86_step` used to do |
|---|---|---|
| `encode_mov_rm8_r8` | `undecodable byte 0x88` | no arm for opcode `88` at all |
| `encode_mov_rm16_r16` | `mov rm32, r32 with a memory operand is not emitted` | no arm behind the `0x66` prefix but `0F 6E` |
| `encode_movzx_r64_rm8` | `movzx_r64_r8 with a memory operand is not emitted` | resumed one byte into the displacement |
| `encode_movzx_r64_rm16` | same | same |
| `encode_movsx_r64_rm8` | same | same |
| `encode_movsx_r64_rm16` | same | same |
| `encode_movsx_r64_rm32` | `movsxd with a memory operand is not emitted` | resumed one byte into the displacement |
| `encode_mov_r32_rm32`, `encode_mov_rm32_r32` (memory) | same | same |

Every "is not emitted" in that table is **false**: the encoder emits it, and
`formal/x86_64.py`'s own docstrings say why each one exists (a `Pointer[UInt8]`
store must not overwrite the seven bytes after the pointee; a `Pointer[Int16]`
likewise; `Pointer[UInt8]`/`[Int16]`/`[Int32]` loads must not over-read).
`formal/x86_64_decode.py` is a second, hand-maintained description of what the
backend emits, and it has drifted.

## Why this matters beyond the seven rows

The decoder is the arbiter of "is this sample real". While it refuses a form, a
sample naming that form is reported as a **decoder** failure and the coverage
question is never asked — so adding the samples without fixing the decoder would
turn a green test red for the wrong reason, which is why this doc exists rather
than a larger `samples()`.

## Exact next step

1. Teach `formal/x86_64_decode.py` the eight forms above: `0x88` /r, the
   `66`-prefixed `89` /r, the memory forms of `0F B6`/`B7`/`BE`/`BF`, `REX.W 63`
   with a memory operand, and `8B`/`89` without REX.W. Each already has a decoder
   arm for its register form; the memory cases are the ones missing.
2. Then add the seven rows to `formal/x86_64_model_coverage_test.py`'s
   `samples()`, in the comment already left there naming them, so that a
   regression in any of them fails by name.

A regression guard that does not need step 1 is already in place:
`formal/x86_64_model_fuzz.py --census` builds one program per pool entry from the
encoders themselves, so a new `encode_*` is covered the moment it exists.
