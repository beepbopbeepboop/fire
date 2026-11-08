# plan/step-00e: proofs broken by the shifted-register model — `arm64_step_cmp_reg_n31_reads_zero`, `while_lt_exit_contract_*`
**Status: DONE 2026-11-05 (verified by a real build).** Findings: (1) `arm64_step_cmp_reg_n31_reads_zero` needed only `arm64_shifted_reg_zero` (new, next to the definition); (2) `while_lt_exit_contract_bottom` had LOST ITS WHOLE PROOF in the splice — restored verbatim from `9a6616e83` (statement identical); (3) an ORPHAN copy of that proof (124 lines) sat after `while_lt_exit_contract_bottom_s` — deleted; (4) `_bottom_s` was missing its signed `hlt` premise (the generator passes `hpc hr hb hlt hframe`) — restored; its induction passed OLD-state sign-bound facts to `ih` and used `rw [arm64_reg_pc, arm64_reg_pc]` (rewrites one instantiation twice) — rewritten with `simp only [arm64_reg_pc]` and explicit `hr1/hb1` for `bodyex st`. Prefix build 1..5400: 0 errors.
Class: mid      Size: L      Depends: 00d      Blocks: 00a
Source: build/probe_head 2026-11-05: `ProofLib.lean:3543` (`rfl` failed), `:5044` (unsolved goals), `:5143, 5174, 5177, 5185, 5201, 5203, 5211, 5217`.

## Current state
- `arm64_step_cmp_reg_n31_reads_zero` (3525-3545): after `c9661e6db` (shifted-register ops read their shift) the SUBS/CMP arm computes `diff := arm64_reg rn s - arm64_shifted_reg word s xm` and `nzcv := arm64_subs_flags (arm64_reg rn s) (arm64_shifted_reg …)`. The theorem's right-hand side still says `arm64_reg 16 s`. The final `rfl` fails because `arm64_shifted_reg` of this word (shift field 0) is NOT syntactically `arm64_reg 16 s`.
- `while_lt_exit_contract_bottom` (5044) and `_bottom_s` (5143-5217): proofs written before the `evalExpr`/state changes; errors are `unsolved goals`, a failed `rewrite`, `apply` unification, and an `omega` failure.

## Decisions already made
- For `arm64_step_cmp_reg_n31_reads_zero`: prove a small lemma `arm64_shifted_reg_zero_shift (w : UInt32) (s) (m : Nat) (h : (w >>> 22) &&& 3 = 0 ∧ (w >>> 10) &&& 63 = 0) : arm64_shifted_reg w s m = arm64_reg m s` (unfold the definition; read it first), placed right after `arm64_shifted_reg`'s definition, and `rw` it in the theorem (the word is the literal `0xeb1003ff`: shift type 0, amount 0, `decide` discharges `h`). Do NOT change the theorem statement: it is a pin of the hardware reading.
- For the contract theorems: do not rewrite the proofs from scratch. Print the first unsolved goal (prefix probe with `-DmaxErrors=5000`), find which hypothesis changed shape (`d0`-`d7` fields in the record, `checkPc` update, `evalExpr` extra argument from 00d), and adjust the one `rw`/`simp only` list. If a contract theorem cannot be repaired in a bounded effort, move it to `lib/Scaffold.lean` with `sorry` + ledger row and record which generator template uses it (`grep -n "while_lt_exit_contract" formal/arm64_proof_gen.py`); that makes loops with that shape unprovable, which the proof census (`tools/formal_proof_census.py`) will show as a regression: note the examples in this file.

## Work order
1. The cmp lemma. 2. Prefix probe `1..5300`; fix `_bottom` (5044) then `_bottom_s`. 3. Record in this file what each failure was and how it was fixed.

## Do NOT
Weaken a theorem statement; edit the generator to avoid a theorem.

## Verification
Prefix probe `1..5300` has no errors in 3525-5300.

## Done when
- [ ] no errors in lines 3525-5300 on a prefix build  - [ ] if any theorem moved to Scaffold: ledger row + this file lists the affected examples

## If stuck
Paste the goal state of the first unsolved goal into this file.
