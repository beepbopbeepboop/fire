# the ISA census's EX column matches a form to an image by disassembly MNEMONIC, so two encodings of one instruction are indistinguishable

**Area:** `tools/formal_isa_census.py`, the `EX` column (`_image_mnemonics`,
`_encoder_mnemonics`, `_forms_in_image`). **Found 2026-10-05** while closing the
x86-64 backlog (the former instruction-coverage-backlog doc, deleted 2026-10-08
with the fix of the other two instrument defects it named), **reported there
rather than edited** while the census was a shared write set. It is filed here
so the finding survives the deletion of the doc that carried it.

## What it is

`_encoder_mnemonics` assembles each encoder's canonical word and disassembles it,
keeping the FIRST TOKEN of the disassembly as the encoder's mnemonic.
`_image_mnemonics` does the same for every instruction `otool` finds in a built
example image. `_forms_in_image` then answers "is this form in this image" with a
set intersection of those mnemonic strings — so two encodings that print the SAME
mnemonic are indistinguishable.

The measured case is the one the deleted doc already quoted: the row for
`encode_imul_r64_r64_imm` claimed **"8 examples are blocked from being walked"**,
and those eight images contain only `0F AF` (`imulq %rax, %r11`). The encoder the
row is about emits `6B /r ib` (`imulq $7, %rbx, %rax`), which the backend does not
emit for those images at all. Both spellings disassemble with the first token
`imulq`, so the EX column credits the `6B` encoder for images that contain only
the `0F AF` form — an attribution the corpus does not support.

## Why it matters, and what it does not

It is an **over-attribution in an informational column**, not a wrong verdict:
the `EX` column is `?` unless `--examples` has been run, and no gate test reads
it. But it is exactly the "a stale attribution is a coverage claim" failure this
census exists to prevent — it let a row's own justification (a corpus that uses
it) be false without anything saying so.

## The exact next step

Key the column on `(mnemonic, operand shape)` rather than on the mnemonic alone:
capture the operand text along with the mnemonic on both sides and match on both,
and report the cell as `ambiguous` where two encoders of one mnemonic share an
operand shape (so the reading is honest about what it cannot separate rather than
picking one). `_forms_in_image` and the two `_*_mnemonics` readers are the three
functions, and `tools/formal_isa_census_examples.json` (the `EX` cache) has to be
re-measured for both architectures afterwards — `python3
tools/formal_isa_census.py --examples`, ~104 compiles and cheap. A regression row
belongs in `test_formal_isa_census.py` that asserts the `imulq` spelling pair is
NOT credited to the same image.

## Not part of this, and already handled elsewhere

The deleted doc also named a fuzz-attribution hole ("`_impossible_on_hardware`
explains a flag difference only when the program's LAST flag-writing instruction
is a multiply or divide"). That is no longer reachable: `formal/x86_64_model_fuzz.py`'s
`_taint` now propagates an undefined operand into the flags of every ALU form
(`flags = set(_FLAGS4) if src else set()`), so a flag set by an `and` over an
undefined register is skipped rather than reported `WRONG`. Nothing is filed for
it.
