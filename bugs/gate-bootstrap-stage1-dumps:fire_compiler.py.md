# Gate: bootstrap-stage1-dumps:fire_compiler.py is red on master

**Job:** `bootstrap-stage1-dumps:fire_compiler.py`. Filed by the full gate at `0cce3da396`.
**Two states:** this doc exists = the job is red and this is the work. Delete it when the job is green on master.

Reproduce on master (`python3 tools/suite.py bootstrap-stage1-dumps:fire_compiler.py`), then fix the cause.

## Gate ledger

- **Last known working:** `e8421fc41b` integrate fix-merge-fix-merge-fix-merge-bug-formal-formal-proof-covera
- **First known not working:** `c38d24c92d` bugs/formal/FORMAL_integer_overflow_at_run_time_is_still_untrapped: the // row — INT64_MIN // -1 now traps at INT_OVERFLOW_TRAP_STATUS on both backends: arm64's SDIV of the pair leaves V clear (measured: the same N=1 Z=0 C=1 V=0 that INT64_MIN, 1 leaves, so no flag a post-check could read names the case) and x86-64's IDIV raises #DE before any flag exists, so the one check both machines emit is the sentinel divisor == -1 AND dividend == INT64_MIN BEFORE the divide, branching into the shared trap block (arm64 carries -1 in a register — the 12-bit compare immediate's sign-extended floor is -4096 — x86 in the sign-extended 8-bit immediate); INT_OVERFLOW_OPS gains // with % and / still out (their own pinned rows), division_needs_overflow_precheck keeps a dead sentinel out of the image (a // 4 carries no out-of-image call, the two-calls rule) and the folded pair stays division_overflow_refusal's byte-identical divide; var_floordiv_min flips to ("trapped", TRAP) with the new var_floordiv_fits control (test: test_formal_int_semantics VARIABLE_ROWS 18/18 + full 184/184, TestTheZeroDivisorGuardAgainstLean 3/3, TestCompilerTrapIsNotAProgramCall 11/11, TestTheZeroDivisorGuardIsAFalseGoal 4/4; regenerated q proof 8 errors, all pre-existing class, 3 of the 5 cmp_reg baseline-verified without this change)
- **Seen red in the full gate at:** `0cce3da396` (log `/Users/mrs/net/chatgpt/claude/work-verify/verify-0cce3da3.log`)
- **Skipped:** the job's registration in `tools/suite.py` carries `disabled='bugs/gate-bootstrap-stage1-dumps:fire_compiler.py.md'`, so the gate spends no time on it. To fix it: remove the `disabled=` argument, make the job pass, and delete this doc in the same commit.
