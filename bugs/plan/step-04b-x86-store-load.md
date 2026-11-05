# plan/step-04b: `x86_64/store_load` — `mov [b+d], r ; mov r, [b+d]` (no SIB; disp8 form first)
Class: mid      Size: M      Depends: 02, 01b      Blocks: 05b
Source: `bugs/FORMAL_peephole_rules_without_proofs.md` §3 table row `x86_64/store_load`.

## Current state (measured; verified 2026-11-05)
- Proved step lemmas that ALREADY EXIST in `lib/X86.lean`: store `x86_step_mov_mem_disp8` (:3031), `_nodisp` (:3056), `_disp32` (:3100); load `x86_step_mov_rm64_mem_disp8` (:2950), `_disp32` (:2991), `_nodisp` (:3075). Each needs `rm ≠ 4` (no SIB) — SIB forms have their own lemmas (`…_sib_*` :3215-3286) that this step does NOT cover.
- Read-after-write: `mem_read_bytes_write_same` (X86:3694). Register identity: `x86_set_reg_self` (Peephole:563).
- Matcher already exists: `formal/peephole.py::_x_store_load` (line ~789) — **unsound as written** (see 05b): compares `(rm, mem_base, mem_disp)` with `(reg, mem_base, mem_disp)` and ignores SIB index and RIP-relative operands, because the decoder (`formal/x86_64_decode.py:108-154`) sets `mem_base=None` for RIP-relative and overwrites `rm` with the base for SIB.

## Decisions already made
- Scope: forms with an existing step-lemma pair, i.e. `mod ∈ {0 (rm ≠ 5), 1, 2}` and `rm ≠ 4`. One theorem per displacement form is too many: state ONE theorem `peephole_x86_store_load_disp8` first (the form the emitters produce for locals: `[rbp+disp8]`); `…_disp32` and `…_nodisp` are later copies (list them in this file as follow-ups, do not do them now).
- Conclusion shape: with `t1` the store-alone state and `t2` the pair's final state, `t2 = { t1 with rip := m + 8 }` where the store's own `rip` is `m + 4` (disp8 form: REX, 89, modrm, disp8 = 4 bytes) and the load adds another 4.
- Side conditions: `rm ≠ 4`, `mod = 1`, same `modrm`, same `disp`, `reg + x86_rex_r rex < 16`. No condition on `reg = base`: the load's address is computed from the state after the store, which changed only memory.
- Fallback: Scaffold + ledger.

## Work order
1. State theorem against the two existing lemmas. 2. Prove: rewrite with store lemma, then load lemma at `t1`, then `mem_read_bytes_write_same`, then `x86_set_reg_self`. 3. Witness `example` (`48 89 45 f8 ; 48 8b 45 f8`, i.e. `mov [rbp-8],rax ; mov rax,[rbp-8]`).

## Do NOT
Declare the SIB or RIP-relative forms covered. Edit `lib/X86.lean`.

## Verification / Done when
As 04a (three commands); [ ] theorem + witness; [ ] follow-up forms listed in this file.

## If stuck
Scaffold + ledger `step-04b`.
