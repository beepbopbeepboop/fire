# FORMAL isa census: the EX column matches an image by DISASSEMBLY MNEMONIC, so two encodings of one instruction are indistinguishable

**Area:** `tools/formal_isa_census.py` — the `EX` (examples) column, via
`_encoder_mnemonics` + `_forms_in_image`. **Found** 2026-10-05 by
`work/formal42-5`, carried by `bugs/FORMAL_x86_64_instruction_coverage_backlog.md`
and recorded here when that backlog closed (2026-10-12, `work/formal300-docs`),
because the backlog is empty but this instrument inaccuracy is not fixed.

## What it is

`_encoder_mnemonics(arch, ...)` assembles each encoder's canonical word, runs
`otool -tv`, and keeps only the FIRST TOKEN of the disassembly as that encoder's
mnemonic. `_forms_in_image(image, table)` then reports every encoder whose
mnemonic occurs anywhere in the image:

    return [(mn, name) for name, mn in sorted(table.items()) if mn in have]

So the column answers "does this image contain an instruction whose mnemonic is
`imulq`", not "does this image contain the ENCODING this encoder produces". Two
encodings of one instruction with the same mnemonic read as one.

## The measurement

The backlog's own case: `encode_imul_r64_r64_imm` emits `6B /r ib` (the
three-operand `imul r64, r/m64, imm8`), while `encode_imul_r64_r64` emits
`0F AF /r` (the two-operand form). Both disassemble with the mnemonic `imulq`,
so `_forms_in_image` attributed images containing only `0F AF`
(`imulq %rax, %r11`) to the `6B` row — which is why the row's old exemption
claimed "8 examples are blocked from being walked" for a form those examples
never contain. 39 of the 52 examples emit a `terminates` theorem today.

## Why it no longer misleads, and why it is still worth fixing

`encode_imul_r64_r64_imm` is now `yes/yes/yes` (LEAN/FUZZ/AS) and is no longer
exempted, so no coverage verdict rests on the EX column. The column is
informational, and its inaccuracy is invisible to every test: it changes a
printed example list, not a `missing()` result. That is exactly why it was
"reported rather than edited" while the backlog stood — and why it is filed here
rather than left to be re-derived.

## The exact next step

Key the column on (mnemonic, operand shape) and report `ambiguous` where that
does not separate two encodings — the fix the deleted backlog doc names. It
needs the `--examples` cache re-measured for both architectures (cheap: 104
compiles, ~5 s). A pinning test belongs in `test_formal_isa_census.py`: two
encoders sharing a mnemonic whose images differ must not both be reported for an
image containing only one, and a shared-mnemonic pair that cannot be separated
must read `ambiguous` rather than one of the two.
