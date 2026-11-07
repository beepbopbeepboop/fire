# plan/step-04c: `x86_64/mem_pair` — duplicate store, duplicate load (no SIB)
**Status: SCAFFOLDED 2026-11-06 (measured).** The rule theorem is a LEDGERED `sorry` in `lib/Scaffold.lean` (structure first, soundness later), the supporting step lemmas that exist compile, and the rule is registered as scaffolded in `formal/peephole.py`. NOT proved. `lib/` builds clean (`ensure_library`, 2026-11-06); `test_formal_proof_gaps.py` 5/5; `test_formal_peephole.py` OK.

Class: mid      Size: M      Depends: 00a, 02, 04b      Blocks: 05b
Source: `bugs/FORMAL_peephole_rules_without_proofs.md` §3 table row `x86_64/mem_pair`.

## Current state (measured; verified 2026-11-05)
- Same step lemmas as 04b. Store;store: needs `mem_write_bytes8_idem` (step 02). Load;load: **needs `reg ≠ base`** (first load overwrites the base register otherwise) — the existing matcher `_x_mem_pair` (peephole.py ~765) has no such check.
- Matcher also covers `mov_rm64_imm32` pairs (store of an immediate): needs a third step lemma (`mov qword [m], imm32`, REX.W C7 /0). `grep -n "0xc7" lib/X86.lean`: if no disp8 lemma exists, DO NOT cover it: the rule matcher in 05b must decline `mov_rm64_imm32` pairs until a lemma exists.

## Decisions already made
- Two theorems, disp8 form only (as 04b): `peephole_x86_store_pair_disp8`, `peephole_x86_load_pair_disp8` (hypothesis `reg + x86_rex_r rex ≠ rm + x86_rex_b rex`). Two registry rows in 05b.
- Rewrite deletes the second instruction; conclusion `t2 = { t1 with rip := m + 8 }`.
- Fallback: Scaffold + ledger.

## Work order
1. Store pair: rewrite by the store lemma twice, `mem_write_bytes8_idem`. 2. Load pair: load lemma twice; second address equals first because base register is unchanged (needs `x86_get_reg (x86_set_reg s dst v) b = x86_get_reg s b` for `dst ≠ b` — grep for the existing `x86_get_reg_set_reg_*` lemma; add to Peephole.lean if missing). 3. Witnesses for both, and a comment (not theorem) of the `reg = base` counterexample `mov rax,[rax] ; mov rax,[rax]`.

## Do NOT
Drop `reg ≠ base`. Cover the immediate-store form without a step lemma.

## Verification / Done when
As 04b.

## If stuck
Scaffold the stuck one; ledger `step-04c`.
