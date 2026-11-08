# plan/step-06b: `ccmp` in the machine model: `arm64_step` arms, `_STEP_CONDS` rows, `_step_rhs`, `_regs_written`
**Status: DONE 2026-11-06 (measured).** `arm64_step` has CCMP (reg and imm) arms (`lib/ProofLib.lean`, appended after FCVTZS); `check_step_conds()` is silent (no drift); `lib/` builds clean (`ensure_library`, 2026-11-06); hardware oracle `tools/formal_model_fuzz.py --mix flags`: AGREE 200/200 (seed 11, length 1) and 600/600 (seed 23). Fixed on the way: the fuzz harness built `Arm64State` without `d0..d7` (every Lean eval depended on `sorry`).
Class: mid      Size: M      Depends: 00a, 00b, 06a      Blocks: 06c
Source: `bugs/FORMAL_arm64_instruction_coverage.md` ("the four-things rule": encoder, machine model, proof tables, lowering).

## Current state (measured; verified 2026-11-05)
- `lib/ProofLib.lean` `def arm64_step` (line 2097) is one `if/else if` chain; its LAST arm before `else none` is FCVTZS (`0x9e780000`, ~line 3010). Flags live in `Arm64State.nzcv : UInt8` in the order **N=bit0, Z=bit1, C=bit2, V=bit3** (see `arm64_matches_condition` line 1954 and `arm64_subs_flags` line 1977: `diff = 0 -> 0x2`, sign -> `0x1`, `a >= b -> 0x4`, overflow -> `0x8`). The CCMP instruction's `#nzcv` immediate is architectural: N=8, Z=4, C=2, V=1. **The bit order is reversed**; this is the trap in this step.
- `formal/arm64_proof_gen.py` `_STEP_CONDS` has 82 rows after step-00b (positions 0..81; last = STRB regoff at 81, FCVTZS at 79). New rows are APPENDED (comment at ~4175: "a new instruction goes last").
- Rows are consumed by position in: `_step_rhs` (line ~4390; returns the Lean `some ...` text for a concrete word; `None` = unmodelled), `_regs_written` (line ~5852; GPRs written, `set()` for none; the tuple on line ~5855 `if idx in (0, 13, 14, 16, 17, 34, 35, 51, 67)` is the "writes no GPR" list), and `_step_facts` (generic: excludes every other row per word with `native_decide`, so NO per-instruction library lemma is needed for the generator to work).
- `check_step_conds()` (line ~12410) fails if `_STEP_CONDS` and the `else if (insn &&& M) = B` conditions of `arm64_step` (parsed by `_decoder_branch_conds`) differ as SETS; `audit_step_table` (line 5270) additionally requires that when two rows can match one word, the earlier TABLE row is tested earlier in Lean.
- Words: `ccmp x1, x2, #4, eq` = `0xfa420024`; `ccmp x1, #5, #0, ne` = `0xfa451820`. Register form: bit 11 = 0; immediate form: bit 11 = 1; bit 10 (o2) and bit 4 (o3) must be 0. Mask `0xffe00c10` keeps bits 31:21, 11, 10, 4.
- Overlap check (computed 2026-11-05 over the current table): neither CCMP mask/base overlaps ANY existing row, so no ordering constraint applies; `audit_step_table` re-checks it.

## Decisions already made
- Two rows, appended: **82 = CCMP register** `(0xffe00c10, 0xfa400000)`, **83 = CCMP immediate** `(0xffe00c10, 0xfa400800)`. (If another step landed rows first, take the next free numbers; the rule is `len(_STEP_CONDS)` at landing.)
- Model arms are appended after the FCVTZS arm, before `else none`. **Because they are last, no existing `work_step_*` lemma changes and no `hne_` fact is added to any of them** (each lemma negates only arms BEFORE its own; `work_step_csel` at ProofLib ~7756 is the model: `hne_ret, hne_1.. hne_68` then `rw [if_neg ..., if_pos h]`). The generator needs no `work_step_*` lemma for a row (it uses `_step_facts`), so **no `work_step_ccmp*` theorem is written in this step**; if a library lemma is wanted later, it is a Scaffold/ProofLib follow-up and uses `python3 tools/lean_hne_chain.py --mask M --value B` (step-03a) to emit the `hne_` chain.
- Semantics, written exactly: `nzcv' = if arm64_matches_condition cond s.nzcv then arm64_subs_flags (arm64_reg rn s) OP2 else NZCV_MODEL`, where `cond = (insn >>> 12) &&& 0xf`, `OP2 = arm64_reg rm s` (register form) or `UInt64.ofNat ((insn >>> 16) &&& 0x1f)` (immediate form), and `NZCV_MODEL` is the architectural `insn &&& 0xf` **bit-reversed** into the model's order. Nothing else changes (no register, no memory, no pc; the run loop adds pc+4).
- Register 31 in `Rn`/`Rm` is XZR (`arm64_reg 31 s` is the zero read, as in the CMP arm).
- 32-bit CCMP (`0x7a400000`) and `ccmn` stay unmodelled and keep falling to `_unmodelled_instruction` -> `None`.

## Work order
1. `lib/ProofLib.lean`: append the two arms after the FCVTZS arm. Lean text (register form; the immediate form differs only in the mask/base and OP2):
```
  -- CCMP Xn, Xm, #nzcv, cond: 0xFA400000 (register form; imm form 0xFA400800)
  else if (insn &&& 0xffe00c10) = 0xFA400000 then
    let rn := ((insn >>> 5) &&& 0x1f).toNat
    let rm := ((insn >>> 16) &&& 0x1f).toNat
    let cond := ((insn >>> 12) &&& 0xf).toNat
    let i4 := (insn &&& 0xf)
    let rev := ((i4 >>> 3) &&& 1) ||| (((i4 >>> 2) &&& 1) <<< 1) ||| (((i4 >>> 1) &&& 1) <<< 2) ||| ((i4 &&& 1) <<< 3)
    some { s with nzcv := if arm64_matches_condition cond s.nzcv
                          then arm64_subs_flags (arm64_reg rn s) (arm64_reg rm s)
                          else rev.toUInt8 }
```
   with a comment block in the file's style: the semantics, the bit-order warning, "appended last so no earlier `work_step_*` lemma changes".
2. `formal/arm64_proof_gen.py`: (a) append the two rows to `_STEP_CONDS` with comments `# 82 CCMP Xn, Xm` / `# 83 CCMP Xn, #imm5`; (b) `_step_rhs`: add `if idx in (82, 83):` returning `some { s with nzcv := if arm64_matches_condition <C> s.nzcv then arm64_subs_flags (arm64_reg <rn> s) <OP2> else <REV> }` where `<C>`, `<rn>`, `<OP2>` are the concrete numbers read from the word (same style as the CSEL branch at `idx == 69`) and `<REV>` is the Python-computed model-order literal (e.g. `(0x5 : UInt8)`; compute it with a small helper `_ccmp_model_nzcv(i4)` defined next to `_step_rhs`, and unit-test it); the printed `rev.toUInt8` must be defeq to this literal — write it as the same `rev` expression evaluated, or check by `decide` in the test below; (c) `_regs_written`: add `82, 83` to the "writes no GPR" tuple.
3. `test_formal_call_proof_gen.py` (class `TestGeneratorSource`, next to `test_csel_is_modelled_and_disjoint_from_cset`): `test_ccmp_is_modelled`. Assert, for words built with the 06a encoders over all 14 conditions and Rn/Rm/imm5 corners: `_step_branch_index(w) == 82` (resp. 83); `_regs_written(w, 82) == set()`; the mask keeps bits 11, 10 and 4; `_ccmp_model_nzcv` is a bijection on 0..15 that maps architectural N(8)->1, Z(4)->2, C(2)->4, V(1)->8; no CSEL/CSET/CSINC word decodes to 82/83.
4. Hardware oracle (this is what keeps the arm TRUE): `tools/formal_model_fuzz.py` — add `gen_ccmp(rng, free)` returning `("ccmp x%d, x%d, #%d, %s" % ..., A.encode_ccmp_xn_xm(...))` and the immediate form, drawing `nzcv` 0..15 and `cond` from `CONDS`; add it to the `"flags"` mix (`MIXES["flags"] = (gen_flags, gen_alu, gen_ccmp)`). Flags must be seeded non-trivially: `gen_flagseed` (line ~697) already precedes cases; read it to make sure both outcomes of the condition occur.
5. Run the fuzz mix (Lean-backed, slow; this is the soundness check): `python3 tools/memslot.py --gb 16 --label t -- python3 tools/formal_model_fuzz.py --mix flags --cases 400 --length 1 --seed 11` — expect 0 DISAGREE and 0 NOSTEP. Paste the tally line into this file's Done section.
6. Pins (S4): the library changed. Run `test_formal_admitted.py`, `test_formal_axiom_closure_pinned.py`; if (and only if) they fail on a count that moved because of this edit, update from the measured value with a `# step-06b` comment.

## Do NOT
- Do not copy the immediate `#nzcv` into the model unreversed. A model with N and Z swapped passes every test that never uses a condition reading those bits (`eq` after a failed `cc` ...): the fuzz cases in item 4 must include `mi/pl/eq/ne/lt/ge` outcomes.
- Do not insert the arms in the middle of the chain (every `work_step_*` lemma after the insertion point would need new `hne_` facts and the file would not elaborate).
- Do not write a `work_step_ccmp` theorem with `sorry` in `lib/ProofLib.lean` (S1: the only home of a scaffold hole is `lib/Scaffold.lean`); this step needs none.
- Do not touch `_WORK_STEP`: a row absent from it takes the generic path, which is correct.

## Verification
```
export PATH=/opt/homebrew/bin:$PATH
python3 -c "import formal.arm64_proof_gen as G; G.check_step_conds(); G.audit_step_table('lib/ProofLib.lean'); print(len(G._STEP_CONDS))"   # 84
python3 tools/memslot.py --gb 8 --label t -- python3 -m pytest -q test_formal_call_proof_gen.py -k "ccmp or csel or sp_encodings"
python3 tools/memslot.py --gb 16 --label t -- python3 test_formal_axioms.py
python3 tools/memslot.py --gb 16 --label t -- python3 tools/formal_model_fuzz.py --mix flags --cases 400 --length 1 --seed 11
python3 tools/memslot.py --gb 8 --label t -- python3 test_formal_isa_census.py
```

## Done when
- [ ] `check_step_conds()` and `audit_step_table()` pass with 84 rows
- [ ] `test_ccmp_is_modelled` passes; the library builds
- [ ] fuzz tally for `--mix flags` shows 0 disagreements, 0 NOSTEP (paste the line)
- [ ] pins updated only if they moved, each with a measured value

## If stuck
If the fuzz disagrees, minimise with `tools/formal_model_fuzz.py`'s `minimise` output, write the case and both flag values into this file under "Blocked", and stop: do not edit the arm until the disagreement is understood (a wrong arm is worse than none).
