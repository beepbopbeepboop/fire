# plan/step-03c: `arm64/store_load` — `STR Xt,[Xn,#o] ; LDR Xt,[Xn,#o]`
**Status: DONE (verified by agent, work landed)**

Class: mid      Size: M      Depends: 00a, 02, 03a      Blocks: 05a
Source: `bugs/FORMAL_peephole_rules_without_proofs.md` §2 table row `arm64/store_load`.

## Current state (measured; verified 2026-11-05)
- STR arm `lib/ProofLib.lean:2541` (`0xF9000000`): `addr = arm64_reg_or_sp rn s + UInt64.ofNat (imm12*8)`; `some { s with mem := mem_write_u64 s.mem addr.toNat (arm64_reg rt s) }`. Registers, flags, pc unchanged.
- LDR arm `:2392` (`0xF9400000`): same address expression; destination `arm64_set_reg rt s (mem_read_u64 s.mem addr.toNat)` (read the arm to confirm the exact shape).
- Needed facts: `mem_read_after_write_u64` (ProofLib:297), `arm64_set_reg_self` (step 02), `arm64_step_movz64`-style step lemmas.
- Window effect: after STR then LDR of the same address into the same `rt`, the loaded value equals `arm64_reg rt s` (the stored value), so the LDR re-sets `rt` to what it already holds; the pair equals the STR alone.

## Decisions already made
- Side conditions: `rt < 31` (so `arm64_set_reg rt` is a register write, not SP and not XZR), same `rn`, same `imm12`. NO condition on `rt = rn`: the address is computed from the state BEFORE the LDR's write and the STR does not change registers, so `rt = rn` is fine (worker: prove it, do not assume it).
- Step lemmas `arm64_step_str64` and `arm64_step_ldr64` go in `lib/Peephole.lean` using `lean_hne_chain.py` (step 03a). STR/LDR step lemmas take `(hrt : (w &&& 0x1f).toNat < 31)` for LDR only (STR may read XZR=0 correctly via `arm64_reg`; keep `rt < 31` for both for uniformity).
- Theorem `peephole_arm64_store_load`; conclusion = registers equal (all `k<31`), `nzcv` equal, memory equal (`s2.mem = s1.mem` where `s1` is the STR-alone state), pc clauses via `arm64_steps_two_seq`/`one_seq`. Rewrite deletes the LDR (second instruction).
- Fallback as in 03b: theorem to Scaffold with `sorry` + ledger row; step lemmas stay.

## Work order
1. Generate hne chains for LDR (`0xffe00000/0xF9400000`) and STR (`0xffe00000/0xF9000000`); write the two step lemmas.
2. State and prove `peephole_arm64_store_load` using `mem_read_after_write_u64` and `arm64_set_reg_self`.
3. Add a witness `example` at a concrete window (`str x1,[x2,#8] ; ldr x1,[x2,#8]`, plus the `rt = rn` case `str x2,[x2,#8] ; ldr x2,[x2,#8]`) to show hypotheses are satisfiable.

## Do NOT
- Do not forget STR with `Rn = 31` means SP (`arm64_reg_or_sp`), not XZR — use the arm's own helper in the statement.
- Do not rewrite `arm64_step`.

## Verification
Same three commands as 03b.

## Done when
- [ ] `arm64_step_str64`, `arm64_step_ldr64` proved; `peephole_arm64_store_load` proved (or Scaffold + ledger)
- [ ] witness examples elaborate (incl. `rt = rn`)
- [ ] pins updated from measurement; three commands pass

## If stuck
Record the goal state under "Blocked"; Scaffold the theorem.
