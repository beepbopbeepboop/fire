# PERF: the `formal` job peaks at 46.2 GB and its class was 8 GB, so it could never pass

**Status: open, measured 2026-10-09. The class is fixed (8 GB -> `stage`), the
46 GB is not.** The registry bug — a job whose ceiling was an order of magnitude
below its need — is landed with the measurement; what the 46 GB is made of is the
open question, and it is the same question as every other row in
`PERF_memory_over_4gb_is_a_bug.md`, one level further out.

## What was run and what it said

    $ python3 tools/suite.py --no-cache formal
    RESOURCE-CAPPED (not a verdict on the output)
    suite: 2 passed, 0 failed, 0 skipped, 1 resource-capped  (peak 21.2 GB)

memcap killed it at the `small` class (8 GB) with 21.2 GB already on the tree,
2.4 s in, 40 processes. It never had a chance: 8 GB is not this job's size.

Re-run once at `MEMLIMIT_GB=96`, which is what the task calls for when a job is
capped by its own class:

    $ MEMLIMIT_GB=96 python3 tools/suite.py --no-cache formal
    suite: 2 passed, 1 failed  (1129 s wall, peak 46.2 GB)

`memcap: done, peak 46.2 GB across up to 32 procs (ceiling 96.0 GB)`. So the real
peak is **5.8x the class the job carried**, and `class_for_peak(46.2)` is `stage`
(96 GB covers 1.5x of 69.3; `program` (55) does not).

## Why the number is recorded even though the run is RED

The run exits 1, so `trusted_peaks` will not take it, and that rule is right in
general. It is wrong to apply it here, and the difference is visible in what the
job did: **1129 s, 93 proofs, PASS=34 KNOWN-GAP=31 FAIL=28, 32 processes**. The
exit 1 is a bookkeeping assertion in the sweep's own report —

    STALE expected-failure entries (now passing — remove them):
      main_calls_helper: the entry calls a second function in the same image...

— i.e. a row of the sweep's expected-failure table that has started passing. A
job that died early peaks at how far it got; this one finished all its work and
then disagreed with a list. The peak is what it needs.

(The stale row itself is a formal-lane cleanup, not filed here: it is a symptom
of proofs improving, and `formal`'s own report names it.)

## The open question: 46.2 GB is an UPPER bound, and probably a loose one

`tools/procrun.py` documents what `tree_rss` is: RSS summed over the whole
process tree, which **double-counts pages shared between processes** — chiefly
the copy-on-write runtime image — "so the true total is somewhat below this
figure". With 32 concurrent Lean processes that correction is not a rounding
error, and nobody has measured it. Two consequences, both of which matter:

* The honest reading of 46.2 GB is "at most 46.2, and the overcount is
  proportional to the number of concurrent Lean processes". The real figure could
  be a third of it, which would make `program` (55 GB, and 1.5x of ~37) the right
  class instead of `stage` — a 96 GB reservation out of a 96 GB ledger is a real
  cost: it admits NOTHING beside it, so the whole `proofs` bucket serialises
  behind this one job.
* Which is why the class landed at `stage` rather than at a number chosen for
  convenience. `stage` is the safe direction for a ceiling (the instrument errs
  high), and the cost of being wrong in the other direction — a RESOURCE verdict
  on the corpus sweep — is worse than a slow proofs bucket. `excl` was NOT added:
  at 96 of 96 the reservation already means "alone", so the marker would be a
  restatement of the arithmetic rather than a scheduling decision.

## Next step

Measure the correction instead of assuming it, because it decides the class:

1. Take the same 93-proof run and record per-process RSS rather than the sum, so
   shared pages are counted once (`procrun.ps_snapshot` already hands out the
   per-pid table `tree_usage` folds up; a variant that sums unique pages is a
   few lines and is the instrument this row actually wants).
2. Re-derive `class_for_peak` from that. If the corrected peak is under 36.7 GB
   (1.5x <= 55), `formal` drops from `stage` to `program` and the proofs bucket
   gets its parallelism back.
3. Whatever it comes out as, it is a row over the debt line in
   `PERF_memory_over_4gb_is_a_bug.md`, and the fix is not a smaller ceiling: it is
   why 93 generated proofs need tens of GB at all, which is Lean's elaborator
   over `native_decide` goals and belongs with the `formal/lean.py` measurements
   already cited there.

Do NOT "fix" this by capping Lean lower. That was measured and it breaks the
build: at `-M 4096` the `ProofLib` build fails with "(kernel) excessive memory
consumption detected" (`formal/lean.py`).