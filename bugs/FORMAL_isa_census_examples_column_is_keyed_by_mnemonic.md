# FORMAL_isa_census: the EX column identifies a form by its DISASSEMBLY MNEMONIC, so two encodings of one instruction are indistinguishable

**Area:** `tools/formal_isa_census.py` — the optional `EX` column
(`measure_examples` / `_image_mnemonics` / `_encoder_mnemonics` /
`_forms_in_image`). Found 2026-10-05 by the `-14` round's own reading; kept alive
here on 2026-10-13 when the x86-64 ISA-backlog document was deleted (its
subject — 18 emitted forms with a missing column — is closed, but this defect is
about the instrument, not about any one form).

## What it is

`EX` answers "does any proved example's image contain this form". The image's
instructions are read out of `otool -tv` and the encoder table is assembled from
canonical words and disassembled the same way; both sides are reduced to the
FIRST TOKEN of the disassembly (`_encoder_mnemonics`) or to the token of each
image line (`_image_mnemonics`), and `_forms_in_image` intersects the two sets.

Two encodings that print the same mnemonic therefore cannot be told apart. The
measured case is x86-64 `imul`:

* `encode_imul_r64_r64_imm` emits `6B /r ib` (the four-byte `imulq $7, %rbx, %rax`
  spelling);
* the decoder's original `imul` arm was `0F AF` (`imulq %rax, %r11`).

Both disassemble to a line whose first token is `imul`, so the census claimed
`encode_imul_r64_r64_imm` appeared in eight images that in fact contained only
the `0F AF` form. That was a **false attribution** and it was read as the fix's
motivation for a while (the doc it came from records this directly).

## Why it is off the ratchet, and why it is still worth fixing

`EX` is `?` unless `--examples` has been run, and `Row.missing()` does not read
it, so it cannot fail `test_formal_isa_census.py`. That is why it has been
"reported rather than fixed" for several rounds. It is still worth fixing
because the answer to "does this form appear in any proved image" is exactly the
question a person asks when deciding whether a form matters, and a column that
can answer it wrongly is worse than one that says `ambiguous`.

## The exact next step

Key the column on (mnemonic, operand shape), and report `ambiguous` where that
does not separate two encodings, as the deleted backlog doc's own note proposed:

1. `_encoder_mnemonics` returns `{encoder: (mnemonic, shape)}` where `shape` is
   the operand spelling with each register number erased (so `addsd %xmm1,
   %xmm0` and `addsd %xmm2, %xmm1` share a shape but `imulq $7, %rbx, %rax`
   and `imulq %rax, %r11` do not).
2. `_image_mnemonics` returns the same shape key per instruction line.
3. `_forms_in_image` reports a form present only when the shape matches, and
   records `ambiguous` for an encoder whose shape collides with another's.
4. Re-measure the `--examples` cache for both architectures (104 compiles, ~5 s
   on the cache's own measurement) and check the x86-64 `imul` row against the
   eight images by hand, since that is the case the current column gets wrong.

`test_formal_isa_census.py` is the ratchet for the three boolean columns; a
`shape` reading that a table has never seen should also be a test the day this
is fixed, so the false `imul` attribution cannot come back.
