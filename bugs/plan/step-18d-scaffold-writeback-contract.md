# plan/step-18d: scaffold the write-back contract (depth bound as a hypothesis, per-exit obligation as `sorry`)
**Status: DONE 2026-11-07 (measured).** `lib/Scaffold.lean` now holds REAL statements (they were `True` placeholders): `scaffold_cell_writeback_one_exit` / `_multi_exit` over `Arm64State`, `Frame.FrameFits p 1` (no wrap), `h_above : s.sp.toNat + W <= p.toNat` (the cell is above the callee's window; depth bound is a hypothesis, no axiom), `hrun : arm64_exec_go_exit ...`, concluding `Frame.frameRead s'.mem p 0 = v` plus non-interference outside the cell and `[sp-W, sp)`. They need `hmeth : CellSetMethod code s.pc exit_pc W`, an OPAQUE predicate declared in Scaffold (without it the statements quantify over arbitrary code and are false). Typecheck: `lean Scaffold.lean` -> 3 sorry warnings (canary + these two), no errors; `test_formal_proof_gaps.py` 5/5. Ledger rows moved from `placeholder` to `scaffold`. First proof obligation of a real discharge: define `CellSetMethod`.
Class: mid      Size: M      Depends: 18a, 18c, 01b      Blocks: none
Source: 18a's section (D2, D3 and the Lean skeleton); `doc/finish-formal.md` Shared mechanics S1, S2.

## Current state (verify first: 18a's section and `lib/Scaffold.lean`, `formal/proof_gaps.py` exist)
- `lib/Refine.lean`, `lib/Contracts.lean` have no theorem about a caller-frame cell. `lib/Scaffold.lean` is the only file in `lib/` that may contain `sorry` (header says so); `formal/proof_gaps.py::SCAFFOLD_HOLES: dict[str, Hole]` is the ledger, checked by `test_formal_proof_gaps.py` from `formal/lean.py::library_census`.

## Decisions already made
- Write the theorem skeleton 18a produced into `lib/Scaffold.lean` (imports `ProofLib` only if enough; else `Contracts`), one theorem per hole, named `scaffold_cell_writeback_<one|multi>_exit`. The depth bound is a THEOREM HYPOTHESIS, never an `axiom`. Each is `by sorry` and ledgered with `Hole(step="step-18d", reason="...", kind="scaffold")`.
- Do NOT edit `lib/ProofLib.lean`/`lib/X86.lean` (S4: expensive, pinned). Do NOT wire the generator to emit these yet.

## Work order
1. Append the theorems to `lib/Scaffold.lean`. 2. Add rows to `SCAFFOLD_HOLES`. 3. The Lean check: Lean is expensive; do NOT run it. Hand the Lean typecheck to the user: state "needs `python3 tools/memslot.py --gb 16 --label lean -- python3 test_formal_proof_gaps.py` run by the user/gate worker" in the commit message and the Status; run only `python3 -c "import formal.proof_gaps"` here.
4. Dated Status paragraph in `bugs/FORMAL_known_limits.md` §6.3: what is stated, which hypotheses, which holes.

## Do NOT
- Do not state a theorem you cannot argue is TRUE of the machine model (a `sorry` over a false statement is worse than none): if the skeleton in 18a does not typecheck by inspection against `Frame.*` definitions, narrow it to what does and record the narrowing.

## Verification
```
export PATH=/opt/homebrew/bin:$PATH
python3 -c "import formal.proof_gaps"
python3 tools/plan_index.py --check
```

## Done when
- [ ] holes ledgered and named in Status; the Lean typecheck explicitly handed off

## If stuck
Write the unprovable-looking premise into §6.3 Status as a named open question and stop.
