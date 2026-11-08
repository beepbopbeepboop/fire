# plan/step-00d: finish the `callFunc2` migration (`runF`, `evalFuncF`, the `runF_*` lemmas, the generator templates)
**Status: DONE 2026-11-05 (verified by a real build).** `noCall2` added; `runF` takes `cf2` LAST with default `noCall2`; the 15 `runF_*` lemmas carry `{cf2}` implicitly; `evalFuncF` and the generator templates (`formal/arm64_proof_gen.py` decrement-while shape, `formal/x86_64_proof_gen.py:383`) pass `noCall2`. Prefix build 1..5400: 0 errors. NOTE: `formal/arm64_proof_gen.py`'s generated proofs have NOT been re-run against it yet.
Class: mid      Size: M      Depends: none      Blocks: 00e, 00a
Source: build/probe_head 2026-11-05: errors at `ProofLib.lean:3684, 3693, 3697, 3701, 3706, 3710, 3715-3718, 3725-3727, 3734-3736, 3743-3747, 3752-3754, 3760-3762, 3768-3770, 3777-3782, 3786`; commit `3d32c0e66` ("support 2-arg admitted contracts via call2/callFunc2").

## Current state (measured)
- `evalExpr (callFunc) (callFunc2) e env` now takes the second callback as an EXPLICIT argument; `runF` (ProofLib:3636) took `(cf2 := fun _ _ _ => 0)` as an optParam in the MIDDLE: `runF fuel cf cf2 stmts env`. Positional callers `runF f cf stmts env` put `stmts` in the `cf2` slot, hence "Application type mismatch … expected `optParam (String → UInt64 → UInt64 → UInt64)`".
- The ~15 `runF_*` equation lemmas (3681-3790) and `evalFuncF`'s call sites were never updated: they still say `runF (f+1) cf [..] env` and `evalExpr cf e env`.
- The generator templates at `formal/arm64_proof_gen.py:12627-12760` (decrement-while shape) still emit the OLD API: `evalExpr handler (COND) env`, `runF_while_false g handler (COND)`, `runF g handler (prog) (envOf m)`. Only 2-argument admitted contracts (`test_formal_admitted_two_args.py`) need `callFunc2`.

## Decisions already made
- Add `def noCall2 : String → UInt64 → UInt64 → UInt64 := fun _ _ _ => 0` once (before `evalExpr`'s first use that needs it) and use it as the default and in the templates. Name it; do not repeat the lambda.
- **Move `cf2` to the END of `runF`**: `runF (fuel) (cf) (stmts) (env) (cf2 := noCall2)`. Reason: every pre-existing caller, including the generator templates and the lemma statements, keeps its argument order; only `evalExpr` calls inside change. Recursion inside `runF` passes `cf2` last.
- `evalFuncF`: keep its existing trailing `cf2` and pass it to `runF` last.
- Each `runF_*` lemma gets `(cf2 : String → UInt64 → UInt64 → UInt64 := noCall2)` as its LAST binder and states `runF … env cf2 = …` / `evalExpr cf cf2 e env`; proofs stay `rfl` / `simp only [runF]`. (`runF_while_false` has `unsolved goals` and a reference to `hc`: re-read its hypotheses after the rename; the `hc` binder name must match.)
- The generator templates change `evalExpr handler (X) env` to `evalExpr handler noCall2 (X) env` (and nothing else); then `runF_*` calls are unchanged.

## Work order
1. Edit `runF` and its recursion. 2. Edit `evalFuncF`. 3. Edit the 15 lemmas, mechanically. 4. Edit the templates. 5. Search for other users: `grep -n "runF\|evalExpr " lib/Refine.lean lib/Contracts.lean lib/work.lean formal/*.py`.
6. Prefix probe lines `1..3800`.

## Do NOT
Keep a middle optParam (the bug). Change `evalExpr`'s signature.

## Verification
Prefix probe shows no error in 3636-3800; then `python3 tools/memslot.py --gb 8 --label t -- python3 test_formal_admitted_two_args.py` (Python side only; Lean after 00a).

## Done when
- [ ] no error in lines 3636-3800 and 12627-12760's templates use `noCall2`  - [ ] `grep -n "evalExpr [a-z]* (" formal/arm64_proof_gen.py` shows no 3-argument call

## If stuck
List the lemma that will not close with its goal state, here.
