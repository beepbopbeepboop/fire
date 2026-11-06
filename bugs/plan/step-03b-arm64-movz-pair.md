# plan/step-03b: `arm64/movz_pair` — step lemma and rule theorem
**Status: DONE (verified by agent, work landed)**

Class: mid      Size: M      Depends: 00a, 01a, 01b, 03a      Blocks: 05a
Source: `bugs/FORMAL_peephole_rules_without_proofs.md` §2 table row `arm64/movz_pair`.

## Current state (measured; verified 2026-11-05)
- Arm: `lib/ProofLib.lean:2476`: `(insn &&& 0xffe00000) = 0xd2800000` → `some (arm64_set_reg rd s (UInt64.ofNat imm16))`, `imm16 = (insn>>>5)&&&0xffff`. No flags, memory or pc change; `hw` (bits 22:21) is ignored by the model (the mask 0xffe00000 includes bit 21 so `hw=0` only; other `hw` is MOVK-adjacent — the mask excludes it).
- Template for lemma + rule shape: `arm64_step_add_imm64` (Peephole.lean:166) and `peephole_arm64_add_imm_fuse` (:299-420, statement shape: `hpc`, `hread1/2`, class hypotheses, `hs1`, `hpair`, then conclusion = registers ∧ nzcv ∧ mem ∧ `arm64_steps … 2` ∧ `arm64_steps … 1`). Rule = delete the FIRST of `MOVZ Xd,#i ; MOVZ Xd,#j` (same `Xd`).
- Helper lemmas available: `arm64_reg_set_reg_other`, `arm64_set_reg_pc_congr`, `arm64_steps_one_seq`, `arm64_steps_two_seq` (Peephole.lean ~100-240).

## Decisions already made
- Both lemma and theorem go in `lib/Peephole.lean` (proved). The `rd = 31` case is excluded by hypothesis `(w &&& 0x1f).toNat < 31` (SP/XZR ambiguity — same reason as add_imm).
- Theorem name `peephole_arm64_movz_pair`; step lemma `arm64_step_movz64`.
- Statement (mirror `add_imm_fuse`): original pair `w1`,`w2` both MOVZ, same `rd`; rewritten program `w3 = w2` (the second alone); conclusion: for all `k<31` registers of the pair's final state equal those of the one-instruction run, `nzcv` and `mem` equal the start's, and the `arm64_steps` pc advance clauses (pair → `pc+8`, rewrite → `pc+4`).
- The rewrite deletes `w1`; `w3` is the same word as `w2` — say so in a comment, do not introduce a new encoding.
- If after ~one sitting the `bv_decide` chain or the register frame argument does not close, move ONLY the theorem to `lib/Scaffold.lean` with `sorry` + ledger row `step-03b`; keep `arm64_step_movz64` (it is mechanical) in Peephole.lean.

## Work order
1. `python3 tools/lean_hne_chain.py --mask 0xffe00000 --value 0xd2800000` → paste into `arm64_step_movz64 (s code pc w) (hpc) (hread) (h : (w &&& 0xffe00000) = 0xd2800000) (hrd : (w &&& 0x1f).toNat ≠ 31) : arm64_step s code = some (arm64_set_reg ((w &&& 0x1f).toNat) s (UInt64.ofNat ((w >>> 5) &&& 0xffff).toNat))`. Write it with the same unfold/rw as the template. NOTE the hypothesis `h` for the target must also kill the earlier arms that overlap the class — generator output covers this.
2. State and prove `peephole_arm64_movz_pair`.
3. Add the theorem name to nothing else (rules are registered in step 05a, not here).

## Do NOT
- Do not edit `arm64_step`.
- Do not put a `sorry` in `Peephole.lean` — Scaffold only.
- Do not add the rule to `RULES` here.

## Verification
```
export PATH=/opt/homebrew/bin:$PATH
python3 tools/memslot.py --gb 8 --label t -- python3 test_formal_peephole.py
python3 tools/memslot.py --gb 24 --label t -- python3 test_formal_proof_gaps.py
python3 tools/memslot.py --gb 24 --label t -- python3 test_formal_admitted.py
```
Update the `Peephole` pins in `test_formal_admitted.py`/`test_formal_axiom_closure_pinned.py` from the measurement.

## Done when
- [ ] `arm64_step_movz64` proved; `peephole_arm64_movz_pair` proved (or Scaffold + ledger)
- [ ] `declared_theorems()` contains the name iff it is proved in Peephole.lean
- [ ] hypotheses are SATISFIABLE: add a `example` (or `#eval`-free witness) instantiating the theorem at a concrete window `movz x0,#1 ; movz x0,#2` — a lemma with contradictory hypotheses is inapplicable and green hides it
- [ ] three commands pass

## If stuck
Write the failing goal state into this file under "Blocked" and move the theorem to Scaffold.
