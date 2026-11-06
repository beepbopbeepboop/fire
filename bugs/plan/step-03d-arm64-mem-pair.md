# plan/step-03d: `arm64/mem_pair` — duplicate `STR;STR` and `LDR;LDR`
**Status: DONE (verified by agent, work landed)**

Class: mid      Size: M      Depends: 00a, 02, 03c      Blocks: 05a
Source: `bugs/FORMAL_peephole_rules_without_proofs.md` §2 table row `arm64/mem_pair`.

## Current state (measured; verified 2026-11-05)
- Step lemmas `arm64_step_str64`/`arm64_step_ldr64` come from 03c.
- STR;STR identical: second store writes the same value (`arm64_reg rt s` unchanged — STR changes only `mem`) at the same address; needs `mem_write_u64_idem` (step 02).
- LDR;LDR identical: **UNSOUND without `rt ≠ rn`**. If `rt = rn` the first load overwrites the base register, so the second load reads from a different address. This is a real hazard, not a hypothetical: the existing x86 matcher `formal/peephole.py::_x_mem_pair` (`mov_r64_rm64` pair) compares `(reg, mem_base, mem_disp)` but never `reg != mem_base` (see step 05b).

## Decisions already made
- Two theorems, one per form, because the side conditions differ: `peephole_arm64_str_pair` (no register condition beyond `rt < 31`) and `peephole_arm64_ldr_pair` (adds `hne : (w1 &&& 0x1f) ≠ ((w1 >>> 5) &&& 0x1f)`, i.e. `rt ≠ rn`). Both are the single registry rule `arm64/mem_pair` in step 05a (the matcher dispatches on the opcode); the registry's `theorem` field is a single name, so register TWO `Rule` rows: `arm64/mem_pair_str`, `arm64/mem_pair_ldr`. (Rows are keyed by name, check `ARM64_RULES_BY_NAME`.)
- Rewrite deletes the second instruction.
- Fallback: Scaffold + ledger as in 03b.

## Work order
1. State/prove `peephole_arm64_str_pair`: pair state = STR-alone state because `mem_write_u64 (mem_write_u64 m a v) a v = mem_write_u64 m a v` (`mem_write_u64_idem`).
2. State/prove `peephole_arm64_ldr_pair` with `rt ≠ rn`: second load's address equals the first's (base register unchanged since `rt ≠ rn`; `arm64_reg_or_sp` frame lemma `arm64_reg_set_reg_other`), memory unchanged by LDR, so the second `arm64_set_reg rt` writes the same value → `arm64_set_reg` idempotent on same value.
3. Witness examples for both, plus one that shows the `rt = rn` hypothesis is necessary: a short comment explaining the counterexample (`ldr x1,[x1,#0]` twice differs) — as a comment only, not a theorem.

## Do NOT
- Do not drop the `rt ≠ rn` hypothesis to make the proof go through.
- Do not combine the two theorems into one with a disjunction.

## Verification / Done when
Same as 03c (replace theorem names); plus [ ] both witnesses elaborate.

## If stuck
Scaffold the stuck theorem; the other still lands.
