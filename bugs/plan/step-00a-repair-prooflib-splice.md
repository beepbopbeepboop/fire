# plan/step-00a: repair `lib/ProofLib.lean` so the library elaborates again (mangled `work_step_*` region + earlier errors)
Class: mid      Size: M      Depends: none      Blocks: 06b, 07a, 08a, 09a, 03a-03d (anything that builds the library)
Source: found 2026-11-05 while verifying steps 06-09; no `FORMAL_*.md` owns it. Introduced by commit `bd61c9036` ("arm64: add FP reg file and FCMP step model"), made worse by `e9ed86deb`.

## Current state (measured; verified 2026-11-05, NO lean run — textual evidence only)
- `lib/ProofLib.lean` HEAD has **39 lines** where a `theorem work_step_*` header (or a `/-- ... -/` docstring tail) is glued onto the END of a previous line: `grep -c '[^ ]theorem work_step_' lib/ProofLib.lean` -> 39. Example, line 5452: `  rw [if_neg hne_ret, if_neg hne_70,theorem work_step_add_reg (s : Arm64State) ...`. A `rw [` list that never closes followed by `theorem` cannot parse. The text between (the rest of the `rw`, the tail of the proof, the blank line, the docstring) was eaten by a bad splice.
- Pre-damage file: `git show bd61c9036^:lib/ProofLib.lean` has 0 such lines and the 13 `work_step_*` of that era intact (e.g. `work_step_mov` ends `rw [if_neg hne_ret, if_pos h]; try dsimp; try rfl; try simp`).
- The commit also inserted `hne_70..hne_79` facts (negations of the new FP arms) before `rw [hpc, hread]` in lemmas for arms that come BEFORE the FP arms. They are unnecessary: the FP arms are the END of the `arm64_step` chain, and a lemma only negates arms before its own (`lib/ProofLib.lean` comment at the SMULH arm: "every other one negates the branches BEFORE its own and this arm is after all of them").
- `lib/ProofLib.olean` is dated Nov 2 (older than the damage) and `.srcsha256` does not match the file (`shasum -a 256 lib/ProofLib.lean` vs `lib/ProofLib.olean.srcsha256`): nothing has built this file since.
- `_WORK_STEP` (formal/arm64_proof_gen.py ~5004) names `work_step_fmul` (idx 73 after step-00b) but no `theorem work_step_fmul` exists in the file (`grep -c 'theorem work_step_fmul' lib/ProofLib.lean` -> 0): lost in the splice.
- **A SECOND, independent break is already observed (a real library build, 2026-11-05, from `test_formal_call_proof_gen.py` output):** `lib/ProofLib.lean:1338:2: error: Tactic rfl failed`, `:1343:2: error: Tactic rfl failed`, `:1347:55: error(lean.synthInstanceFailed)` — the `evalExpr_var` / `evalExpr_int` / `evalExpr_bool` lemmas (~1334-1347). Likely cause: `evalExpr` gained a second call function (commit `3d32c0e66`, "support 2-arg admitted contracts via call2/callFunc2", Nov 3) and its per-node lemmas / `MojoExpr` constructors were not updated. Work order item 0 fixes these first; the splice damage (line 5452 onward) is only reached after Lean gets past them, so the full error list is unknown until item 0 is done.
- The library may be broken elsewhere too. Do not assume these two are the only defects.

## Decisions already made
- Repair = RESTORE the `work_step_*` region (from `/-! Per-instruction step lemmas (routed from the generator)` to the end of `work_step_csel`) **verbatim from `git show bd61c9036^:lib/ProofLib.lean`**. Do NOT keep the `hne_70..79` additions in lemmas for pre-FP arms.
- The FP-arm lemmas (`work_step_fcmp`, `fadd`, `fsub`, `fmul`, `fdiv`, `fneg`, `fmov_gpr_v`, `fmov_v_gpr`, `scvtf`, `fcvtzs`) are NEW in `bd61c9036`/`e9ed86deb`, so they cannot come from the pre-damage file: take them from HEAD where intact, rewrite where glued, and write `work_step_fmul` by copying `work_step_fsub` (arm text `lib/ProofLib.lean` "FMUL Dd, Dn, Dm", conclusion `arm64_set_reg_d rd s (fmulBits (arm64_reg_d rn s) (arm64_reg_d rm s))`). Each FP lemma negates every arm before its own (use `tools/lean_hne_chain.py` from step-03a if landed; else copy the chain from `work_step_csel` and append the FP arms before its own).
- Everything outside the `work_step_*` region that `bd61c9036`/`e9ed86deb` changed (the `arm64_step` FP arms, `arm64_reg_d`, `fcmp_nzcv`, etc.) is kept as is — verify, do not rewrite.

## Work order
0. Get the first errors: `python3 tools/memslot.py --gb 16 --label t -- python3 test_formal_axioms.py 2>&1 | grep -E 'error' | head -20` (the library build prints them). For the `evalExpr_*` errors: `grep -n 'inductive MojoExpr\|def evalExpr' lib/ProofLib.lean`, read the current `evalExpr` signature (it takes `callFunc` and now probably `callFunc2`), and update each of the three lemmas' statements to the new signature (each is still `rfl`). If the cause is different, fix what the error says; do not weaken a statement.
1. Confirm the damage: `grep -n '[^ ]theorem work_step_' lib/ProofLib.lean | cut -c1-60` (39 hits at time of writing). Also list every other glued construct: `grep -nE '[^ ] *(theorem|lemma|def) [a-z]' lib/ProofLib.lean | grep -vE '^[0-9]+:\s*(--|/-)' | cut -c1-80` and read each hit.
2. `git diff bd61c9036^ HEAD -- lib/ProofLib.lean > $SCRATCH/pl.diff` (SCRATCH = your scratchpad). Read it hunk by hunk; classify each hunk: (a) FP arm / helper definition: keep; (b) `hne_7x` facts in a pre-FP lemma: drop; (c) glued text: restore.
3. Rebuild the file: start from the pre-damage file, re-apply the (a) hunks only. Faster equivalent: take HEAD, replace the span of the 13 pre-FP lemmas + `work_step_csel` + the other pre-FP lemmas between them (`work_step_cmn`, `tst`, ldrb ... `strb_regoff`, `smulh`) with the pre-damage span, then repair the FP lemmas.
4. Add `theorem work_step_fmul` (see Decisions).
5. Textual check (no lean): `grep -c '[^ ]theorem work_step_' lib/ProofLib.lean` -> 0; and
   `python3 - <<'E'` that, for each lemma name in `formal/arm64_proof_gen.py::_WORK_STEP`, asserts `theorem <name> ` occurs at line start in the file.
6. Build through the library API (never `lean` directly): `python3 tools/memslot.py --gb 16 --label t -- python3 test_formal_axioms.py` (it calls `ensure_library`). Read any elaboration error and fix it in the lemma it names. Expect time: the file is 10.8k lines, ~minutes.
7. Pins: `test_formal_admitted.py` and `test_formal_axiom_closure_pinned.py` may move because lemmas were removed/added; update only from the measured output (S4).

## Do NOT
- Do not `git checkout`/`git restore`/`git stash` anything. Produce the repaired file with Edit/Write; `git show ... > scratch` is fine.
- Do not keep `hne_70..79` in pre-FP lemmas "to be safe": an unused `bv_decide` fact per lemma is 40 wasted SAT calls and it is what was mis-spliced.
- Do not touch the `arm64_step` chain order.
- Do not run `lean` directly (`formal/lean.py::run_lean` carries the memory/wall bounds).

## Verification
```
export PATH=/opt/homebrew/bin:$PATH
grep -c '[^ ]theorem work_step_' lib/ProofLib.lean          # 0
python3 tools/memslot.py --gb 16 --label t -- python3 test_formal_axioms.py
python3 tools/memslot.py --gb 16 --label t -- python3 test_formal_admitted.py
python3 tools/memslot.py --gb 16 --label t -- python3 test_formal_axiom_closure_pinned.py
python3 tools/memslot.py --gb 8 --label t -- python3 test_formal.py --backend arm64 absval
```
(the last one is a smoke run of one real proof; step-28 owns its verdict — here it only has to get past library loading.)

## Done when
- [ ] `grep -c '[^ ]theorem work_step_' lib/ProofLib.lean` prints 0 and every `_WORK_STEP` lemma name is a declared theorem
- [ ] `lib/ProofLib.olean.srcsha256` matches `shasum -a 256 lib/ProofLib.lean` after the build
- [ ] the three Lean-backed tests above pass; any pin changed has a one-line comment citing this step and the measured value

## If stuck
If the library fails to elaborate for a reason outside the splice (a second, unrelated defect), write the first error verbatim into this file under "Blocked", and stop. Every Lean-touching step (06b, 07a, 08a, 09a) is blocked on this.

## Blocked
```
/Users/mrs/net/chatgpt/claude/mojo-reference2/lib/ProofLib.lean:743:10: error(lean.unknownIdentifier): Unknown identifier `u64_ofNat_sub`
/Users/mrs/net/chatgpt/claude/mojo-reference2/lib/ProofLib.lean:747:46: error: Application type mismatch: The argument
```
First errors are unrelated to the work_step_* splice (u64_ofNat_sub missing / type issues in mem_read_write_below_split). Splice damage fixed: no glued `theorem work_step_*` lines; all _WORK_STEP lemmas present (including work_step_fmul, work_step_strb_regoff); work_step region restored from pre-damage with FP arms preserved from HEAD.
