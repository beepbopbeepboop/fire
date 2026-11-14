# The extended-register refusal names the option the word carries, not "the other extend options" (part 2)

Part 2 of `bugs/hard/FORMAL_arm64_instruction_coverage.md`.
Class: easy — one arm of `_unmodelled_instruction` in
`formal/arm64_proof_gen.py`, plus a test.

## Measured (2026-11-14, this tree)

`_unmodelled_instruction`'s extended arm returns, for every refused word in
the class, the same name and the same `why`. `add x0, x1, w2, uxtw`
(`0x8b224020`), `add w0, w1, w2, uxtx` (`0x0b226020`, sf=0) and
`add x0, x1, w2, uxtw #4` (`0x8b225020`) all get `name="ADD extended"` and:

    A64's EXTENDED-register `ADD`/`SUB` — bits 28..24 = 01011 with bit 21 set —
    which is where the architecture keeps the SP encoding for `Rn`. ... This
    class is modelled for UXTX (option=011), 64-bit only; the other extend
    options remain unmodelled. Measured by assembling the spelling and running
    it: `add x0, sp, x1, uxtw` remains unmodelled while ...

Nothing in that message says WHICH option the word carries, what its imm3 is,
or that sf=0 is why an option=011 word (which the table also refuses) did not
reach rows 86-88. A reader holding a hex word — the exact position someone is
in when this refusal fires from `_cfg_decomposition_refusal` on an image the
emitter grew a new encoder for — has to re-decode by hand. The arm's
paragraph already explains the class; what is missing is the word's own
fields.

The existing pin
`test_the_sp_encodings_are_named_rather_than_left_unnamed` asserts
`name == "ADD extended"` and `"UXTX" in why` for `add x0, sp, w1, uxtw`; the
change must keep both (the why keeps its "modelled for UXTX" sentence).

## Goal

`_unmodelled_instruction`'s extended arm decodes `sf` (bit 31), `option`
(bits 15-13) and `imm3` (bits 12-10) from the word and appends them to the
`why` it returns, by architectural name: the refusal names e.g.
`option=010 (UXTW), imm3=0`, or, for sf=0,
`32-bit, option=011 (UXTX), imm3=0`. The `name` stays "ADD extended" /
"SUB extended" / "SUBS/CMP extended"; the BLR, STUR and LDUR arms and the
fall-through arm are untouched; the message is a statement about the word,
not about clang.

## Acceptance

- `add x0, x1, w2, uxtw` → why names UXTW and imm3=0;
  `sub x0, x1, x2, sxtx #4` → why names SXTX and imm3=4;
  `cmp x1, x2, sxtx` → name is "SUBS/CMP extended" with SXTX and imm3=0;
  `add w0, w1, w2, uxtx` → why says 32-bit and UXTX.
- All eight option names are spelled as the architecture spells them
  (UXTB 000, UXTH 001, UXTW 010, UXTX 011, SXTB 100, SXTH 101, SXTW 110,
  SXTX 111); the decode is masked (`(word >> 13) & 0x7`), not positional
  guessing.
- `python3 test_formal_call_proof_gen.py TestRegister31` stays green; the
  BLR and STUR/LDUR messages are byte-identical; no table or model change.

## Done when

File: `test_formal_call_proof_gen.py` (repo root)

Command: `python3 test_formal_call_proof_gen.py TestExtendRefusalNamesTheOption`

It runs the new class and passes; each case is one `_unmodelled_instruction`
call on a word assembled once by `_assembler_word`, so it is instant.

## Where to start

`formal/arm64_proof_gen.py::_unmodelled_instruction`, the arm that starts
`if (((word >> 21) & 0x7) == 0x1 and ((word >> 24) & 0x1f) == 0x0b):` —
`option = (word >> 13) & 0x7`, `imm3 = (word >> 10) & 0x7`,
`sf = (word >> 31) & 0x1`. Keep the existing paragraph and append the decode
at the end of the `why`, mirroring the existing one-line style of the other
arms' messages.
