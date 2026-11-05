# plan/step-28: `absval` frame-peel `K` reconciliation and corpus re-measure

**Source:** `bugs/FORMAL_absval_proof_does_not_check.md`.
**Master plan:** `doc/finish-formal.md` §"Step 28".

## Goal

`formal/examples/absval.mojo`'s arm64 proof used to pass and now Lean rejects
it: the frame-slot peel's pattern names a slot at `s_0.sp - 32 - 16` while the
goal's store chain is at `s_0.sp - 131072 - 16` — a difference of the emitter's
128 KiB `_SCRATCH` frame stride. This is the frame/window canonicalisation
emitting a peel whose `K` does not match the address the goal carries.

## What to add

1. Reproduce cheaply:
   `python3 test_formal.py --backend arm64 absval` under
   `python3 tools/memslot.py --gb 8 --label t --`.
2. Reconcile the `K` list `_emit_peels`/`mem_read_write_below`/`_pair_below`
   writes against the store stack the goal unfolds to
   (`formal/arm64_proof_gen.py`, ~line 10531). The goal carries `- 131072 - 16`,
   the pattern carries `- 32 - 16`.
3. Re-run `test_formal.py --backend arm64` over all stems and enumerate the
   unexpected reds, since the same frame-machinery change may have moved others
   (a first `-j 2` pass over the 31 declared gaps showed only
   `main_calls_helper` flipping to PASS).

## Structure-only rule

If the correct `K` cannot be derived, state the peel with the right window and
leave the reconciliation obligation as a counted hole (step-01) rather than a
wrong `rw`. `absval` is **not** in `test_formal.py`'s `EXPECTED_FAILURES`; a
formerly-passing example that now fails is a regression.

## Files

`formal/arm64_proof_gen.py`, `test_formal.py`, ledger.

## Verification

`python3 test_formal.py --backend arm64 absval`; the full arm64 corpus; the
memory cap.

## Done when

- [ ] `absval` proves (0 sorries), or is a declared `KNOWN-GAP` with the
      frame-stride reason and a ledger entry
- [ ] no other formerly-passing example is red
- [ ] the K/stores reconciliation is stated where the peel is emitted

## Dependencies

step-01. step-02's memory lemmas if the fix rewrites through them.
