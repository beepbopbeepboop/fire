# plan/step-00g: the FP `work_step_*` block — duplicates, timeouts, fragments
**Status: DONE 2026-11-06 (measured).** The regenerated FP work-step proofs elaborate: a full-file elaboration of `lib/IEEE754.lean` + `lib/ProofLib.lean` (580,157 bytes, as of 2026-11-06 11:35, `lean -o`, 24 GB cap, wall 9000 s) returned rc 0 with 0 `error` lines (~1 h 25 m).
Class: mid      Size: L      Depends: 00f      Blocks: 00a
Source: build/probe_head 2026-11-05: `ProofLib.lean:8020-8704` (`simp` timeouts in `fcmp, fadd, fsub, fdiv, fneg, fmov_gpr_v, fmov_v_gpr, scvtf, fcvtzs`), `:8704` (`unexpected identifier`), `:8747-9486` ("`work_step_X` has already been declared" for `fcmp, fadd, fdiv, fneg, fmov_gpr_v, fmov_v_gpr, scvtf, fcvtzs`), `:8980` (`fmul`), `:9000-9062` (`strb_regoff`).

## Current state
- Two copies of the FP step theorems exist in the file: the first block (~7959-8700: fcmp, fadd, fsub, fdiv, fneg, fmov_gpr_v, fmov_v_gpr, scvtf, fcvtzs) and a second block (~8747-9500: fcmp, fadd, fmul, strb_regoff, fdiv, fneg, fmov_gpr_v, fmov_v_gpr, scvtf, fcvtzs). `work_step_fmul` and `work_step_strb_regoff` exist ONLY in the second; `work_step_fsub` ONLY in the first. This is the signature of two merges of the same commit (`bd61c9036`/`e9ed86deb`) pasted together.
- Every FP theorem ends in `try dsimp; try rfl; try simp` which is where the `simp` heartbeat timeouts occur (200000 default).

## Decisions already made
1. **Keep exactly one copy of each name.** Diff the two blocks per name (`diff` of the extracted theorem texts); where they differ, the copy whose conclusion matches the arm in `arm64_step` (read the arm; FP arms are the `fadd/fsub/…` branches added by `e9ed86deb`) wins. Where they are identical, keep the first.
2. `work_step_fmul`, `work_step_strb_regoff`, `work_step_fsub` must survive (each exists once).
3. Replace the closing `try dsimp; try rfl; try simp` with a deterministic finish: after the `rw [if_neg …, if_pos h]` chain the goal should be `some (…) = some (…)`; close with `simp only [arm64_set_fp, …]`/`rfl` for the specific definitions used (read the arm); add `set_option maxHeartbeats 4000000 in` before each theorem.
4. The IEEE-754 semantics lives in `lib/IEEE754.lean` (builds, 0 errors); do not edit it. If a theorem needs a lemma from there, import-level lemma only.
5. A theorem that will not close goes to `lib/Scaffold.lean` with a ledger row; record the generator uses.

## Work order
1. Extract per-name texts into `build/fpdup/` (scratch) and diff. 2. Delete the losing copies and the `ide`-style fragment at ~8704. 3. Fix finishers. 4. ONE prefix probe over the whole file after 00f (full file; this is the 30-minute one).

## Do NOT
Rename a theorem (the generator emits these names). Keep both copies "just in case".

## Verification
Full-file elaboration shows no "already been declared" and no heartbeat timeout: `grep -c "already been declared\|maxHeartbeats" build/probe_head/lib/ProofLib.out` is 0.

## Done when
- [ ] each `work_step_f*` name appears exactly once: `grep -c "^theorem work_step_fadd" lib/ProofLib.lean` is 1 (and the same for the other ten)  - [ ] `lean_hne_chain.py` chains agree with the file for each

## If stuck
List each unresolved name with its first goal.
