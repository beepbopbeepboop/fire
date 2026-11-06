# plan/step-07a: `csinc` / `csinv` / `csneg` in the machine model, step table and fuzzer
Class: mid      Size: M      Depends: 00a, 00b      Blocks: 07b
Source: `bugs/FORMAL_arm64_instruction_coverage.md` (the CSEL neighbours; `csinc` 3,014 in the 2026-10-05 reading).

## Current state (measured; verified 2026-11-05)
- Encoders exist and are byte-exact: `formal/arm64.py:1166/1173/1180` `encode_csinc_xd_xm_cond`, `encode_csinv_xd_xm_cond`, `encode_csneg_xd_xm_cond(xd, xn, xm, cond)`; `test_arm64_encoders.py:86-93` sweeps them against `as` (4 register triples x 6 conditions). Bases: CSINC `0x9A800400`, CSINV `0xDA800000`, CSNEG `0xDA800400`; field layout as CSEL (`Rm<<16 | cond<<12 | Rn<<5 | Rd`). They have no caller outside the test: `python3 tools/arm64_insn_audit.py` lists all three under "encoders no lowering emits".
- Re-measured 2026-11-05 (`python3 tools/arm64_insn_audit.py --top 80`; 4,129,102 instr, 200 binaries): `csinc` 3,255, `cinc` 2,060 (assembler alias: `csinc Rd, Rn, Rn, inv(cond)`), `csinv` 483, `csetm` 164 (alias of csinv), `csneg` 362, `cneg` 522 (alias of csneg). `cset` is a `csinc` with `Rn=Rm=XZR`.
- Model: no `arm64_step` arm. The CSEL arm (`lib/ProofLib.lean` ~2914, mask `0xffe00c00`/base `0x9a800000`) is the template: `some (arm64_set_reg rd s (if arm64_matches_condition cond s.nzcv then arm64_reg rn s else arm64_reg rm s))`, `cond = ((insn >>> 12) &&& 0xf).toNat` — the RAW field, no inversion.
- Overlap (computed 2026-11-05 against the current table): the CSINC mask/base `(0xffe00c00, 0x9a800400)` overlaps exactly ONE row, CSET (`position 30`, `(0xffff0fe0, 0x9a9f07e0)`: a CSET word has bit 10 set, so it satisfies the CSINC test). CSINV and CSNEG overlap nothing. The CSET arm is earlier in both `arm64_step` and `_STEP_CONDS`, which is what `audit_step_table` requires of an overlap; `_step_facts` already leaves a shadowed row unconstrained.
- Stale text to fix: `lib/ProofLib.lean` ~2920 comment "(…and the CSINC/CSNEG/CSINV encoders do the same)" is fine; the CSEL arm comment says only CSEL changes `work_step_csel`.

## Decisions already made
- Three rows APPENDED to `_STEP_CONDS` (positions `len` at landing; after 06b that is **84 csinc, 85 csinv, 86 csneg**; take the next free numbers if 06b has not landed), masks `0xffe00c00`, bases `0x9a800400`, `0xda800000`, `0xda800400`. Three arms appended after the last arm of `arm64_step` (after the CCMP arms if 06b landed, else after FCVTZS).
- Semantics (Lean): CSINC `if c then Xn else Xm + 1`; CSINV `if c then Xn else Xm ^^^ 0xffffffffffffffff`; CSNEG `if c then Xn else 0 - Xm` (write it `(0 : UInt64) - arm64_reg rm s`). Registers `Rn`/`Rm` = 31 read as zero (`arm64_reg`), exactly like CSEL. No flags, memory, pc, sp change.
- **No `work_step_*` library theorem and no `hne_` fact is added.** Arms are last, so no existing lemma changes; the generator takes the generic `_step_facts` path for rows absent from `_WORK_STEP`. (If someone later wants a lemma, it goes in `lib/Scaffold.lean` per S1 if it carries a hole, else `lib/ProofLib.lean`; the `hne_` chain is emitted by `tools/lean_hne_chain.py` from step-03a.)
- The CSET<->CSINC relationship (`cset Xd, c` = `csinc Xd, xzr, xzr, inv(c)`) is stated ONCE, in a comment on the CSINC arm, and is checked by a test, not re-implemented: for every condition, the CSET word (`encode_cset_xd_cond`) and the CSINC word (`encode_csinc_xd_xm_cond(xd, 31, 31, inv(c))`) are the same word. (Verify this claim first: it should hold bit-for-bit; if it does not, the test's finding is the deliverable.)

## Work order
1. `lib/ProofLib.lean`: append the three arms (comment each: encoding, semantics, "RAW condition field", "last arm: no earlier lemma changes", the CSET overlap sentence on CSINC).
2. `formal/arm64_proof_gen.py`: (a) append three rows to `_STEP_CONDS`; (b) `_step_rhs`: one `if idx in (84, 85, 86):` branch, building the `if arm64_matches_condition <C> s.nzcv then arm64_reg <rn> s else <expr>` text from the concrete word, same style as the `idx == 69` CSEL branch (line ~4622); (c) `_regs_written`: add 84, 85, 86 to the tuple at line ~5884 that returns `{rd}`.
3. `test_formal_call_proof_gen.py`, next to `test_csel_is_modelled_and_disjoint_from_cset` (line 923): `test_csinc_csinv_csneg_are_modelled`. For all 14 conditions, Rd in 0..30, Rn/Rm in (0, 31): the word decodes to its row; `_regs_written == {rd}`; CSEL, CSET words do NOT decode to these rows (`_step_branch_index(cset_word) == 30`); the CSET==CSINC identity above.
4. `tools/formal_model_fuzz.py::gen_select` (line 496): extend to draw `csinc`/`csinv`/`csneg` (choice of 5 instead of the current coin flip: csel, cset, csinc, csinv, csneg) with text `"csinc x%d, x%d, x%d, %s"` and the `A.encode_*` call. This is the hardware oracle.
5. Run: `python3 tools/memslot.py --gb 16 --label t -- python3 tools/formal_model_fuzz.py --mix select --cases 400 --length 1 --seed 11` — 0 disagreements, 0 NOSTEP; paste the tally.
6. `tools/formal_isa_census.py`: the three encoders gain LEAN=yes and FUZZ=yes; `_ARM64_OVERRIDES` needs `encode_csinc_xd_xm_cond: (0, 3, 4, "eq")` etc. like the CSEL entry (line ~149) — add three lines. They remain unemitted until 07b, so they stay out of the census's emitted-form set (no BACKLOG row needed).
7. Pins (S4): run `test_formal_admitted.py`, `test_formal_axiom_closure_pinned.py`; update only measured, with `# step-07a`.

## Do NOT
- Do not give CSINC a row BEFORE CSET in the table, or widen CSET's mask; CSET must keep decoding to row 30.
- Do not invert the condition (that is CSET's `field +/- 1` trick); CSINC/CSINV/CSNEG take the raw field like CSEL.
- Do not write `Xm - 1` for csinc or `-Xm` via `UInt64.neg`; use `+ 1`, `^^^ 0xffffffffffffffff`, `0 - Xm` (the spellings the neighbouring arms use, which `bv_decide`/`simp` already handle).

## Verification
```
export PATH=/opt/homebrew/bin:$PATH
python3 -c "import formal.arm64_proof_gen as G; G.check_step_conds(); G.audit_step_table('lib/ProofLib.lean')"
python3 tools/memslot.py --gb 8 --label t -- python3 -m pytest -q test_formal_call_proof_gen.py -k "csinc or csel or ccmp"
python3 tools/memslot.py --gb 4 --label t -- python3 test_arm64_encoders.py
python3 tools/memslot.py --gb 16 --label t -- python3 test_formal_axioms.py
python3 tools/memslot.py --gb 16 --label t -- python3 tools/formal_model_fuzz.py --mix select --cases 400 --length 1 --seed 11
python3 tools/memslot.py --gb 8 --label t -- python3 test_formal_isa_census.py
```

## Done when
- [ ] table check passes; new test passes; library builds
- [ ] fuzz tally: 0 disagreements and 0 NOSTEP for `--mix select` (paste line)
- [ ] CSET stays row 30 (the test says so)

## If stuck
A fuzz disagreement on a CSET/CSINC overlap word means an arm's order or a mask is wrong: write the case and both flag/register values into "Blocked", fix your own arm text by editing it (never `git checkout`/`stash`), and stop if it still disagrees.
