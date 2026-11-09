# plan/step-09: arm64 extended-register `ADD`/`SUB`/`SUBS(CMP)` with `UXTX` (the SP class), modelled, no lowering
**Status: DONE 2026-11-06 (measured).** `arm64_step` has the UXTX extended-register ADD/SUB/SUBS arms (SP class; rd=31 is SP for ADD/SUB, XZR for SUBS). No lowering added: no emitter produces the class. `lib/` builds clean (`ensure_library`, 2026-11-06); `--mix alu`: AGREE 600/600 on two seeds. The fuzz uses REGISTER bases: SP-based forms cannot be compared (the model's SP is a fixed stand-in for the hardware's).
Class: mid      Size: M      Depends: 00a, 00b      Blocks: none
Source: `bugs/FORMAL_arm64_instruction_coverage.md` §"The one class the census cannot see: the EXTENDED-register `ADD`/`SUB`" (line ~436).

## Current state (measured; verified 2026-11-05)
- A64 keeps the SP encoding for `Rn` in the extended-register class (bits 28..24 = `01011`, bit 21 SET), not the shifted-register class the step table has (`0x8b000000`/`0xcb000000`/`0xeb000000`, bit 21 clear). Words assembled with `clang -arch arm64` on 2026-11-05: `add x0, sp, x1` = `0x8b2163e0`; `add x0, sp, x1, lsl #3` = `0x8b216fe0`; `cmp sp, x16` = `0xeb3063ff`; `add x0, sp, w1, uxtw` = `0x8b2143e0`. Layout: `sf op S 01011 00 1 Rm option(15:13) imm3(12:10) Rn Rd`. `option = 011` is UXTX (a.k.a. LSL for the 64-bit form); `option = 010` is UXTW, etc.
- Nothing this backend emits is in the class. `_unmodelled_instruction` (formal/arm64_proof_gen.py:8076) already NAMES it (`ADD extended`/`SUB extended`/`SUBS/CMP extended`; test `test_formal_call_proof_gen.py::TestRegister31.test_the_sp_encodings_are_named_rather_than_left_unnamed`, line 1684, asserts the four `_assembler_word(...)` forms above decode to `None` AND are named).
- Overlap (computed 2026-11-05): `(0xffe0e000, 0x8b206000)`, `(0xffe0e000, 0xcb206000)`, `(0xffe0e000, 0xeb206000)` overlap NO existing `_STEP_CONDS` row (bit 21 separates them from the shifted class).
- Lean helpers: `arm64_reg_or_sp i s` (ProofLib.lean:1837, `if i = 31 then s.sp else arm64_reg i s`), `arm64_reg` (31 reads zero), `arm64_set_reg` (31 is the identity = discard), `arm64_subs_flags`. State has `sp : UInt64`. There is no `arm64_set_reg_or_sp`; the ADD/SUB-immediate arm shows how the model writes SP (read it: `grep -n "ADD Xd, Xn, #imm12" lib/ProofLib.lean`).
- No encoder exists for this class, so the census/fuzz machinery (which keys on encoders) does not apply; the hardware oracle is a raw-word fuzz draw (below).

## Decisions already made
- Model ONLY `option = 011` (UXTX/LSL), 64-bit: three rows APPENDED (positions `len(_STEP_CONDS)` at landing; 87, 88, 89 if 06b and 07a landed first, else next free): ADD `(0xffe0e000, 0x8b206000)`, SUB `(0xffe0e000, 0xcb206000)`, SUBS/CMP `(0xffe0e000, 0xeb206000)`. The other options (UXTB/UXTH/UXTW/SXT*) and the 32-bit forms stay unmodelled and stay NAMED. The words of the doc table (`add x0, sp, x1`, `sub x0, sp, x1`, `subs x0, sp, x1`, `cmp sp, x16`) are all UXTX with imm3 = 0, so they become modelled.
- Semantics: `v = arm64_reg_or_sp rn s  OP  (arm64_reg rm s <<< UInt64.ofNat imm3)` with `imm3 = ((insn >>> 10) &&& 0x7).toNat`. ADD/SUB: `Rd = 31` is SP: `if rd = 31 then some { s with sp := v } else some (arm64_set_reg rd s v)`. SUBS: `Rd = 31` is XZR: `some (arm64_set_reg rd { s with nzcv := arm64_subs_flags a b } (a - b))` with `a` the SP-aware read (so `cmp sp, x16` works). `imm3 > 4` is an unallocated encoding the architecture rejects; the arm models it as the shift (deterministic) and the comment says it is never emitted (matches how the file treats other unreachable corners).
- NO lowering (the source doc: "not worth landing for an image no emitter produces"); the step records this decision in the arm comments and here.
- NO `work_step_*` theorem and no `hne_` facts: arms are last in the chain; the generator takes the generic `_step_facts` path.
- The naming test is UPDATED, not deleted: the four doc words now decode to the new rows; add a fifth form that remains unmodelled and named: `add x0, sp, w1, uxtw` (`0x8b2143e0`, still "ADD extended").

## Work order
1. `lib/ProofLib.lean`: append the three arms after the last existing arm (comment: class, option=011 only, SP semantics, measured words from "Current state").
2. `formal/arm64_proof_gen.py`: (a) append the rows; (b) `_step_rhs`: one branch for the three indices producing the concrete `some ...` text (use the literal `rn`, `rd`, `rm`, `imm3`; for `rd == 31` emit the `{ s with sp := ... }` form); (c) `_regs_written`: ADD/SUB rows return `{rd}` (31 = sp, per the function's own convention), SUBS row returns `{rd} if rd != 31 else set()` (add the SUBS index to the `(6, 66)` tuples at lines ~5865/5882 or give it its own `if`); (d) update `_unmodelled_instruction`'s docstring and message: the class is "modelled for UXTX; the other extend options remain unmodelled".
3. `test_formal_call_proof_gen.py`: rewrite `test_the_sp_encodings_are_named_rather_than_left_unnamed` as described (four forms -> `_step_branch_index` equals the new row, `_regs_written` as above; `uxtw` form -> `None` and named "ADD extended"). Add `test_extended_register_class_is_disjoint_from_shifted`: for a sweep of Rd/Rn/Rm in (0, 30, 31) and imm3 0..4, no shifted-register word (`0x8b000000|...`) decodes to the new rows and vice versa.
4. Hardware oracle: `tools/formal_model_fuzz.py` — add `gen_ext_sp(rng, free)` returning `("add x%d, sp, x%d, lsl #%d", struct.pack("<I", 0x8b206000 | (m<<16) | (k<<10) | (31<<5) | d))` and the sub/subs variants, `d` from `_dst` (never 31, SP is the harness anchor and must not move), `k` in 0..4; register it in the `"alu"` mix. Run: `python3 tools/memslot.py --gb 16 --label t -- python3 tools/formal_model_fuzz.py --mix alu --cases 400 --length 1 --seed 11` — 0 disagreements. (Check the harness: it asserts nothing about SP-relative reads other than anchoring; read `gen_mem` for how it treats SP-based accesses before relying on the value comparison.)
5. Pins (S4) as in step-06b item 6.

## Do NOT
- Do not widen the mask to `0xffe00000`/include `option`: that would claim UXTW/SXTW words (`add x0, sp, w1, uxtw`) with the wrong semantics (they zero/sign-extend the register operand).
- Do not write SP through `arm64_set_reg 31` (the identity: the write would be silently dropped).
- Do not add an encoder or a lowering. (An encoder with no caller is exactly the "not an instruction" failure the audit exists to catch.)

## Verification
```
export PATH=/opt/homebrew/bin:$PATH
python3 -c "import formal.arm64_proof_gen as G; G.check_step_conds(); G.audit_step_table('lib/ProofLib.lean')"
python3 tools/memslot.py --gb 8 --label t -- python3 -m pytest -q test_formal_call_proof_gen.py -k "sp_encodings or extended_register"
python3 tools/memslot.py --gb 16 --label t -- python3 test_formal_axioms.py
python3 tools/memslot.py --gb 16 --label t -- python3 tools/formal_model_fuzz.py --mix alu --cases 400 --length 1 --seed 11
```

## Done when
- [ ] table checks pass; rewritten naming test + disjointness test pass
- [ ] fuzz tally for the `alu` mix: 0 disagreements, 0 NOSTEP (paste line)
- [ ] this file records "no lowering added: no emitter produces the class"

## If stuck
If the fuzz harness cannot compare SP-relative reads, drop item 4, say so in Status with the harness line that blocks it, and leave the arm covered by the Python-side tests only (state that the arm is then UNVERIFIED against hardware).
