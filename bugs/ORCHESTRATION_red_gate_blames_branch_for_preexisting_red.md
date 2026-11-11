# ORCHESTRATION_red_gate_blames_branch_for_preexisting_red

## Summary
When a landing batch goes red, `swarm.py` picks a culprit (`find_culprit`) and holds it. But the red can
already be on master. Then the culprit is innocent and the held work is wasted, while the real red stays.

## Evidence
- Round 31 of `bug-codegen-class-rebind-late-binding` was blamed for `stdlib-syntax` (philox, test/math/*) in
  several batches. The same six failures occur on a master snapshot with no branch (see
  `CODEGEN_simd_math_call_violated_constraint`).
- The chain then went r4 to r31 on this same red.

## Repro
Land a branch onto a master that is already red on a job it does not touch; observe `red: <branch> breaks the gate`.

## Status
Open. Not started. The landing check should first run the failing job on master (or compare with the last
known-green master) before blaming any branch.

## Done when
A red job that is also red on master is reported as "pre-existing" and does not hold or supersede any branch,
with a test. Then delete this doc in the same commit.
