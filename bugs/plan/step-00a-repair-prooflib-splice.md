# plan/step-00a: `lib/ProofLib.lean` elaborates again (umbrella: gate for every Lean step)
Class: mid      Size: M      Depends: 00c, 00d, 00e, 00f, 00g      Blocks: every step that edits or builds a Lean library
Source: measured 2026-11-05 (this file); `doc/finish-formal.md` S0.

## Current state (measured; build/probe_head, 2026-11-05)
- `lib/ProofLib.lean` does NOT elaborate: a full pass with `-DmaxErrors=5000` reports **143 errors at ~100 sites** (list and grouping in 00c-00g). `lib/ProofLib.olean` is stale (built from the Oct-18 source `e9973f5a7`), so every library-touching test that is green today is green on an old binary: `formal.lean.ensure_library` accepts an `.olean` newer than its source when the stamp is missing, and `library_census` caches by source hash.
- History (bisected by building each version alone; ProofLib takes **~30 minutes and ~10 GB** per build): `9a6616e83` (Oct 18) BUILDS. `6fa9db2d2`, `a34ee4100`, `39cd95d43` all FAIL (16-32 errors). So the break is older than the FP-register commits: it entered between `9a6616e83` and `39cd95d43` (the `callFunc2`/`strlen`/`u64_ofNat_sub` work), and `bd61c9036`/`e9ed86deb` (FP regs `d0`-`d7`, FP step arms) and the last commit's partial "repair" (-2382/+1132 lines) added the rest.
- **Reverting is not an option**: `formal/arm64_proof_gen.py` generates proofs against the newer model (FP regs, CSEL, STRB-regoff, shifted-register ADD/SUB, `callFunc2`).
- Already fixed in the working tree on 2026-11-05 (do not redo): `mem_read_write_below_split` and `mem_read_write_pair_below_split` (declared before `u64_ofNat_sub`; `have hK := a - b` shadowed a hypothesis). Unverified until a build.
- Not an error but wrong: `def strlen : UInt64 → UInt64 := fun _ => 0` (ProofLib ~977) is a FABRICATED zero for every address. It stays here (step 12a/12c own it) but must not be "fixed" by reintroducing `axiom strlen` (FORMAL.md §7: no axioms; `axiom` + computable defs also gave `dependsOnNoncomputable` errors in the old bisect versions).

## Fast iteration (use this; a full build is 30 minutes)
Errors cluster in four regions and depend only on a PREFIX of the file. To test a fix in region R, write `build/probe_x/lib/ProofLib.lean` = lines `1..E` of the real file, where `E` is the last line of the last theorem of R (cut on a blank line between declarations), copy `lib/IEEE754.lean` beside it, and elaborate with `formal.lean.run_lean(lean, ["-DmaxErrors=5000","-o",out,src], env={"LEAN_PATH": dir}, wall_s=3600, cpu_s=6000, mem_mb=24000)` under `python3 tools/memslot.py --gb 16 --label x --`. The source must live under the repo root (`build/` is untracked scratch). Prefix up to line ~3900 costs minutes, not 30. The reference script is `headprobe.py` pattern: copy IEEE754.lean + ProofLib.lean into `build/probe_head/lib`, elaborate IEEE754 then ProofLib, write stdout+stderr to `ProofLib.out`.

## Work order
1. Do 00c, 00d, 00e, 00f, 00g (independent regions; 00d before 00e).
2. Full pass: `python3 tools/memslot.py --gb 24 --label t -- python3 -c "import formal.lean as L,os; L.ensure_library(L.find_lean(), os.path.abspath('lib'))"`. Expect 0 errors; if not, repeat with the leftover list (still `-DmaxErrors` high) and append the sites to this file.
3. Delete the stale oleans' influence: `ensure_library` rebuilds `X86`, `work`, `Refine`, `Contracts`, `Peephole`, `Scaffold`, `Specs`; fix any error that surfaces there (they were never rebuilt against the new ProofLib).
4. Re-measure and update pins DELIBERATELY: `test_formal_admitted.py` (`AXIOM_CLOSURE`, tally table), `test_formal_axiom_closure_pinned.py`, `test_formal_proof_gaps.py` (the Scaffold census has never run on a fresh build).

## Do NOT
- Do not use `git checkout`/`git restore`/`git stash` to restore an old ProofLib (CLAUDE.md; also it would drop the FP model the generator needs).
- Do not add `sorry`/`axiom` to make a theorem pass. A theorem that cannot be repaired in this step is moved to `lib/Scaffold.lean` WITH a ledger row and the reason, and any generator use of it is noted here.
- Do not widen `maxHeartbeats` globally; use `set_option maxHeartbeats 4000000 in` on the one theorem (the file already does this for `work_step_smulh`).

## Verification
```
export PATH=/opt/homebrew/bin:$PATH
python3 tools/memslot.py --gb 24 --label t -- python3 -c "import formal.lean as L,os; L.ensure_library(L.find_lean(), os.path.abspath('lib')); print('LIBRARY BUILDS')"
python3 tools/memslot.py --gb 24 --label t -- python3 test_formal_proof_gaps.py
python3 tools/memslot.py --gb 24 --label t -- python3 test_formal_admitted.py
python3 tools/memslot.py --gb 24 --label t -- python3 test_formal_axiom_closure_pinned.py
```

## Done when
- [ ] `LIBRARY BUILDS` printed from a tree whose `lib/*.olean` were deleted first (`rm lib/*.olean lib/*.olean.srcsha256`) so no stale artifact answers
- [ ] the three tests pass; pins updated from measurement in the same commit
- [ ] steps 01-05, 06b, 07a, 09, 12, 18d, 27 rows are re-verified on this build (their "DONE" markers predate it)

## If stuck
Append the leftover error sites (file:line:message first line) to this file and stop; do not guess.
