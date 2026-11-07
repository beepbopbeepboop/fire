# plan/step-00c: struct literals that predate the FP register fields (`d0`-`d7`)
**Status: DONE 2026-11-05 (verified by a real build).** The two `arm64_go_exit_step_*` literals became `{ st' with pc := … }`. A prefix build of `ProofLib.lean` lines 1..5400 reports 0 errors.
Class: easy      Size: S      Depends: none      Blocks: 00a
Source: build/probe_head 2026-11-05: `ProofLib.lean:3868:22` and `:3882:22` ("Fields missing: `d0` … `d7`"), plus the `unsolved goals` at :3868:581 / :3882.

## Current state
`Arm64State` gained eight FP registers `d0`-`d7` in `bd61c9036`. Two theorems build a state with a structure literal `{ x0 := …, …, mem := … }` and never name them: `arm64_go_exit_step_seq` (~3868) and `arm64_go_exit_step_jump` (~3882). Every other site uses `{ s with … }` and is fine.

## Decisions already made
Rewrite each literal as `{ st' with pc := … }`/`{ st with … }` form (copy the state, change only the named fields) rather than appending `d0 := st.d0, …`; the former cannot go stale the next time a field is added. If the literal genuinely builds a state from scratch, add the eight fields explicitly.

## Work order
1. `sed -n '3855,3900p' lib/ProofLib.lean`; fix both theorems. 2. Prefix-probe lines `1..3900` (00a "Fast iteration"). 3. Grep for other full literals: `grep -n "{ x0 :=" lib/*.lean`; fix any that omit `d0`.

## Do NOT
Change `Arm64State`.

## Verification
Prefix probe of lines 1..3900 shows no error at 3868/3882 (other errors in that range belong to 00d/00e).

## Done when
- [ ] no "Fields missing" error in a prefix probe  - [ ] `grep -n "{ x0 :=" lib/*.lean` is empty or all list `d0`

## If stuck
Write the theorem statements into this file and stop.
