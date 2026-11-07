# plan/step-04c: `x86_64/mem_pair` — duplicate store, duplicate load (no SIB)
**Status: DONE 2026-11-07 (measured).** Proved `peephole_x86_store_pair_disp8` and `peephole_x86_load_pair_disp8` (both sorry-free) and moved them into `lib/Peephole.lean` (before the `x86_64/imm_zero` design note), adding helper `x86_get_reg_set_reg_same` in Peephole. Removed both theorems from `lib/Scaffold.lean` and deleted their rows from `formal/proof_gaps.py::SCAFFOLD_HOLES`. `formal/peephole.py` rule lists not edited (promotion to live is step 05a/05b). **Statements checked and not corrected:** store pair uses `mem_write_bytes8_idem` (registers/memory-address inputs unchanged by a store); load pair keeps `h_ne : reg + x86_rex_r rex ≠ rm + x86_rex_b rex` (without it, the first load can overwrite the base, e.g. `mov rax,[rax]; mov rax,[rax]`, so the second reads a different address) — counterexample noted in the load-pair docstring in `Peephole.lean`. `python3 tools/memslot.py --gb 8 --label plan04c-ensure-lib -- python3 -c "import formal.lean as L; L.ensure_library(L.find_lean(), 'lib')"` (peak 1.7 GB, exit 0); `python3 tools/memslot.py --gb 8 --label plan04c-proof-gaps -- python3 test_formal_proof_gaps.py` 5/5 OK (0.313s); `python3 tools/memslot.py --gb 8 --label plan04c-peephole -- python3 test_formal_peephole.py` 82/82 OK (32.130s).

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
