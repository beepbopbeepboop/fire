# The extend-option census of the extended-register class is a runnable test, not a docstring (part 1)

Part 1 of `bugs/hard/FORMAL_arm64_instruction_coverage.md`.
Class: easy — a test class and nothing else; no production change.

The original doc is RESOLVED for its first three parts (`3049e7aa7`,
`2a3ab7d27`, `aca4f2bbf`). The one item it deliberately leaves open is the
census of the *other* extend options in the extended-register
`ADD`/`SUB`/`SUBS` class (UXTW/SXTW/SXTX — and the 8/16-bit sign/zero
extends, the 32-bit spellings, and the `imm3 <= 4` half of the "option=011,
imm3 <= 4" qualifier), which the `lib/ProofLib.lean` coverage note says
"remain outside the model and are refused rather than mis-read", with this
doc named as where their census belongs. Today that census exists only as
prose; the one machine-checked pin in the tree is
`test_the_sp_encodings_are_named_rather_than_left_unnamed`, which pins a
single non-UXTX spelling.

## Measured (2026-11-14, this tree)

Each word assembled with clang (`-target arm64-apple-macos11`), then asked of
`formal/arm64_proof_gen.py` (`_step_branch_index`, `_step_rhs`,
`_unmodelled_instruction`). Fields: sf = bit 31, option = bits 15-13,
imm3 = bits 12-10:

| spelling | word | idx | rhs | named by `_unmodelled_instruction` |
|---|---|---|---|---|
| `add x0, x1, x2, uxtx` | `0x8b226020` | 86 | yes | — (modelled) |
| `add x0, x1, *2, uxtb` / `uxth` / `uxtw` / `sxtb` / `sxth` / `sxtw` / `sxtx` | `0x8b220020` / `2020` / `4020` / `8020` / `a020` / `c020` / `e020` | None | None | ADD extended |
| `sub x0, x1, *2, uxtx` | `0xcb226020` | 87 | yes | — (modelled) |
| `sub x0, x1, *2, uxtb` / `uxth` / `uxtw` / `sxtb` / `sxth` / `sxtw` / `sxtx` | `0xcb220020` … `e020` | None | None | SUB extended |
| `subs x0, x1, *2, uxtx` | `0xeb226020` | 88 | yes | — (modelled) |
| `subs x0, x1, *2, uxtb` / `uxth` / `uxtw` / `sxtb` / `sxth` / `sxtw` / `sxtx` | `0xeb220020` … `e020` | None | None | SUBS/CMP extended |
| `cmp x1, x2, sxtx` | `0xeb22e03f` | None | None | SUBS/CMP extended |
| `add w0, w1, w2, uxtx` (sf=0, option=011) | `0x0b226020` | None | None | ADD extended |
| `add x0, x1, x2, uxtx #4` | `0x8b227020` | 86 | yes | — (modelled) |
| `add x0, x1, x2, uxtx #5` | clang refuses | — | — | — |

(`*` is `w` for the 8/16/32-bit options and the shifted W register operand; W
for uxtb/uxth/uxtw/sxtb/sxth/sxtw, X for uxtx/sxtx.)

The census must record these, and the test pins them:

- Rows 86-88 (`_STEP_CONDS`, mask `0xffe0e000`) pin bit 31 (sf) and the option
  field (bits 15-13 = 011) but NOT imm3 (bits 12-10): a hand-crafted UXTX word
  with imm3 = 7 (`0x8b227c20`) IS claimed by row 86 and `_step_rhs` answers
  with a shift of 7. The coverage note says "option=011, imm3 <= 4"; nothing
  in the tree pins the `imm3 <= 4` half of that qualifier.
- The refused words are NAMED by `_unmodelled_instruction` as
  "ADD extended" / "SUB extended" / "SUBS/CMP extended" — the `why` explains
  the class but does not decode this word's option/imm3/*sf* (naming them is
  part 2, not this part).
- SP-in-Rn spellings in a refused option (`add sp, x1, w2, uxtw` = `0x8b22403f`,
  `add x0, sp, w2, sxtw` = `0xcb22c3e0`) behave the same: unclaimed, named.

## Goal

`test_formal_call_proof_gen.py` gains a `TestExtendOptionCensus` class that
assembles every spelling in the table above (all 8 options × the three ops at
64-bit width; the three 32-bit `uxtx` spellings; UXTX imm3 0-4; one imm3>0
non-UXTX spelling per op; one unallocated-imm3 UXTX word assembled by hand) and
asserts the disposition word by word: 64-bit UXTX → rows 86-88 with a non-None
`_step_rhs`; everything else → `_step_branch_index` None, `_step_rhs(...) is
None`, and `_unmodelled_instruction`'s name in the class's set. A word whose
disposition changes fails loudly, with the option field decoded in the
failure message.

## Acceptance

- Every option value 0-7 for the three ops is in the census; nothing is
  silently skipped. A spelling clang refuses is asserted as a refusal, not
  dropped.
- 64-bit UXTX (imm3 0-4) → 86/87/88 with a non-None `_step_rhs`; the
  hand-crafted `0x8b227c20` (option=011, imm3=7) is pinned as claimed by row 86,
  labelled in the test as the unallocated-encoding caveat it is.
- Every non-UXTX word and every 32-bit word → `idx is None`, `_step_rhs(...) is
  None`, and `name in {"ADD extended", "SUB extended", "SUBS/CMP extended"}`.
- No production code changes;
  `python3 test_formal_call_proof_gen.py TestRegister31` stays green and the
  existing `test_the_sp_encodings_are_named_rather_than_left_unnamed` is
  untouched and green.

## Done when

File: `test_formal_call_proof_gen.py` (repo root)

Command: `python3 test_formal_call_proof_gen.py TestExtendOptionCensus`

It runs the new class and passes. It assembles one tiny probe per spelling
(like every `_assembler_word` pin in that file), so it runs in seconds.

## Where to start

`_assembler_word(form)` assembles a spelling and returns the word, or None
when clang refuses it. `test_the_sp_encodings_are_named_rather_than_left_
unnamed` is the pattern to copy (and to keep green). Option field = bits
15-13 (`(word >> 13) & 0x7`), imm3 = bits 12-10, sf = bit 31; the class's
option values are UXTB=0, UXTH=1, UXTW=2, UXTX=3, SXTB=4, SXTH=5, SXTW=6,
SXTX=7 (measured, clang).
