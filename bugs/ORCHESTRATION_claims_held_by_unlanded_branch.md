# ORCHESTRATION_claims_held_by_unlanded_branch

## Summary
A finished branch that cannot land keeps its claims forever, and every queued task with the same claim is blocked
(`claim_blocker` in `control.py`). Nothing releases a claim after repeated failed landings.

## Evidence
- On 2026-11-11, 31 `exited-ok` tasks held claims while nothing landed (last landing about 22:40).
- One of them, `bug-python3-15-lazy-imports-8186` (1 commit), blocked 21 queued items on its own.
- Queue: 32 easy items blocked by claims while the qwen slot was free and idle.

## Repro
Finish a task with commits that can't merge. Queue another task on the same claim: it never starts.

## Status
Open. Not started.

## Done when
A claim is released after a branch has failed landing N times, and the blocked tasks start, with a test.
Then delete this doc in the same commit.
