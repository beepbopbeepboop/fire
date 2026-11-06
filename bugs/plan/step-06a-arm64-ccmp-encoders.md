# plan/step-06a: arm64 `ccmp` encoders (register and immediate), byte-exact against `as`
Class: easy      Size: S      Depends: none      Blocks: 06b
Source: `bugs/FORMAL_arm64_instruction_coverage.md` gap table row `ccmp` ("no encoder at all").

## Current state (measured; verified 2026-11-05)
- `grep -n -i ccmp formal/arm64.py` -> nothing: there is no `ccmp`/`ccmn` encoder. `tools/arm64_insn_audit.py` `FAMILIES` already names `ccmp` and `ccmn`, so the audit maps a new `encode_ccmp_*` to the right base with no table edit (`test_a_base_mnemonic_is_either_wired_or_named` checks this).
- Re-measured 2026-11-05 with `python3 tools/arm64_insn_audit.py --top 80` (4,129,102 instructions, 200 binaries, 9 s): `ccmp` 14,455 (the doc's 13,842 is the 2026-10-05 reading, over a different corpus); `ccmn` 92. Re-measure if you quote them.
- Words (assembled with `clang -arch arm64 -c`, read with `otool -t`, 2026-11-05): `ccmp x1, x2, #4, eq` = `0xfa420024`; `ccmp x1, #5, #0, ne` = `0xfa451820`; `ccmn x1, #5, #0, ne` = `0xba451820`. Layout: `0xFA400000 | Rm<<16 | cond<<12 | Rn<<5 | nzcv` (register), `0xFA400800 | imm5<<16 | cond<<12 | Rn<<5 | nzcv` (immediate; bit 11 set); `ccmn` is the same with `0xBA...`.
- Template encoders: `encode_csel_xd_xm_cond` / `encode_cmp_xn_xm` in `formal/arm64.py` (~1149); `_cond(cond)` maps a condition name to its 4-bit code and accepts aliases (`lo`, `hs`).
- Test table: `test_arm64_encoders.py::cases()` (line 77) returns `(assembler_text, our_bytes)`; `main()` assembles each text with `as` and compares.

## Decisions already made
- Add exactly TWO encoders, 64-bit only: `encode_ccmp_xn_xm(xn, xm, nzcv, cond)` and `encode_ccmp_xn_imm5(xn, imm5, nzcv, cond)`. Argument order = the mnemonic's operand order.
- `ccmn` is NOT added (92 occurrences = 0.002%; no planned lowering uses it; an encoder with no caller lands in the audit's "no lowering emits" list). Record this in the docstring of the register encoder.
- `nzcv` is the ARCHITECTURAL 4-bit immediate (N=8, Z=4, C=2, V=1). The Lean model stores flags in the opposite bit order (N=1, Z=2, C=4, V=8): 06b converts; the encoder does not.
- Bounds: `0 <= xn <= 31` (31 = XZR here), `0 <= xm <= 31`, `0 <= imm5 <= 31`, `0 <= nzcv <= 15`, `cond` any of the 14 names (reject `al`/`nv` via `_cond(...) != 14, 15`: read `_cond` to see what it returns for them and `assert` accordingly).

## Work order
1. `formal/arm64.py`: add the two encoders directly after `encode_csneg_xd_xm_cond`. Docstrings: what the instruction does (`if cond: flags = cmp(Xn, op2) else: flags = #nzcv`), the bit layout above, and the nzcv-order note.
2. `test_arm64_encoders.py::cases()`: new block `# ── CCMP ──` with, for every one of the 14 conditions (`eq ne cs cc mi pl vs vc hi ls ge lt gt le`) and `(xn, xm|imm5, nzcv)` in `((1,2,4),(30,31,15),(0,0,0),(5,31,8))` resp. `((1,5,0),(30,31,15),(0,0,2),(7,16,9))`: the pair `(f"ccmp x{xn}, x{xm}, #{nzcv}, {cond}", enc(...))` and `(f"ccmp x{xn}, #{imm5}, #{nzcv}, {cond}", enc(...))`. (`as` spells register 31 in a source slot as `xzr`; `ccmp x30, xzr, ...` — write `xzr` in the text when `xm == 31`.)
3. Add a refusal test in the same file next to `test_range_is_enforced`: `encode_ccmp_xn_imm5(1, 32, 0, "eq")`, `encode_ccmp_xn_xm(1, 2, 16, "eq")` raise `AssertionError`.
4. `tools/formal_isa_census.py::_ARM64_OVERRIDES`: add `"encode_ccmp_xn_xm": (3, 4, 4, "eq")` and `"encode_ccmp_xn_imm5": (3, 5, 4, "eq")` (the name rules cannot guess `nzcv`/`cond`).

## Do NOT
- Do not add the model arm, the table rows or a lowering here (06b, 06c).
- Do not use `a if c else b` style tricks to build the word; use the explicit OR of fields like the neighbouring encoders.
- Do not name an encoder in `test_the_survey_does_not_count_an_encoder_nothing_emits` (that test deliberately names none).

## Verification
```
export PATH=/opt/homebrew/bin:$PATH
python3 tools/memslot.py --gb 4 --label t -- python3 test_arm64_encoders.py
python3 tools/memslot.py --gb 4 --label t -- python3 test_formal_isa_census.py
python3 tools/arm64_insn_audit.py --top 5 | head -30     # ccmp still listed as uncovered; the two new encoders appear under "encoders no lowering emits"
```

## Done when
- [ ] `test_arm64_encoders.py` passes and its case count rose by 2*14*4 = 112 (compare the printed pass count before/after)
- [ ] `ccmp x1, x2, #4, eq` encodes to `0xfa420024` and `ccmp x1, #5, #0, ne` to `0xfa451820` (`python3 -c` one-liner)
- [ ] `test_formal_isa_census.py` is no worse than before (note its pre-existing failures first; the new unwired encoders must not add one)

## If stuck
If `as` rejects a spelling, print the error into this file's "Blocked" and stop; do not hand-assemble expected words.
