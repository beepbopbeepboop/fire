# test_x86_64_examples.py exits 0 when every example is SKIPped

## Symptom

`python3 test_x86_64_examples.py` printed `SKIP=93 of 93 examples` and exited 0.
Each SKIP was `arm64 reference unavailable (build failed: ...)`. The gate job
`x86-examples` is therefore green while the examples test nothing: no
arm64-vs-x86-64 comparison happened for any of them.

The exit status is `return 1 if counts.get("FAIL") else 0`, so SKIP never fails
the run. A SKIP is correct for one example whose reference genuinely cannot be
built. It is not a green result for the whole corpus.

## Expected

A run where the reference is unavailable for most examples fails. A single
genuinely unbuildable example may stay a SKIP, as long as the failure is
visible in the tally and the exit code, and the count is bounded.

## Next steps

1. Decide the policy with the owner of the harness. Two options:
   (a) fail the run when `SKIP` is above a stated count, with the count and
   its reason in the test; or (b) make every SKIP name a `bugs/` doc, the way
   `expect=` does, and fail on any SKIP that does not.
2. Once the thread race in `bugs/FORMAL_build_is_not_reentrant.md` is gone, the
   all-SKIP state should not recur. Keep this doc until the policy is decided
   and tested with a forced all-SKIP run (for example by pointing the arm64
   build at a missing file).
3. Note: `tools/suite.py` registers `x86-examples` with `mem='tiny'` and no
   `expect=`, so a gate that counts only the exit status will keep reporting
   this job green in the all-SKIP state.
