# plan/step-00f: broken non-FP `work_step_*` proofs — `cmn`, `tst`, `ldur`, `stur`, `smulh`, `csel`
**Status: DONE 2026-11-06 (measured).** The regenerated non-FP work-step proofs elaborate: a full-file elaboration of `lib/IEEE754.lean` + `lib/ProofLib.lean` (580,157 bytes, as of 2026-11-06 11:35, `lean -o`, 24 GB cap, wall 9000 s) returned rc 0 with 0 `error` lines (~1 h 25 m).
Class: mid      Size: L      Depends: none      Blocks: 00a
Source: build/probe_head 2026-11-05: `ProofLib.lean:6402` (`work_step_cmn`), `:6486` (`work_step_tst`), `:7346` (`work_step_ldur`), `:7429` (`work_step_stur`), `:7740` (`work_step_smulh`), `:7839`, `:7916`, `:7958` (`work_step_csel`).

## Current state
- The five proofs fail with `unsolved goals` at the end of the `rw [if_neg …, if_pos h]` chain: the RHS they state no longer matches what the arm computes after the shifted-register / `d0`-`d7` / pc changes. Start with the hne chain: the CHAIN is mechanical and regenerable with `python3 tools/lean_hne_chain.py --mask <MASK> --value <VALUE>` (step 03a); a stale chain (an arm inserted earlier since the theorem was written) is the most likely cause of `unsolved goals`.
- `work_step_csel` additionally contains **splice garbage**: after its closing `try dsimp; try rfl; try simp` there is a fragment starting `ide` / `have hne_27 : …` (see ~7905-7920 in the probe copy) which is the tail of a different theorem pasted in the middle; that is the `unexpected identifier` at 7916, and the heartbeat timeout at 7958 follows from it.

## Decisions already made
- Regenerate each theorem's hne chain with `lean_hne_chain.py` and compare with the file; replace, do not patch line by line.
- State each conclusion by READING the arm in `arm64_step` (`lib/ProofLib.lean:2097+`), not from memory; a theorem whose statement does not match its arm is wrong even if it can be closed.
- Remove the garbage fragment in `work_step_csel`; if it contains a `hne_` for an arm that IS missing from the real csel chain, the regenerated chain supersedes it.
- Per-theorem heartbeat bump only: `set_option maxHeartbeats 4000000 in`.
- Anything not repaired in a sitting goes to `lib/Scaffold.lean` with a ledger row, and the generator's use of that `work_step_*` name is listed here (`grep -n "work_step_<name>" formal/arm64_proof_gen.py`).

## Work order
For each theorem in order cmn, tst, ldur, stur, smulh, csel: regenerate chain; re-state from the arm; close; prefix-probe at the theorem's last line (the larger the line number, the longer the probe: 6402 is ~15 min, 7840 ~25 min; do all six, then ONE probe to line 8000).

## Do NOT
Touch the FP theorems (00g). Add `sorry` to Peephole/ProofLib.

## Verification
One prefix probe `1..8000`; no error between 6300 and 8000.

## Done when
- [ ] six theorems elaborate (or are in Scaffold with rows)  - [ ] no `ide`-style fragment remains: `grep -n "^ide$" lib/ProofLib.lean` is empty

## If stuck
List which of the six remain and their first goal.
