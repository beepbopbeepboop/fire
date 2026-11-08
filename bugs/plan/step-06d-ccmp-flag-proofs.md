# plan/step-06d: the proof generator understands flags set by `ccmp`, then `CCMP_LOWERING` defaults on
**Status: DONE 2026-11-07 (measured).** Root cause fixed in commit 5e1a39959 (the short-circuit table registered the stack-floor guard block as the chain's own branch). Full arm64 corpus with the lowering on: PASS 55 (was 50 in `/tmp/up/corpus2.out`), KNOWN-GAP 5, FAIL 28, TOO-LARGE 6; new passes absval bigconst call_both_arms localmul shiftlr wdiff; the only example that passed before and not now is `swapadd`, which has NO condition (so no ccmp) and is TOO-LARGE with `FIRE_CCMP_LOWERING=0` too: its proof is 642 KB at every commit back to the start of this session, 7.2 GB RSS under `-M 12288` (284 s), over the 6144 MB `LEAN_MEMORY_MB` of `formal/lean.py`, so its earlier PASS was a borderline run, not a regression from this work. `CCMP_LOWERING` now defaults ON (`FIRE_CCMP_LOWERING=0` switches it off); `test_arm64_emission.py` 11/11. A first corpus attempt was killed by its own 48 GB memory ceiling with 34 processes (a RESOURCE failure, not a verdict) and rerun with `-j 5`.
Class: hard      Size: L      Depends: 06c      Blocks: none
Source: `bugs/plan/step-06c-*.md` Status; `formal/arm64_proof_gen.py` ~10290-10490 (`_cset_cond`, `_COND_LEMMA`, the `unsupported: branch condition value flow` guard); `lib/ProofLib.lean:3037` (the CCMP step arm).

## Current state (measured 2026-11-07)
- `FIRE_CCMP_LOWERING=1 python3 test_formal.py --backend arm64 both` FAILS with `unsupported: branch condition value flow (frame/flag unavailable)`; without the variable it PASSES. So the machine code is right and the model has a hole.
- For a plain compare the generator names the branch's flag predicate from the `b.cond` terminator via `_COND_LEMMA` and states `arm64_matches_condition cc (arm64_subs_flags a b)` of the LAST `cmp`. After `cmp A ; ccmp B, #nzcv, condA ; b.inv(condB)` the flags are `if arm64_matches_condition condA (subs a1 b1) then subs a2 b2 else <nzcv>`.

## Work order
1. Find why the guard `if not _is_bit_test and (not _Xs or _fl is None)` fires for the ccmp block (print `_Xs`, `_fl`, `_cnd` for `both`).
2. Teach the chain to produce, for a block ending `cmp ; ccmp ; b.cond`, the fact `arm64_matches_condition condB' flags = (condA(a1,b1) && condB(a2,b2))`, where `flags` is the ccmp result: `simp only [arm64_matches_condition, arm64_subs_flags]` then `split <;> simp_all`, as the 06c step file's work-order 5(b) sketches. Read the CCMP arm in `ProofLib.lean:3037` for the exact flag expression.
3. `FIRE_CCMP_LOWERING=1 python3 test_formal.py --backend arm64 both` PASSES with 0 sorries; then set `CCMP_LOWERING = True` as the default in `formal/arm64_codegen.py`, delete the opt-in comment, run the whole `test_formal.py --backend arm64` and compare the PASS count with the count before (it must not drop).

## Do NOT
- Do not widen `EXPECTED_FAILURES`. Do not default the flag on before step 3 passes.
