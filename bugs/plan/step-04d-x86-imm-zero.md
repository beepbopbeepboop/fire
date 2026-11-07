# plan/step-04d: `x86_64/imm_zero` — `add r, 0` / `sub r, 0` with dead flags
**Status: DONE 2026-11-07 (measured).** Proved `peephole_x86_imm_zero_flags` in `lib/Peephole.lean` (moved from `lib/Scaffold.lean`, removed from `formal/proof_gaps.py::SCAFFOLD_HOLES`). Statement checked true before proving and required **no correction** (scaffolded statement was correct): for REX.W 81 /0 or /5 id, mod==3, imm32==0, the step lemmas give `t` with flags from `x86_flags_add`/`x86_flags_sub` on `(r, 0, r)`, so CF/OF are false and ZF/SF reflect `r`. `peephole_x86_imm_zero_regs`/`_add`/`_sub` were already proved. PF/AF not modelled in `X86State`. Rule NOT enabled (05b); pass cannot use the flag fact soundly without a continuation predicate (design note remains). `ensure_library` exit 0; `test_formal_proof_gaps.py` 5/5; `test_formal_peephole.py` 82/82 OK.

Class: mid      Size: M      Depends: 00a, 01a, 01b      Blocks: 05b
Source: `bugs/FORMAL_peephole_rules_without_proofs.md` §3 table row `x86_64/imm_zero`.

## Current state (measured; verified 2026-11-05)
- Proved step lemmas: `x86_step_add_ri32` (X86:2809, REX.W 81 /0 id, mod 3) and its `sub` sibling just below (digit 5). They produce a state whose `zf/sf/cf/of_` come from `x86_flags_add`/`x86_flags_sub` — `add r,0` is NOT a no-op for flags (it sets ZF/SF from `r`, clears CF/OF), so the rewrite is sound only when no flag is read before the next flag write.
- The matcher `_x_imm_zero` (peephole.py ~835) already asks `ctx.flags_dead_after(a.index + 1)`; check that function exists and what it returns for a block ending at a `jcc`/call/ret. The imm8 form (83 /0 ib) is NOT covered by the lemmas above; the matcher requires `d.form in ("alu_ri32:add","alu_ri32:sub")` — verify `83` decodes to those forms or is separate.
- `PF`/`AF`: `X86State` carries `zf/sf/cf/of_` only (grep `structure X86State`); PF/AF not modelled (noted in the proved theorem).

## Decisions already made
- **Flags are not claimed by the Peephole theorem.** `peephole_x86_imm_zero_regs` (proved, in `lib/Peephole.lean`) states: all registers equal, memory equal, `t.rip = m + 7`, and says nothing about `zf/sf/cf/of_`. Reason: stating "flags dead" needs a Lean predicate over the *continuation* of the program, which does not exist yet; inventing one in an iceman step is a design call (see "Design" below).
- **The flag fact is a closed, checkable lemma** `peephole_x86_imm_zero_flags`. Statement checked true and proved by `simp [x86_flags_add]`/`[x86_flags_sub, UInt64.ofInt]` from `x86_step_add_ri32`/`x86_step_sub_ri32`; moved to `lib/Peephole.lean` (no correction needed). Ledger row removed.
- **The rule is NOT enabled** by this step (05b records it under `SCAFFOLDED_RULES`): the pass-side `flags_dead_after` is a syntactic scan, and no theorem connects it to semantics.
- **Design (for a later hard round, written here, not decided):** the sound statement is "for every continuation whose first flag access is a write, the final state agrees". The minimal Lean form is a relation `FlagsDeadFrom (code) (rip)` defined by recursion over `x86_step` with fuel, plus a simulation lemma. Estimate: a week of proof work. Do not start it in this step.

## Work order
1. Prove `peephole_x86_imm_zero_regs` from `x86_step_add_ri32` and `x86_step_sub_ri32` (`+ 0`, `- 0` identities; `UInt64.ofInt 0 = 0`). 2. Scaffold theorem for the flags with `sorry` + ledger row. 3. Write the "Design" paragraph recording the recommendation above and the continuation-predicate question for a later hard round.

## Do NOT
Enable the rule (flags). Claim flag preservation.

## Verification / Done when
As 04a; [x] regs theorem proved; [x] flags theorem proved and moved to Peephole.lean (ledger row removed; statement true, no correction); [x] Design paragraph written.

## If stuck
Scaffold both; ledger rows `step-04d`.
