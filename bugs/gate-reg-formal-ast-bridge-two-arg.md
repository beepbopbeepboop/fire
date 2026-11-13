# Gate: reg-formal-ast-bridge-two-arg is red on master

**Job:** `reg-formal-ast-bridge-two-arg`. Filed by the full gate at `203fd5ea3c`.
**Two states:** this doc exists = the job is red and this is the work. Delete it when the job is green on master.

Reproduce on master (`python3 tools/suite.py reg-formal-ast-bridge-two-arg`), then fix the cause.

## Gate ledger

- **Last known working:** `e8421fc41b` integrate fix-merge-fix-merge-fix-merge-bug-formal-formal-proof-covera
- **First known not working:** `c38d24c92d` bugs/formal/FORMAL_integer_overflow_at_run_time_is_still_untrapped: the // row — INT64_MIN // -1 now traps at INT_OVERFLOW_TRAP_STATUS on both backends: arm64's SDIV of the pair leaves V clear (measured: the same N=1 Z=0 C=1 V=0 that INT64_MIN, 1 leaves, so no flag a post-check could read names the case) and x86-64's IDIV raises #DE before any flag exists, so the one check both machines emit is the sentinel divisor == -1 AND dividend == INT64_MIN BEFORE the divide, branching into the shared trap block (arm64 carries -1 in a register — the 12-bit compare immediate's sign-extended floor is -4096 — x86 in the sign-extended 8-bit immediate); INT_OVERFLOW_OPS gains // with % and / still out (their own pinned rows), division_needs_overflow_precheck keeps a dead sentinel out of the image (a // 4 carries no out-of-image call, the two-calls rule) and the folded pair stays division_overflow_refusal's byte-identical divide; var_floordiv_min flips to ("trapped", TRAP) with the new var_floordiv_fits control (test: test_formal_int_semantics VARIABLE_ROWS 18/18 + full 184/184, TestTheZeroDivisorGuardAgainstLean 3/3, TestCompilerTrapIsNotAProgramCall 11/11, TestTheZeroDivisorGuardIsAFalseGoal 4/4; regenerated q proof 8 errors, all pre-existing class, 3 of the 5 cmp_reg baseline-verified without this change)
- **Seen red in the full gate at:** `203fd5ea3c` (log `/Users/mrs/net/chatgpt/claude/work-verify/verify-203fd5ea.log`)
- **Skipped:** the job's registration in `tools/suite.py` carries `disabled='bugs/gate-reg-formal-ast-bridge-two-arg.md'`, so the gate spends no time on it. To fix it: remove the `disabled=` argument, make the job pass, and delete this doc in the same commit.

## Done when

`python3 test_reg_formal_ast_bridge_two_arg.py` passes (it currently refuses with `FormalBuildError`, see Status). Then remove the `disabled=` argument in `tools/suite.py`, delete this doc, and run `python3 tools/dangling_doc_refs.py --ratchet`.

## Status (2026-11-12): planning round, root cause localized, nothing landed yet

**This is not a two-argument bug.** The refusal happens for `def main(x): return x + 1` as well. The bridge is not involved. The failure is the arm64 CFG generator's handling of the `svc` instruction, which changed meaning in f03896fff (`formal: svc exit halts, write returns`, Nov 11, after the last-known-working `e8421fc41b`).

**Measured (probe: `compile_formal(prove=True)` on `def main(x): return x + 1`, arm64):**

- The walk and block decomposition succeed: `_walk_range` gives `end = 0x100000514`, and `_cfg_blocks` gives 7 blocks.
- The block layout (`b0` is the function entry, `b1` is the stack-floor guard's trap tail):
  - `b0 0x100000454 cbz` (10 instrs), taken edge to `b1`, fall-through `b2`.
  - `b1 0x10000047c seq` (11 instrs), trap. It contains a **continuing** write `svc #0x80` at `0x100000494` (x16 = 4, set by `movz x16,#4` at `0x100000490`) and a **halting** exit `svc #0x80` at `0x1000004a4` (x16 = 1, set by `movz` at `0x1000004a0`).
  - `b2 0x1000004a8 cbz`, `b3 0x1000004c8 b`, `b4 0x1000004cc bl` (trap, `bl` to `0x1000009d8`), `b5 0x1000004f4 seq` (trap, ends in `svc`), `b6 0x100000504 ret`.
- `_gen_run_cert` (`formal/arm64_proof_gen.py:6658`) refuses `b1`. `_step_rhs(0xd4001001, 35)` is now `if arm64_reg 16 s = 1 then none else some { s with pc := s.pc + 4 }`, and `_gen_run_cert` only accepts RHS strings that start with `some ` (the check at ~6700). Every block containing an `svc` is therefore refused, and the universal theorem returns None. `generate_arm64_proof` (~14865) then raises `_cfg_decomposition_refusal`.
- **The refusal message is misleading.** `_cfg_decomposition_refusal` (~8930) searches only for words with no step branch, and every word here has one. So it says "every instruction has a step" while the real cause is an svc run that `_gen_run_cert` cannot certify. Fix the message in the same change, so it names the svc.
- There is a second, deeper mismatch. `emit_block`'s `seq` arm (~10018) continues to `last instr + 4` (`nxt_pc = block["instrs"][-1] + 4`). On the trap path it therefore steps through the exit `svc` as if it returned, which the model no longer does. Before f03896fff this was consistent with the no-op model. Now it is a wrong model. The existing `_halts` mechanism (~9956: `run_last_pc + 4 == EXIT` ends a run at the halt address) is the machinery for a halting terminal.

**Decision needed (D1), which only the owner can make:** what the universal theorem claims on a path that reaches a trap tail's exit `svc`.

- (a) Per-path halt claim. On a trap path the theorem states that the machine halts at the exit `svc` (`arm64_go_exit` returns `some s` with `s.pc = svc_pc`). On the normal path it states `x0 = mojo n` at the `ret`. This is the strongest true statement, and it reuses `_halts`. **Recommended.**
- (b) Treat the stack-floor trap tail as opaque, like the `_opaque` call boundary (`exit_at` + `halt_only`), and state only the non-trap paths. Equally true, but it weakens the statement for every compiled function that carries the guard, which is every function here.

Under (a), the test's universal theorem must have the trap path's conclusion be a halt, not `eval_eq_mojo`. The test only checks `eval_eq_mojo` text, so it cannot tell the difference. Lean must check the halt conjunct, and that is the integrator's gate, not this lane's.

**Implementation plan (after D1 is chosen as (a)):**

1. `formal/arm64_proof_gen.py::_gen_run_cert` (~6658): for an `svc` (idx 35) inside a run, call `_svc_static_x16(words, pc, leaders)` (already exists, ~8397, from fd89c015b). If the value is `c != 1`, the RHS is `some { s with pc := s.pc + 4 }`, which is a continuing write. If it is `1` or dynamic (None), return None with a named reason. The caller passes `leaders` (the block starts) so a block-entry `svc` is dynamic.
2. `_gen_universal_e2e_cfg` run loop (~9340): for a block in `_trap` ending in an exit `svc`, exclude that final `svc` from `run_pcs` so the certificate covers only the prefix. Mark the block as halting (`run_info` entry gets a halt flag).
3. `emit_block` `seq` arm (~10018): a halting block emits the halt terminal, not a continuation to `last + 4`. The path ends with the halt conjunct from D1.
4. `_cfg_decomposition_refusal` (~8930): search also for svc runs that `_gen_run_cert` refuses, and name the svc, so the message stops blaming "every instruction has a step".
5. Universal statement (~14865 caller): add the halt conjunct per trap path, and keep `eval_eq_mojo` for the `ret` path.

**Tests that prove it:**

- `python3 test_reg_formal_ast_bridge_two_arg.py` (the Done-when test; currently FAILS with `FormalBuildError`).
- `python3 test_formal_call_proof_gen.py` for the touched generator paths. Narrowest run: `-k svc` or `-k run_cert` if those names exist, otherwise the class that covers `_gen_run_cert`.
- A unit test next to the existing ones: `_gen_run_cert` accepts a continuing `svc` with static x16 = 4, refuses a `svc` with x16 = 1 and a dynamic one, and the refusal text names the `svc`.
- Lean check of the generated proof for the probe is the integrator's gate. This round did not run Lean, and the python test does not check Lean.

**Not done this round:** no code change. The job stays `disabled=` in `tools/suite.py`, and this doc stays. The guide is for the next round after D1 is answered.
